"""Exporter tests use a tiny fake application and tmp_path, never tracked docs.

Local AI draft: Codex. These tests cover previously unexercised export/check paths.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import yaml

from api import openapi_export as exporter


@pytest.fixture
def fake_app():
    shared = {"description": "line one\nline two"}
    return SimpleNamespace(
        openapi=Mock(return_value={"openapi": "3.1.0", "a": shared, "b": shared})
    )


def test_yaml_is_roundtrippable_without_aliases(fake_app):
    text = exporter.render_spec_yaml(fake_app)
    assert "&id" not in text and "*id" not in text
    assert "description: |" in text
    assert yaml.safe_load(text) == fake_app.openapi()


def test_write_makes_nested_directory_and_check_is_clean(fake_app, tmp_path):
    folder = tmp_path / "nested" / "docs"
    files = exporter.write_artifacts(fake_app, folder)
    assert {p.name for p in files} == {exporter.SPEC_NAME, exporter.ERRORS_NAME}
    assert exporter.check_artifacts(fake_app, folder) == []


def test_check_missing_files_does_not_write(fake_app, tmp_path):
    assert len(exporter.check_artifacts(fake_app, tmp_path)) == 2
    assert list(tmp_path.iterdir()) == []


def test_check_modified_file_reports_diff_without_changing_it(fake_app, tmp_path):
    exporter.write_artifacts(fake_app, tmp_path)
    spec = tmp_path / exporter.SPEC_NAME
    spec.write_text("old content\n", encoding="utf-8")
    problems = exporter.check_artifacts(fake_app, tmp_path)
    assert len(problems) == 1 and "-old content" in problems[0]
    assert spec.read_text(encoding="utf-8") == "old content\n"


def test_cli_generate_then_check_and_drift(fake_app, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("api.main.create_app", lambda: fake_app)
    args = ["--out-dir", str(tmp_path)]
    assert exporter.main(args) == 0
    assert exporter.main([*args, "--check"]) == 0
    (tmp_path / exporter.ERRORS_NAME).write_text("changed", encoding="utf-8")
    assert exporter.main([*args, "--check"]) == 1
    assert "[FAIL]" in capsys.readouterr().out
