"""Самостійна перевірка актуальності інвентарю джерел Лаб6."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "docs/testing/lab06"


def changed_source_paths(expected: dict[str, str], actual: dict[str, str]) -> list[str]:
    """Повертає шляхи, які відрізняються між очікуваним і фактичним інвентарями."""
    all_paths = expected.keys() | actual.keys()
    changed = [path for path in all_paths if expected.get(path) != actual.get(path)]
    return sorted(changed)


def main() -> int:
    """Запускає перевірку інвентарю; початкова заглушка для TDD."""
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
