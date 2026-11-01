import json

import pytest

from scripts import check_lab06
from scripts.check_lab06 import debug_stages_valid

pytestmark = pytest.mark.req("QA-14")


def test_expected_red_green_sequence_is_valid():
    stages = [
        {"stage": "red", "exit_code": 1},
        {"stage": "green", "exit_code": 0},
    ]

    assert debug_stages_valid(stages) is True


@pytest.mark.parametrize(
    "stages",
    [
        [{"stage": "green", "exit_code": 1}, {"stage": "red", "exit_code": 0}],
        [{"exit_code": 1}, {"stage": "green", "exit_code": 0}],
        [{"stage": "red", "exit_code": 2}, {"stage": "green", "exit_code": 0}],
        [{"stage": "red", "exit_code": 1}],
        [{"stage": "red", "exit_code": 1}, {"stage": "green", "exit_code": 0}, {}],
        None,
        [{"stage": "red", "exit_code": 1}, None],
    ],
)
def test_wrong_debug_sequences_are_rejected(stages):
    assert debug_stages_valid(stages) is False


@pytest.mark.parametrize(("red_code", "green_code"), [(True, 0), (1, False), (1.0, 0), (1, "0")])
def test_exit_codes_must_be_exact_integers(red_code, green_code):
    stages = [{"stage": "red", "exit_code": red_code}, {"stage": "green", "exit_code": green_code}]
    assert debug_stages_valid(stages) is False


def test_additional_metadata_is_allowed_without_modifying_input():
    stages = [
        {"stage": "red", "exit_code": 1, "duration_ms": 12},
        {"stage": "green", "exit_code": 0},
    ]
    before = json.loads(json.dumps(stages))
    assert debug_stages_valid(stages) is True
    assert stages == before


def test_main_checks_stage_helper_and_source_integrity_separately(tmp_path, monkeypatch):
    report = tmp_path / "docs/testing/lab06"
    evidence = report / "evidence"
    evidence.mkdir(parents=True)
    for path in (
        "docs/testing/coverage-report.md",
        "docs/testing/debugging-log.md",
        "docs/testing/testing-strategy.md",
        "docs/testing/lab06/htmlcov/index.html",
        "Labs/Lab06/README.md",
        "Labs/Lab06/requirements-checklist.md",
    ):
        file = tmp_path / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.touch()
    (report / "run.json").write_text(
        json.dumps({"exit_code": 0, "files_sha256": {}}), encoding="utf-8"
    )
    (report / "coverage.json").write_text(
        json.dumps({"totals": {"percent_covered": 90}}), encoding="utf-8"
    )
    cases = "".join(f'<testcase classname="tests.unit.module{i % 2}" />' for i in range(10))
    (report / "junit.xml").write_text(f"<testsuite>{cases}</testsuite>", encoding="utf-8")
    stages = [{"stage": "red", "exit_code": 1}, {"stage": "green", "exit_code": 0}]
    (evidence / "debug-results.json").write_text(
        json.dumps({"stages": stages, "working_source_unchanged": False}), encoding="utf-8"
    )
    monkeypatch.setattr(check_lab06, "ROOT", tmp_path)
    monkeypatch.setattr(check_lab06, "REPORT", report)
    calls = []
    monkeypatch.setattr(
        check_lab06, "debug_stages_valid", lambda value: calls.append(value) or False
    )

    assert check_lab06.main() == 1
    result = json.loads((report / "artifact-check.json").read_text(encoding="utf-8"))
    assert calls == [stages]
    assert "debug challenge must show a failing then passing test" in result["errors"]
    assert "debug challenge did not restore working source" in result["errors"]
