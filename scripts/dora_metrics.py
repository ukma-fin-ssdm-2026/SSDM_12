#!/usr/bin/env python3
"""Метрики DORA з історії запусків GitHub Actions (Лаб 10, бонус 1; вимога QA-22).

Скрипт читає запуски workflow на гілці через GitHub REST API (`gh api`, а без `gh` —
напряму HTTPS із токеном із GH_TOKEN/GITHUB_TOKEN) і рахує чотири метрики за
визначеннями курсу (умова Лаб 10, «Визначення курсу»):

* розгортання — успішний (зелений) запуск на `main`;
* невдала зміна — червоний запуск на `main`; червоні запуски на PR не рахуються;
* частота збоїв змін — червоні запуски / усі завершені запуски на `main`;
* час відновлення — від червоного запуску на `main` до наступного зеленого;
* час виконання змін — від першого коміту злитого PR до завершення зеленого запуску
  на `main`, що містить цей коміт; для прямого push — від самого коміту.

Черга (старт спроби → старт першого job) і виконання (старт першого job → завершення
останнього) рахуються окремо для кожної спроби: повторний запуск (re-run) — це нова
спроба того самого запуску, а `gh run list` показує лише останню. Тому скрипт додатково
перелічує запуски, що стали зеленими без зміни коду, і рахує метрики на рівні спроб.

Кілька workflow на коміт: коміт зелений, лише якщо зелені всі враховані workflow, і
червоний, якщо червоний хоч один (`--workflow` можна повторити).

Приклади (з кореня репозиторію):

    # зібрати дані через gh, зберегти набір даних і звіт
    python scripts/dora_metrics.py --since 2026-10-19 --until 2026-11-09 \
        --dataset docs/ci-cd/evidence/dora-dataset.json \
        --out docs/ci-cd/dora-auto.md --json docs/ci-cd/dora-auto.json

    # перерахувати офлайн зі збереженого набору даних — без мережі
    python scripts/dora_metrics.py --from-dataset docs/ci-cd/evidence/dora-dataset.json \
        --out docs/ci-cd/dora-auto.md

    # «розгортання» = публікація образу (бонус 5): інший workflow і подія
    python scripts/dora_metrics.py --since 2026-11-11 --until 2026-11-15 \
        --workflow "Release image" --event workflow_run --out docs/ci-cd/dora-image.md

Коди виходу: 0 — звіт записано; 2 — неправильні аргументи, шлях або відповідь API.
Скрипт не змінює нічого в GitHub: лише GET-запити.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import statistics

# Fixed `gh` executable with a list of arguments; no shell, no user-built command line.
import subprocess  # nosec B404
import sys
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

API_ROOT = "https://api.github.com/"
DEFAULT_REPO = "ukma-fin-ssdm-2026/SSDM_12"
SHORT_SHA = 7  # 7 символів: довгі hex-рядки detect-secrets сприймає як можливі секрети

GREEN = frozenset({"success"})
RED = frozenset({"failure", "timed_out", "startup_failure"})
CANCELLED = frozenset({"cancelled"})

# Розподіли відповідей опитування DORA 2025 (рис. 11–14 звіту): межа рівня і частка
# опитаних із таким самим або кращим результатом («Top %»). Межі — у годинах.
LEAD_TIME_LEVELS = (
    (1, "менше години", 9.4),
    (24, "менше доби", 24.4),
    (24 * 7, "від доби до тижня", 56.4),
    (24 * 30, "від тижня до місяця", 84.7),
    (24 * 182, "від місяця до шести місяців", 98.0),
    (float("inf"), "понад шість місяців", 100.0),
)
RECOVERY_LEVELS = (
    (1, "менше години", 21.3),
    (24, "менше доби", 56.5),
    (24 * 7, "від доби до тижня", 84.5),
    (24 * 30, "від тижня до місяця", 93.9),
    (24 * 182, "від місяця до шести місяців", 98.8),
    (float("inf"), "понад шість місяців", 100.0),
)
CFR_LEVELS = (
    (2, "0–2 %", 8.5),
    (4, "2–4 %", 16.7),
    (8, "4–8 %", 36.2),
    (16, "8–16 %", 62.2),
    (32, "16–32 %", 81.6),
    (64, "32–64 %", 94.1),
    (float("inf"), "понад 64 %", 100.0),
)
# Частота розгортань — у розгортаннях на добу; межа — нижня. Опитування самозвітне:
# «на вимогу (кілька разів на день)» і «від разу на годину до разу на добу» за числом
# перекриваються. Злиття в main у нас відбуваються, щойно PR готовий, — тобто на вимогу,
# тож більше одного розгортання на добу відносимо до «на вимогу»; строге прочитання
# («між разом на годину й разом на добу», Top 22,7 %) звіт показує як перевірку чутливості.
DEPLOY_LEVELS = (
    (1.0, "на вимогу (кілька разів на день)", 16.2),
    (1 / 7, "від разу на добу до разу на тиждень", 44.6),
    (1 / 30, "від разу на тиждень до разу на місяць", 76.1),
    (1 / 182, "від разу на місяць до разу на шість місяців", 96.4),
    (0.0, "рідше ніж раз на шість місяців", 100.0),
)
DEPLOY_STRICT_HOURLY_DAILY = ("від разу на годину до разу на добу", 22.7)


# --------------------------------------------------------------------------- модель


def parse_time(value: str | None) -> datetime | None:
    """ISO 8601 з API (`...Z`) → datetime в UTC; порожнє значення → None."""
    if not value:
        return None
    moment = datetime.fromisoformat(value)
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def iso(moment: datetime | None) -> str | None:
    """Datetime → ISO 8601 в UTC із суфіксом Z (як у GitHub API)."""
    if moment is None:
        return None
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Job:
    """Один job спроби: час старту й завершення (None — job не стартував)."""

    name: str
    started_at: str | None
    completed_at: str | None
    conclusion: str | None = None
    runner: str | None = None
    steps: list[list] = field(default_factory=list)  # [[назва, секунди, висновок], ...]


@dataclass
class Attempt:
    """Одна спроба запуску (1 — перший прогін, 2+ — re-run)."""

    number: int
    started_at: str  # коли спробу створено або перезапущено
    conclusion: str | None
    jobs: list[Job] = field(default_factory=list)
    updated_at: str | None = None

    @property
    def first_job_start(self) -> datetime | None:
        """Старт першого job, що справді стартував."""
        starts = [parse_time(j.started_at) for j in self.jobs if j.started_at]
        return min(starts) if starts else None

    @property
    def completed(self) -> datetime | None:
        """Завершення останнього job; без jobs — останнє оновлення спроби."""
        ends = [parse_time(j.completed_at) for j in self.jobs if j.completed_at]
        return max(ends) if ends else parse_time(self.updated_at)

    @property
    def queue_minutes(self) -> float | None:
        """Черга: від старту спроби до старту першого job."""
        first = self.first_job_start
        if first is None:
            return None
        return max(0.0, (first - parse_time(self.started_at)).total_seconds() / 60)

    @property
    def execution_minutes(self) -> float | None:
        """Виконання: від старту першого job до завершення останнього."""
        first, last = self.first_job_start, self.completed
        if first is None or last is None:
            return None
        return max(0.0, (last - first).total_seconds() / 60)

    def step_seconds(self, pattern: re.Pattern[str]) -> float:
        """Сума тривалостей кроків, назва яких відповідає шаблону (усі jobs спроби)."""
        return sum(s[1] for j in self.jobs for s in j.steps if pattern.search(str(s[0])))


@dataclass
class Pull:
    """PR, з якого прийшов коміт: номер і ключові моменти часу."""

    number: int
    created_at: str
    merged_at: str | None
    first_commit_at: str
    changed_lines: int | None = None


@dataclass
class Run:
    """Запуск workflow на гілці з усіма спробами й PR, з якого прийшов коміт."""

    id: int
    workflow: str
    sha: str
    created_at: str
    attempts: list[Attempt]
    url: str = ""
    event: str = "push"
    pull: Pull | None = None
    commit_at: str | None = None  # дата автора коміту — для прямого push без PR

    @property
    def last(self) -> Attempt:
        """Остання спроба — її бачить `gh run list`."""
        return self.attempts[-1]

    @property
    def conclusion(self) -> str | None:
        """Висновок запуску = висновок останньої спроби."""
        return self.last.conclusion


def classify(conclusion: str | None) -> str:
    """success → green, failure/timed_out/startup_failure → red, cancelled → cancelled."""
    if conclusion in GREEN:
        return "green"
    if conclusion in RED:
        return "red"
    if conclusion in CANCELLED:
        return "cancelled"
    return "other"


def run_from_dict(data: dict) -> Run:
    """Відновлює Run із набору даних (JSON)."""
    attempts = [
        Attempt(
            number=a["number"],
            started_at=a["started_at"],
            conclusion=a.get("conclusion"),
            updated_at=a.get("updated_at"),
            jobs=[Job(**j) for j in a.get("jobs", [])],
        )
        for a in data["attempts"]
    ]
    pull = Pull(**data["pull"]) if data.get("pull") else None
    return Run(
        id=data["id"],
        workflow=data["workflow"],
        sha=data["sha"],
        created_at=data["created_at"],
        attempts=attempts,
        url=data.get("url", ""),
        event=data.get("event", "push"),
        pull=pull,
        commit_at=data.get("commit_at"),
    )


# ------------------------------------------------------------- одиниця «розгортання»


@dataclass
class Unit:
    """Один коміт на гілці: статус і час за всіма врахованими workflow."""

    sha: str
    created: datetime
    status: str  # green | red | cancelled | other
    completed: datetime | None
    queue: float | None
    execution: float | None
    runs: list[Run]

    @property
    def pull(self) -> Pull | None:
        """PR коміту (з будь-якого запуску коміту)."""
        return next((r.pull for r in self.runs if r.pull), None)

    @property
    def change_start(self) -> datetime | None:
        """Початок відліку часу виконання змін: перший коміт PR або сам коміт."""
        if self.pull:
            return parse_time(self.pull.first_commit_at)
        return parse_time(next((r.commit_at for r in self.runs if r.commit_at), None))


def build_units(runs: Iterable[Run]) -> list[Unit]:
    """Групує запуски за комітом: червоний, якщо червоний хоч один; зелений — якщо всі."""
    by_sha: dict[str, list[Run]] = {}
    for run in runs:
        by_sha.setdefault(run.sha, []).append(run)
    units = []
    for sha, group in by_sha.items():
        statuses = {classify(r.conclusion) for r in group}
        if "red" in statuses:
            status = "red"
        elif statuses == {"green"}:
            status = "green"
        elif "cancelled" in statuses:
            status = "cancelled"
        else:
            status = "other"
        starts = [parse_time(r.last.started_at) for r in group]
        firsts = [r.last.first_job_start for r in group if r.last.first_job_start]
        ends = [r.last.completed for r in group if r.last.completed]
        first, start, end = (min(firsts) if firsts else None), min(starts), max(ends, default=None)
        units.append(
            Unit(
                sha=sha,
                created=min(parse_time(r.created_at) for r in group),
                status=status,
                completed=end,
                queue=(first - start).total_seconds() / 60 if first else None,
                execution=(end - first).total_seconds() / 60 if first and end else None,
                runs=group,
            )
        )
    return sorted(units, key=lambda u: u.created)


# ------------------------------------------------------------------------ метрики


def median(values: Sequence[float]) -> float | None:
    """Медіана або None для порожнього набору."""
    return statistics.median(values) if values else None


def mean(values: Sequence[float]) -> float | None:
    """Середнє або None для порожнього набору."""
    return statistics.fmean(values) if values else None


def percentile(values: Sequence[float], q: float) -> float | None:
    """Перцентиль методом найближчого рангу (без інтерполяції)."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(q / 100 * len(ordered)))
    return ordered[min(rank, len(ordered)) - 1]


