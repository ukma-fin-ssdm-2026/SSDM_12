"""Створення бронювання адресними SQL-запитами з тими самими чистими правилами."""

import uuid
from dataclasses import asdict
from datetime import datetime, timedelta

from sqlalchemy import exists, func, select, true

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


def _details(conn, slot_id, *, lock=False):
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
        .where(t.slots.c.id == slot_id)
    )
    return (
        conn.execute(query.with_for_update(of=t.slots) if lock else query).mappings().one_or_none()
    )


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
        conn.exec_driver_sql("SELECT pg_advisory_xact_lock_shared(%s)", (LOCK_KEY,))
        eligible = conn.execute(
            select(t.users.c.id)
            .join(t.roles)
            .where(t.users.c.id == student.id, t.roles.c.role == "student")
            .with_for_update(of=t.users)
        ).scalar_one_or_none()
        if eligible is None:
            raise ApiProblem(ErrorCode.FORBIDDEN_ROLE)
        if key is not None:
            previous = (
                conn.execute(
                    select(t.idempotency).where(
                        t.idempotency.c.student_id == student.id, t.idempotency.c.key == key
                    )
                )
                .mappings()
                .one_or_none()
            )
            if previous:
                if previous["slot_id"] != slot_id:
                    raise ApiProblem(ErrorCode.IDEMPOTENCY_KEY_REUSED)
                old = (
                    conn.execute(
                        select(t.bookings).where(t.bookings.c.id == previous["booking_id"])
                    )
                    .mappings()
                    .one()
                )
                booking = BookingRec(**{**old, "status": BookingStatus(old["status"])})
                return _response(booking, _details(conn, slot_id), now), True
        row = _details(conn, slot_id, lock=True)
        if row is None:
            raise ApiProblem(ErrorCode.SLOT_NOT_FOUND)
        if not row["is_active"]:
            raise ApiProblem(ErrorCode.SLOT_WITHDRAWN)
        # Fresh statement after a possible row-lock wait sees the preceding winner.
        open_intervals = (
            select(func.json_agg(func.json_build_array(t.slots.c.starts_at, t.slots.c.ends_at)))
            .join(t.bookings, t.bookings.c.slot_id == t.slots.c.id)
            .where(
                t.bookings.c.student_id == student.id,
                t.bookings.c.status == "confirmed",
                t.slots.c.ends_at > now,
            )
            .scalar_subquery()
        )
        taken, open_rows = conn.execute(
            select(
                exists(
                    select(t.bookings.c.id).where(
                        t.bookings.c.slot_id == slot_id, t.bookings.c.status == "confirmed"
                    )
                ),
                open_intervals,
            )
        ).one()
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
        conn.execute(t.bookings.insert().values(**asdict(booking)))
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
        conn.execute(
            t.notifications.insert(),
            [
                asdict(build_notification(booking, slot, resource, provider, recipient, kind, at))
                for recipient, kind, at in messages
            ],
        )
        if key is not None:
            conn.execute(
                t.idempotency.insert().values(
                    student_id=student.id, key=key, slot_id=slot_id, booking_id=booking.id
                )
            )
        return _response(booking, row, now), False
