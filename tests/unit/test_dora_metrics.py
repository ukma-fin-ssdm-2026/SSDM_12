"""Метрики DORA з історії запусків CI (Лаб 10, бонус 1; QA-22).

Набори даних синтетичні: кожен тест задає запуски так, щоб очікуване значення можна
було порахувати вручну. Мережі тести не потребують — транспорт API підмінено.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from scripts import dora_metrics as dm

pytestmark = pytest.mark.req("QA-22")

T0 = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)  # понеділок; вікно — тиждень від T0
WEEK = (T0, T0 + timedelta(days=7))


def at(minutes: float) -> str:
    """Момент T0 + minutes у форматі GitHub API."""
    return dm.iso(T0 + timedelta(minutes=minutes))


def attempt(number: int, start: float, queue: float, run: float, conclusion: str) -> dm.Attempt:
    """Спроба з одним job: старт спроби, черга й виконання — у хвилинах від T0."""
    job = dm.Job("build", at(start + queue), at(start + queue + run), conclusion)
    return dm.Attempt(number, at(start), conclusion, [job])


def run(
    run_id: int,
    created: float,
    conclusion: str = "success",
    *,
    queue: float = 1,
    duration: float = 5,
    first_commit: float | None = None,
    pull: int | None = None,
    attempts: list[dm.Attempt] | None = None,
    workflow: str = "CI",
    sha: str | None = None,
) -> dm.Run:
    """Запуск на main: за замовчуванням одна спроба й PR із першим комітом за 60 хв."""
    tries = attempts or [attempt(1, created, queue, duration, conclusion)]
    first = created - 60 if first_commit is None else first_commit
    return dm.Run(
        id=run_id,
        workflow=workflow,
        sha=sha or f"{run_id:07x}".ljust(40, "f"),
        created_at=at(created),
        attempts=tries,
        url=f"https://example.invalid/runs/{run_id}",
        pull=dm.Pull(pull or run_id, at(first + 10), at(created), at(first)),
    )


def test_queue_and_execution_are_measured_per_attempt():
    a = attempt(1, 0, queue=3, run=7, conclusion="success")
    assert a.queue_minutes == pytest.approx(3)
    assert a.execution_minutes == pytest.approx(7)


def test_execution_spans_from_first_job_start_to_last_job_end():
    jobs = [dm.Job("build", at(1), at(6), "success"), dm.Job("reliability", at(6), at(8))]
    a = dm.Attempt(1, at(0), "success", jobs)
    assert a.queue_minutes == pytest.approx(1)
    assert a.execution_minutes == pytest.approx(7)  # два jobs на одному раннері — послідовно


def test_job_that_never_started_has_no_queue_or_execution():
    a = dm.Attempt(1, at(0), "cancelled", [dm.Job("build", None, None, "cancelled")], at(5))
    assert a.queue_minutes is None
    assert a.execution_minutes is None
    assert a.completed == T0 + timedelta(minutes=5)


@pytest.mark.parametrize(
    ("conclusion", "expected"),
    [
        ("success", "green"),
        ("failure", "red"),
        ("timed_out", "red"),
        ("startup_failure", "red"),
        ("cancelled", "cancelled"),
        ("skipped", "other"),
        (None, "other"),
    ],
)
def test_conclusions_are_classified(conclusion, expected):
    assert dm.classify(conclusion) == expected


def test_deployment_frequency_counts_green_runs_per_week():
    runs = [run(i, i * 600) for i in range(1, 5)] + [run(9, 3000, "failure")]
    result = dm.compute(runs, *WEEK)
    assert result["deployment_frequency"]["per_week"] == pytest.approx(4)
    assert result["deployment_frequency"]["level"] == ("від разу на добу до разу на тиждень", 44.6)


def test_change_fail_rate_uses_all_completed_runs_including_cancelled():
    runs = [run(1, 0), run(2, 100, "failure"), run(3, 200, "cancelled"), run(4, 300)]
    cfr = dm.compute(runs, *WEEK)["change_fail_rate"]
    assert cfr["percent"] == pytest.approx(25)  # 1 / 4 за визначенням курсу
    assert cfr["percent_without_cancelled"] == pytest.approx(100 / 3)


def test_skipped_runs_are_not_deployment_attempts():
    """Публікація образу пропущена, бо CI червоний: це не розгортання й не збій."""
    runs = [run(1, 0), run(2, 100, "skipped"), run(3, 200, "failure"), run(4, 300)]
    result = dm.compute(runs, *WEEK)
    assert result["counts"]["other"] == 1
    assert result["change_fail_rate"]["percent"] == pytest.approx(100 / 3)
    changes = dm.lead_times(dm.build_units(runs), lambda u: True)
    assert len(changes) == 4  # зміна з пропущеним запуском доїжджає з наступним зеленим


def test_collector_asks_only_for_push_runs_on_main():
    get, calls = transport_for({"actions/runs": {"workflow_runs": []}})
    collector = dm.Collector("a/b", get)
    assert collector.collect("main", "push", ["CI"], *WEEK, lookahead_days=7) == []
    (call,) = calls  # червоні запуски PR не потрапляють навіть у запит
    assert "branch=main" in call
    assert "event=push" in call
    assert "created=2026-11-02..2026-11-16" in call


def test_recovery_runs_from_red_completion_to_next_green_completion():
    runs = [run(1, 0, "failure", duration=10), run(2, 100, duration=5), run(3, 200)]
    rec = dm.compute(runs, *WEEK)["recovery"]
    assert rec["count"] == 1
    assert rec["median_min"] == pytest.approx((100 + 1 + 5) - (0 + 1 + 10))


def test_consecutive_red_runs_are_separate_failures_but_one_incident():
    runs = [run(1, 0, "failure"), run(2, 30, "failure"), run(3, 100)]
    rec = dm.compute(runs, *WEEK)["recovery"]
    assert rec["count"] == 2
    assert rec["incidents"] == 1
    assert rec["incident_median_min"] == pytest.approx(100 - 0)


def test_recovery_may_end_after_the_window():
    runs = [run(1, 7 * 1440 - 30, "failure"), run(2, 7 * 1440 + 30)]
    rec = dm.compute(runs, *WEEK)["recovery"]
    assert rec["count"] == 1
    assert rec["median_min"] == pytest.approx(60)


def test_lead_time_starts_at_first_pull_request_commit():
    lt = dm.compute([run(1, 300, first_commit=0, queue=2, duration=8)], *WEEK)["lead_time"]
    assert lt["median_hours"] == pytest.approx((300 + 2 + 8) / 60)


def test_change_whose_own_run_is_red_arrives_with_the_next_green_run():
    runs = [
        run(1, 100, "failure", first_commit=0),
        run(2, 200, first_commit=150, queue=1, duration=4),
    ]
    lt = dm.compute(runs, *WEEK)["lead_time"]
    assert lt["changes"] == 2
    assert lt["own_run_not_green"] == 1
    changes = dm.lead_times(dm.build_units(runs), lambda u: True)
    assert [round(c.hours * 60) for c in changes] == [205, 55]


def test_change_without_a_later_green_run_is_not_yet_deployed():
    runs = [run(1, 0), run(2, 100, "failure")]
    assert dm.compute(runs, *WEEK)["lead_time"]["changes"] == 1


def test_direct_push_without_pull_request_starts_at_the_commit():
    direct = run(1, 120, queue=0, duration=10)
    direct.pull, direct.commit_at = None, at(100)
    change = dm.lead_times(dm.build_units([direct]), lambda u: True)[0]
    assert change.pull is None
    assert change.hours * 60 == pytest.approx(30)


def test_queue_and_execution_shares_come_from_the_green_run_that_ends_lead_time():
    runs = [run(1, 60, first_commit=0, queue=6, duration=24)]  # 90 хв усього
    lt = dm.compute(runs, *WEEK)["lead_time"]
    assert lt["queue_share"] == pytest.approx(6 / 90)
    assert lt["execution_share"] == pytest.approx(24 / 90)
    assert lt["median_review_min"] == pytest.approx(50)  # PR відкрито через 10 хв


def test_rerun_that_turned_green_without_code_change_is_listed():
    tries = [attempt(1, 0, 0, 10, "failure"), attempt(2, 420, 0, 5, "success")]
    result = dm.compute([run(1, 0, attempts=tries), run(2, 600)], *WEEK)
    assert result["counts"]["green"] == 2  # gh run list бачить лише останню спробу
    (rerun,) = result["reruns"]
    assert rerun["green_without_code_change"] is True
    assert [a["conclusion"] for a in rerun["attempts"]] == ["failure", "success"]
    assert result["attempts"]["red"] == 1
    assert result["attempts"]["cfr_percent"] == pytest.approx(100 / 3)
    assert result["attempts"]["recovery_median_min"] == pytest.approx(425 - 10)


def test_rerun_that_stayed_red_is_not_green_without_code_change():
    tries = [attempt(1, 0, 0, 10, "failure"), attempt(2, 30, 0, 10, "failure")]
    (rerun,) = dm.compute([run(1, 0, attempts=tries)], *WEEK)["reruns"]
    assert rerun["green_without_code_change"] is False


def test_commit_is_red_if_any_counted_workflow_is_red():
    sha = "a" * 40
    runs = [run(1, 0, sha=sha), run(2, 0, "failure", workflow="API docs", sha=sha)]
    (unit,) = dm.build_units(runs)
    assert unit.status == "red"


def test_commit_is_green_only_if_all_counted_workflows_are_green():
    sha = "b" * 40
    runs = [run(1, 0, sha=sha, duration=5), run(2, 0, sha=sha, workflow="Docs", duration=9)]
    (unit,) = dm.build_units(runs)
    assert unit.status == "green"
    assert unit.completed == T0 + timedelta(minutes=1 + 9)  # коміт зелений, коли зелені всі


def test_runs_outside_the_window_are_not_counted():
    runs = [run(1, -60), run(2, 60), run(3, 7 * 1440 + 1)]
    assert dm.compute(runs, *WEEK)["counts"]["runs"] == 1


@pytest.mark.parametrize(
    ("hours", "expected"),
    [
        (0.99, ("менше години", 9.4)),
        (1.0, ("менше доби", 24.4)),
        (23.9, ("менше доби", 24.4)),
        (24.0, ("від доби до тижня", 56.4)),
        (24 * 200, ("понад шість місяців", 100.0)),
    ],
)
def test_lead_time_levels_follow_dora_2025(hours, expected):
    assert dm.level(hours, dm.LEAD_TIME_LEVELS) == expected


@pytest.mark.parametrize(
    ("percent", "expected"),
    [
        (0.0, ("0–2 %", 8.5)),
        (5.8, ("4–8 %", 36.2)),
        (8.0, ("8–16 %", 62.2)),
        (70, ("понад 64 %", 100.0)),
    ],
)
def test_change_fail_rate_levels_follow_dora_2025(percent, expected):
    assert dm.level(percent, dm.CFR_LEVELS) == expected


@pytest.mark.parametrize(
    ("per_day", "top"),
    [(4.6, 16.2), (1.0, 44.6), (4 / 7, 44.6), (1 / 10, 76.1), (0.0, 100.0)],
)
def test_deployment_frequency_levels_follow_dora_2025(per_day, top):
    assert dm.deploy_level(per_day)[1] == top


def test_percentile_is_nearest_rank():
    assert dm.percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 90) == 9
    assert dm.percentile([], 90) is None


@pytest.mark.parametrize(
    "path",
    [
        "repos/a/b/../../../user",
        "https://evil.example/repos/a/b/x",
        "users/octocat",
        "repos/a/b/actions/runs?q=$(rm)",
    ],
)
def test_api_paths_outside_the_repository_are_rejected(path):
    with pytest.raises(dm.ApiError):
        dm._check_api_path(path)


def test_api_query_with_github_date_range_is_allowed():
    path = "repos/a/b/actions/runs?branch=main&created=2026-10-19..2026-11-09&page=1"
    assert dm._check_api_path(path) == path


def fake_api(runs_payload: dict) -> dict[str, object]:
    """Відповіді API для одного запуску з PR #7 (перший коміт за 2 год до злиття)."""
    sha = "c" * 40
    return {
        "actions/runs": runs_payload,
        "actions/runs/42/attempts/1/jobs": {
            "jobs": [
                {
                    "name": "build",
                    "started_at": at(1),
                    "completed_at": at(6),
                    "conclusion": "success",
                    "runner_name": "SSDM12-Windows",
                    "steps": [
                        {
                            "name": "Install API dependencies",
                            "started_at": at(1),
                            "completed_at": at(2),
                            "conclusion": "success",
                        },
                    ],
                }
            ]
        },
        f"commits/{sha}/pulls": [
            {"number": 7, "merged_at": at(0), "merge_commit_sha": sha, "created_at": at(-60)}
        ],
        "pulls/7/commits": [{"commit": {"author": {"date": at(-120)}}}],
        "pulls/7": {"additions": 10, "deletions": 2},
    }