def level(value: float, levels: Sequence[tuple[float, str, float]]) -> tuple[str, float]:
    """Рівень DORA 2025 для «менше межі» (час, частка збоїв): назва й Top %."""
    for limit, name, top in levels:
        if value < limit:
            return name, top
    return levels[-1][1], levels[-1][2]


def deploy_level(per_day: float) -> tuple[str, float]:
    """Рівень DORA 2025 для частоти розгортань (розгортань на добу)."""
    for lower, name, top in DEPLOY_LEVELS:
        if per_day > lower:
            return name, top
    return DEPLOY_LEVELS[-1][1], DEPLOY_LEVELS[-1][2]


@dataclass
class Change:
    """Одна зміна (злитий PR або прямий push) і її час виконання."""

    sha: str
    pull: int | None
    start: datetime
    end: datetime
    own_status: str
    queue: float | None  # черга й виконання зеленого запуску, що завершив відлік
    execution: float | None
    opened: datetime | None
    merged: datetime | None

    @property
    def hours(self) -> float:
        """Час виконання змін, год."""
        return (self.end - self.start).total_seconds() / 3600


def lead_times(units: Sequence[Unit], in_window: Callable[[Unit], bool]) -> list[Change]:
    """Час виконання змін для кожного коміту у вікні.

    Кінець відліку — найраніше завершення зеленого запуску цього коміту або пізнішого:
    гілка лінійна, тож пізніший коміт містить попередній. Якщо власний запуск коміту
    червоний чи скасований, зміна «доїжджає» з наступним зеленим.
    """
    changes = []
    for index, unit in enumerate(units):
        if not in_window(unit) or unit.change_start is None:
            continue
        greens = [u for u in units[index:] if u.status == "green" and u.completed]
        if not greens:
            continue  # зеленого запуску ще немає — зміна не розгорнута
        target = min(greens, key=lambda u: u.completed)
        pull = unit.pull
        changes.append(
            Change(
                sha=unit.sha,
                pull=pull.number if pull else None,
                start=unit.change_start,
                end=target.completed,
                own_status=unit.status,
                queue=target.queue,
                execution=target.execution,
                opened=parse_time(pull.created_at) if pull else None,
                merged=parse_time(pull.merged_at) if pull else None,
            )
        )
    return changes


