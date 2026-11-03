"""Планування outbox у тій самій одиниці роботи, що й зміна бронювання."""

from __future__ import annotations

import uuid
from datetime import datetime

from api.stubs.store import BookingRec, store
from unislot.notifications.domain.model import Notification


def _enqueue(booking: BookingRec, recipient: uuid.UUID, kind: str, scheduled: datetime) -> None:
    slot = store.slots[booking.slot_id]
    resource = store.resources[slot.resource_id]
    provider = store.users[resource.provider_id]
    notice = build_notification(booking, slot, resource, provider, recipient, kind, scheduled)
    store.notifications[notice.id] = notice


def build_notification(
    booking, slot, resource, provider, recipient, kind, scheduled
) -> Notification:
    """Той самий payload для SQL-команди й демо-адаптера; без побічних записів."""
    payload = {
        "booking_id": str(booking.id),
        "resource_id": str(resource.id),
        "resource_name": resource.name,
        "provider_name": provider.full_name,
        "starts_at": slot.starts_at.isoformat(),
        "ends_at": slot.ends_at.isoformat(),
        "cancel_deadline_at": booking.cancel_deadline_at.isoformat(),
    }
    if booking.cancellation_reason:
        payload["reason"] = booking.cancellation_reason
    return Notification(uuid.uuid4(), booking.id, recipient, kind, payload, scheduled)


def booking_created(booking: BookingRec, now: datetime) -> None:
    """Підтвердження студенту, сповіщення провайдеру та відкладене нагадування."""
    _enqueue(booking, booking.student_id, "confirmation", now)
    provider = store.resources[store.slots[booking.slot_id].resource_id].provider_id
    _enqueue(booking, provider, "provider_created", now)
    due = store.reminders.get(booking.id)
    if due is not None:
        _enqueue(booking, booking.student_id, "reminder", due)


def booking_cancelled(booking: BookingRec, now: datetime, *, by_provider: bool = False) -> None:
    """Скасовує pending-нагадування; провайдер не отримує дубль власного блокування."""
    for notice in store.notifications.values():
        if (
            notice.booking_id == booking.id
            and notice.kind == "reminder"
            and notice.status in ("pending", "sending")
        ):
            notice.status = "cancelled"
            notice.claim_token = notice.locked_until = None
    store.reminders.pop(booking.id, None)
    if by_provider:
        _enqueue(booking, booking.student_id, "cancelled", now)
    else:
        provider = store.resources[store.slots[booking.slot_id].resource_id].provider_id
        _enqueue(booking, provider, "provider_cancelled", now)
