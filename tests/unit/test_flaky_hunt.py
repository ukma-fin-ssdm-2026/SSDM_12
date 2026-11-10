"""Пошук нестабільних тестів повторами на одному коміті (Лаб 10, бонус 4; QA-23)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts import flaky_hunt as fh

pytestmark = pytest.mark.req("QA-23")


def junit(**cases: str) -> str:
    """JUnit XML у форматі pytest: ключ `module__test`, значення — результат."""
    body = {
        "passed": "",
        "failed": "<failure message='boom'/>",
        "error": "<error message='setup'/>",
        "skipped": "<skipped message='no db'/>",
    }
    rows = "".join(
        f'<testcase classname="{key.split("__")[0]}" name="{key.split("__")[1]}">'
        f"{body[outcome]}</testcase>"
        for key, outcome in cases.items()
    )
    return (
        f'<?xml version="1.0"?><testsuites><testsuite name="pytest">{rows}</testsuite></testsuites>'
    )


def rep(number: int, **cases: str) -> fh.Repetition:
    return fh.Repetition(number, fh.outcomes(junit(**cases)))


def test_same_results_in_every_repetition_is_clean():
    reps = [rep(i, a__one="passed", a__two="skipped") for i in range(1, 6)]
    verdict = fh.analyze(reps)
    assert verdict.clean
    assert "нестабільних тестів не виявлено" in fh.render(verdict)


def test_test_that_passed_and_failed_is_flaky_with_its_pattern():
    reps = [rep(1, a__one="passed"), rep(2, a__one="failed"), rep(3, a__one="passed")]
    verdict = fh.analyze(reps)
    assert verdict.flaky == {"a::one": ["passed", "failed", "passed"]}
    assert "| `a::one` | P F P |" in fh.render(verdict)


def test_test_skipped_only_sometimes_is_flaky():
    reps = [rep(1, a__one="passed"), rep(2, a__one="skipped")]
    assert list(fh.analyze(reps).flaky) == ["a::one"]


def test_test_missing_from_one_collection_is_flaky():
    reps = [rep(1, a__one="passed", a__two="passed"), rep(2, a__one="passed")]
    verdict = fh.analyze(reps)
    assert verdict.flaky == {"a::two": ["passed", None]}
    assert "| `a::two` | P — |" in fh.render(verdict)


def test_test_failing_in_every_repetition_is_broken_not_flaky():
    reps = [rep(i, a__one="failed", a__two="error", a__three="passed") for i in (1, 2, 3)]
    verdict = fh.analyze(reps)
    assert verdict.flaky == {}
    assert verdict.broken == ["a::one", "a::two"]
    assert not verdict.clean


def test_one_repetition_cannot_be_compared():
    with pytest.raises(ValueError, match="два повтори"):
        fh.analyze([rep(1, a__one="passed")])


def test_each_repetition_gets_its_own_hash_seed_and_junit_file(tmp_path, monkeypatch):
    seen = []

    def fake_run(args, env, check, shell):
        assert shell is False
        assert len(args) == 7
        assert args[1:6] == [
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
        ]

        junit_path = Path(
            next(a for a in args if a.startswith("--junitxml=")).split("=", 1)[1]
        )

        seen.append((env["PYTHONHASHSEED"], junit_path.name))
        junit_path.write_text(junit(a__one="passed"), encoding="utf-8")
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(fh.subprocess, "run", fake_run)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    assert fh.main(["--repetitions", "3", "--out-dir", "out"]) == 0

    assert seen == [
        ("1", "run-1.xml"),
        ("2", "run-2.xml"),
        ("3", "run-3.xml"),
    ]

    assert (tmp_path / "out" / "report.md").is_file()


def test_missing_junit_after_a_crash_counts_as_an_empty_collection(tmp_path, monkeypatch):
    def fake_run(args, env, check, shell):
        if env["PYTHONHASHSEED"] == "1":
            Path(args[-1].split("=", 1)[1]).write_text(junit(a__one="passed"), encoding="utf-8")
        return subprocess.CompletedProcess(args, 0 if env["PYTHONHASHSEED"] == "1" else 4)

    monkeypatch.setattr(fh.subprocess, "run", fake_run)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert fh.main(["--repetitions", "2", "--out-dir", "out"]) == 3
    report = (tmp_path / "out" / "report.md").read_text(encoding="utf-8")
    assert "| `a::one` | P — |" in report
    assert "- повтор 2: код pytest 4" in report


def test_broken_environment_is_never_reported_as_clean(tmp_path, monkeypatch):
    # Every repetition fails before collecting a single test (e.g. a missing dependency
    # in conftest.py): there is nothing to compare, so "no flaky tests" would be a lie.
    def fake_run(args, env, check, shell):
        return subprocess.CompletedProcess(args, 4)

    monkeypatch.setattr(fh.subprocess, "run", fake_run)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert fh.main(["--repetitions", "3", "--out-dir", "out"]) == 3
    report = (tmp_path / "out" / "report.md").read_text(encoding="utf-8")
    assert "**Повторів без жодного результату: 3**" in report
    assert "нестабільних тестів не виявлено" not in report


def test_cli_analyzes_saved_junit_files_and_writes_summary(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "r1.xml").write_text(junit(a__one="passed"), encoding="utf-8")
    (tmp_path / "r2.xml").write_text(junit(a__one="failed"), encoding="utf-8")
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    assert fh.main(["--from-junit", "r1.xml", "r2.xml", "--out-dir", "out"]) == 1
    assert "**Нестабільних тестів: 1**" in summary.read_text(encoding="utf-8")
    assert '"a::one"' in (tmp_path / "out" / "report.json").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "argv",
    [
        ["--from-junit", "../outside.xml", "r1.xml"],
        ["--from-junit", "missing.xml", "r1.xml"],
        ["--from-junit", "r1.xml", "r1.xml", "--out-dir", "../out"],
        ["--from-junit", "r1.xml"],
    ],
)
def test_cli_rejects_unsafe_or_insufficient_input(tmp_path, monkeypatch, argv):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "r1.xml").write_text(junit(a__one="passed"), encoding="utf-8")
    assert fh.main(argv) == 2


def test_cli_rejects_arbitrary_pytest_arguments():
    with pytest.raises(SystemExit) as exc_info:
        fh.main([
            "--repetitions",
            "2",
            "--out-dir",
            "reports/flaky",
            "--",
            "-k",
            "smoke",
        ])

    assert exc_info.value.code == 2