def recoveries(events: Sequence[tuple[datetime, str]]) -> list[tuple[datetime, datetime]]:
    """Пари (червоний, наступний зелений) за часом завершення; без зеленого — пропуск."""
    ordered = sorted(events)
    pairs = []
    for moment, status in ordered:
        if status != "red":
            continue
        nxt = next((m for m, s in ordered if s == "green" and m > moment), None)
        if nxt is not None:
            pairs.append((moment, nxt))
    return pairs


def incidents(events: Sequence[tuple[datetime, str]]) -> list[tuple[datetime, datetime]]:
    """Те саме, але кілька червоних поспіль — один інцидент від першого червоного."""
    pairs, opened = [], None
    for moment, status in sorted(events):
        if status == "red" and opened is None:
            opened = moment
        elif status == "green" and opened is not None:
            pairs.append((opened, moment))
            opened = None
    return pairs


def _minutes(pairs: Sequence[tuple[datetime, datetime]]) -> list[float]:
    return [(b - a).total_seconds() / 60 for a, b in pairs]


def compute(
    runs: Sequence[Run],
    since: datetime,
    until: datetime,
    step_pattern: str | None = None,
) -> dict:
    """Усі метрики для вікна [since, until): основний варіант і перевірки чутливості."""
    units = build_units(runs)

    def inside(unit: Unit) -> bool:
        return since <= unit.created < until

    window = [u for u in units if inside(u)]
    days = (until - since).total_seconds() / 86400
    green = [u for u in window if u.status == "green"]
    red = [u for u in window if u.status == "red"]
    cancelled = [u for u in window if u.status == "cancelled"]
    # «Усі завершені» — зелені, червоні й скасовані. Пропущений запуск (`skipped`, наприклад
    # публікація образу, коли CI червоний) — не спроба розгортання, тож у знаменник не йде.
    completed = green + red + cancelled

    per_week = len(green) / (days / 7) if days else 0.0
    cfr = 100 * len(red) / len(completed) if completed else 0.0
    cfr_no_cancel = 100 * len(red) / (len(green) + len(red)) if green or red else 0.0

    # Відновлення: червоні запуски вікна; наступний зелений може бути й після вікна.
    events = [(u.completed, u.status) for u in units if u.completed]
    red_moments = {u.completed for u in red if u.completed}
    rec = [p for p in recoveries(events) if p[0] in red_moments]
    inc = [p for p in incidents(events) if p[0] in red_moments]

    # Рівень спроб: кожна спроба (re-run) — окремий прогін конвеєра.
    attempt_rows = [
        a for r in runs if since <= parse_time(r.created_at) < until for a in r.attempts
    ]
    att_red = sum(1 for a in attempt_rows if classify(a.conclusion) == "red")
    att_done = sum(1 for a in attempt_rows if a.completed)
    all_attempt_events = [
        (a.completed, classify(a.conclusion)) for r in runs for a in r.attempts if a.completed
    ]
    red_attempts = {
        a.completed for a in attempt_rows if a.completed and classify(a.conclusion) == "red"
    }
    att_rec = [p for p in recoveries(all_attempt_events) if p[0] in red_attempts]

    changes = lead_times(units, inside)
    hours = [c.hours for c in changes]
    queues = [c.queue for c in changes if c.queue is not None]
    execs = [c.execution for c in changes if c.execution is not None]
    total_minutes = sum(hours) * 60
    review = [(c.merged - c.opened).total_seconds() / 60 for c in changes if c.opened and c.merged]
    branch = [(c.opened - c.start).total_seconds() / 60 for c in changes if c.opened]

    reruns = [
        rerun_record(run)
        for run in runs
        if len(run.attempts) > 1 and since <= parse_time(run.created_at) < until
    ]

    rows = []
    pattern = re.compile(step_pattern) if step_pattern else None
    for number, unit in enumerate(window, 1):
        pull = unit.pull
        run = unit.runs[0]
        rows.append(
            {
                "n": number,
                "sha": unit.sha[:SHORT_SHA],
                "pull": pull.number if pull else None,
                "first_commit_at": pull.first_commit_at if pull else run.commit_at,
                "completed_at": iso(unit.completed),
                "queue_min": unit.queue,
                "execution_min": unit.execution,
                "status": unit.status,
                "attempts": max(len(r.attempts) for r in unit.runs),
                "run": run.id,
                "url": run.url,
                "steps_seconds": sum(r.last.step_seconds(pattern) for r in unit.runs)
                if pattern
                else None,
            }
        )

    lead_level = level(median(hours) or 0.0, LEAD_TIME_LEVELS)
    rec_minutes = _minutes(rec)
    rec_level = level((median(rec_minutes) or 0.0) / 60, RECOVERY_LEVELS)
    return {
        "window": {"since": iso(since), "until": iso(until), "days": days},
        "counts": {
            "runs": len(window),
            "green": len(green),
            "red": len(red),
            "cancelled": len(cancelled),
            "other": len(window) - len(completed),
            "completed": len(completed),
        },
        "deployment_frequency": {
            "per_week": per_week,
            "per_day": per_week / 7,
            "level": deploy_level(per_week / 7),
        },
        "lead_time": {
            "changes": len(changes),
            "mean_hours": mean(hours),
            "median_hours": median(hours),
            "p90_hours": percentile(hours, 90),
            "level": lead_level,
            "buckets": _buckets(hours),
            "own_run_not_green": sum(1 for c in changes if c.own_status != "green"),
            "queue_share": sum(queues) / total_minutes if total_minutes else None,
            "execution_share": sum(execs) / total_minutes if total_minutes else None,
            "median_branch_min": median(branch),
            "median_review_min": median(review),
            "mean_branch_min": mean(branch),
            "mean_review_min": mean(review),
            "median_queue_min": median(queues),
            "median_execution_min": median(execs),
            "mean_queue_min": mean(queues),
            "mean_execution_min": mean(execs),
        },
        "change_fail_rate": {
            "percent": cfr,
            "percent_without_cancelled": cfr_no_cancel,
            "level": level(cfr, CFR_LEVELS),
        },
        "recovery": {
            "count": len(rec_minutes),
            "mean_min": mean(rec_minutes),
            "median_min": median(rec_minutes),
            "level": rec_level,
            "pairs": [[iso(a), iso(b)] for a, b in rec],
            "incidents": len(inc),
            "incident_median_min": median(_minutes(inc)),
            "incident_mean_min": mean(_minutes(inc)),
        },
        "attempts": {
            "count": len(attempt_rows),
            "red": att_red,
            "completed": att_done,
            "cfr_percent": 100 * att_red / att_done if att_done else 0.0,
            "recovery_count": len(att_rec),
            "recovery_median_min": median(_minutes(att_rec)),
            "recovery_mean_min": mean(_minutes(att_rec)),
        },
        "telemetry": {
            "success_rate": 100 * len(green) / len(completed) if completed else None,
            "return_to_green_median_min": median(rec_minutes),
            "duration_median_min": median([u.execution for u in window if u.execution]),
            "duration_p90_min": percentile([u.execution for u in window if u.execution], 90),
            "queue_median_min": median([u.queue for u in window if u.queue is not None]),
            "queue_p90_min": percentile([u.queue for u in window if u.queue is not None], 90),
        },
        "reruns": reruns,
        "rows": rows,
    }


