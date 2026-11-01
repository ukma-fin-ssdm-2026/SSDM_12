"""Outbox claim/ack та ідемпотентна заглушка доставки в особисту скриньку (C-002)."""

from __future__ import annotations

import copy
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError

from api.infrastructure import tables as t
from api.stubs.store import store
from unislot.notifications.domain.model import Notification, RetryPolicy


class DeliveryUnavailable(Exception):
    """Контрольований збій адаптера, не помилка бронювання."""


def _due(notice: Notification, now: datetime) -> bool:
    ready = (notice.next_attempt_at or notice.scheduled_for) <= now
    return ready and (
        notice.status == "pending"
        or (
            notice.status == "sending"
            and notice.locked_until is not None
            and notice.locked_until <= now
        )
    )


def _claim(notice: Notification, now: datetime, policy: RetryPolicy) -> None:
    notice.status = "sending"
    notice.attempts += 1
    notice.claim_token = uuid.uuid4()
    notice.locked_until = now + timedelta(seconds=policy.lease_seconds)


def _finish(notice: Notification, now: datetime, policy: RetryPolicy, error: bool) -> None:
    notice.locked_until = notice.claim_token = None
    if error:
        notice.status = "failed" if notice.attempts >= policy.max_attempts else "pending"
        notice.next_attempt_at = policy.next_attempt(now, notice.attempts)
        notice.last_error = "gateway_unavailable"
    else:
        notice.status, notice.sent_at, notice.last_error = "sent", now, None
        notice.next_attempt_at = None


class MemoryOutbox:
    """Адаптер для unit/API-тестів без заяви про стійкість до перезапуску."""

    def claim(self, now: datetime, batch: int, policy: RetryPolicy) -> list[Notification]:
        """Копії повідомлень залишають lock до виклику зовнішнього адаптера."""
        with store.lock:
            result = []
            ready = sorted(
                store.notifications.values(),
                key=lambda n: (
                    n.next_attempt_at or n.scheduled_for,
                    n.kind == "reminder",
                    str(n.id),
                ),
            )
            for notice in ready:
                if _due(notice, now):
                    if notice.attempts >= policy.max_attempts:
                        notice.status, notice.last_error = "failed", "lease_expired"
                        notice.claim_token = notice.locked_until = None
                        continue
                    _claim(notice, now, policy)
                    result.append(copy.deepcopy(notice))
                    if len(result) == batch:
                        break
            return result

    def deliver(self, notice: Notification, now: datetime) -> bool:
        """Фейкова скринька має унікальний id — повтор не створює дубль."""
        with store.lock:
            current = store.notifications[notice.id]
            if current.status != "sending" or current.claim_token != notice.claim_token:
                return False
            if (
                notice.kind == "reminder"
                and store.bookings[notice.booking_id].status != "confirmed"
            ):
                return False
            store.deliveries.setdefault(
                notice.id,
                {
                    "id": notice.id,
                    "recipient_id": notice.recipient_id,
                    "kind": notice.kind,
                    "payload": copy.deepcopy(notice.payload),
                    "delivered_at": now,
                },
            )
            return True

    def finish(self, notice: Notification, now: datetime, policy: RetryPolicy, error: bool) -> None:
        """Прострочений Worker не може підтвердити чужу новішу спробу."""
        with store.lock:
            current = store.notifications[notice.id]
            if current.status == "sending" and current.claim_token == notice.claim_token:
                _finish(current, now, policy, error)
                if not error and notice.kind == "reminder":
                    store.reminders.pop(notice.booking_id, None)


