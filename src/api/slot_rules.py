"""Lab6 prepared reference: slot_rules.py. AI-assisted draft."""

from datetime import UTC, date, datetime, time, timedelta

from api.policy import KYIV


def kyiv_day_bounds(day: date) -> tuple[datetime, datetime]:
    """A-007: half-open UTC interval of a Kyiv date, including 23/25-hour DST days."""
    first = datetime.combine(day, time.min, tzinfo=KYIV)
    following = datetime.combine(day + timedelta(days=1), time.min, tzinfo=KYIV)
    return first.astimezone(UTC), following.astimezone(UTC)
