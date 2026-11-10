"""Кешоване середовище для self-hosted раннера (Лаб 10, бонус 2; QA-24).

Справжній `pip install` у тестах не запускаємо: збірку й перевірку підмінено функціями,
що лише створюють файли й рахують виклики. Один тест будує справжній venv без pip —
щоб перевірити шляхи на поточній ОС.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts import ci_venv

pytestmark = pytest.mark.req("QA-24")


class FakeBuilder:
    """Замість venv + pip: створює python-файл і рахує збірки."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, env_dir: Path) -> None:
        self.calls += 1
        python = ci_venv.python_in(env_dir)
        python.parent.mkdir(parents=True, exist_ok=True)
        python.write_text("fake", encoding="utf-8")


def healthy(env_dir: Path) -> bool:
    return ci_venv.python_in(env_dir).is_file()


@pytest.fixture
def reqs(tmp_path: Path) -> Path:
    """requirements-testing.txt → requirements-dev.txt → requirements.txt, як у репозиторії."""
    (tmp_path / "requirements.txt").write_text("fastapi==0.143.1\n", encoding="utf-8")
    (tmp_path / "requirements-dev.txt").write_text("-r requirements.txt\nruff==0.17.1\n", "utf-8")
    top = tmp_path / "requirements-testing.txt"
    top.write_text("-r requirements-dev.txt\ncoverage==7.16.2\n", encoding="utf-8")
    return top


def test_requirement_files_follow_nested_includes(reqs):
    names = [p.name for p in ci_venv.requirement_files(reqs)]
    assert names == ["requirements-testing.txt", "requirements-dev.txt", "requirements.txt"]


