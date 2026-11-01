"""FR-012: календарна генерація незалежно від HTTP та сховища."""

from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from unislot.availability.domain.templates import WeeklyPattern, generate_occurrences

pytestmark = pytest.mark.req("FR-012", "TC-031")
KYIV = ZoneInfo("Europe/Kyiv")
NOW = datetime(2026, 10, 19, 9, tzinfo=UTC)
PATTERN = WeeklyPattern(3, time(14), time(16), 30, date(2026, 10, 19))
HORIZON = timedelta(days=14)


def test_kyiv_wall_time_is_preserved_across_fall_clock_change() -> None:
    slots, conflicts = generate_occurrences(PATTERN, NOW, HORIZON, KYIV)
    assert not conflicts and len(slots) == 8
    assert slots[0].starts_at == datetime(2026, 10, 21, 11, tzinfo=UTC)
    assert slots[4].starts_at == datetime(2026, 10, 28, 12, tzinfo=UTC)
    assert all(s.ends_at - s.starts_at == timedelta(minutes=30) for s in slots)
    assert (
        slots[0].starts_at.astimezone(KYIV).hour == slots[4].starts_at.astimezone(KYIV).hour == 14
    )


def test_kyiv_wall_time_is_preserved_across_spring_clock_change() -> None:
    now = datetime(2026, 3, 16, 9, tzinfo=UTC)
    pattern = replace(PATTERN, weekday=7, valid_from=now.date())
    slots, conflicts = generate_occurrences(pattern, now, HORIZON, KYIV)
    assert not conflicts and len(slots) == 8
    assert slots[0].starts_at == datetime(2026, 3, 22, 12, tzinfo=UTC)
    assert slots[4].starts_at == datetime(2026, 3, 29, 11, tzinfo=UTC)


@pytest.mark.parametrize(
    ("now", "code"),
    [
        (datetime(2026, 3, 16, 9, tzinfo=UTC), "nonexistent_local_time"),
        (NOW, "ambiguous_local_time"),
    ],
)
def test_dst_gap_or_fold_is_reported_without_guessing(now: datetime, code: str) -> None:
    pattern = WeeklyPattern(7, time(3), time(4), 30, now.date())
    slots, conflicts = generate_occurrences(pattern, now, HORIZON, KYIV)
    assert len(conflicts) == 2
    assert {c.code for c in conflicts} == {code}
    assert not {s.starts_at.astimezone(KYIV).date() for s in slots} & {c.day for c in conflicts}


def test_slot_crossing_transition_cannot_change_its_absolute_duration() -> None:
    pattern = WeeklyPattern(7, time(2, 30), time(4, 30), 120, NOW.date())
    _, conflicts = generate_occurrences(pattern, NOW, HORIZON, KYIV)
    assert [c.code for c in conflicts] == ["dst_duration"]


def test_validity_dates_are_inclusive() -> None:
    pattern = replace(PATTERN, valid_from=date(2026, 10, 21), valid_to=date(2026, 10, 21))
    slots, conflicts = generate_occurrences(pattern, NOW, HORIZON, KYIV)
    assert len(slots) == 4 and not conflicts
    assert {s.starts_at.astimezone(KYIV).date() for s in slots} == {date(2026, 10, 21)}


def test_only_start_inside_the_absolute_horizon_is_materialized() -> None:
    now = datetime(2026, 10, 21, 11, tzinfo=UTC)  # Рівно 14:00 за Києвом.
    slots, _ = generate_occurrences(PATTERN, now, timedelta(minutes=30), KYIV)
    assert [s.starts_at for s in slots] == [now + timedelta(minutes=30)]


def test_rule_outside_its_validity_has_no_occurrences() -> None:
    pattern = replace(PATTERN, valid_to=date(2026, 10, 19))
    assert generate_occurrences(pattern, NOW, HORIZON, KYIV) == ([], [])


@pytest.mark.parametrize(
    "changes",
    [
        {"weekday": 0},
        {"weekday": True},
        {"slot_minutes": 0},
        {"slot_minutes": True},
        {"start_local": time(14, tzinfo=UTC)},
        {"start_local": time(14, 0, 1)},
        {"end_local": time(13)},
        {"end_local": time(15, 1)},
        {"valid_to": date(2026, 10, 18)},
    ],
)
def test_invalid_pattern_cannot_enter_the_generator(changes: dict) -> None:
    with pytest.raises(ValueError, match=r"weekday|slot_minutes|локальний час|проміжок|valid_to"):
        replace(PATTERN, **changes)


@pytest.mark.parametrize(
    ("now", "horizon"),
    [
        (NOW.replace(tzinfo=None), HORIZON),
        (NOW, timedelta(0)),
    ],
)
def test_generator_requires_absolute_now_and_positive_horizon(now, horizon) -> None:
    with pytest.raises(ValueError, match="now із часовим поясом та додатний горизонт"):
        generate_occurrences(PATTERN, now, horizon, KYIV)


def test_ambiguous_candidates_outside_the_horizon_are_not_reported() -> None:
    now = datetime(2026, 10, 11, 0, tzinfo=UTC)
    pattern = WeeklyPattern(7, time(3), time(4), 30, now.date())
    _, conflicts = generate_occurrences(pattern, now, HORIZON, KYIV)
    assert [(c.day, c.start_local) for c in conflicts] == [(date(2026, 10, 25), time(3))]
