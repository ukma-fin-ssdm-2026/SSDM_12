"""Lab6 prepared reference: test_kyiv_day_bounds.py. AI-assisted draft."""

from datetime import UTC, date, datetime, timedelta

import pytest

from api.slot_rules import kyiv_day_bounds


def test_summer_day_bounds_are_utc():
    start, end = kyiv_day_bounds(date(2026, 7, 21))
    assert start == datetime(2026, 7, 20, 21, tzinfo=UTC)
    assert end == datetime(2026, 7, 21, 21, tzinfo=UTC)
    assert end - start == timedelta(hours=24)


@pytest.mark.parametrize(("day", "hours"), [(date(2026, 10, 25), 25), (date(2026, 3, 29), 23)])
def test_day_length_follows_dst(day, hours):
    start, end = kyiv_day_bounds(day)
    assert end - start == timedelta(hours=hours)


def test_leap_day_ends_at_next_calendar_midnight():
    start, end = kyiv_day_bounds(date(2028, 2, 29))
    assert start == datetime(2028, 2, 28, 22, tzinfo=UTC)
    assert end == datetime(2028, 2, 29, 22, tzinfo=UTC)
