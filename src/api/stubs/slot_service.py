"""Заглушки `SlotSearch` і публікації слотів з `AvailabilityService` (HLD §5.2) для Лаб 4."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

from api.enums import ResourceType
from api.errors import ApiProblem, ErrorCode
from api.pagination import decode_cursor, encode_cursor
from api.policy import HORIZON, KYIV
from api.schemas.common import PersonSummary, ResourceSummary
from api.schemas.slots import SlotCreate, SlotDetail, SlotOut
from api.security import CurrentUser
from api.slot_rules import kyiv_day_bounds
from api.stubs.store import SlotRec, store


def _minutes(slot: SlotRec) -> int:
    return int((slot.ends_at - slot.starts_at).total_seconds() // 60)


def to_out(slot: SlotRec) -> SlotOut:
    """Схема слота для пошуку: час, тривалість, ресурс і провайдер (лише ім'я)."""
    resource = store.resources[slot.resource_id]
    provider = store.users[resource.provider_id]
    return SlotOut(
        id=slot.id,
        starts_at=slot.starts_at,
        ends_at=slot.ends_at,
        duration_minutes=_minutes(slot),
        resource=ResourceSummary(
            id=resource.id, name=resource.name, type=resource.type, capacity=resource.capacity
        ),
        provider=PersonSummary(id=provider.id, full_name=provider.full_name),
    )


def to_detail(slot: SlotRec, now: datetime) -> SlotDetail:
    """Схема одного слота з ознакою `available` на момент `now`."""
    return SlotDetail(**to_out(slot).model_dump(), available=is_free(slot, now))


def is_free(slot: SlotRec, now: datetime) -> bool:
    """Вільний слот (FR-020, FR-023): у межах горизонту, ще не почався,
    не зайнятий і не заблокований."""
    return (
        now < slot.starts_at <= now + HORIZON
        and store.confirmed_booking_for_slot(slot.id) is None
        and not store.is_blocked(slot)
    )


def check_search_date(day: date, now: datetime) -> None:
    """Дата пошуку має лежати між сьогодні й кінцем горизонту A-001 (за Києвом)."""
    first, last = now.astimezone(KYIV).date(), (now + HORIZON).astimezone(KYIV).date()
    if not first <= day <= last:
        raise ApiProblem(
            ErrorCode.DATE_OUT_OF_HORIZON,
            f"Пошук доступний для дат від {first} до {last} включно (A-001).",
        )


def search_free(
    *,
    now: datetime,
    provider_id: uuid.UUID | None,
    resource_type: ResourceType | None,
    day: date | None,
    min_capacity: int | None,
    limit: int,
    cursor: str | None,
) -> tuple[list[SlotRec], str | None]:
    """Вільні слоти за фільтрами, упорядковані за (starts_at, id); повертає сторінку й курсор.

    `min_capacity` застосовується лише до аудиторій: якщо фільтр задано, консультації
    з результатів зникають (FR-022, US-004).
    """
    if day is not None:
        check_search_date(day, now)
    bounds = kyiv_day_bounds(day) if day is not None else None
    after = decode_cursor(cursor) if cursor else None
    found = []
    for slot in store.slots.values():
        resource = store.resources[slot.resource_id]
        if not is_free(slot, now):
            continue
        if provider_id is not None and resource.provider_id != provider_id:
            continue
        if resource_type is not None and resource.type is not resource_type:
            continue
        if bounds is not None and not bounds[0] <= slot.starts_at < bounds[1]:
            continue
        if min_capacity is not None and (
            resource.type is not ResourceType.ROOM or (resource.capacity or 0) < min_capacity
        ):
            continue
        if after is not None and (slot.starts_at, str(slot.id)) <= (after[0], str(after[1])):
            continue
        found.append(slot)
    found.sort(key=lambda s: (s.starts_at, str(s.id)))
    page = found[: limit + 1]  # «limit + 1»: чи є наступна сторінка — без окремого підрахунку
    has_more = len(page) > limit
    page = page[:limit]
    next_cursor = encode_cursor(page[-1].starts_at, page[-1].id) if has_more else None
    return page, next_cursor


def get_slot(slot_id: uuid.UUID) -> SlotRec:
    """Слот за id або 404 `SLOT_NOT_FOUND`."""
    slot = store.slots.get(slot_id)
    if slot is None:
        raise ApiProblem(ErrorCode.SLOT_NOT_FOUND)
    return slot


def create_slot(
    actor: CurrentUser, resource_id: uuid.UUID, data: SlotCreate, now: datetime
) -> SlotRec:
    """Разовий слот (FR-010, FR-011): лише на власному ресурсі, у майбутньому, без перетинів."""
    with store.lock:
        resource = store.resources.get(resource_id)
        if resource is None:
            raise ApiProblem(ErrorCode.RESOURCE_NOT_FOUND)
        if resource.provider_id != actor.id:
            raise ApiProblem(ErrorCode.NOT_OWNER, "Слоти створює лише провайдер цього ресурсу.")
        if data.starts_at <= now:
            raise ApiProblem(ErrorCode.SLOT_IN_PAST)
        starts_at = data.starts_at.astimezone(UTC)  # зберігаємо в UTC (A-007)
        ends_at = starts_at + timedelta(minutes=data.duration_minutes)
        clash = next(
            (
                s
                for s in store.slots.values()
                if s.resource_id == resource_id and s.starts_at < ends_at and starts_at < s.ends_at
            ),
            None,
        )
        if clash is not None:
            raise ApiProblem(
                ErrorCode.SLOT_OVERLAP,
                "На цьому ресурсі вже є слот, що перетинається з новим; "
                "суміжні слоти (кінець одного = початок іншого) дозволені.",
            )
        slot = SlotRec(
            id=uuid.uuid4(), resource_id=resource_id, starts_at=starts_at, ends_at=ends_at
        )
        store.slots[slot.id] = slot
        return slot