def transport_for(responses: dict[str, object]):
    calls = []

    def get(path: str) -> object:
        calls.append(path)
        tail = path.split("/", 3)[3]
        for prefix, payload in responses.items():
            if tail.split("?")[0] == prefix:
                return payload
        raise AssertionError(f"unexpected API call: {path}")

    return get, calls


def test_cli_collects_from_the_api_and_writes_dataset_and_report(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    payload = {
        "workflow_runs": [
            {
                "id": 42,
                "name": "CI",
                "status": "completed",
                "conclusion": "success",
                "head_sha": "c" * 40,
                "created_at": at(0),
                "run_started_at": at(0),
                "run_attempt": 1,
                "html_url": "https://example.invalid/42",
                "event": "push",
            },
            {
                "id": 43,
                "name": "API docs",
                "status": "completed",
                "conclusion": "failure",
                "head_sha": "c" * 40,
                "created_at": at(0),
                "run_attempt": 1,
            },
        ]
    }
    get, calls = transport_for(fake_api(payload))
    code = dm.main(
        [
            "--since",
            "2026-11-02",
            "--until",
            "2026-11-09",
            "--with-steps",
            "--step-pattern",
            "Install",
            "--dataset",
            "evidence/data.json",
            "--out",
            "dora.md",
            "--json",
            "dora.json",
        ],
        transport=get,
    )
    assert code == 0
    assert all(c.startswith("repos/ukma-fin-ssdm-2026/SSDM_12/") for c in calls)
    report = (tmp_path / "dora.md").read_text(encoding="utf-8")
    assert "**1,0 / тиждень**" in report
    assert "| 1 | [`ccccccc`]" in report  # короткий SHA, workflow «API docs» не враховано
    data = json.loads((tmp_path / "evidence/data.json").read_text(encoding="utf-8"))
    assert data["runs"][0]["sha"] == "ccccccc"
    assert data["runs"][0]["attempts"][0]["jobs"][0]["steps"][0][1] == 60.0
    metrics = json.loads((tmp_path / "dora.json").read_text(encoding="utf-8"))
    assert metrics["metrics"]["lead_time"]["median_hours"] == pytest.approx(2.1)


def test_cli_recomputes_offline_from_a_saved_dataset(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    meta = {
        "repo": "a/b",
        "branch": "main",
        "event": "push",
        "workflows": ["CI"],
        "since": dm.iso(WEEK[0]),
        "until": dm.iso(WEEK[1]),
    }
    dm.save_dataset(tmp_path / "d.json", [run(1, 0), run(2, 100, "failure")], meta)
    assert dm.main(["--from-dataset", "d.json", "--out", "r.md"]) == 0
    assert "**50,0 %** (1 / 2)" in (tmp_path / "r.md").read_text(encoding="utf-8")


def test_saved_dataset_keeps_short_shas_unique(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    twins = [run(1, 0, sha="abcdef01" + "0" * 32), run(2, 100, sha="abcdef02" + "0" * 32)]
    meta = {
        "repo": "a/b",
        "branch": "main",
        "event": "push",
        "workflows": ["CI"],
        "since": dm.iso(WEEK[0]),
        "until": dm.iso(WEEK[1]),
    }
    dm.save_dataset(tmp_path / "d.json", twins, meta)
    loaded, _ = dm.load_dataset(tmp_path / "d.json")
    assert [r.sha for r in loaded] == ["abcdef01", "abcdef02"]
    assert dm.compute(loaded, *WEEK)["counts"]["runs"] == 2


@pytest.mark.parametrize(
    "argv",
    [
        ["--since", "2026-11-09", "--until", "2026-11-02"],
        ["--since", "2026-11-02"],
        ["--from-dataset", "missing.json"],
        ["--since", "2026-11-02", "--until", "2026-11-09", "--repo", "a/b/../c"],
    ],
)
def test_cli_rejects_bad_arguments_with_exit_code_2(tmp_path, monkeypatch, argv):
    monkeypatch.chdir(tmp_path)
    assert dm.main(argv, transport=lambda path: {}) == 2


def test_cli_refuses_to_write_outside_the_repository(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    meta = {
        "repo": "a/b",
        "branch": "main",
        "event": "push",
        "workflows": ["CI"],
        "since": dm.iso(WEEK[0]),
        "until": dm.iso(WEEK[1]),
    }
    dm.save_dataset(tmp_path / "d.json", [run(1, 0)], meta)
    assert dm.main(["--from-dataset", "d.json", "--out", "../outside.md"]) == 2
    assert not (tmp_path.parent / "outside.md").exists()


@pytest.mark.parametrize("option", ["--out", "--json"])
def test_cli_rejects_output_path_traversal(tmp_path, monkeypatch, option):
    monkeypatch.chdir(tmp_path)
    meta = {
        "repo": "a/b",
        "branch": "main",
        "event": "push",
        "workflows": ["CI"],
        "since": dm.iso(WEEK[0]),
        "until": dm.iso(WEEK[1]),
    }
    dm.save_dataset(tmp_path / "d.json", [run(1, 0)], meta)

    target = tmp_path.parent / "outside-dora-test.json"
    assert (
        dm.main(
            [
                "--from-dataset",
                "d.json",
                option,
                "../outside-dora-test.json",
            ]
        )
        == 2
    )
    assert not target.exists()


def test_dataset_rejects_path_traversal(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(dm.ApiError):
        dm.save_dataset(tmp_path / "../outside-dora-test.json", [], {})


def test_loading_dataset_rejects_path_traversal(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(dm.ApiError):
        dm.load_dataset(tmp_path / "../outside-dora-test.json")


@pytest.mark.skipif(dm.os.name == "nt", reason="Windows runner cannot create symlinks")
def test_output_rejects_symlink_escape(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    outside = tmp_path.parent
    (tmp_path / "external").symlink_to(outside, target_is_directory=True)

    with pytest.raises(dm.ApiError):
        dm.safe_output(tmp_path / "external" / "outside-dora-test.json")


@pytest.mark.skipif(dm.os.name == "nt", reason="Windows runner cannot create symlinks")
def test_write_report_rejects_symlink_inserted_after_validation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-outside-report.txt"
    outside.write_text("original", encoding="utf-8")

    target = tmp_path / "report.txt"
    original_safe_output = dm.safe_output
    calls = 0

    def insert_symlink(path):
        nonlocal calls
        result = original_safe_output(path)
        calls += 1
        if calls == 2:
            target.symlink_to(outside)
        return result

    monkeypatch.setattr(dm, "safe_output", insert_symlink)

    try:
        with pytest.raises(dm.ApiError):
            dm.write_report(target, "changed")
        assert outside.read_text(encoding="utf-8") == "original"
    finally:
        outside.unlink(missing_ok=True)