class PostgresOutbox:
    """Окремі короткі транзакції Worker; без загального lock API під час доставки."""

    def __init__(self, engine) -> None:
        """Використовує той самий runtime-рівень прав, що й API."""
        self.engine = engine

    def claim(self, now: datetime, batch: int, policy: RetryPolicy) -> list[Notification]:
        """FOR UPDATE SKIP LOCKED розподіляє готові записи між Worker-процесами."""
        with self.engine.begin() as conn:
            due = (
                func.coalesce(t.notifications.c.next_attempt_at, t.notifications.c.scheduled_for)
                <= now
            )
            available = or_(
                t.notifications.c.status == "pending",
                and_(t.notifications.c.status == "sending", t.notifications.c.locked_until <= now),
            )
            selected = (
                conn.execute(
                    select(t.notifications)
                    .where(due, available)
                    .order_by(
                        t.notifications.c.scheduled_for,
                        t.notifications.c.kind == "reminder",
                        t.notifications.c.id,
                    )
                    .limit(batch)
                    .with_for_update(skip_locked=True)
                )
                .mappings()
                .all()
            )
            result = []
            for row in selected:
                notice = Notification(**row)
                if notice.attempts >= policy.max_attempts:
                    conn.execute(
                        update(t.notifications)
                        .where(t.notifications.c.id == notice.id)
                        .values(
                            status="failed",
                            last_error="lease_expired",
                            claim_token=None,
                            locked_until=None,
                        )
                    )
                    continue
                _claim(notice, now, policy)
                conn.execute(
                    update(t.notifications)
                    .where(t.notifications.c.id == notice.id)
                    .values(
                        status=notice.status,
                        attempts=notice.attempts,
                        claim_token=notice.claim_token,
                        locked_until=notice.locked_until,
                    )
                )
                result.append(notice)
            return result

    def deliver(self, notice: Notification, now: datetime) -> bool:
        """Постійна C-002 скринька: INSERT один раз за id повідомлення."""
        with self.engine.begin() as conn:
            valid = conn.execute(
                select(t.notifications.c.id)
                .where(
                    t.notifications.c.id == notice.id,
                    t.notifications.c.status == "sending",
                    t.notifications.c.claim_token == notice.claim_token,
                )
                .with_for_update()
            ).scalar_one_or_none()
            if valid is None:
                return False
            if notice.kind == "reminder":
                status = conn.execute(
                    select(t.bookings.c.status).where(t.bookings.c.id == notice.booking_id)
                ).scalar_one()
                if status != "confirmed":
                    return False
            conn.execute(
                insert(t.deliveries)
                .values(
                    id=notice.id,
                    recipient_id=notice.recipient_id,
                    kind=notice.kind,
                    payload=notice.payload,
                    delivered_at=now,
                )
                .on_conflict_do_nothing()
            )
            return True

    def finish(self, notice: Notification, now: datetime, policy: RetryPolicy, error: bool) -> None:
        """Підтверджує лише власний чинний lease; помилка залишається в черзі."""
        token = notice.claim_token
        _finish(notice, now, policy, error)
        with self.engine.begin() as conn:
            conn.execute(
                update(t.notifications)
                .where(
                    t.notifications.c.id == notice.id,
                    t.notifications.c.status == "sending",
                    t.notifications.c.claim_token == token,
                )
                .values(
                    status=notice.status,
                    locked_until=None,
                    claim_token=None,
                    sent_at=notice.sent_at,
                    next_attempt_at=notice.next_attempt_at,
                    last_error=notice.last_error,
                )
            )


class MailboxGateway:
    """Контрольована заглушка доставки (C-002); режим збою читає Worker."""

    def __init__(self, repository) -> None:
        """Адаптер скриньки не викликається у запиті бронювання."""
        self.repository = repository

    def send(self, notice: Notification, now: datetime) -> bool:
        """Доставляє в особисту скриньку або імітує недоступність провайдера."""
        if os.environ.get("UNISLOT_NOTIFICATION_FAILURE", "").lower() in ("1", "true", "yes"):
            raise DeliveryUnavailable
        try:
            return self.repository.deliver(notice, now)
        except DBAPIError:
            raise DeliveryUnavailable from None


@dataclass
class DispatchResult:
    """Лічильники одного прогону без тіл повідомлень чи персональних даних."""

    claimed: int = 0
    sent: int = 0
    failed: int = 0


def dispatch_due(
    repository, now: datetime, *, batch: int = 50, policy: RetryPolicy | None = None, gateway=None
) -> DispatchResult:
    """Доставка поза транзакцією бронювання; керований збій не губить повідомлення."""
    if not 1 <= batch <= 100:
        raise ValueError("batch must be between 1 and 100")
    policy = policy or RetryPolicy()
    gateway = gateway or MailboxGateway(repository)
    claimed = repository.claim(now, batch, policy)
    result = DispatchResult(claimed=len(claimed))
    for notice in claimed:
        try:
            sent = gateway.send(notice, now)
        except (DeliveryUnavailable, TimeoutError, OSError):
            repository.finish(notice, now, policy, error=True)
            result.failed += 1
        else:
            if sent:
                repository.finish(notice, now, policy, error=False)
                result.sent += 1
    return result
