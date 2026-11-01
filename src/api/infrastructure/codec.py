"""Перетворення dataclass-записів у реляційні рядки; HTTP тут немає."""

import hashlib
from dataclasses import asdict
from datetime import timedelta

from sqlalchemy import select

from api.enums import BookingStatus, CancellationKind, ResourceType, Role
from api.infrastructure import tables as t
from api.infrastructure.passwords import UNUSABLE_HASH
from api.stubs.store import (
    BookingRec,
    PolicyRec,
    ResourceRec,
    SlotRec,
    TemplateRec,
    TimeBlockRec,
    UserRec,
)
from unislot.auth.domain.sessions import Credential, LoginAttempt, Session
from unislot.availability.domain.templates import WeeklyPattern
from unislot.notifications.domain.model import Notification

COLLECTIONS = (
    "users",
    "resources",
    "templates",
    "policies",
    "slots",
    "blocks",
    "bookings",
    "idempotency",
    "notifications",
    "deliveries",
    "reminders",
    "audit",
    "policy",
    "credentials",
    "sessions",
    "login_attempts",
)


def load(conn, state) -> None:
    """Завантажує узгоджений знімок після захоплення транзакційного advisory lock."""
    for name in COLLECTIONS:
        if name != "policy":
            getattr(state, name).clear()
    roles = {}

    def read(table):
        query = select(table)
        if table is t.audit:
            query = query.order_by(t.audit.c.seq)
        return conn.execute(query).mappings()

    for name, table, cls, key in (("login_attempts", t.login_attempts, LoginAttempt, "key"),):
        for row in read(table):
            getattr(state, name)[row[key]] = cls(**row)
    for row in read(t.sessions):
        data = dict(row)
        data["token_hash"], data["csrf_hash"] = (
            bytes(row["token_hash"]).hex(),
            bytes(row["csrf_hash"]).hex(),
        )
        state.sessions[data["token_hash"]] = Session(**data)
    for row in read(t.roles):
        roles.setdefault(row["user_id"], set()).add(Role(row["role"]))
    for row in read(t.users):
        data = dict(row)
        state.credentials[row["id"]] = Credential(row["id"], data.pop("password_hash"))
        key = hashlib.sha256(row["email"].lower().encode("utf-8")).hexdigest()
        failures, blocked, last = (
            data.pop("failed_login_count"),
            data.pop("locked_until"),
            data.pop("last_failed_login_at"),
        )
        if failures:
            state.login_attempts[key] = LoginAttempt(key, failures, blocked, last)
        state.users[row["id"]] = UserRec(**data, roles=frozenset(roles.get(row["id"], ())))
    for row in read(t.resources):
        data = dict(row)
        data.pop("provider_role")
        data["type"] = ResourceType(data["type"])
        state.resources[row["id"]] = ResourceRec(**data)
    for row in read(t.templates):
        data = dict(row)
        tid, rid = data.pop("id"), data.pop("resource_id")
        state.templates[tid] = TemplateRec(tid, rid, WeeklyPattern(**data))
    for row in read(t.policies):
        state.policies[row["id"]] = PolicyRec(
            row["id"], row["booking_limit"], timedelta(minutes=row["cancel_window_minutes"])
        )
    current = conn.execute(select(t.current_policy.c.policy_id)).scalar_one_or_none()
    state.policy = state.policies.get(current)
    for name, table, cls in (("slots", t.slots, SlotRec), ("blocks", t.blocks, TimeBlockRec)):
        for row in read(table):
            getattr(state, name)[row["id"]] = cls(**row)
    for row in read(t.bookings):
        data = dict(row)
        data["status"] = BookingStatus(data["status"])
        if data["cancellation_kind"] is not None:
            data["cancellation_kind"] = CancellationKind(data["cancellation_kind"])
        state.bookings[row["id"]] = BookingRec(**data)
    for row in read(t.idempotency):
        state.idempotency[(row["student_id"], row["key"])] = {
            "slot_id": row["slot_id"],
            "booking_id": row["booking_id"],
        }
    for row in read(t.notifications):
        notice = Notification(**row)
        state.notifications[notice.id] = notice
        if notice.kind == "reminder" and notice.status in ("pending", "sending"):
            state.reminders[notice.booking_id] = notice.scheduled_for
    for row in read(t.deliveries):
        state.deliveries[row["id"]] = dict(row)
    for row in read(t.audit):
        data = dict(row)
        data.pop("seq")
        state.audit.append(data)


def rows(state) -> dict:
    """Готує записи для запису різниці, без скидання чи переписування таблиць."""
    result = {}
    for name in (
        "slots",
        "blocks",
        "bookings",
        "notifications",
        "resources",
        "login_attempts",
    ):
        result[name] = {key: asdict(value) for key, value in getattr(state, name).items()}
    result["sessions"] = {
        v.id: {
            **asdict(v),
            "token_hash": bytes.fromhex(v.token_hash),
            "csrf_hash": bytes.fromhex(v.csrf_hash),
        }
        for v in state.sessions.values()
    }
    known_keys = {
        hashlib.sha256(u.email.lower().encode("utf-8")).hexdigest() for u in state.users.values()
    }
    result["login_attempts"] = {
        key: row for key, row in result["login_attempts"].items() if key not in known_keys
    }

    def user_row(user):
        credential = state.credentials.get(user.id)
        key = hashlib.sha256(user.email.lower().encode("utf-8")).hexdigest()
        attempt = state.login_attempts.get(key, LoginAttempt(key, 0, None))
        return {
            "id": user.id,
            "full_name": user.full_name,
            "email": user.email,
            "password_hash": credential.password_hash if credential else UNUSABLE_HASH,
            "is_active": user.is_active,
            "created_at": user.created_at,
            "failed_login_count": attempt.failures,
            "locked_until": attempt.blocked_until,
            "last_failed_login_at": attempt.last_failed_login_at,
        }

    result["users"] = {k: user_row(v) for k, v in state.users.items()}
    result["roles"] = {
        (u.id, role.value): {"user_id": u.id, "role": role.value}
        for u in state.users.values()
        for role in u.roles
    }
    result["templates"] = {
        k: {"id": v.id, "resource_id": v.resource_id, **asdict(v.pattern)}
        for k, v in state.templates.items()
    }
    result["policies"] = {
        k: {
            "id": v.id,
            "booking_limit": v.booking_limit,
            "cancel_window_minutes": int(v.cancel_window.total_seconds() // 60),
        }
        for k, v in state.policies.items()
    }
    result["current_policy"] = (
        {1: {"singleton": 1, "policy_id": state.policy.id}} if state.policy else {}
    )
    result["idempotency"] = {
        k: {"student_id": k[0], "key": k[1], **value} for k, value in state.idempotency.items()
    }
    return result