def rerun_record(run: Run) -> dict:
    """Запуск із повторними спробами: чи позеленів він без зміни коду."""
    outcomes = [classify(a.conclusion) for a in run.attempts]
    return {
        "run": run.id,
        "sha": run.sha[:SHORT_SHA],
        "pull": run.pull.number if run.pull else None,
        "url": run.url,
        "attempts": [
            {
                "number": a.number,
                "conclusion": a.conclusion,
                "started_at": a.started_at,
                "completed_at": iso(a.completed),
            }
            for a in run.attempts
        ],
        "green_without_code_change": outcomes[-1] == "green" and "red" in outcomes[:-1],
    }


def _buckets(hours: Sequence[float]) -> dict[str, int]:
    result = {name: 0 for _, name, _ in LEAD_TIME_LEVELS}
    for value in hours:
        result[level(value, LEAD_TIME_LEVELS)[0]] += 1
    return result


# ---------------------------------------------------------------------- звіт (MD)


def _num(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "—"
    return f"{value:.{digits}f}".replace(".", ",")


def _kyiv(value: str | None) -> str:
    """UTC → «дд.мм гг:хх» за Києвом (UTC+2 після 25.10, UTC+3 до)."""
    moment = parse_time(value)
    if moment is None:
        return "—"
    return moment.astimezone(ZoneInfo("Europe/Kyiv")).strftime("%d.%m %H:%M")


def render(result: dict, meta: dict) -> str:
    """Markdown-звіт для docs/ci-cd/."""
    c, df, lt = result["counts"], result["deployment_frequency"], result["lead_time"]
    cfr, rec, att, tel = (
        result["change_fail_rate"],
        result["recovery"],
        result["attempts"],
        result["telemetry"],
    )
    lines = [
        f"# {meta.get('title', 'Метрики DORA — автоматичний розрахунок')}",
        "",
        "> Згенеровано `scripts/dora_metrics.py` (Лаб 10, бонус 1). Не редагуйте вручну —",
        "> перезапустіть команду нижче.",
        "",
        f"- **Репозиторій:** `{meta['repo']}` · **гілка:** `{meta['branch']}` · "
        f"**подія:** `{meta['event']}` · **workflow:** "
        + ", ".join(f"`{w}`" for w in meta["workflows"]),
        f"- **Вікно:** {result['window']['since']} — {result['window']['until']} "
        f"({_num(result['window']['days'], 0)} дн., межа праворуч не включена)",
        f"- **Дані зібрано:** {meta.get('collected_at', '—')}",
        f"- **Команда:** `{meta.get('command', '')}`",
        "",
        "## 1. Чотири метрики",
        "",
        "| Метрика | Формула | Результат | Рівень DORA 2025 → Top % |",
        "|---|---|---|---|",
        f"| Частота розгортань | зелені запуски / тижні вікна | **{_num(df['per_week'])} / тиждень** "
        f"({_num(df['per_day'])} / добу); зелених {c['green']} | {df['level'][0]} → "
        f"{_num(df['level'][1])} % |",
        f"| Час виконання змін | перший коміт PR → завершення зеленого запуску з комітом | "
        f"медіана **{_num(lt['median_hours'], 2)} год** · середнє {_num(lt['mean_hours'], 2)} год "
        f"· p90 {_num(lt['p90_hours'], 1)} год (змін: {lt['changes']}) | {lt['level'][0]} → "
        f"{_num(lt['level'][1])} % |",
        f"| Частота збоїв змін | червоні / усі завершені | **{_num(cfr['percent'])} %** "
        f"({c['red']} / {c['completed']}); без скасованих — {_num(cfr['percent_without_cancelled'])} % "
        f"| {cfr['level'][0]} → {_num(cfr['level'][1])} % |",
        f"| Час відновлення | червоний → наступний зелений (завершення) | медіана "
        f"**{_num(rec['median_min'], 0)} хв** · середнє {_num(rec['mean_min'], 0)} хв "
        f"(випадків: {rec['count']}) | {rec['level'][0]} → {_num(rec['level'][1])} % |",
        "",
        f"Запусків у вікні: {c['runs']} — зелених {c['green']}, червоних {c['red']}, "
        f"скасованих {c['cancelled']}.",
        "",
        "## 2. Черга й виконання в часі виконання змін",
        "",
        "| Складова | Медіана, хв | Середнє, хв | Частка суми часу виконання змін |",
        "|---|--:|--:|--:|",
        f"| Робота в гілці (1-й коміт → відкриття PR) | {_num(lt['median_branch_min'])} | "
        f"{_num(lt['mean_branch_min'])} | — |",
        f"| Очікування рев'ю (відкриття → злиття PR) | {_num(lt['median_review_min'])} | "
        f"{_num(lt['mean_review_min'])} | — |",
        f"| **Черга CI** | {_num(lt['median_queue_min'], 2)} | {_num(lt['mean_queue_min'])} | "
        f"**{_num((lt['queue_share'] or 0) * 100, 2)} %** |",
        f"| **Виконання CI** | {_num(lt['median_execution_min'])} | "
        f"{_num(lt['mean_execution_min'])} | **{_num((lt['execution_share'] or 0) * 100, 2)} %** |",
        "",
        "Черга й виконання взято з того зеленого запуску, що завершив відлік зміни.",
        f"Змін, чий власний запуск не був зеленим (доїхали з наступним зеленим): "
        f"{lt['own_run_not_green']}.",
        "",
        "Розподіл часу виконання змін за рівнями DORA: "
        + "; ".join(f"{k} — {v}" for k, v in lt["buckets"].items() if v),
        "",
        "## 3. Телеметрія CI проти орієнтирів CircleCI",
        "",
        "| Показник | Орієнтир | Наше значення |",
        "|---|---|---|",
        f"| Успішність запусків на основній гілці | 90 % | {_num(tel['success_rate'])} % |",
        f"| Повернення основної гілки до зеленого | до 60 хв | медіана "
        f"{_num(tel['return_to_green_median_min'], 0)} хв |",
        f"| Тривалість запуску workflow | до 10 хв | медіана {_num(tel['duration_median_min'])} хв"
        f", p90 {_num(tel['duration_p90_min'])} хв |",
        f"| Черга (довідково) | — | медіана {_num(tel['queue_median_min'], 2)} хв, p90 "
        f"{_num(tel['queue_p90_min'])} хв |",
        "",
        "## 4. Перевірки чутливості",
        "",
        "| Варіант | Значення |",
        "|---|---|",
        f"| Частота розгортань за строгим прочитанням рівня «{DEPLOY_STRICT_HOURLY_DAILY[0]}» "
        f"(для 1–24 розгортань на добу) | {_num(df['per_day'])} / добу → "
        f"{_num(DEPLOY_STRICT_HOURLY_DAILY[1])} % |",
        f"| Частота збоїв без скасованих у знаменнику | {_num(cfr['percent_without_cancelled'])} % |",
        f"| Відновлення по інцидентах (червоні поспіль — один випадок) | {rec['incidents']} "
        f"інцидентів; медіана {_num(rec['incident_median_min'], 0)} хв, середнє "
        f"{_num(rec['incident_mean_min'], 0)} хв |",
        f"| Рівень спроб (кожен re-run — окремий прогін) | спроб {att['count']}, червоних "
        f"{att['red']}; частота збоїв {_num(att['cfr_percent'])} %; відновлень "
        f"{att['recovery_count']}, медіана {_num(att['recovery_median_min'], 0)} хв, середнє "
        f"{_num(att['recovery_mean_min'], 0)} хв |",
        "",
        "## 5. Запуски на гілці, що мали повторні спроби (re-run)",
        "",
    ]
    if result["reruns"]:
        lines += [
            "| Запуск | Коміт | PR | Спроби | Позеленів без зміни коду |",
            "|---|---|---|---|---|",
        ]
        for item in result["reruns"]:
            tries = " → ".join(
                f"{a['number']}: {a['conclusion']} ({_kyiv(a['completed_at'])})"
                for a in item["attempts"]
            )
            pull = f"#{item['pull']}" if item["pull"] else "—"
            flag = "**так**" if item["green_without_code_change"] else "ні"
            lines.append(
                f"| [{item['run']}]({item['url']}) | `{item['sha']}` | {pull} | {tries} | {flag} |"
            )
    else:
        lines.append("Повторних спроб у вікні немає.")
    has_steps = any(r["steps_seconds"] is not None for r in result["rows"])
    lines += [
        "",
        "## 6. Запуски (час — Київ)",
        "",
        "| № | Коміт | PR | Перший коміт PR | Запуск завершено | Черга, хв | Виконання, хв "
        "| Статус | Спроб |" + (" Кроки, с |" if has_steps else ""),
        "|--:|---|--:|---|---|--:|--:|:--:|--:|" + ("--:|" if has_steps else ""),
    ]
    icons = {"green": "✅", "red": "❌", "cancelled": "⏹️", "other": "·"}
    for row in result["rows"]:
        pull = f"#{row['pull']}" if row["pull"] else "—"
        cells = [
            str(row["n"]),
            f"[`{row['sha']}`]({row['url']})" if row["url"] else f"`{row['sha']}`",
            pull,
            _kyiv(row["first_commit_at"]),
            _kyiv(row["completed_at"]),
            _num(row["queue_min"]),
            _num(row["execution_min"]),
            icons.get(row["status"], "·"),
            str(row["attempts"]),
        ]
        if has_steps:
            cells.append(_num(row["steps_seconds"], 0))
        lines.append("| " + " | ".join(cells) + " |")
    lines += [
        "",
        "## Як відтворити",
        "",
        "```bash",
        meta.get("command", "python scripts/dora_metrics.py --help"),
        "```",
        "",
    ]
    return "\n".join(lines)


# ------------------------------------------------------------------ збір даних (API)


class ApiError(RuntimeError):
    """Помилка запиту до GitHub API."""


def _check_api_path(path: str) -> str:
    """Лише відносний шлях `repos/...` без схеми й без сегментів `..` — щоб не вийти за API."""
    route = path.split("?", 1)[0]
    if not re.fullmatch(r"repos/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/[A-Za-z0-9_./=&%:-]+", route):
        raise ApiError(f"недозволений шлях API: {path}")
    if ".." in route.split("/"):
        raise ApiError(f"недозволений шлях API: {path}")
    if "?" in path and not re.fullmatch(r"[A-Za-z0-9_.=&%:-]+", path.split("?", 1)[1]):
        raise ApiError(f"недозволений запит API: {path}")
    return path


def gh_transport(path: str) -> object:
    """GET через `gh api` — використовує вхід, зроблений `gh auth login`."""
    gh = shutil.which("gh")
    if gh is None:
        raise ApiError("gh не знайдено в PATH")
    completed = subprocess.run(  # noqa: S603 -- fixed executable, argument list, no shell
        [gh, "api", "-H", "Accept: application/vnd.github+json", _check_api_path(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=60,
    )  # nosec B603
    if completed.returncode:
        raise ApiError(f"gh api {path}: {completed.stderr.strip()[:300]}")
    return json.loads(completed.stdout)


def http_transport(path: str) -> object:
    """GET напряму через HTTPS (токен — з GH_TOKEN або GITHUB_TOKEN, якщо заданий)."""
    url = API_ROOT + _check_api_path(path)
    if urllib.parse.urlsplit(url).scheme != "https":  # pragma: no cover - константа
        raise ApiError("лише https")
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})  # noqa: S310
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        # URL is built from the fixed https://api.github.com/ root and a validated path.
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310  # nosec B310
            return json.loads(response.read().decode("utf-8"))
    except OSError as error:
        raise ApiError(f"GET {path}: {error}") from None


def pick_transport(name: str) -> Callable[[str], object]:
    """auto → gh, якщо встановлено, інакше HTTPS."""
    if name == "gh" or (name == "auto" and shutil.which("gh")):
        return gh_transport
    return http_transport


class Collector:
    """Збирає набір даних через транспорт; кеш — лише в межах одного запуску."""

    def __init__(self, repo: str, get: Callable[[str], object], *, with_steps: bool = False):
        """repo — `власник/назва`; get — функція GET для шляху `repos/...`."""
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
            raise ApiError(f"неправильна назва репозиторію: {repo}")
        self.repo, self.get, self.with_steps = repo, get, with_steps
        self._cache: dict[str, object] = {}
        self.calls = 0

    def api(self, tail: str) -> object:
        """GET `repos/<repo>/<tail>` із кешем."""
        path = f"repos/{self.repo}/{tail}"
        if path not in self._cache:
            self.calls += 1
            self._cache[path] = self.get(path)
        return self._cache[path]

    def runs(self, branch: str, event: str, since: date, until: date) -> list[dict]:
        """Усі запуски гілки й події, створені в [since, until] (дати UTC, включно)."""
        query = urllib.parse.urlencode(
            {"branch": branch, "event": event, "created": f"{since}..{until}", "per_page": 100}
        )
        items, page = [], 1
        while True:
            data = self.api(f"actions/runs?{query}&page={page}")
            batch = data.get("workflow_runs", []) if isinstance(data, dict) else []
            items += batch
            if len(batch) < 100:
                return items
            page += 1

    def jobs(self, run_id: int, attempt: int) -> list[Job]:
        """Jobs однієї спроби."""
        data = self.api(f"actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100")
        jobs = []
        for job in data.get("jobs", []):
            steps = []
            if self.with_steps:
                for step in job.get("steps") or []:
                    begin, end = (
                        parse_time(step.get("started_at")),
                        parse_time(step.get("completed_at")),
                    )
                    seconds = (end - begin).total_seconds() if begin and end else 0.0
                    steps.append([step.get("name", ""), seconds, step.get("conclusion")])
            jobs.append(
                Job(
                    name=job.get("name", ""),
                    started_at=job.get("started_at"),
                    completed_at=job.get("completed_at"),
                    conclusion=job.get("conclusion"),
                    runner=job.get("runner_name"),
                    steps=steps,
                )
            )
        return jobs

    def pull_for(self, sha: str) -> Pull | None:
        """Злитий PR, з якого прийшов коміт, і дата його першого коміту."""
        pulls = self.api(f"commits/{sha}/pulls")
        merged = [p for p in pulls if p.get("merged_at")] if isinstance(pulls, list) else []
        exact = [p for p in merged if p.get("merge_commit_sha") == sha]
        chosen = (exact or merged or [None])[0]
        if chosen is None:
            return None
        number = chosen["number"]
        commits = self.api(f"pulls/{number}/commits?per_page=100")
        detail = self.api(f"pulls/{number}")
        first = commits[0]["commit"]["author"]["date"] if commits else chosen["created_at"]
        lines = (detail.get("additions") or 0) + (detail.get("deletions") or 0)
        return Pull(
            number=number,
            created_at=chosen["created_at"],
            merged_at=chosen.get("merged_at"),
            first_commit_at=first,
            changed_lines=lines,
        )

    def collect(
        self,
        branch: str,
        event: str,
        workflows: Sequence[str],
        since: datetime,
        until: datetime,
        lookahead_days: int,
    ) -> list[Run]:
        """Запуски вікна (+ запас праворуч для кінця відліку) з усіма спробами й PR."""
        last_day = (until + timedelta(days=lookahead_days)).date()
        raw = self.runs(branch, event, since.date(), last_day)
        runs = []
        for item in sorted(raw, key=lambda r: r["created_at"]):
            if item.get("name") not in workflows or item.get("status") != "completed":
                continue
            attempts = []
            for number in range(1, int(item.get("run_attempt") or 1) + 1):
                if number == item.get("run_attempt"):
                    meta = item
                else:
                    meta = self.api(f"actions/runs/{item['id']}/attempts/{number}")
                attempts.append(
                    Attempt(
                        number=number,
                        started_at=meta.get("run_started_at") or meta["created_at"],
                        conclusion=meta.get("conclusion"),
                        updated_at=meta.get("updated_at"),
                        jobs=self.jobs(item["id"], number),
                    )
                )
            sha = item["head_sha"]
            pull = self.pull_for(sha) if event in ("push", "workflow_run") else None
            commit_at = None
            if pull is None:
                commit = self.api(f"commits/{sha}")
                commit_at = commit["commit"]["author"]["date"]
            runs.append(
                Run(
                    id=item["id"],
                    workflow=item["name"],
                    sha=sha,
                    created_at=item["created_at"],
                    attempts=attempts,
                    url=item.get("html_url", ""),
                    event=item.get("event", event),
                    pull=pull,
                    commit_at=commit_at,
                )
            )
        return runs


# ---------------------------------------------------------------------- CLI і файли


def safe_output(path: Path) -> Path:
    """Писати можна лише всередині поточного каталогу (кореня репозиторію)."""
    root = Path.cwd().resolve()
    target = path.resolve()
    if not target.is_relative_to(root):
        raise ApiError(f"шлях поза репозиторієм: {path}")
    return target


def write_report(path: Path, content: str) -> None:
    """Записує звіт у дозволеному каталозі без переходу за symlink файлу."""
    target = safe_output(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target = safe_output(target)

    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW
    try:
        fd = os.open(target, flags, 0o600)
    except OSError as error:
        raise ApiError(f"не вдалося відкрити файл: {path}: {error}") from error

    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(content)


def unique_prefix(shas: Iterable[str], minimum: int = SHORT_SHA) -> int:
    """Найкоротша довжина префікса (не менше minimum), за якої всі SHA різні — як у git."""
    values = set(shas)
    for length in range(minimum, 41):
        if len({v[:length] for v in values}) == len(values):
            return length
    return 40


def save_dataset(path: Path, runs: Sequence[Run], meta: dict) -> None:
    """Набір даних — короткі SHA (від 7 символів), без токенів і тіл відповідей.

    Повні 40-символьні SHA detect-secrets у CI приймає за можливі секрети, тому зберігаємо
    найкоротший унікальний префікс: для перерахунку цього досить.
    """
    length = unique_prefix(r.sha for r in runs)
    payload = {"meta": meta, "runs": []}
    for run in runs:
        data = asdict(run)
        data["sha"] = run.sha[:length]
        payload["runs"].append(data)
    write_report(path, json.dumps(payload, ensure_ascii=False, indent=1) + "\n")


def load_dataset(path: Path) -> tuple[list[Run], dict]:
    """Читає набір даних, збережений save_dataset."""
    target = safe_output(path)
    if not target.is_file():
        raise ApiError(f"не знайдено набір даних: {path}")
    payload = json.loads(target.read_text(encoding="utf-8"))
    return [run_from_dict(r) for r in payload["runs"]], payload["meta"]


def _date(value: str) -> datetime:
    return datetime.combine(date.fromisoformat(value), datetime.min.time(), tzinfo=UTC)


def build_parser() -> argparse.ArgumentParser:
    """Аргументи командного рядка."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--since", type=_date, help="початок вікна, дата UTC (включно)")
    source.add_argument("--from-dataset", type=Path, help="перерахувати зі збереженого JSON")
    parser.add_argument("--until", type=_date, help="кінець вікна, дата UTC (не включно)")
    parser.add_argument("--repo", default=DEFAULT_REPO, help="власник/назва")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--event", default="push", help="push або workflow_run")
    parser.add_argument(
        "--workflow", action="append", help="назва workflow (можна кілька; типово CI)"
    )
    parser.add_argument("--lookahead-days", type=int, default=7)
    parser.add_argument("--transport", choices=("auto", "gh", "http"), default="auto")
    parser.add_argument("--with-steps", action="store_true", help="зберегти тривалості кроків")
    parser.add_argument("--step-pattern", help="регулярний вираз назв кроків для стовпця «Кроки»")
    parser.add_argument("--dataset", type=Path, help="куди зберегти зібраний набір даних")
    parser.add_argument("--out", type=Path, help="Markdown-звіт")
    parser.add_argument("--json", type=Path, help="метрики у JSON")
    parser.add_argument("--title", help="заголовок звіту")
    return parser


def main(argv: list[str] | None = None, *, transport: Callable[[str], object] | None = None) -> int:
    """Точка входу CLI; transport — для тестів (замість мережі)."""
    args = build_parser().parse_args(argv)
    try:
        if args.from_dataset:
            runs, meta = load_dataset(args.from_dataset)
            since, until = parse_time(meta["since"]), parse_time(meta["until"])
            if args.since or args.until:
                raise ApiError("--from-dataset бере вікно з набору даних")
        else:
            if args.until is None or args.until <= args.since:
                raise ApiError("потрібен --until, пізніший за --since")
            since, until = args.since, args.until
            workflows = args.workflow or ["CI"]
            collector = Collector(
                args.repo, transport or pick_transport(args.transport), with_steps=args.with_steps
            )
            runs = collector.collect(
                args.branch, args.event, workflows, since, until, args.lookahead_days
            )
            meta = {
                "repo": args.repo,
                "branch": args.branch,
                "event": args.event,
                "workflows": workflows,
                "since": iso(since),
                "until": iso(until),
                "collected_at": iso(datetime.now(UTC)),
                "api_calls": collector.calls,
            }
            if args.dataset:
                save_dataset(args.dataset, runs, meta)
        meta["command"] = "python scripts/dora_metrics.py " + " ".join(
            argv if argv is not None else sys.argv[1:]
        )
        if args.title:
            meta["title"] = args.title
        result = compute(runs, since, until, step_pattern=args.step_pattern)
        if args.out:
            write_report(args.out, render(result, meta))
        if args.json:
            payload = {"meta": meta, "metrics": {k: v for k, v in result.items() if k != "rows"}}
            write_report(
                args.json,
                json.dumps(payload, ensure_ascii=False, indent=1, default=str) + "\n",
            )
    except (ApiError, re.error, KeyError, ValueError) as error:
        print(f"Помилка: {error}", file=sys.stderr)
        return 2
    c, lt = result["counts"], result["lead_time"]
    print(
        f"Запусків {c['runs']}: зелених {c['green']}, червоних {c['red']}, скасованих "
        f"{c['cancelled']}. Розгортань/тиждень {_num(result['deployment_frequency']['per_week'])}; "
        f"час виконання змін — медіана {_num(lt['median_hours'], 2)} год; частота збоїв "
        f"{_num(result['change_fail_rate']['percent'])} %; відновлення — медіана "
        f"{_num(result['recovery']['median_min'], 0)} хв."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
