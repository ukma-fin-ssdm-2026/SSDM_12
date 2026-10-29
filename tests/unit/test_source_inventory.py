"""TDD Аксенії: незалежна перевірка інвентарю джерел."""

import copy

import pytest

from scripts import check_source_inventory as checker


def test_changed_hash_is_reported():
    expected = {"src/api/example.py": "old"}
    actual = {"src/api/example.py": "new"}
    assert checker.changed_source_paths(expected, actual) == ["src/api/example.py"]


@pytest.mark.parametrize("inventory", [{}, {"src/api/example.py": "same"}])
def test_equal_source_inventories_have_no_changes(inventory):
    assert checker.changed_source_paths(inventory, dict(inventory)) == []


def test_inventory_comparison_keeps_inputs():
    expected = {"src/api/example.py": "old"}
    actual = {"src/api/example.py": "new"}
    before = copy.deepcopy((expected, actual))
    checker.changed_source_paths(expected, actual)
    assert (expected, actual) == before
