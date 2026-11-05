"""Правила релізу Лаб 8: SemVer за Conventional Commits і формат Keep a Changelog."""

import pytest

from scripts import release

pytestmark = pytest.mark.req("QA-19")

PYPROJECT = """
[project]
name = "unislot"
version = "0.1.0"

[tool.commitizen]
major_version_zero = true
"""

CHANGELOG = """# Журнал змін

## [Unreleased]

## [0.1.0] - 2026-11-05

### Added

- Перша записана версія.

[Unreleased]: https://example.invalid/compare/v0.1.0...HEAD
[0.1.0]: https://example.invalid/releases/tag/v0.1.0
"""


def log(*headers: str, body: str = "") -> str:
    """Вивід `git log --format='%H%x1f%s%x1f%b%x1e'` для заданих заголовків комітів."""
    return "".join(f"{n:040x}\x1f{h}\x1f{body}\x1e\n" for n, h in enumerate(headers, 1))


def next_version(*headers: str, body: str = "", pyproject: str = PYPROJECT) -> str:
    commits = release.parse_commits(log(*headers, body=body))
    level = release.increment(commits, major_version_zero=release.major_version_zero(pyproject))
    return release.bump(release.project_version(pyproject), level)


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("refactor(store): Extract Method — split flush [REFACTOR]", "0.1.1"),
        ("fix(security): validate the PlantUML jar path", "0.1.1"),
        ("perf: cache the OpenAPI schema", "0.1.1"),
        ("feat: weekly templates", "0.2.0"),
        ("feat!: drop the demo bearer tokens", "0.2.0"),
        ("docs: refresh the report", "0.1.0"),
        ("Merge pull request #1 from ukma-fin-ssdm-2026/x", "0.1.0"),
    ],
)
def test_conventional_commit_type_decides_the_increment(header, expected):
    assert next_version(header) == expected


def test_refactor_only_release_is_a_patch_even_with_docs_and_tests_around():
    assert next_version("docs: report", "refactor: extract helper", "test: pin output") == "0.1.1"


def test_breaking_change_footer_counts_like_the_bang():
    assert next_version("refactor: rename field", body="BREAKING CHANGE: field renamed") == "0.2.0"


def test_breaking_change_is_major_once_version_one_is_reached():
    stable = PYPROJECT.replace('version = "0.1.0"', 'version = "1.2.3"')
    assert next_version("fix!: change error code", pyproject=stable) == "2.0.0"
    assert next_version("refactor: extract helper", pyproject=stable) == "1.2.4"


def test_bump_rejects_a_version_that_is_not_semver():
    with pytest.raises(ValueError, match="SemVer"):
        release.bump("1.0.0-alpha.1", release.PATCH)


def test_valid_changelog_matches_the_project_version():
    assert release.check_changelog(CHANGELOG, "0.1.0") == []


def test_version_mismatch_between_pyproject_and_changelog_is_reported():
    assert release.check_changelog(CHANGELOG, "0.1.1") == [
        "версія в pyproject.toml 0.1.1, а перший реліз у CHANGELOG.md — 0.1.0"
    ]


@pytest.mark.parametrize(
    ("broken", "problem"),
    [
        ("## [0.1.0] - 2026-11-05", "## [0.1.0] (2026-11-05)"),
        ("### Added", "### Features"),
        ("## [Unreleased]\n", ""),
        ("2026-11-05", "2026-02-30"),
    ],
)
def test_keep_a_changelog_violations_are_reported(broken, problem):
    assert release.check_changelog(CHANGELOG.replace(broken, problem), "0.1.0")


CURATED = CHANGELOG.replace(
    "## [Unreleased]\n", "## [Unreleased]\n\n### Refactoring\n\n- Extract Method у flush.\n"
)


