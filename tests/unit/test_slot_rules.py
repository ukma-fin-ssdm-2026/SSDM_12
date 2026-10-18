"""Pure search-date rule and slot availability checks without HTTP."""

from __future__ import annotations

from datetime import timedelta

import pytest

from api import clock
from api.errors import ApiProblem
from api.policy import HORIZON, KYIV
from api.stubs.slot_service import check_search_date, is_free
from api.stubs.store import Ids, store


@pytest.mark.parametrize(
    ("offset_days", "allowed"),
    [
        (-1, False),
        (0, True),
        (1, True),
        (7, True),
        (14, True),
        (15, False),
    ],
)
def test_search_date_horizon(offset_days: int, allowed: bool) -> None:
    now = clock.utc_now()
    first = now.astimezone(KYIV).date()
    last = (now + HORIZON).astimezone(KYIV).date()
    target = first + timedelta(days=offset_days)

    if allowed:
        assert first <= target <= last
        check_search_date(target, now)
    else:
        with pytest.raises(ApiProblem):
            check_search_date(target, now)


@pytest.mark.parametrize(
    ("slot_id", "expected"),
    [
        (Ids.SLOT_DB_D1_1030, True),
        (Ids.SLOT_DB_D1_1000, False),  # booked
        (Ids.SLOT_317_D2_1500, False),  # blocked
        (Ids.SLOT_DB_STARTED, False),
        (Ids.SLOT_DB_D20, False),  # outside booking horizon
    ],
)
def test_slot_availability_rule(slot_id, expected: bool) -> None:
    slot = store.slots[slot_id]
    assert is_free(slot, clock.utc_now()) is expected
