"""Slot discovery/publication unit tests, including Kyiv and half-open boundaries.

Local AI draft: Codex; no HTTP server or external state is required.
"""

from __future__ import annotations

import copy
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest

from api.enums import ResourceType
from api.errors import ApiProblem, ErrorCode
from api.policy import HORIZON, KYIV
from api.schemas.slots import SlotCreate
from api.stubs import slot_service as service
from api.stubs.store import Ids, store


@pytest.mark.parametrize(
    ("delta", "available"),
    [(timedelta(0), False), (timedelta(microseconds=1), True), (HORIZON, True)],
)
def test_availability_boundaries(now, delta, available):
    slot = copy.deepcopy(store.slots[Ids.SLOT_DB_D1_1030])
    slot.starts_at = now + delta
    slot.ends_at = slot.starts_at + timedelta(minutes=30)
    assert service.is_free(slot, now) is available


def test_one_microsecond_outside_horizon_is_unavailable(now):
    slot = copy.deepcopy(store.slots[Ids.SLOT_DB_D1_1030])
    slot.starts_at = now + HORIZON + timedelta(microseconds=1)
    assert not service.is_free(slot, now)


@pytest.mark.parametrize("slot_id", [Ids.SLOT_DB_D1_1000, Ids.SLOT_317_D2_1500])
def test_occupied_and_blocked_slots_are_not_free(slot_id, now):
    assert not service.is_free(store.slots[slot_id], now)


def test_availability_short_circuits_after_taken_slot(monkeypatch, now):
    slot = store.slots[Ids.SLOT_DB_D1_1030]
    blocked = Mock(side_effect=AssertionError("unnecessary block lookup"))
    monkeypatch.setattr(store, "confirmed_booking_for_slot", Mock(return_value=object()))
    monkeypatch.setattr(store, "is_blocked", blocked)
    assert not service.is_free(slot, now)
    blocked.assert_not_called()


def test_search_date_uses_kyiv_day_not_utc_day():
    late_utc = datetime(2026, 10, 19, 22, tzinfo=UTC)
    local_day = late_utc.astimezone(KYIV).date()
    service.check_search_date(local_day, late_utc)
    with pytest.raises(ApiProblem) as error:
        service.check_search_date(local_day - timedelta(days=1), late_utc)
    assert error.value.code is ErrorCode.DATE_OUT_OF_HORIZON


def test_search_date_accepts_last_day_across_dst(now):
    service.check_search_date((now + HORIZON).astimezone(KYIV).date(), now)
    with pytest.raises(ApiProblem):
        service.check_search_date((now + HORIZON).astimezone(KYIV).date() + timedelta(days=1), now)


def search(now, **changes):
    args = {
        "now": now,
        "provider_id": None,
        "resource_type": None,
        "day": None,
        "min_capacity": None,
        "limit": 100,
        "cursor": None,
    }
    return service.search_free(**(args | changes))


def test_capacity_filter_excludes_consultations(now):
    rows, _ = search(now, min_capacity=20)
    assert rows
    assert all(store.resources[s.resource_id].type is ResourceType.ROOM for s in rows)
    assert all(store.resources[s.resource_id].capacity >= 20 for s in rows)


def test_cursor_pages_do_not_repeat_when_slot_becomes_occupied(now, other_student):
    from api.stubs import booking_service

    first, cursor = search(now, limit=1)
    assert cursor
    booking_service.book(other_student, first[0].id, now)
    second, _ = search(now, limit=100, cursor=cursor)
    assert first[0].id not in [s.id for s in second]
    assert all((s.starts_at, str(s.id)) > (first[0].starts_at, str(first[0].id)) for s in second)


def test_tied_times_use_uuid_as_tiebreaker(now):
    first = copy.deepcopy(store.slots[Ids.SLOT_DB_D1_1030])
    second = copy.deepcopy(first)
    first.id, second.id = uuid.UUID(int=1), uuid.UUID(int=2)
    store.slots.clear()
    store.slots.update({second.id: second, first.id: first})
    page, cursor = search(now, limit=1)
    following, end = search(now, limit=1, cursor=cursor)
    assert [page[0].id, following[0].id] == [first.id, second.id]
    assert end is None


def test_create_converts_timezone_and_accepts_adjacent_slot(provider, now):
    previous = store.slots[Ids.SLOT_DB_D1_1100]
    data = SlotCreate(starts_at=previous.ends_at.astimezone(KYIV), duration_minutes=30)
    created = service.create_slot(provider, previous.resource_id, data, now)
    assert created.starts_at == previous.ends_at
    assert created.starts_at.tzinfo is UTC
    assert created.ends_at - created.starts_at == timedelta(minutes=30)


@pytest.mark.parametrize("resource_id", [Ids.RES_ROOM_1_225, uuid.UUID(int=0)])
def test_failed_creation_has_no_side_effects(provider, now, resource_id):
    before = copy.deepcopy(store.slots)
    data = SlotCreate(starts_at=now + timedelta(days=1), duration_minutes=30)
    with pytest.raises(ApiProblem):
        service.create_slot(provider, resource_id, data, now)
    assert store.slots == before
