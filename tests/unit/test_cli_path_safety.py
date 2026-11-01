"""Boundary checks for paths accepted by the local administration utilities."""

import pytest

from scripts import load_midterm, manage_db


@pytest.mark.req("QA-13")
def test_environment_file_is_limited_to_project(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    local_file = project / ".env.local"
    local_file.write_text("UNISLOT_PATH_TEST=allowed\n", encoding="utf-8")
    outside_file = tmp_path / "outside.env"
    outside_file.write_text("UNISLOT_PATH_TEST=outside\n", encoding="utf-8")
    monkeypatch.setattr(manage_db, "ROOT", project)
    monkeypatch.delenv("UNISLOT_PATH_TEST", raising=False)

    manage_db.load_environment(local_file)
    assert manage_db.os.environ["UNISLOT_PATH_TEST"] == "allowed"
    with pytest.raises(ValueError, match="inside the project"):
        manage_db.load_environment(project / ".." / "outside.env")
    assert manage_db.os.environ["UNISLOT_PATH_TEST"] == "allowed"


@pytest.mark.req("QA-13")
def test_load_results_cannot_escape_designated_directory(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(load_midterm, "ROOT", project)
    allowed = tmp_path / "local-load-results"

    assert load_midterm.validated_output(allowed / "run-1") == allowed / "run-1"
    with pytest.raises(ValueError, match="local-load-results"):
        load_midterm.validated_output(allowed / ".." / "other")


@pytest.mark.req("QA-13")
@pytest.mark.parametrize("workers", [0, 3, True, "2", "2 --reload"])
def test_load_runner_rejects_untrusted_worker_arguments(tmp_path, monkeypatch, workers):
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(load_midterm, "ROOT", project)
    with pytest.raises(ValueError, match="api_workers"):
        load_midterm.run(tmp_path / "local-load-results", 50, workers)
