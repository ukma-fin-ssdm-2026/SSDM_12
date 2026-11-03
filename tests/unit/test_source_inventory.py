"""TDD Аксенії: незалежна перевірка інвентарю джерел."""

import copy

import pytest

from scripts import check_source_inventory as checker

pytestmark = pytest.mark.req("QA-17")


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


def test_new_source_file_is_reported():
    expected = {"src/api/old.py": "hash1"}
    actual = {
        "src/api/old.py": "hash1",
        "src/api/new.py": "hash2",
    }
    assert checker.changed_source_paths(expected, actual) == ["src/api/new.py"]


def test_deleted_source_file_is_reported():
    expected = {
        "src/api/old.py": "hash1",
        "src/api/removed.py": "hash2",
    }
    actual = {"src/api/old.py": "hash1"}
    assert checker.changed_source_paths(expected, actual) == ["src/api/removed.py"]


def test_main_succeeds_when_source_hashes_match(tmp_path, monkeypatch):
    import hashlib
    import json

    source = tmp_path / "src" / "example.py"
    source.parent.mkdir()
    source.write_text("original", encoding="utf-8")

    report = tmp_path / "run.json"
    report.write_text(
        json.dumps(
            {"files_sha256": {"src/example.py": hashlib.sha256(source.read_bytes()).hexdigest()}}
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(checker, "ROOT", tmp_path)
    monkeypatch.setattr(checker, "REPORT", report)

    assert checker.main() == 0


def test_main_fails_when_source_hash_changes(tmp_path, monkeypatch):
    import hashlib
    import json

    source = tmp_path / "src" / "example.py"
    source.parent.mkdir()
    source.write_text("original", encoding="utf-8")

    original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    source.write_text("modified", encoding="utf-8")

    report = tmp_path / "run.json"
    report.write_text(
        json.dumps({"files_sha256": {"src/example.py": original_hash}}), encoding="utf-8"
    )

    monkeypatch.setattr(checker, "ROOT", tmp_path)
    monkeypatch.setattr(checker, "REPORT", report)

    assert checker.main() == 1


def test_main_fails_when_new_source_file_is_added(tmp_path, monkeypatch):
    import json

    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "new.py").write_text("x = 1", encoding="utf-8")

    report = tmp_path / "run.json"
    report.write_text(json.dumps({"files_sha256": {}}), encoding="utf-8")

    monkeypatch.setattr(checker, "ROOT", tmp_path)
    monkeypatch.setattr(checker, "REPORT", report)

    assert checker.main() == 1
