"""Lab6 prepared reference: test_resource_rules.py. AI-assisted draft."""

import pytest

from api.enums import ResourceType
from api.resource_rules import capacity_valid

pytestmark = pytest.mark.req("FR-060", "QA-06", "TC-044", "TP-07")


def test_room_requires_capacity():
    assert capacity_valid(ResourceType.ROOM, 20)
    assert not capacity_valid(ResourceType.ROOM, None)


def test_consultation_cannot_have_capacity():
    assert capacity_valid(ResourceType.CONSULTATION, None)
    assert not capacity_valid(ResourceType.CONSULTATION, 20)


@pytest.mark.parametrize("value", [1, 1000])
def test_room_capacity_inclusive_bounds(value):
    assert capacity_valid(ResourceType.ROOM, value)


@pytest.mark.parametrize("value", [0, -1, 1001, "20", 1.5])
def test_non_integer_or_out_of_range_capacity_is_rejected(value):
    assert not capacity_valid(ResourceType.ROOM, value)


def test_unknown_resource_type_is_rejected():
    assert not capacity_valid("unknown", None)


@pytest.mark.parametrize("value", [True, False])
def test_bool_capacity_is_not_an_integer_capacity(value):
    assert not capacity_valid(ResourceType.ROOM, value)


@pytest.mark.parametrize(
    ("kind", "capacity"),
    [("room", 20), ("consultation", None), ("unknown", 20), ("aaa", None)],
)
def test_strict_resource_type_requires_enum_not_raw_string(kind, capacity):
    assert not capacity_valid(kind, capacity)
