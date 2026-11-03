"""Створення бронювання адресними SQL-запитами з тими самими чистими правилами."""

import uuid
from dataclasses import asdict
from datetime import datetime, timedelta
from functools import lru_cache

from sqlalchemy import Boolean, DateTime, Text, bindparam, column, func, select, union_all
from sqlalchemy.dialects.postgresql import JSONB

from api.enums import BookingStatus, ResourceType
from api.errors import ApiProblem, ErrorCode
from api.infrastructure import tables as t
from api.policy import HORIZON
from api.schemas.bookings import BookingOut, BookingSlot
from api.schemas.common import PersonSummary, ResourceSummary
from api.stubs.notification_service import build_notification
from api.stubs.store import BookingRec, ResourceRec, SlotRec, UserRec
from unislot.booking.domain import rules
from unislot.booking.domain.model import BookingPolicy, Interval
from unislot.notifications.domain.reminders import reminder_due_at


@lru_cache(maxsize=1)
def _read_query():
    context = func.public.booking_context(
        bindparam("student_id", type_=t.users.c.id.type),
        bindparam("slot_id", type_=t.slots.c.id.type),
        bindparam("now", type_=DateTime(timezone=True)),
        bindparam("demo", type_=Boolean),
        bindparam("key", type_=Text),
    ).table_valued(column("authorized", Boolean), column("details", JSONB), column("state", JSONB))
    return select(context)


def _decode_record(value):
    if value is None:
        return None
    row = dict(value)
    for name in (
        "id",
        "slot_id",
        "student_id",
        "resource_id",
        "provider_id",
        "policy_id",
        "template_id",
        "cancelled_by",
        "rescheduled_to_id",
    ):
        if row.get(name) is not None:
            row[name] = uuid.UUID(row[name])
    for name in ("starts_at", "ends_at", "created_at", "cancel_deadline_at", "cancelled_at"):
        if row.get(name) is not None:
            row[name] = datetime.fromisoformat(row[name])
    return row


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
        # VOLATILE PL/pgSQL uses separate snapshots after gate and row-lock waits.
        read = (
            conn.execute(
                _read_query(),
                {
                    "student_id": student.id,
                    "slot_id": slot_id,
                    "now": now,
                    "demo": student.is_demo,
                    "key": key,
                },
            )
            .mappings()
            .one()
        )
        if not read["authorized"]:
            raise ApiProblem(ErrorCode.FORBIDDEN_ROLE)
        row, state = _decode_record(read["details"]), read["state"]
        if state["previous"] is not None:
            old = _decode_record(state["previous"])
            if old["slot_id"] != slot_id:
                raise ApiProblem(ErrorCode.IDEMPOTENCY_KEY_REUSED)
            booking = BookingRec(**{**old, "status": BookingStatus(old["status"])})
            return _response(booking, row, now), True
        if row is None:
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
