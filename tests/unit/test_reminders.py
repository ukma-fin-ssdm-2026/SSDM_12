"""Момент нагадування про бронювання (A-004, FR-051; TP-12) — тести-специфікація.

Лаб 7, бонус 3: тести написано до реалізації й закомічено червоними — модуля
`unislot.notifications.domain.reminders` на той момент не існувало. Вони кажуть агенту,
що означає «коректно», точніше за промпт: межі A-004, абсолютний час через перехід на
зимовий час і відмова від часу без поясу (A-007). Що відбувається з нагадуванням,
коли бронювання скасовують чи переносять, задає `tests/api/test_booking_reminders.py`.

Рішення, які задають ці тести (власні, а не зі специфікації вимог):
- рівно за 24 год до початку нагадування ще планується: A-004 відсікає лише бронювання,
  створені *пізніше*, ніж за 24 год;
- 24 год — абсолютний проміжок часу, а не «та сама година напередодні» за Києвом.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from api.policy import KYIV
from unislot.notifications.domain.reminders import REMINDER_LEAD, reminder_due_at

pytestmark = pytest.mark.req("US-005", "FR-051", "TP-12")

US = timedelta(microseconds=1)
START = datetime(2026, 10, 22, 8, 0, tzinfo=UTC)  # четвер, 11:00 за Києвом


def test_lead_is_24_hours_as_in_a004() -> None:
    assert timedelta(hours=24) == REMINDER_LEAD


@pytest.mark.req("TC-017")
def test_reminder_is_planned_24_hours_before_start() -> None:
    booked_at = datetime(2026, 10, 19, 9, 0, tzinfo=UTC)
    assert reminder_due_at(START, booked_at) == datetime(2026, 10, 21, 8, 0, tzinfo=UTC)


def test_booking_exactly_24_hours_ahead_still_gets_a_reminder() -> None:
    booked_at = START - REMINDER_LEAD
    assert reminder_due_at(START, booked_at) == booked_at


@pytest.mark.req("TC-018")
@pytest.mark.parametrize(
    "booked_at",
    [START - REMINDER_LEAD + US, START - timedelta(hours=1), START, START + timedelta(hours=1)],
    ids=["24h-minus-1us", "1h-before", "at-start", "after-start"],
)
def test_booking_later_than_24_hours_ahead_gets_only_confirmation(booked_at: datetime) -> None:
    assert reminder_due_at(START, booked_at) is None


def test_lead_is_absolute_time_across_the_dst_change() -> None:
    """25.10.2026 о 01:00 UTC Київ переходить з UTC+3 на UTC+2 (A-007)."""
    slot_start = datetime(2026, 10, 25, 8, 0, tzinfo=UTC)  # неділя, 10:00 за Києвом (UTC+2)
    due = reminder_due_at(slot_start, datetime(2026, 10, 20, 9, 0, tzinfo=UTC))
    assert due == datetime(2026, 10, 24, 8, 0, tzinfo=UTC)  # рівно 24 год
    assert due is not None and due.astimezone(KYIV).hour == 11  # субота, 11:00 (UTC+3)


def test_custom_lead_is_respected() -> None:
    booked_at = datetime(2026, 10, 19, 9, 0, tzinfo=UTC)
    assert reminder_due_at(START, booked_at, lead=timedelta(hours=2)) == START - timedelta(hours=2)


@pytest.mark.parametrize(
    ("slot_start", "booked_at"),
    [
        (START.replace(tzinfo=None), datetime(2026, 10, 19, 9, 0, tzinfo=UTC)),
        (START, datetime(2026, 10, 19, 9, 0)),  # без поясу — саме це й перевіряємо
    ],
    ids=["naive-slot-start", "naive-booked-at"],
)
def test_time_without_zone_is_rejected(slot_start: datetime, booked_at: datetime) -> None:
    with pytest.raises(ValueError, match="часов"):
        reminder_due_at(slot_start, booked_at)


@pytest.mark.parametrize("lead", [timedelta(0), timedelta(hours=-1)], ids=["zero", "negative"])
def test_non_positive_lead_is_rejected(lead: timedelta) -> None:
    with pytest.raises(ValueError, match="lead"):
        reminder_due_at(START, datetime(2026, 10, 19, 9, 0, tzinfo=UTC), lead=lead)
