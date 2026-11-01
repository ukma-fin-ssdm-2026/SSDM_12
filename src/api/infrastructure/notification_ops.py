"""Операторський огляд і аудитований повтор вичерпаного outbox без розкриття ПД."""

import uuid
from datetime import datetime

from sqlalchemy import insert, select, update

from api.infrastructure import tables as t
from api.infrastructure.postgres import LOCK_KEY


class RetryRejected(ValueError):
    """Безпечний машинний код відмови без тіла повідомлення або адреси."""


def failed_messages(engine, *, limit: int = 50, offset: int = 0) -> list[dict]:
    """Лише ID, тип, час і стан спроб; жодних payload чи recipient_id."""
    if not 1 <= limit <= 100 or offset < 0:
        raise ValueError("limit 1..100 and nonnegative offset required")
    with engine.connect() as conn:
        rows = conn.execute(
            select(
                t.notifications.c.id,
                t.notifications.c.kind,
                t.notifications.c.attempts,
                t.notifications.c.last_error,
                t.notifications.c.scheduled_for,
            )
            .where(t.notifications.c.status == "failed")
            .order_by(t.notifications.c.scheduled_for, t.notifications.c.id)
            .limit(limit)
            .offset(offset)
        ).mappings()
        return [dict(row) for row in rows]


def retry_failed(
    engine, notice_id: uuid.UUID, actor_id: uuid.UUID, reason: str, now: datetime
) -> str:
    """Повтор лише failed; стара доставка з тим самим ID не дублюється у скриньці."""
    if not reason.strip() or len(reason) > 500:
        raise RetryRejected("reason_required_1_500")
    with engine.begin() as conn:
        # Same ordering as API: global transaction lock, then notification row lock.
        conn.exec_driver_sql("SELECT pg_advisory_xact_lock(%s)", (LOCK_KEY,))
        admin = conn.execute(
            select(t.users.c.id)
            .join(t.roles)
            .where(t.users.c.id == actor_id, t.users.c.is_active, t.roles.c.role == "admin")
        ).scalar_one_or_none()
        if admin is None:
            raise RetryRejected("active_admin_required")
        notice = (
            conn.execute(
                select(t.notifications).where(t.notifications.c.id == notice_id).with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        if notice is None:
            raise RetryRejected("notification_not_found")
        if notice["status"] != "failed":
            raise RetryRejected("notification_not_failed")
        status = "pending"
        if notice["kind"] == "reminder":
            booking = conn.execute(
                select(t.bookings.c.status, t.slots.c.starts_at)
                .join(t.slots)
                .where(t.bookings.c.id == notice["booking_id"])
            ).one()
            if booking.status != "confirmed" or booking.starts_at <= now:
                status = "cancelled"
        conn.execute(
            update(t.notifications)
            .where(t.notifications.c.id == notice_id)
            .values(
                status=status,
                attempts=0 if status == "pending" else notice["attempts"],
                next_attempt_at=now if status == "pending" else None,
                locked_until=None,
                claim_token=None,
                last_error=None if status == "pending" else "reminder_obsolete",
            )
        )
        conn.execute(
            insert(t.audit).values(
                id=uuid.uuid4(),
                actor_id=actor_id,
                action="notification.retry"
                if status == "pending"
                else "notification.retry_skipped",
                object_id=notice_id,
                before={
                    "status": "failed",
                    "attempts": notice["attempts"],
                    "last_error": notice["last_error"],
                },
                after={
                    "status": status,
                    "attempts": 0 if status == "pending" else notice["attempts"],
                    "reason": reason.strip(),
                },
                at=now,
            )
        )
        return status
