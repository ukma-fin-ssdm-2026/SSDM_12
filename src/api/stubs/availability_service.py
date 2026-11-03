"""Блокування власного ресурсу через memory/PostgreSQL StoreProxy (FR-013/014)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from api.enums import BookingStatus, CancellationKind, Role
from api.errors import ApiProblem, ErrorCode, validation_problem
from api.schemas.availability import TimeBlockCreate, TimeBlockOut
from api.security import CurrentUser
from api.stubs import notification_service
from api.stubs.store import TimeBlockRec, store


def check_owner(actor: CurrentUser, resource_id: uuid.UUID) -> None:
    """Під lock перевіряє чинну роль і власника ресурсу (SEC-002, SEC-004)."""
    user = store.users.get(actor.id)
    if user is None or Role.PROVIDER not in user.roles:
        raise ApiProblem(ErrorCode.FORBIDDEN_ROLE)
    resource = store.resources.get(resource_id)
    if resource is None:
        raise ApiProblem(ErrorCode.RESOURCE_NOT_FOUND)
    if resource.provider_id != actor.id:
        raise ApiProblem(ErrorCode.NOT_OWNER)


def create_block(
    actor: CurrentUser,
    resource_id: uuid.UUID,
    data: TimeBlockCreate,
    now: datetime,
) -> TimeBlockOut:
    """Атомарно блокує час і скасовує майбутні бронювання разом із нагадуваннями.

    FR-045: бронювання, що вже почалося, не скасовується навіть провайдером;
    у такому разі весь запит відхиляється до будь-якої зміни стану.
    """
    with store.lock:
        check_owner(actor, resource_id)
        starts_at, ends_at = data.starts_at.astimezone(UTC), data.ends_at.astimezone(UTC)
        if starts_at < now:
            raise validation_problem(
                "Блокування починається в минулому.",
                field="body.starts_at",
                kind="time_in_past",
                message="Оберіть поточний або майбутній момент",
            )
        affected = []
        for booking in store.bookings.values():
            slot = store.slots[booking.slot_id]
            if (
                booking.status is BookingStatus.CONFIRMED
                and slot.resource_id == resource_id
                and slot.starts_at < ends_at
                and starts_at < slot.ends_at
            ):
                if slot.starts_at <= now:
                    raise ApiProblem(ErrorCode.SLOT_STARTED)
                affected.append(booking)
        rec = TimeBlockRec(uuid.uuid4(), resource_id, starts_at, ends_at, data.reason)
        store.blocks[rec.id] = rec
        for booking in affected:
            booking.status = BookingStatus.CANCELLED
            booking.cancelled_at = now
            booking.cancelled_by = actor.id
            booking.cancellation_kind = CancellationKind.PROVIDER_BLOCK
            booking.cancellation_reason = data.reason
            notification_service.booking_cancelled(booking, now, by_provider=True)
        return TimeBlockOut(
            id=rec.id,
            resource_id=rec.resource_id,
            starts_at=rec.starts_at,
            ends_at=rec.ends_at,
            reason=rec.reason,
            cancelled_bookings=len(affected),
        )


def remove_block(actor: CurrentUser, resource_id: uuid.UUID, block_id: uuid.UUID) -> None:
    """Знімає власне блокування; раніше скасовані бронювання не відновлюються."""
    with store.lock:
        check_owner(actor, resource_id)
        rec = store.blocks.get(block_id)
        if rec is None or rec.resource_id != resource_id:
            raise ApiProblem(ErrorCode.BLOCK_NOT_FOUND)
        del store.blocks[block_id]
