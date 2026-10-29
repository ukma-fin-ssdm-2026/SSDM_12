"""Unit and property-based tests for the cursor codec, independent of HTTP."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta, timezone

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from api.errors import ApiProblem
from api.pagination import decode_cursor, encode_cursor

pytestmark = pytest.mark.req("QA-11")


@pytest.mark.parametrize(
    ("offset_hours", "offset_minutes"),
    [(-5, 0), (0, 0), (2, 0), (5, 30)],
)
def test_cursor_roundtrip_with_timezones(offset_hours: int, offset_minutes: int) -> None:
    zone = timezone(timedelta(hours=offset_hours, minutes=offset_minutes))
    starts_at = datetime(2026, 10, 19, 9, 30, 45, tzinfo=zone)
    item_id = uuid.UUID("12345678-1234-4234-8234-123456789012")

    assert decode_cursor(encode_cursor(starts_at, item_id)) == (starts_at, item_id)


@pytest.mark.req("QA-06")
@pytest.mark.parametrize(
    "bad_cursor",
    ["", "not-a-cursor", "e30", "bm90LWpzb24", "%%%%"],
)
def test_invalid_cursor_is_rejected(bad_cursor: str) -> None:
    with pytest.raises(ApiProblem):
        decode_cursor(bad_cursor)


@settings(max_examples=60)
@given(
    starts_at=st.datetimes(
        min_value=datetime(2000, 1, 1),
        max_value=datetime(2100, 12, 31),
        timezones=st.just(UTC),
    ),
    item_id=st.uuids(),
)
def test_cursor_roundtrip_property(starts_at: datetime, item_id: uuid.UUID) -> None:
    """Arbitrary valid UTC timestamps and UUIDs survive a round-trip unchanged."""
    encoded = encode_cursor(starts_at, item_id)
    assert decode_cursor(encoded) == (starts_at, item_id)
