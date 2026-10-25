"""Ізольовані тести BookingService: FR-030..045, часові межі та атомарність відмов.

Фікстури й заглушки ізолюють перевірки від HTTP та БД. Чернетка з допомогою Codex.
"""

from __future__ import annotations

import copy
import uuid
from datetime import timedelta
from unittest.mock import Mock

import pytest

from api.enums import BookingState, BookingStatus, CancellationKind
from api.errors import ApiProblem, ErrorCode
from api.stubs import booking_service as service
from api.stubs.store import Ids, store
from unislot.platform.errors import DomainError


@pytest.mark.parametrize(
    ("position", "expected"),
    [(-1, BookingState.ACTIVE), (0, BookingState.IN_PROGRESS), (30, BookingState.COMPLETED)],
)
def test_state_changes_at_start_and_end(position, expected):
    # Arrange: слот триває рівно тридцять хвилин.
    booking = store.bookings[Ids.BOOKING_ACTIVE]
    slot = store.slots[booking.slot_id]
    when = slot.starts_at + timedelta(minutes=position)
    # Act / Assert: граничний момент належить наступному стану.
    assert service.booking_state(booking, slot, when) is expected


def test_cancelled_state_has_priority_over_time(now):
    booking = store.bookings[Ids.BOOKING_CANCELLED]
    slot = store.slots[booking.slot_id]
    assert service.booking_state(booking, slot, now) is BookingState.CANCELLED


def test_cancel_exact_deadline_allowed(student):
    booking = store.bookings[Ids.BOOKING_ACTIVE]
    deadline = booking.cancel_deadline_at

    result = service.cancel(student, booking.id, deadline)

    assert result.status is BookingStatus.CANCELLED
    assert result.cancelled_at == deadline
    assert result.cancelled_by == student.id


def test_can_cancel_view_agrees_with_command_at_exact_deadline(student):
    booking = store.bookings[Ids.BOOKING_ACTIVE]
    deadline = booking.cancel_deadline_at
    assert service.to_out(booking, deadline).can_cancel is True
    service.cancel(student, booking.id, deadline)
    assert service.to_out(booking, deadline).can_cancel is False


def test_one_microsecond_after_deadline_preserves_booking(student):
    booking = store.bookings[Ids.BOOKING_ACTIVE]
    before = copy.deepcopy(booking)

    with pytest.raises(DomainError) as error:
        service.cancel(student, booking.id, booking.cancel_deadline_at + timedelta(microseconds=1))

    assert error.value.code == ErrorCode.CANCELLATION_DEADLINE_PASSED
    assert error.value.context["cancel_deadline_at"] == booking.cancel_deadline_at
    assert booking == before


def test_cancel_at_slot_start_is_forbidden(student):
    booking = store.bookings[Ids.BOOKING_ACTIVE]
    slot = store.slots[booking.slot_id]
    with pytest.raises(DomainError) as error:
        service.cancel(student, booking.id, slot.starts_at)
    assert error.value.code == ErrorCode.SLOT_STARTED
    assert booking.status is BookingStatus.CONFIRMED


def test_foreign_booking_cannot_be_changed(student, now):
    before = copy.deepcopy(store.bookings)
    with pytest.raises(ApiProblem) as error:
        service.cancel(student, Ids.BOOKING_OTHER, now)
    assert error.value.code == ErrorCode.NOT_OWNER
    assert store.bookings == before


def test_missing_booking_is_distinct_from_forbidden(student):
    with pytest.raises(ApiProblem) as error:
        service.get_owned(student, uuid.UUID(int=0))
    assert error.value.code == ErrorCode.BOOKING_NOT_FOUND


def test_policy_change_does_not_rewrite_saved_deadline(student, now):
    booking, _ = service.book(student, Ids.SLOT_DB_D1_1030, now)
    saved = booking.cancel_deadline_at
    store.policy.cancel_window = timedelta(hours=8)
    assert service.to_out(booking, now).cancel_deadline_at == saved


def test_idempotency_is_scoped_to_user(student, other_student, now):
    first, replayed = service.book(student, Ids.SLOT_DB_D1_1030, now, "same-key-001")
    other, other_replayed = service.book(other_student, Ids.SLOT_NET_D4_0900, now, "same-key-001")
    assert first.id != other.id
    assert not replayed and not other_replayed


def test_replay_does_not_recheck_availability(student, now, monkeypatch):
    first, _ = service.book(student, Ids.SLOT_DB_D1_1030, now, "same-key-001")
    unavailable = Mock(side_effect=AssertionError("replay must not create a booking"))
    monkeypatch.setattr(service, "_check_slot_bookable", unavailable)

    again, replayed = service.book(student, first.slot_id, now, "same-key-001")

    assert replayed and again.id == first.id
    unavailable.assert_not_called()


@pytest.mark.parametrize(
    ("new_slot", "error_type", "code"),
    [
        (Ids.SLOT_DB_D1_1000, DomainError, ErrorCode.SLOT_ALREADY_BOOKED),
        (uuid.UUID(int=0), ApiProblem, ErrorCode.SLOT_NOT_FOUND),
    ],
)
def test_failed_reschedule_is_atomic(student, now, new_slot, error_type, code):
    before = copy.deepcopy(store.bookings)
    with pytest.raises(error_type) as error:
        service.reschedule(student, Ids.BOOKING_ACTIVE, new_slot, now)
    assert error.value.code == code
    assert store.bookings == before


def test_reschedule_rejects_student_overlap(student, now):
    before = copy.deepcopy(store.bookings)
    # Інтервал перетинає BOOKING_SOON: його не можна ігнорувати як попереднє бронювання.
    slot = copy.deepcopy(store.slots[Ids.SLOT_NET_SOON])
    slot.id = uuid.UUID(int=91)
    store.slots[slot.id] = slot
    with pytest.raises(DomainError) as error:
        service.reschedule(student, Ids.BOOKING_ACTIVE, slot.id, now)
    assert error.value.code == ErrorCode.BOOKING_OVERLAP
    assert store.bookings == before


def test_successful_reschedule_links_successor_and_keeps_count(student, now):
    before = len(service._open_bookings(student.id, now))
    new = service.reschedule(student, Ids.BOOKING_ACTIVE, Ids.SLOT_DB_D2_1030, now)
    old = store.bookings[Ids.BOOKING_ACTIVE]
    assert old.rescheduled_to_id == new.id
    assert old.cancellation_kind is CancellationKind.RESCHEDULED
    assert len(service._open_bookings(student.id, now)) == before


def test_list_total_is_count_before_pagination(student, now):
    rows, total = service.list_mine(student, None, 1, 1, now)
    assert len(rows) == 1 and total == 4
    assert rows[0].student_id == student.id
    empty, same_total = service.list_mine(student, None, 10, 99, now)
    assert empty == [] and same_total == total
