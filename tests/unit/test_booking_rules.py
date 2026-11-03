"""Доменні правила бронювання без HTTP, сховища й демо-даних (HLD §6, §9).

Кожен тест будує значення сам: інтервали, політику, момент `now`. Так перевіряються
межі правил — рівно в момент початку слота, рівно на межі горизонту, рівно в
граничний час скасування — без заморожування годинника й без TestClient.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from api.errors import ErrorCode
from unislot.booking.domain import rules
from unislot.booking.domain.errors import (
    BookingAlreadyCancelled,
    BookingLimitReached,
    BookingOverlap,
    BookingRuleViolation,
    CancellationDeadlinePassed,
    SlotAlreadyBooked,
    SlotBlocked,
    SlotOutOfHorizon,
    SlotStarted,
)
from unislot.booking.domain.model import BookingPolicy, BookingState, BookingStatus, Interval

NOW = datetime(2026, 10, 19, 9, 0, tzinfo=UTC)
HORIZON = timedelta(days=14)
POLICY = BookingPolicy(booking_limit=3, cancel_window=timedelta(hours=2))
US = timedelta(microseconds=1)


def slot_at(start: datetime, minutes: int = 30) -> Interval:
    return Interval(start, start + timedelta(minutes=minutes))


# --- Інтервал ------------------------------------------------------------------------


@pytest.mark.req("FR-011", "FR-035")
def test_adjacent_intervals_do_not_overlap() -> None:
    first = slot_at(NOW + timedelta(hours=1))
    second = slot_at(first.ends_at)
    assert not first.overlaps(second)
    assert not second.overlaps(first)


@pytest.mark.req("FR-010")
def test_interval_rejects_empty_or_reversed_time() -> None:
    with pytest.raises(ValueError, match="ends_at"):
        Interval(NOW, NOW)
    with pytest.raises(ValueError, match="ends_at"):
        Interval(NOW, NOW - US)


# --- Похідний стан -------------------------------------------------------------------


@pytest.mark.req("FR-036")
@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        (lambda s: s.starts_at - US, BookingState.ACTIVE),
        (lambda s: s.starts_at, BookingState.IN_PROGRESS),
        (lambda s: s.ends_at - US, BookingState.IN_PROGRESS),
        (lambda s: s.ends_at, BookingState.COMPLETED),
    ],
    ids=["до-початку", "у-момент-початку", "перед-кінцем", "у-момент-кінця"],
)
def test_derive_state_boundaries(moment, expected: BookingState) -> None:
    slot = slot_at(NOW + timedelta(days=1))
    assert rules.derive_state(BookingStatus.CONFIRMED, slot, moment(slot)) is expected


@pytest.mark.req("FR-036")
def test_cancelled_booking_is_cancelled_at_any_time() -> None:
    slot = slot_at(NOW + timedelta(days=1))
    for moment in (slot.starts_at - timedelta(days=1), slot.starts_at, slot.ends_at):
        assert rules.derive_state(BookingStatus.CANCELLED, slot, moment) is BookingState.CANCELLED


# --- Граничний час скасування (FR-041, A-003) ------------------------------------------


@pytest.mark.req("FR-041", "TP-01")
def test_cancel_deadline_is_slot_start_minus_window() -> None:
    start = NOW + timedelta(days=2)
    assert rules.cancel_deadline(start, POLICY) == start - timedelta(hours=2)


@pytest.mark.req("FR-040", "FR-041", "TP-01")
@pytest.mark.parametrize(
    ("state", "offset", "expected"),
    [
        (BookingState.ACTIVE, -US, True),
        (BookingState.ACTIVE, timedelta(0), True),  # рівно в граничний час — ще можна
        (BookingState.ACTIVE, US, False),
        (BookingState.IN_PROGRESS, -timedelta(hours=1), False),
        (BookingState.CANCELLED, -timedelta(hours=1), False),
    ],
)
def test_can_cancel(state: BookingState, offset: timedelta, expected: bool) -> None:
    deadline = NOW + timedelta(hours=5)
    assert rules.can_cancel(state, deadline, deadline + offset) is expected


# --- Чи можна забронювати слот (A-006, A-001, FR-014, INV-01) ----------------------------


@pytest.mark.req("FR-014", "FR-030", "FR-032", "FR-034", "TC-003")
@pytest.mark.parametrize(
    ("start", "blocked", "taken", "error"),
    [
        (NOW, False, False, SlotStarted),  # запис закривається в момент початку
        (NOW - timedelta(minutes=10), True, True, SlotStarted),  # «почався» — найперша причина
        (NOW + HORIZON + US, False, False, SlotOutOfHorizon),
        (NOW + timedelta(days=1), True, True, SlotBlocked),  # блокування важливіше за «зайнятий»
        (NOW + timedelta(days=1), False, True, SlotAlreadyBooked),
    ],
    ids=["почався-рівно-зараз", "почався-і-все-інше", "за-горизонтом", "заблокований", "зайнятий"],
)
def test_slot_not_bookable(start: datetime, blocked: bool, taken: bool, error: type) -> None:
    with pytest.raises(error):
        rules.ensure_slot_bookable(slot_at(start), NOW, HORIZON, blocked=blocked, taken=taken)


@pytest.mark.req("FR-030", "FR-034")
@pytest.mark.parametrize(
    "start", [NOW + US, NOW + HORIZON], ids=["одразу-після-now", "межа-горизонту"]
)
def test_slot_bookable_at_the_edges(start: datetime) -> None:
    rules.ensure_slot_bookable(slot_at(start), NOW, HORIZON, blocked=False, taken=False)


# --- Обмеження студента (A-002, FR-035, FR-044) ------------------------------------------


def _future_slots(count: int) -> list[Interval]:
    return [slot_at(NOW + timedelta(days=day)) for day in range(1, count + 1)]


@pytest.mark.req("FR-033")
def test_limit_reached_reports_limit_and_active_count() -> None:
    with pytest.raises(BookingLimitReached) as caught:
        rules.ensure_within_student_limits(
            _future_slots(3), slot_at(NOW + timedelta(days=5)), NOW, POLICY
        )
    assert caught.value.context == {"limit": 3, "active_bookings": 3}


@pytest.mark.req("FR-033")
def test_below_limit_is_allowed() -> None:
    rules.ensure_within_student_limits(
        _future_slots(2), slot_at(NOW + timedelta(days=5)), NOW, POLICY
    )


@pytest.mark.req("FR-033", "FR-035")
def test_booking_in_progress_does_not_count_against_limit_but_blocks_overlap() -> None:
    in_progress = Interval(NOW - timedelta(minutes=10), NOW + timedelta(minutes=20))
    # Три бронювання, але одне вже триває: активних лише два — ліміт не досягнуто.
    rules.ensure_within_student_limits(
        [in_progress, *_future_slots(2)], slot_at(NOW + timedelta(days=5)), NOW, POLICY
    )
    # А перетин із тим, що триває, — заборонений.
    with pytest.raises(BookingOverlap):
        rules.ensure_within_student_limits([in_progress], slot_at(NOW), NOW, POLICY)


@pytest.mark.req("FR-035")
def test_adjacent_booking_is_not_an_overlap() -> None:
    existing = slot_at(NOW + timedelta(days=1))
    rules.ensure_within_student_limits([existing], slot_at(existing.ends_at), NOW, POLICY)


@pytest.mark.req("FR-035", "FR-044")
def test_reschedule_ignores_limit_but_not_overlap() -> None:
    full = _future_slots(3)
    rules.ensure_within_student_limits(
        full, slot_at(NOW + timedelta(days=5)), NOW, POLICY, counts_against_limit=False
    )
    with pytest.raises(BookingOverlap):
        rules.ensure_within_student_limits(full, full[0], NOW, POLICY, counts_against_limit=False)


@pytest.mark.req("FR-035")
def test_without_policy_only_overlap_is_checked() -> None:
    rules.ensure_within_student_limits(
        _future_slots(10), slot_at(NOW + timedelta(days=20)), NOW, None
    )


# --- Скасування й перенесення (FR-040, FR-041, FR-045) -----------------------------------


@pytest.mark.req("FR-040")
def test_cancelled_booking_cannot_be_changed() -> None:
    slot = slot_at(NOW + timedelta(days=1))
    with pytest.raises(BookingAlreadyCancelled):
        rules.ensure_changeable(BookingStatus.CANCELLED, slot, slot.starts_at, NOW)


@pytest.mark.req("FR-045")
def test_started_slot_cannot_be_changed_even_before_deadline_check() -> None:
    slot = slot_at(NOW)
    with pytest.raises(SlotStarted):
        rules.ensure_changeable(BookingStatus.CONFIRMED, slot, NOW + timedelta(hours=1), NOW)


@pytest.mark.req("FR-040", "FR-041", "TP-01")
@pytest.mark.parametrize(
    ("offset", "allowed"),
    [(-US, True), (timedelta(0), True), (US, False)],
    ids=["до-граничного", "рівно-в-граничний", "після-граничного"],
)
def test_deadline_is_inclusive(offset: timedelta, allowed: bool) -> None:
    slot = slot_at(NOW + timedelta(days=1))
    deadline = rules.cancel_deadline(slot.starts_at, POLICY)
    now = deadline + offset
    if allowed:
        rules.ensure_changeable(BookingStatus.CONFIRMED, slot, deadline, now)
    else:
        with pytest.raises(CancellationDeadlinePassed) as caught:
            rules.ensure_changeable(BookingStatus.CONFIRMED, slot, deadline, now)
        assert caught.value.context == {"cancel_deadline_at": deadline}


# --- Контракт із REST API ----------------------------------------------------------------


def _all_subclasses(cls: type) -> list[type]:
    return [sub for direct in cls.__subclasses__() for sub in [direct, *_all_subclasses(direct)]]


@pytest.mark.req("QA-09")
def test_booking_error_codes_exist_in_api_catalog() -> None:
    """Кожна доменна помилка має опис у каталозі, інакше клієнт отримав би 500."""
    codes = {cls.code for cls in _all_subclasses(BookingRuleViolation)}
    assert codes <= {code.value for code in ErrorCode}
    assert len(codes) == 8
