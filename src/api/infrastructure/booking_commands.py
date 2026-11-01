"""Створення бронювання адресними SQL-запитами з тими самими чистими правилами."""

import uuid
from dataclasses import asdict
from datetime import datetime, timedelta
from functools import lru_cache

from sqlalchemy import DateTime, bindparam, exists, func, select, true, union_all

from api.enums import BookingStatus, ResourceType
from api.errors import ApiProblem, ErrorCode
from api.infrastructure import tables as t
from api.infrastructure.postgres import LOCK_KEY
from api.policy import HORIZON
from api.schemas.bookings import BookingOut, BookingSlot
from api.schemas.common import PersonSummary, ResourceSummary
from api.stubs.notification_service import build_notification
from api.stubs.store import BookingRec, ResourceRec, SlotRec, UserRec
from unislot.booking.domain import rules
from unislot.booking.domain.model import BookingPolicy, Interval
from unislot.notifications.domain.reminders import reminder_due_at


def _details_query():
    query = (
        select(
            t.slots,
            t.resources.c.name,
            t.resources.c.type,
            t.resources.c.capacity,
            t.resources.c.provider_id,
            t.users.c.full_name,
            t.policies.c.id.label("policy_id"),
            t.policies.c.booking_limit,
            t.policies.c.cancel_window_minutes,
            exists(
                select(t.blocks.c.id).where(
                    t.blocks.c.resource_id == t.slots.c.resource_id,
                    t.blocks.c.starts_at < t.slots.c.ends_at,
                    t.blocks.c.ends_at > t.slots.c.starts_at,
                )
            ).label("blocked"),
        )
        .select_from(
            t.slots.join(t.resources)
            .join(t.users, t.users.c.id == t.resources.c.provider_id)
            .join(t.current_policy, true())
            .join(t.policies, t.policies.c.id == t.current_policy.c.policy_id)
        )
        .where(t.slots.c.id == bindparam("slot_id"))
    )
    return query


@lru_cache(maxsize=2)
def _actor_query(demo: bool):
    return (
        select(t.users.c.id.label("actor_id"))
        .select_from(t.users.join(t.roles))
        .where(
            t.users.c.id == bindparam("student_id"),
            t.roles.c.role == "student",
            true() if demo else t.users.c.is_active,
        )
        .with_for_update(of=t.users, key_share=True)
    )


@lru_cache(maxsize=2)
def _context_query(demo: bool):
    """One round trip; materialized actor precedes the target slot row lock."""
    actor = _actor_query(demo).cte("actor").prefix_with("MATERIALIZED")
    details = _details_query().join(actor, true()).with_for_update(of=t.slots, key_share=True)
    details = details.cte("details").prefix_with("MATERIALIZED")
    # Outer join preserves the distinction between revoked role and absent slot.
    return select(details).select_from(actor.outerjoin(details, true()))


@lru_cache(maxsize=2)
def _state_query(remember: bool):
    intervals = (
        select(func.json_agg(func.json_build_array(t.slots.c.starts_at, t.slots.c.ends_at)))
        .join(t.bookings, t.bookings.c.slot_id == t.slots.c.id)
        .where(
            t.bookings.c.student_id == bindparam("student_id"),
            t.bookings.c.status == "confirmed",
            t.slots.c.ends_at > bindparam("now", type_=DateTime(timezone=True)),
        )
        .scalar_subquery()
    )
    query = select(
        exists(
            select(t.bookings.c.id).where(
                t.bookings.c.slot_id == bindparam("slot_id"), t.bookings.c.status == "confirmed"
            )
        ).label("taken"),
        intervals.label("open_rows"),
    )
    if remember:
        previous = (
            select(*(c.label("previous_" + c.name) for c in t.bookings.c))
            .join(t.idempotency, t.idempotency.c.booking_id == t.bookings.c.id)
            .where(
                t.idempotency.c.student_id == bindparam("student_id"),
                t.idempotency.c.key == bindparam("key", type_=t.idempotency.c.key.type),
            )
            .subquery()
        )
        anchor = select(true()).subquery()
        query = query.add_columns(previous).select_from(anchor.outerjoin(previous, true()))
    return query


@lru_cache(maxsize=4)
def _write_query(notice_count: int, remember: bool):
    """Кешується форма SQL, а не значення; 2/3 повідомлення, з ключем або без."""
    created = (
        t.bookings.insert()
        .values({c.name: bindparam("booking_" + c.name, type_=c.type) for c in t.bookings.c})
        .returning(t.bookings.c.id)
        .cte("created")
    )
    notices = [
        select(
            *(
                created.c.id
                if c.name == "booking_id"
                else bindparam(f"notice_{i}_{c.name}", type_=c.type)
                for c in t.notifications.c
            )
        ).select_from(created)
        for i in range(notice_count)
    ]
    # Unlike literal multi-row VALUES this shape can use SQLAlchemy's compiled cache.
    write = t.notifications.insert().from_select(
        [c.name for c in t.notifications.c], union_all(*notices)
    )
    if remember:
        write = write.add_cte(
            t.idempotency.insert()
            .from_select(
                ["student_id", "key", "slot_id", "booking_id"],
                select(
                    bindparam("booking_student_id", type_=t.users.c.id.type),
                    bindparam("idempotency_key", type_=t.idempotency.c.key.type),
                    bindparam("booking_slot_id", type_=t.slots.c.id.type),
                    created.c.id,
                ),
            )
            .cte("remembered")
        )
    return write


