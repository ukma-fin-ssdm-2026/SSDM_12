#!/usr/bin/env python3
"""Пошук нестабільних (flaky) тестів: повний набір N разів на одному коміті (Лаб 10, бонус 4).

Вимога QA-23. Тест нестабільний, якщо його результат відрізнявся між повторами на тому
самому коміті й у тому самому середовищі: пройшов в одному прогоні й упав в іншому, був
пропущений лише інколи або зник зі збору. Тест, що падає в усіх прогонах, — не
нестабільний, а зламаний: його теж показуємо окремо.

Кожен повтор — окремий процес pytest з іншим `PYTHONHASHSEED` (1, 2, …, N): так між
повторами змінюється порядок обходу множин і словників із рядковими ключами, і тест, що
мовчки залежить від цього порядку, має шанс проявитися. Результати читаємо з JUnit XML тим
самим розбором, що й регресійне порівняння Лаб 8 (`scripts/regression_compare.py`).

Запуск з кореня репозиторію:

    python scripts/flaky_hunt.py --repetitions 5 --out-dir reports/flaky
    python scripts/flaky_hunt.py --from-junit reports/flaky/run-1.xml reports/flaky/run-2.xml

Коди виходу: 0 — розбіжностей і зламаних тестів немає; 1 — знайдено нестабільні або
зламані тести; 2 — неправильні аргументи чи шлях; 3 — щонайменше один повтор не дав жодного
результату (pytest не зібрав або не запустив набір — наприклад, бракує залежності), тож
порівнювати нічого: «нестабільних немає» в такому разі було б хибним висновком.
"""

from __future__ import annotations

import argparse
import json
import os

# Fixed interpreter and fixed pytest arguments; no shell, no user-built command line.
import subprocess  # nosec B404
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT)]

from scripts.regression_compare import outcomes  # noqa: E402

SYMBOL = {"passed": "P", "failed": "F", "error": "E", "skipped": "S", None: "—"}
FAILING = frozenset({"failed", "error"})


@dataclass
class Repetition:
    """Один повтор повного набору: результати тестів, код виходу pytest, тривалість."""

    number: int
    results: dict[str, str]
    exit_code: int | None = None
    seconds: float | None = None

    def counts(self) -> Counter:
        """Кількість тестів за результатом."""
        return Counter(self.results.values())

    @property
    def empty(self) -> bool:
        """Повтор не дав жодного результату: набір не зібрано або не запущено."""
        return not self.results


@dataclass
class Verdict:
    """Підсумок порівняння повторів."""

    repetitions: list[Repetition]
    flaky: dict[str, list[str | None]] = field(default_factory=dict)
    broken: list[str] = field(default_factory=list)

    @property
    def empty_runs(self) -> list[Repetition]:
        """Повтори без жодного результату — порівняння з ними нічого не доводить."""
        return [r for r in self.repetitions if r.empty]

    @property
    def clean(self) -> bool:
        """Немає ні нестабільних, ні зламаних тестів, і кожен повтор справді відбувся."""
        return not self.flaky and not self.broken and not self.empty_runs

    @property
    def exit_code(self) -> int:
        """3 — повтор без результатів (висновку немає); 1 — знайдено проблеми; 0 — чисто."""
        if self.empty_runs:
            return 3
        return 0 if self.clean else 1


def analyze(repetitions: list[Repetition]) -> Verdict:
    """Тест нестабільний, якщо між повторами різнився результат або присутність у зборі."""
    if len(repetitions) < 2:
        raise ValueError("для порівняння потрібно щонайменше два повтори")
    verdict = Verdict(repetitions)
    every = sorted(set().union(*(r.results for r in repetitions)))
    for test_id in every:
        seen = [r.results.get(test_id) for r in repetitions]
        if len(set(seen)) > 1:
            verdict.flaky[test_id] = seen
        elif seen[0] in FAILING:
            verdict.broken.append(test_id)
    return verdict


