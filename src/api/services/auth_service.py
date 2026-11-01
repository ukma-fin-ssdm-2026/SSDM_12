"""Реєстрація, вхід і серверні сесії; raw-токени не зберігаються в Store/БД."""

from __future__ import annotations

import hashlib
import math
import re
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from api.config import get_settings
from api.enums import Role
from api.errors import ApiProblem, ErrorCode
from api.infrastructure.passwords import hash_password, hasher, password_matches
from api.stubs.store import Ids, UserRec, store
from unislot.auth.domain.sessions import Credential, LoginAttempt, LoginPolicy, Session

SESSION_COOKIE = "unislot_session"
CSRF_COOKIE = "unislot_csrf"
_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}\Z")


def token_digest(value: str) -> str:
    """SHA-256 для випадкового 256-бітного токена; пароль хешує Argon2id."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def register(full_name: str, email: str, password: str) -> UserRec:
    """Роль самореєстрації задає лише сервер, завжди student."""
    with store.lock:
        email = email.lower()
        if any(user.email.lower() == email for user in store.users.values()):
            raise ApiProblem(ErrorCode.EMAIL_ALREADY_REGISTERED)
        user = UserRec(uuid.uuid4(), full_name, email, frozenset({Role.STUDENT}))
        credential = Credential(user.id, hash_password(password))
        store.users[user.id], store.credentials[user.id] = user, credential
        return user


@dataclass
class LoginResult:
    """Відмова — результат, щоб транзакція закомітила лічильник."""

    user: UserRec | None = None
    session: Session | None = None
    token: str = field(default="", repr=False)
    csrf_token: str = field(default="", repr=False)
    error: ErrorCode | None = None
    retry_after: int = 0


def login(email: str, password: str, now: datetime, previous_token: str | None) -> LoginResult:
    """Фіксує невдалу спробу або видає нову сесію з випадковим ID."""
    with store.lock:
        email = email.lower()
        settings = get_settings()
        policy = LoginPolicy(settings.login_max_failures, settings.login_cooldown_seconds)
        key = token_digest(email)
        attempt = store.login_attempts.get(key, LoginAttempt(key, 0, None))
        if attempt.blocked_until is not None and now < attempt.blocked_until:
            password_matches(None, password)
            return LoginResult(
                error=ErrorCode.LOGIN_THROTTLED,
                retry_after=max(1, math.ceil((attempt.blocked_until - now).total_seconds())),
            )
        user = next((u for u in store.users.values() if u.email.lower() == email), None)
        credential = store.credentials.get(user.id) if user else None
        matches = password_matches(credential.password_hash if credential else None, password)
        if not matches or user is None or not user.is_active:
            policy.record_failure(attempt, now)
            store.login_attempts[key] = attempt
            if attempt.blocked_until is not None and now < attempt.blocked_until:
                return LoginResult(
                    error=ErrorCode.LOGIN_THROTTLED, retry_after=settings.login_cooldown_seconds
                )
            return LoginResult(error=ErrorCode.INVALID_CREDENTIALS)
        store.login_attempts.pop(key, None)
        if hasher.check_needs_rehash(credential.password_hash):
            credential.password_hash = hash_password(password)
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        session = Session(
            token_digest(token),
            user.id,
            token_digest(csrf),
            now,
            now + timedelta(seconds=settings.session_ttl_seconds),
        )
        if previous_token and _TOKEN.fullmatch(previous_token):
            store.sessions.pop(token_digest(previous_token), None)
        store.sessions[session.token_hash] = session
        return LoginResult(user, session, token, csrf)


def resolve_session(token: str, now: datetime) -> tuple[UserRec, Session] | None:
    """Строк перевіряється сервером, ролі читаються заново на кожен запит."""
    if not _TOKEN.fullmatch(token):
        return None
    with store.lock:
        session = store.sessions.get(token_digest(token))
        if session is None or now >= session.expires_at:
            return None
        user = store.users.get(session.user_id)
        return (user, session) if user and user.is_active else None


def logout(token: str | None) -> None:
    """Відкликає поточну сесію; інші пристрої лишаються авторизовані."""
    with store.lock:
        if token:
            store.sessions.pop(token_digest(token), None)


def bootstrap_admin(full_name: str, email: str, password: str, now: datetime) -> UserRec:
    """Одноразова операторська команда; не надається через публічний REST API."""
    with store.lock:
        already_bootstrapped = any(a["action"] == "user.bootstrap_admin" for a in store.audit)
        real_admin = any(
            u.is_active and Role.ADMIN in u.roles and u.id != Ids.ADMIN
            for u in store.users.values()
        )
        if already_bootstrapped or real_admin:
            raise ValueError("an administrator is already initialized")
        email = email.lower()
        legacy = store.users.get(Ids.ADMIN)
        if any(u.email.lower() == email and u is not legacy for u in store.users.values()):
            raise ValueError("email is already registered")
        # Reuse the historical admin identity: references in audit stay valid, and an
        # unreachable demo administrator cannot defeat the last-admin invariant.
        user = legacy or UserRec(uuid.uuid4(), full_name, email, frozenset({Role.ADMIN}))
        user.full_name, user.email, user.is_active = full_name, email, True
        user.roles = frozenset({Role.ADMIN})
        store.users[user.id] = user
        store.credentials[user.id] = Credential(user.id, hash_password(password))
        store.login_attempts.pop(token_digest(email), None)
        store.audit.append(
            {
                "actor_id": user.id,
                "action": "user.bootstrap_admin",
                "object_id": user.id,
                "before": None,
                "after": {"roles": ["admin"], "is_active": True},
                "at": now,
            }
        )
        return user