def test_include_cycle_does_not_loop(tmp_path):
    (tmp_path / "a.txt").write_text("-r b.txt\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("--requirement=a.txt\n", encoding="utf-8")
    assert len(ci_venv.requirement_files(tmp_path / "a.txt")) == 2


def test_missing_included_file_is_an_error(tmp_path):
    (tmp_path / "a.txt").write_text("-r missing.txt\n", encoding="utf-8")
    with pytest.raises(ci_venv.VenvError, match=r"missing\.txt"):
        ci_venv.requirement_files(tmp_path / "a.txt")


def test_key_changes_when_a_nested_requirement_changes(reqs):
    before = ci_venv.cache_key(reqs, "pip>=26.2", python="3.12.10")
    (reqs.parent / "requirements.txt").write_text("fastapi==0.144.0\n", encoding="utf-8")
    assert ci_venv.cache_key(reqs, "pip>=26.2", python="3.12.10") != before


def test_key_changes_with_python_version_and_pip_spec(reqs):
    base = ci_venv.cache_key(reqs, "pip>=26.2", python="3.12.10")
    assert ci_venv.cache_key(reqs, "pip>=26.2", python="3.13.1") != base
    assert ci_venv.cache_key(reqs, "pip>=27", python="3.12.10") != base


def test_key_ignores_line_endings(reqs):
    base = ci_venv.cache_key(reqs, "pip>=26.2", python="3.12.10")
    bytes = reqs.read_bytes().replace(b"\r\n", b"\n")
    reqs.write_bytes(bytes.replace(b"\n", b"\r\n"))
    assert ci_venv.cache_key(reqs, "pip>=26.2", python="3.12.10") == base


def test_first_use_builds_and_second_use_hits_the_cache(tmp_path):
    build = FakeBuilder()
    env, hit = ci_venv.ensure(tmp_path / "cache", "0123456789abcdef", build, healthy)
    assert (hit, build.calls) == (False, 1)
    assert (env / ".ready").read_text(encoding="utf-8").strip() == "0123456789abcdef"
    again, hit = ci_venv.ensure(tmp_path / "cache", "0123456789abcdef", build, healthy)
    assert (again, hit, build.calls) == (env, True, 1)


def test_environment_without_marker_is_rebuilt(tmp_path):
    """Раннер вимкнули посеред pip install: маркера немає — середовище не готове."""
    half = tmp_path / "cache" / "venv-0123456789abcdef"
    (half / "Lib").mkdir(parents=True)
    (half / "Lib" / "leftover.txt").write_text("x", encoding="utf-8")
    build = FakeBuilder()
    env, hit = ci_venv.ensure(tmp_path / "cache", "0123456789abcdef", build, healthy)
    assert (hit, build.calls) == (False, 1)
    assert not (env / "Lib" / "leftover.txt").exists()


def test_environment_failing_pip_check_is_rebuilt(tmp_path):
    build = FakeBuilder()
    ci_venv.ensure(tmp_path / "c", "0123456789abcdef", build, healthy)
    verdicts = iter([False, True])  # зіпсоване → після перебудови здорове
    _, hit = ci_venv.ensure(tmp_path / "c", "0123456789abcdef", build, lambda _: next(verdicts))
    assert (hit, build.calls) == (False, 2)


def test_build_that_fails_pip_check_is_an_error_and_leaves_no_marker(tmp_path):
    with pytest.raises(ci_venv.BuildError):
        ci_venv.ensure(tmp_path / "c", "0123456789abcdef", FakeBuilder(), lambda _: False)
    assert not (tmp_path / "c" / "venv-0123456789abcdef" / ".ready").exists()


def test_prune_keeps_only_the_most_recently_used_environments(tmp_path):
    root, build = tmp_path / "c", FakeBuilder()
    keys = [f"{n:016x}" for n in range(1, 5)]
    for age, key in enumerate(keys):
        env, _ = ci_venv.ensure(root, key, build, healthy, keep=10)
        os.utime(env / ".ready", (1_000_000 + age, 1_000_000 + age))
    ci_venv.ensure(root, keys[0], build, healthy, keep=2)  # знову використали найстаріше
    left = sorted(p.name for p in root.iterdir())
    assert left == [f"venv-{keys[0]}", f"venv-{keys[3]}"]


def test_only_own_cache_directories_are_removed(tmp_path):
    root = tmp_path / "c"
    (root / "not-a-venv").mkdir(parents=True)
    ci_venv.ensure(root, "0123456789abcdef", FakeBuilder(), healthy, keep=1)
    assert (root / "not-a-venv").is_dir()
    with pytest.raises(ci_venv.VenvError, match="чужий"):
        ci_venv.remove_env(root, tmp_path)


def test_real_venv_layout_matches_python_in(tmp_path):
    env = tmp_path / "venv-0123456789abcdef"
    ci_venv.venv.create(env, with_pip=False)
    assert ci_venv.python_in(env).is_file()


def test_cli_writes_venv_dir_to_github_env_and_separates_scopes(tmp_path, monkeypatch, reqs):
    repo = reqs.parent
    monkeypatch.chdir(repo)
    cache, github_env = tmp_path.parent / f"{tmp_path.name}-cache", tmp_path / "github_env"
    monkeypatch.setenv("GITHUB_ENV", str(github_env))
    calls = []

    def build(env_dir: Path, requirements: Path, pip_spec: str) -> None:
        calls.append((requirements.name, pip_spec))
        FakeBuilder()(env_dir)

    args = ["--requirements", "requirements-testing.txt", "--root", str(cache), "--github-env"]
    assert ci_venv.main([*args, "--scope", "push"], build=build, check=healthy) == 0
    assert ci_venv.main([*args, "--scope", "pull_request"], build=build, check=healthy) == 0
    assert calls == [("requirements-testing.txt", "pip>=26.2")] * 2  # PR не бере середовище main
    lines = github_env.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("VENV_DIR=") and "push" in lines[0]
    assert "pull_request" in lines[1]


@pytest.mark.parametrize(
    ("extra", "reason"),
    [
        (["--root", "relative/cache"], "абсолютним"),
        (["--root", "{repo}/inside"], "всередині репозиторію"),
        (["--root", "{cache}", "--scope", "Push;rm"], "--scope"),
    ],
)
def test_cli_rejects_unsafe_arguments(tmp_path, monkeypatch, capsys, reqs, extra, reason):
    repo = reqs.parent
    monkeypatch.chdir(repo)
    values = [v.format(repo=repo, cache=tmp_path.parent / f"{tmp_path.name}-c") for v in extra]
    with pytest.raises(SystemExit) as exit_info:
        ci_venv.main(["--requirements", "requirements-testing.txt", *values])
    assert exit_info.value.code == 2
    assert reason in capsys.readouterr().err


def test_cli_reports_build_failure_with_exit_code_1(tmp_path, monkeypatch, reqs):
    monkeypatch.chdir(reqs.parent)

    def broken(env_dir: Path, requirements: Path, pip_spec: str) -> None:
        raise ci_venv.BuildError("не вдалося встановити залежності")

    root = str(tmp_path.parent / f"{tmp_path.name}-b")
    args = ["--requirements", "requirements-testing.txt", "--root", root]
    assert ci_venv.main(args, build=broken, check=healthy) == 1
