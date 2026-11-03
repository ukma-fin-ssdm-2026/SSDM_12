"""Регресії курсора та явна перевірка структури вводу. Чернетка з допомогою Codex."""

from __future__ import annotations

import base64
import json
import uuid
from datetime import UTC, datetime

import pytest

from api.errors import ApiProblem, ErrorCode
from api.pagination import cursor_fields, decode_cursor, encode_cursor

pytestmark = pytest.mark.req("QA-06")


def test_cursor_fields_preserves_strings():
    assert cursor_fields({"s": "time", "i": "uuid"}) == ("time", "uuid")


@pytest.mark.parametrize(
    "data", [None, [], {}, {"s": 7, "i": "id"}, {"s": "time", "i": 7}, {"s": "time"}]
)
def test_cursor_fields_rejects_invalid_shape(data):
    with pytest.raises(TypeError):
        cursor_fields(data)


def cursor(data):
    return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")


@pytest.mark.req("QA-11")
def test_cursor_roundtrip_and_urlsafe_alphabet():
    now = datetime(2026, 10, 25, 0, 30, tzinfo=UTC)
    item = uuid.UUID(int=123)
    encoded = encode_cursor(now, item)
    assert "=" not in encoded and "+" not in encoded and "/" not in encoded
    assert decode_cursor(encoded) == (now, item)


@pytest.mark.parametrize(
    "data",
    [
        None,
        [],
        {},
        {"s": 7, "i": str(uuid.UUID(int=1))},
        {"s": "2026-10-19T09:00:00", "i": str(uuid.UUID(int=1))},
        {"s": "bad", "i": str(uuid.UUID(int=1))},
        {"s": "2026-10-19T09:00:00Z", "i": "not-a-uuid"},
        {"s": "2026-10-19T09:00:00Z", "i": 7},
        {"s": "2026-10-19T09:00:00Z", "i": {}},
    ],
)
def test_invalid_cursor_shapes_become_validation_problem(data):
    with pytest.raises(ApiProblem) as error:
        decode_cursor(cursor(data))
    assert error.value.code is ErrorCode.VALIDATION_FAILED
    assert error.value.extensions["errors"][0]["field"] == "query.cursor"


@pytest.mark.parametrize("value", ["abc", "!!!!", "☃", "a" * 17])
def test_non_json_cursor_is_validation_problem(value):
    with pytest.raises(ApiProblem) as error:
        decode_cursor(value)
    assert error.value.code is ErrorCode.VALIDATION_FAILED
