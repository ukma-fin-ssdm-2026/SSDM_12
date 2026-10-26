"""Lab6 prepared reference: test_request_ids.py. AI-assisted draft."""

import uuid

import pytest

from api.request_ids import normalize_request_id


def test_valid_identifier_is_preserved():
    assert normalize_request_id("client-id_01") == "client-id_01"


@pytest.mark.parametrize("candidate", ["", "short", "a" * 65, "line\nbreak", "україна123"])
def test_unsafe_identifier_is_replaced(candidate, monkeypatch):
    fixed = uuid.UUID(int=77)
    monkeypatch.setattr("api.request_ids.uuid.uuid4", lambda: fixed, raising=False)
    assert normalize_request_id(candidate) == fixed.hex


@pytest.mark.parametrize("size", [8, 64])
def test_valid_identifier_length_bounds(size):
    assert normalize_request_id("a" * size) == "a" * size


def test_missing_identifier_generates_one(monkeypatch):
    fixed = uuid.UUID(int=99)
    monkeypatch.setattr("api.request_ids.uuid.uuid4", lambda: fixed)
    assert normalize_request_id(None) == fixed.hex
