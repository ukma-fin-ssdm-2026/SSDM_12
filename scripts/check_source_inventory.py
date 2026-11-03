"""Самостійна перевірка актуальності інвентарю джерел Лаб6."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "docs/testing/lab06"


def changed_source_paths(expected: dict[str, str], actual: dict[str, str]) -> list[str]:
    """Повертає шляхи, які відрізняються між очікуваним і фактичним інвентарями."""
    all_paths = expected.keys() | actual.keys()
    changed = [path for path in all_paths if expected.get(path) != actual.get(path)]
    return sorted(changed)


def file_sha256(path: Path) -> str:
    """Обчислює SHA-256 вмісту файлу."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    """Перевіряє SHA-256 джерельних файлів за звітом."""
    report_path = REPORT if REPORT.is_file() else REPORT / "run.json"
    data = json.loads(report_path.read_text(encoding="utf-8"))
    expected = data["files_sha256"]

    actual = {}
    source_paths = sorted((ROOT / "src").rglob("*.py")) + sorted((ROOT / "tests").rglob("*.py"))
    for source_path in source_paths:
        if source_path.is_file():
            relative_path = source_path.relative_to(ROOT).as_posix()
            actual[relative_path] = file_sha256(source_path)

    return 1 if changed_source_paths(expected, actual) else 0


if __name__ == "__main__":
    raise SystemExit(main())