def test_tags_must_match_the_released_versions():
    text = release.release_changelog(CURATED, "0.1.1", "2026-11-07", [])
    assert release.check_changelog(text, "0.1.1", tags={"v0.1.0"}) == []
    assert release.check_changelog(text, "0.1.1", tags=set()) == [
        "реліз 0.1.0 є в CHANGELOG.md, але тегу v0.1.0 немає"
    ]
    assert release.check_changelog(text, "0.1.1", tags={"v0.1.0", "v0.0.9"}) == [
        "тег v0.0.9 є, а розділу [0.0.9] у CHANGELOG.md немає"
    ]


def test_release_moves_unreleased_entries_and_updates_compare_links():
    text = release.release_changelog(CURATED, "0.1.1", "2026-11-07", [])
    assert "## [Unreleased]\n\n## [0.1.1] - 2026-11-07\n\n### Refactoring\n" in text
    assert f"[Unreleased]: {release.REPO_URL}/compare/v0.1.1...HEAD" in text
    assert f"[0.1.1]: {release.REPO_URL}/compare/v0.1.0...v0.1.1" in text
    assert release.check_changelog(text, "0.1.1", tags={"v0.1.0"}) == []


def test_empty_unreleased_is_drafted_from_commits_by_category():
    commits = release.parse_commits(
        log(
            "fix(security): validate the output directory",
            "refactor(store): Extract Method — split flush [REFACTOR]",
            "docs: report",
        )
    )
    text = release.release_changelog(CHANGELOG, "0.1.1", "2026-11-07", commits)
    section = release.notes(text, "0.1.1")
    assert section.index("### Refactoring") < section.index("### Security")
    assert "- Extract Method — split flush (`store`)" in section
    assert "- Validate the output directory (`security`)" in section
    assert "report" not in section


def test_nothing_to_release_is_an_error():
    with pytest.raises(ValueError, match="нічого випускати"):
        release.release_changelog(CHANGELOG, "0.1.1", "2026-11-07", [])


def test_release_commit_message_carries_the_refactor_tag_only_for_refactoring():
    refactor = release.parse_commits(log("refactor: extract helper"))
    fix = release.parse_commits(log("fix: off-by-one"))
    assert release.release_message("0.1.0", "0.1.1", refactor) == (
        "chore(release): 0.1.0 → 0.1.1 [REFACTOR]"
    )
    assert release.release_message("0.1.0", "0.1.1", fix) == "chore(release): 0.1.0 → 0.1.1"


def test_check_command_reads_the_repository_files(tmp_path, monkeypatch, capsys):
    (tmp_path / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(CHANGELOG, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert release.main(["check"]) == 0
    assert "0.1.0" in capsys.readouterr().out
    (tmp_path / "CHANGELOG.md").write_text(CHANGELOG.replace("0.1.0] -", "0.1.9] -"), "utf-8")
    assert release.main(["check"]) == 1


def test_changelog_command_rewrites_only_the_project_changelog(tmp_path, monkeypatch, capsys):
    (tmp_path / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(CURATED, encoding="utf-8")
    (tmp_path / "commits.txt").write_text(log("refactor: extract helper"), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    arguments = ["changelog", "--version", "0.1.1", "--date", "2026-11-07", "--commits"]
    assert release.main([*arguments, "commits.txt"]) == 0
    assert "[0.1.1] - 2026-11-07" in capsys.readouterr().out
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "CHANGELOG.md",
        "commits.txt",
        "pyproject.toml",
    ]
    assert (
        release.check_changelog(
            (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8"), "0.1.1", tags={"v0.1.0"}
        )
        == []
    )


@pytest.mark.parametrize(
    "name", ["../CHANGELOG.md", "/etc/passwd", "CHANGELOG.md.bak", "notes.md", "pyproject.toml"]
)
def test_no_other_file_can_be_written(name, tmp_path, monkeypatch):
    """Шлях запису не складається з даних, а pyproject.toml належить `cz bump`, не цьому скрипту."""
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="не файл проєкту"):
        release._write_project_file(name, "whatever")
    assert list(tmp_path.iterdir()) == []