def render(verdict: Verdict, commit: str | None = None) -> str:
    """Markdown-звіт для підсумку job і для docs/ci-cd/."""
    reps = verdict.repetitions
    lines = [
        "## Пошук нестабільних тестів",
        "",
        f"Повторів повного набору: **{len(reps)}**" + (f" · коміт `{commit}`" if commit else ""),
        "",
        "| Повтор | PYTHONHASHSEED | Тестів | passed | failed | error | skipped | Код pytest "
        "| Тривалість, с |",
        "|--:|--:|--:|--:|--:|--:|--:|--:|--:|",
    ]
    for rep in reps:
        c = rep.counts()
        seconds = "—" if rep.seconds is None else f"{rep.seconds:.0f}"
        code = "—" if rep.exit_code is None else str(rep.exit_code)
        lines.append(
            f"| {rep.number} | {rep.number} | {len(rep.results)} | {c['passed']} | {c['failed']} "
            f"| {c['error']} | {c['skipped']} | {code} | {seconds} |"
        )
    lines += ["", f"**Нестабільних тестів: {len(verdict.flaky)}**", ""]
    if verdict.flaky:
        lines += ["| Тест | Результати за повторами |", "|---|---|"]
        for test_id, seen in verdict.flaky.items():
            pattern = " ".join(SYMBOL.get(s, "?") for s in seen)
            lines.append(f"| `{test_id}` | {pattern} |")
        lines += [
            "",
            "P — passed, F — failed, E — error, S — skipped, «—» — тесту немає у зборі.",
            "",
        ]
    lines.append(f"**Зламаних (падають у кожному повторі): {len(verdict.broken)}**")
    if verdict.broken:
        lines += ["", *(f"- `{test_id}`" for test_id in verdict.broken)]
    if verdict.empty_runs:
        lines += ["", f"**Повторів без жодного результату: {len(verdict.empty_runs)}**", ""]
        lines += [
            f"- повтор {r.number}: код pytest {'—' if r.exit_code is None else r.exit_code}"
            for r in verdict.empty_runs
        ]
        lines += [
            "",
            "Набір у цих повторах не зібрано або не запущено (див. лог повтору): висновок про "
            "нестабільність ненадійний, доки причину не усунуто.",
        ]
    if verdict.clean:
        lines += [
            "",
            "Результат кожного тесту однаковий у всіх повторах — нестабільних тестів не виявлено.",
        ]
    return "\n".join(lines) + "\n"


def inside_repo(path: Path, *, must_exist: bool = False) -> Path:
    """Лише шляхи всередині поточного каталогу (кореня репозиторію)."""
    root, target = Path.cwd().resolve(), path.resolve()
    if not target.is_relative_to(root):
        raise ValueError(f"шлях поза репозиторієм: {path}")
    if must_exist and not target.is_file():
        raise ValueError(f"не знайдено файл: {path}")
    return target


def run_suite(number: int, junit: Path) -> Repetition:
    """Один повтор: окремий процес pytest із PYTHONHASHSEED = номер повтору."""
    env = dict(os.environ, PYTHONHASHSEED=str(number))
    started = time.monotonic()

    completed = subprocess.run(  # noqa: S603  # nosec B603
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            f"--junitxml={junit}",
        ],
        env=env,
        check=False,
        shell=False,
    )

    seconds = time.monotonic() - started
    results = outcomes(junit.read_text(encoding="utf-8")) if junit.is_file() else {}
    return Repetition(number, results, completed.returncode, seconds)


def main(argv: list[str] | None = None) -> int:
    """Точка входу CLI."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--repetitions", type=int, choices=range(2, 21), metavar="2..20")
    source.add_argument("--from-junit", type=Path, nargs="+", help="готові JUnit XML")
    parser.add_argument("--out-dir", type=Path, default=Path("reports/flaky"))
    parser.add_argument("--commit", help="SHA для заголовка звіту")
    args = parser.parse_args(argv)
    try:
        out_dir = inside_repo(args.out_dir)
        if args.from_junit:
            reps = [
                Repetition(i, outcomes(inside_repo(p, must_exist=True).read_text("utf-8")))
                for i, p in enumerate(args.from_junit, 1)
            ]
        else:
            out_dir.mkdir(parents=True, exist_ok=True)
            reps = []
            for number in range(1, args.repetitions + 1):
                print(f"[flaky] повтор {number} з {args.repetitions}", flush=True)
                junit = out_dir / f"run-{number}.xml"
                reps.append(run_suite(number, junit))
        verdict = analyze(reps)
    except ValueError as error:
        print(f"Помилка: {error}", file=sys.stderr)
        return 2
    commit = args.commit or os.environ.get("GITHUB_SHA", "")[:7] or None
    text = render(verdict, commit)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.md").write_text(text, encoding="utf-8")
    payload = {
        "commit": commit,
        "repetitions": [
            {
                "number": r.number,
                "tests": len(r.results),
                "counts": dict(r.counts()),
                "exit_code": r.exit_code,
                "seconds": r.seconds,
            }
            for r in reps
        ],
        "flaky": verdict.flaky,
        "broken": verdict.broken,
    }
    (out_dir / "report.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a", encoding="utf-8") as handle:
            handle.write(text)
    print(text, end="")
    return verdict.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
