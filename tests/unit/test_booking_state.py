"""Direct booking-state checks: no HTTP transport or TestClient."""

from __future__ import annotations

from datetime import timedelta

import pytest

from api.enums import BookingState, BookingStatus
from api.stubs.booking_service import booking_state
from api.stubs.store import Ids, store


@pytest.mark.parametrize(
    ("instant", "expected"),
    [
        ("before", BookingState.ACTIVE),
        ("at_start", BookingState.IN_PROGRESS),
        ("during", BookingState.IN_PROGRESS),
        ("at_end", BookingState.COMPLETED),
        ("after", BookingState.COMPLETED),
    ],
)
def test_confirmed_booking_state_boundaries(instant: str, expected: BookingState) -> None:
    booking = store.bookings[Ids.BOOKING_ACTIVE]
    slot = store.slots[booking.slot_id]
    assert booking.status is BookingStatus.CONFIRMED

    instants = {
        "before": slot.starts_at - timedelta(microseconds=1),
        "at_start": slot.starts_at,
        "during": slot.starts_at + (slot.ends_at - slot.starts_at) / 2,
        "at_end": slot.ends_at,
        "after": slot.ends_at + timedelta(microseconds=1),
    }
    assert booking_state(booking, slot, instants[instant]) is expected


@pytest.mark.parametrize("instant", ["before", "at_start", "after"])
def test_cancelled_booking_stays_cancelled(instant: str) -> None:
    booking = store.bookings[Ids.BOOKING_ACTIVE]
    booking.status = BookingStatus.CANCELLED
    slot = store.slots[booking.slot_id]
    instants = {
        "before": slot.starts_at - timedelta(days=1),
        "at_start": slot.starts_at,
        "after": slot.ends_at + timedelta(days=1),
    }

    assert booking_state(booking, slot, instants[instant]) is BookingState.CANCELLED
