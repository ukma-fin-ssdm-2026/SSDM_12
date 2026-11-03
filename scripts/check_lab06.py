"""Verify local Lab6 evidence: artifacts, video links and tagged TDD commit counts.

Використання ШІ: чернетку написав Codex (PR #207); поля individual_tdd і
technical_submission_ready переписано з Claude (Opus 5). Перевірив Никита:
локальний прогін, огляд diff, схвалення в PR. Присутність скрипт не засвідчує.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess  # nosec B404
from pathlib import Path

from defusedxml import ElementTree

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "docs/testing/lab06"
PEOPLE = ("denys_patselia", "akseniia_kozulina", "pavlo_dziubak", "nykyta_babakov")
EXPECTED_DEBUG_STAGES = (("red", 1), ("green", 0))
TDD_TAG = re.compile(r"\[(?:RED|GREEN|REFACTOR)\]")


def debug_stages_valid(stages: object) -> bool:
    """Перевіряє назви й цілочисельні коди двох стадій налагодження."""
    if not isinstance(stages, list) or len(stages) != len(EXPECTED_DEBUG_STAGES):
        return False
    return all(
        isinstance(stage, dict)
        and stage.get("stage") == name
        and type(stage.get("exit_code")) is int
        and stage["exit_code"] == exit_code
        for stage, (name, exit_code) in zip(stages, EXPECTED_DEBUG_STAGES, strict=True)
    )


def tdd_commits_by_author() -> dict[str, object]:
    """Рахує коміти з тегами циклу TDD за автором; у shallow-клоні не вгадує."""
    # Команда фіксована, аргументи не походять із зовнішніх даних; shell не використовується.
    shallow = subprocess.run(  # nosec B603 B607  # noqa: S603
        ["git", "-C", str(ROOT), "rev-parse", "--is-shallow-repository"],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    if shallow.returncode:
        return {"status": "unavailable: not a git checkout"}
    if shallow.stdout.strip() == "true":
        return {"status": "unavailable: shallow checkout; run on a full clone"}
    log = subprocess.run(  # nosec B603 B607  # noqa: S603
        ["git", "-C", str(ROOT), "log", "--format=%an%x09%s"],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    if log.returncode:
        return {"status": "unavailable: git log failed"}
    counts: dict[str, int] = {}
    for line in log.stdout.splitlines():
        author, _, subject = line.partition("\t")
        if TDD_TAG.search(subject):
            counts[author] = counts.get(author, 0) + 1
    return {
        "status": "counted from git log",
        "scope": "all tagged [RED]/[GREEN]/[REFACTOR] commits in history, not only Lab6",
        "tagged_commits_by_author": dict(sorted(counts.items())),
    }


def main() -> int:
    required = (
        "docs/testing/coverage-report.md",
        "docs/testing/debugging-log.md",
        "docs/testing/testing-strategy.md",
        "docs/testing/lab06/htmlcov/index.html",
        "Labs/Lab06/README.md",
        "Labs/Lab06/requirements-checklist.md",
    )
    errors = [f"missing: {p}" for p in required if not (ROOT / p).is_file()]
    try:
        run = json.loads((REPORT / "run.json").read_text(encoding="utf-8"))
        coverage = json.loads((REPORT / "coverage.json").read_text(encoding="utf-8"))
        cases = ElementTree.parse(REPORT / "junit.xml").findall(".//testcase")
        unit = [t for t in cases if t.get("classname", "").startswith("tests.unit.")]
        if len(unit) < 10:
            errors.append("fewer than ten isolated unit test cases")
        if len({t.get("classname") for t in unit}) < 2:
            errors.append("fewer than two tested unit modules")
        if run["exit_code"] or coverage["totals"]["percent_covered"] < 90:
            errors.append("coverage/test gate failed")
        for name, expected in run["files_sha256"].items():
            actual = hashlib.sha256((ROOT / name).read_bytes().replace(b"\r\n", b"\n"))
            if actual.hexdigest() != expected:
                errors.append(f"report stale after source change: {name}")
        debug = json.loads((REPORT / "evidence/debug-results.json").read_text(encoding="utf-8"))
        if not debug_stages_valid(debug.get("stages")):
            errors.append("debug challenge must show a failing then passing test")
        if not debug["working_source_unchanged"]:
            errors.append("debug challenge did not restore working source")
    except (OSError, KeyError, ValueError) as error:
        errors.append(str(error))
        cases, unit = [], []
    video_links = {}
    for person in PEOPLE:
        path = ROOT / f"Labs/Lab06/video_{person}.txt"
        if path.exists():
            lines = path.read_text(encoding="utf-8").strip().splitlines()
            video_links[person] = len(lines) == 2 and all(
                re.fullmatch(r"https://(?:www\.)?loom\.com/share/[A-Za-z0-9_-]+(?:\?.*)?", s)
                for s in lines
            )
        else:
            video_links[person] = False
    summary = {
        "technical_artifacts_ready": not errors,
        "errors": errors,
        "test_cases": len(cases),
        "isolated_unit_cases": len(unit),
        "video_link_files_present": video_links,
        "individual_tdd": tdd_commits_by_author(),
        "attendance": "unverified; no attendance evidence manufactured",
        "technical_submission_ready": not errors and all(video_links.values()),
        "submission_scope": (
            "technical artifacts and presence of video links; "
            "attendance and video content are not checked"
        ),
    }
    (REPORT / "artifact-check.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
