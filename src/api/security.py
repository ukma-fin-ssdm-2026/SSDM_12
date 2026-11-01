"""Cookie-сесії DD-06 та deny-by-default авторизація.

HttpOnly-токен перевіряється за хешем у сховищі, ролі читаються на кожен запит.
POST/PUT/PATCH/DELETE з cookie вимагають прив'язаного X-CSRF-Token й точного Origin.
Тимчасовий demoBearer DD-18 працює лише за явного UNISLOT_DEMO_AUTH=1.
"""

from __future__ import annotations

import hmac
import uuid
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import APIKeyCookie, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.exc import DBAPIError

from api import clock
from api.config import get_settings
from api.enums import Role
from api.errors import ApiProblem, ErrorCode
from api.services import auth_service
from api.stubs.store import store

_WWW_AUTHENTICATE = {"WWW-Authenticate": 'Bearer realm="unislot"'}

demo_bearer = HTTPBearer(
    auto_error=False,
    scheme_name="demoBearer",
    description=(
        "**Лаб 4 — автентифікація-заглушка.** Передайте один із демо-токенів: "
        "`demo-student`, `demo-student-2`, `demo-provider`, `demo-provider-2`, `demo-admin`. "
        "Основна схема — sessionCookie після /auth/login; demoBearer лише для локального демо."
    ),
)
session_cookie = APIKeyCookie(
    name=auth_service.SESSION_COOKIE,
    auto_error=False,
    scheme_name="sessionCookie",
    description="Cookie-сесія з /auth/login (DD-06).",
)


def check_origin(request: Request) -> None:
    """Приймає лише власний Origin або явно дозволений UI; не довіряє subdomain."""
    origin = request.headers.get("origin")
    allowed = {str(request.base_url).rstrip("/"), *get_settings().cors_origins}
    if (origin is not None and origin not in allowed) or (
        origin is None and request.headers.get("sec-fetch-site") == "cross-site"
    ):
        raise ApiProblem(ErrorCode.CSRF_FAILED)


def check_public_auth_request(request: Request) -> None:
    """Login CSRF: точний Origin і JSON-only; HTML-форма не є запитом входу."""
    check_origin(request)
    if request.headers.get("content-type", "").split(";", 1)[0].strip() != "application/json":
        raise ApiProblem(ErrorCode.CSRF_FAILED)


def _session_identity(request: Request, token: str):
    with nullcontext() if store.persistent else store.lock:
        resolved = (
            store.resolve_session(token, clock.utc_now())
            if store.persistent
            else auth_service.resolve_session(token, clock.utc_now())
        )
        if resolved is None:
            raise ApiProblem(ErrorCode.AUTH_REQUIRED, headers=_WWW_AUTHENTICATE)
        user, session = resolved
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            check_origin(request)
            csrf = request.headers.get("x-csrf-token", "")
            if len(csrf) != 43 or not hmac.compare_digest(
                auth_service.token_digest(csrf), session.csrf_hash
            ):
                raise ApiProblem(ErrorCode.CSRF_FAILED)
        return user


@dataclass(frozen=True)
class CurrentUser:
    """Автентифікований користувач запиту."""

    id: uuid.UUID
    full_name: str
    email: str
    roles: frozenset[Role]


def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(demo_bearer)],
    token: Annotated[str | None, Depends(session_cookie)],
) -> CurrentUser:
    """Повертає користувача за токеном або відповідає 401 (AUTH_REQUIRED)."""
    try:
        if token is not None:
            user = _session_identity(request, token)
        elif credentials is not None and get_settings().demo_auth_enabled:
            user = store.user_by_token(credentials.credentials)
        else:
            raise ApiProblem(ErrorCode.AUTH_REQUIRED, headers=_WWW_AUTHENTICATE)
    except DBAPIError:
        raise ApiProblem(ErrorCode.TRANSIENT_CONFLICT, headers={"Retry-After": "1"}) from None
    if user is None:
        raise ApiProblem(ErrorCode.AUTH_REQUIRED, "Невідомий токен.", headers=_WWW_AUTHENTICATE)
    request.state.user_id = str(user.id)  # для журналу запитів (middleware)
    return CurrentUser(user.id, user.full_name, user.email, user.roles)


def require_roles(*roles: Role) -> Callable[[CurrentUser], CurrentUser]:
    """Залежність маршруту: пропускає лише користувачів з однією з ролей (deny-by-default)."""
    allowed = frozenset(roles)
    names = ", ".join(sorted(r.value for r in allowed))

    def dependency(user: Annotated[CurrentUser, Depends(get_current_user)]) -> CurrentUser:
        if not user.roles & allowed:
            raise ApiProblem(ErrorCode.FORBIDDEN_ROLE, f"Операція доступна ролям: {names}.")
        return user

    return dependency


# Скорочення для сигнатур маршрутів.
AnyUser = Annotated[CurrentUser, Depends(get_current_user)]
Student = Annotated[CurrentUser, Depends(require_roles(Role.STUDENT))]
Provider = Annotated[CurrentUser, Depends(require_roles(Role.PROVIDER))]
Admin = Annotated[CurrentUser, Depends(require_roles(Role.ADMIN))]