def _response(booking, row, now):
    state = rules.derive_state(booking.status, Interval(row["starts_at"], row["ends_at"]), now)
    return BookingOut(
        id=booking.id,
        state=state,
        slot=BookingSlot(id=row["id"], starts_at=row["starts_at"], ends_at=row["ends_at"]),
        resource=ResourceSummary(
            id=row["resource_id"], name=row["name"], type=row["type"], capacity=row["capacity"]
        ),
        provider=PersonSummary(id=row["provider_id"], full_name=row["full_name"]),
        cancel_deadline_at=booking.cancel_deadline_at,
        can_cancel=rules.can_cancel(state, booking.cancel_deadline_at, now),
        created_at=booking.created_at,
        cancelled_at=booking.cancelled_at,
        cancellation_kind=booking.cancellation_kind,
        cancellation_reason=booking.cancellation_reason,
        rescheduled_to_id=booking.rescheduled_to_id,
    )


def create_booking(engine, student, slot_id, now, key=None):
    """Shared gate → student → slot; незалежні студенти/слоти не серіалізуються.

    Старі адміністративні, cancel/reschedule й maintenance беруть exclusive gate.
    Одна транзакція містить бронь, ідемпотентність і outbox; помилка відкочує все.
    """
    with engine.begin() as conn:
        # This must be a separate statement: after a gate wait READ COMMITTED
        # needs a new snapshot of roles, policy and blocks changed by the admin.
        conn.exec_driver_sql("SELECT pg_advisory_xact_lock_shared(%s)", (LOCK_KEY,))
        parameters = {"student_id": student.id, "slot_id": slot_id, "now": now, "key": key}
        row = conn.execute(_context_query(student.is_demo), parameters).mappings().one_or_none()
        if row is None:
            raise ApiProblem(ErrorCode.FORBIDDEN_ROLE)
        if row["id"] is None and key is None:
            raise ApiProblem(ErrorCode.SLOT_NOT_FOUND)
        # A separate statement after lock waits sees both the winner and its key.
        state = conn.execute(_state_query(key is not None), parameters).mappings().one()
        if key is not None and state["previous_id"] is not None:
            if state["previous_slot_id"] != slot_id:
                raise ApiProblem(ErrorCode.IDEMPOTENCY_KEY_REUSED)
            old = {c.name: state["previous_" + c.name] for c in t.bookings.c}
            booking = BookingRec(**{**old, "status": BookingStatus(old["status"])})
            return _response(booking, row, now), True
        if row["id"] is None:
            raise ApiProblem(ErrorCode.SLOT_NOT_FOUND)
        if not row["is_active"]:
            raise ApiProblem(ErrorCode.SLOT_WITHDRAWN)
        taken, open_rows = state["taken"], state["open_rows"]
        interval = Interval(row["starts_at"], row["ends_at"])
        rules.ensure_slot_bookable(interval, now, HORIZON, taken=taken, blocked=row["blocked"])
        policy = BookingPolicy(
            row["booking_limit"], timedelta(minutes=row["cancel_window_minutes"])
        )
        rules.ensure_within_student_limits(
            [Interval(*(datetime.fromisoformat(v) for v in r)) for r in (open_rows or [])],
            interval,
            now,
            policy,
        )
        booking = BookingRec(
            uuid.uuid4(),
            slot_id,
            student.id,
            BookingStatus.CONFIRMED,
            row["policy_id"],
            rules.cancel_deadline(row["starts_at"], policy),
            now,
        )
        slot = SlotRec(slot_id, row["resource_id"], row["starts_at"], row["ends_at"])
        resource = ResourceRec(
            row["resource_id"],
            row["name"],
            ResourceType(row["type"]),
            row["capacity"],
            row["provider_id"],
        )
        provider = UserRec(row["provider_id"], row["full_name"], "", frozenset())
        messages = [(student.id, "confirmation", now), (provider.id, "provider_created", now)]
        due = reminder_due_at(row["starts_at"], now)
        if due is not None:
            messages.append((student.id, "reminder", due))
        notices = [
            asdict(build_notification(booking, slot, resource, provider, recipient, kind, at))
            for recipient, kind, at in messages
        ]
        parameters = {"booking_" + k: v for k, v in asdict(booking).items()}
        parameters.update(
            (f"notice_{i}_{k}", v)
            for i, notice in enumerate(notices)
            for k, v in notice.items()
            if k != "booking_id"
        )
        if key is not None:
            parameters["idempotency_key"] = key
        conn.execute(_write_query(len(notices), key is not None), parameters)
        return _response(booking, row, now), False
