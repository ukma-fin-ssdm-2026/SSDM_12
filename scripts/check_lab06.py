"""Verify local Lab6 evidence, keeping individual student requirements pending.

AI-assisted draft: Codex. This does not certify attendance or somebody else's work.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from defusedxml import ElementTree

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "docs/testing/lab06"
PEOPLE = ("denys_patselia", "akseniia_kozulina", "pavlo_dziubak", "nykyta_babakov")


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
        if [r["exit_code"] for r in debug["stages"]] != [1, 0]:
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
        "individual_tdd": "pending: prepared files do not prove individual RED/GREEN/REFACTOR history",
        "attendance": "unverified; no attendance evidence manufactured",
        "submission_ready": False,
    }
    (REPORT / "artifact-check.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
