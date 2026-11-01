"""Адресні SQL-проєкції сесії й пошуку без глобального знімка або кешу ролей."""

from functools import lru_cache

from sqlalchemy import DateTime, Integer, bindparam, exists, func, select, tuple_

from api.enums import Role
from api.infrastructure import tables as t
from api.pagination import decode_cursor, encode_cursor
from api.policy import HORIZON
from api.schemas.slots import SlotList
from api.services import auth_service
from api.slot_rules import kyiv_day_bounds
from api.stubs.store import UserRec
from unislot.auth.domain.sessions import Session


@lru_cache(maxsize=1)
def _session_query():
    """Кешується лише SQL-вираз: значення сесії та ролей щоразу читаються з БД."""
    joined = t.sessions.join(t.users, t.users.c.id == t.sessions.c.user_id).outerjoin(
        t.roles, t.roles.c.user_id == t.users.c.id
    )
    return (
        select(
            t.sessions,
            t.users.c.full_name,
            t.users.c.email,
            t.users.c.created_at.label("user_created_at"),
            func.array_agg(t.roles.c.role).label("roles"),
        )
        .select_from(joined)
        .where(
            t.sessions.c.token_hash == bindparam("token_hash"),
            t.sessions.c.expires_at > bindparam("now", type_=DateTime(timezone=True)),
            t.users.c.is_active,
        )
        .group_by(t.sessions.c.id, t.users.c.id)
    )


def session_identity(engine, token, now):
    """Один SELECT, лише незавершена сесія активного користувача та поточні ролі."""
    if not auth_service._TOKEN.fullmatch(token):
        return None
    # A single read keeps its statement snapshot without a separate BEGIN/ROLLBACK.
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        row = (
            conn.execute(
                _session_query(),
                {"token_hash": bytes.fromhex(auth_service.token_digest(token)), "now": now},
            )
            .mappings()
            .one_or_none()
        )
    if row is None:
        return None
    user = UserRec(
        row["user_id"],
        row["full_name"],
        row["email"],
        frozenset(Role(r) for r in row["roles"] if r),
        created_at=row["user_created_at"],
    )
    session = Session(
        bytes(row["token_hash"]).hex(),
        row["user_id"],
        bytes(row["csrf_hash"]).hex(),
        row["created_at"],
        row["expires_at"],
        row["id"],
    )
    return user, session


@lru_cache(maxsize=32)
def _search_query(filters: frozenset[str]):
    """Only 32 query shapes; all timestamps, filters and cursors are bind parameters."""
    query = (
        select(
            t.slots.c.id,
            t.slots.c.starts_at,
            t.slots.c.ends_at,
            t.resources.c.id.label("resource_id"),
            t.resources.c.name,
            t.resources.c.type,
            t.resources.c.capacity,
            t.users.c.id.label("provider_id"),
            t.users.c.full_name,
        )
        .select_from(
            t.slots.join(t.resources).join(t.users, t.users.c.id == t.resources.c.provider_id)
        )
        .where(
            t.slots.c.is_active,
            t.slots.c.starts_at > bindparam("now", type_=DateTime(timezone=True)),
            t.slots.c.starts_at <= bindparam("horizon", type_=DateTime(timezone=True)),
            ~exists(
                select(t.bookings.c.id).where(
                    t.bookings.c.slot_id == t.slots.c.id, t.bookings.c.status == "confirmed"
                )
            ),
            ~exists(
                select(t.blocks.c.id).where(
                    t.blocks.c.resource_id == t.slots.c.resource_id,
                    t.blocks.c.starts_at < t.slots.c.ends_at,
                    t.slots.c.starts_at < t.blocks.c.ends_at,
                )
            ),
        )
    )
    if "provider_id" in filters:
        query = query.where(
            t.resources.c.provider_id == bindparam("provider_id", type_=t.users.c.id.type)
        )
    if "resource_type" in filters:
        query = query.where(t.resources.c.type == bindparam("resource_type"))
    if "day_start" in filters:
        query = query.where(
            t.slots.c.starts_at >= bindparam("day_start", type_=DateTime(timezone=True)),
            t.slots.c.starts_at < bindparam("day_end", type_=DateTime(timezone=True)),
        )
    if "min_capacity" in filters:
        query = query.where(
            t.resources.c.type == "room", t.resources.c.capacity >= bindparam("min_capacity")
        )
    if "cursor_id" in filters:
        query = query.where(
            tuple_(t.slots.c.starts_at, t.slots.c.id)
            > tuple_(
                bindparam("cursor_start", type_=DateTime(timezone=True)),
                bindparam("cursor_id", type_=t.slots.c.id.type),
            )
        )
    return query.order_by(t.slots.c.starts_at, t.slots.c.id).limit(
        bindparam("page_size", type_=Integer)
    )


def search_slots(engine, *, now, provider_id, resource_type, day, min_capacity, limit, cursor):
    """Фільтри та LIMIT у PostgreSQL; тільки публічні поля ресурсу й провайдера."""
    parameters = {"now": now, "horizon": now + HORIZON, "page_size": limit + 1}
    if provider_id is not None:
        parameters["provider_id"] = provider_id
    if resource_type is not None:
        parameters["resource_type"] = resource_type.value
    if day is not None:
        parameters["day_start"], parameters["day_end"] = kyiv_day_bounds(day)
    if min_capacity is not None:
        parameters["min_capacity"] = min_capacity
    if cursor:
        parameters["cursor_start"], parameters["cursor_id"] = decode_cursor(cursor)
    filters = frozenset(parameters).intersection(
        {"provider_id", "resource_type", "day_start", "min_capacity", "cursor_id"}
    )
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        rows = conn.execute(_search_query(filters), parameters).mappings().all()
    more, rows = len(rows) > limit, rows[:limit]
    # One recursive core validation instead of 3 Python model constructors per slot.
    return SlotList.model_validate(
        {
            "items": [
                {
                    "id": r["id"],
                    "starts_at": r["starts_at"],
                    "ends_at": r["ends_at"],
                    "duration_minutes": int((r["ends_at"] - r["starts_at"]).total_seconds() // 60),
                    "resource": {
                        "id": r["resource_id"],
                        "name": r["name"],
                        "type": r["type"],
                        "capacity": r["capacity"],
                    },
                    "provider": {"id": r["provider_id"], "full_name": r["full_name"]},
                }
                for r in rows
            ],
            "pagination": {
                "limit": limit,
                "has_more": more,
                "next_cursor": encode_cursor(rows[-1]["starts_at"], rows[-1]["id"])
                if more
                else None,
            },
        }
    )
