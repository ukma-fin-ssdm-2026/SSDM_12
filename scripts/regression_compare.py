#!/usr/bin/env python3
"""Compare pytest JUnit XML runs before and after refactoring (Lab 8, QA-20)."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from defusedxml import ElementTree

OUTCOMES = ("passed", "failed", "error", "skipped")


def outcomes(xml_text: str) -> dict[str, str]:
    """Map pytest JUnit testcase IDs to outcomes."""
    root = ElementTree.fromstring(xml_text)
    result = {}
    for case in root.iter("testcase"):
        test_id = f"{case.get('classname', '')}::{case.get('name', '')}"
        tags = {child.tag for child in case}
        if "failure" in tags:
            result[test_id] = "failed"
        elif "error" in tags:
            result[test_id] = "error"
        elif "skipped" in tags:
            result[test_id] = "skipped"
        else:
            result[test_id] = "passed"
    return result


def compare(before: dict[str, str], after: dict[str, str]) -> dict[str, list[str]]:
    """Return sorted removed, degraded, failing, and added testcase IDs."""
    return {
        "removed": sorted(before.keys() - after.keys()),
        "degraded": sorted(
            t for t in before.keys() & after.keys() if before[t] == "passed" != after[t]
        ),
        "failing": sorted(t for t, outcome in after.items() if outcome in {"failed", "error"}),
        "added": sorted(after.keys() - before.keys()),
    }


def _summary(name: str, results: dict[str, str]) -> str:
    counts = Counter(results.values())
    parts = " · ".join(f"{outcome} {counts.get(outcome, 0)}" for outcome in OUTCOMES)
    return f"{name}: тестів {len(results)} — {parts}"


def report(before: dict[str, str], after: dict[str, str]) -> tuple[str, bool]:
    """Render a regression report and indicate whether it is clean."""
    groups = compare(before, after)
    lines = [_summary("До", before), _summary("Після", after), ""]
    titles = {
        "removed": "Зникли тести (були до, немає після)",
        "degraded": "Погіршилися (passed до → інакше після)",
        "failing": "Падають після",
        "added": "Нові тести (для інформації)",
    }
    for key, title in titles.items():
        lines.append(f"{title}: {len(groups[key])}")
        lines += [f"  {test_id}" for test_id in groups[key]]
    clean = not (groups["removed"] or groups["degraded"] or groups["failing"])
    lines += ["", "Регресій немає." if clean else "Є регресії — див. вище."]
    return "\n".join(lines) + "\n", clean


def _load(path: Path) -> dict[str, str]:
    """Load only local JUnit XML files within the working directory."""
    root = Path.cwd().resolve()
    candidate = path.resolve()
    if candidate.suffix.lower() != ".xml" or not candidate.is_relative_to(root):
        print(f"Недозволений шлях до JUnit XML: {path}")
        raise SystemExit(2)
    path = candidate
    if not path.is_file():
        print(f"Не знайдено звіт {path}.")
        raise SystemExit(2)
    try:
        return outcomes(path.read_text(encoding="utf-8"))
    except ElementTree.ParseError as error:
        print(f"Не вдалося розібрати {path}: {error}")
        raise SystemExit(2) from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("before", type=Path, help="JUnit XML прогону «до»")
    parser.add_argument("after", type=Path, help="JUnit XML прогону «після»")
    args = parser.parse_args(argv)
    text, clean = report(_load(args.before), _load(args.after))
    print(text, end="")
    return 0 if clean else 1


if __name__ == "__main__":
    sys.exit(main())
