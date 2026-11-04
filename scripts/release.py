#!/usr/bin/env python3
"""Метадані релізу UniSlot: версія, журнал змін і правила Conventional Commits (Лаб 8).

Підкоманди:
  version    — друкує версію з pyproject.toml ([project].version);
  check      — версія в pyproject.toml збігається з першим релізом у CHANGELOG.md, а журнал
               відповідає Keep a Changelog; з --tags — ще й кожен попередній реліз має тег;
  next       — наступна версія за комітами від останнього тегу (файл із `git log`);
  message    — повідомлення коміту релізу; з тегом [REFACTOR], якщо в релізі є рефакторинг;
  changelog  — переносить «## [Unreleased]» у «## [X.Y.Z] - РРРР-ММ-ДД»; порожній
               Unreleased заповнює чернеткою з комітів;
  notes      — текст розділу версії для GitHub Release.

Правила SemVer за Conventional Commits — ті самі, що вбудовані в commitizen
(`cz_conventional_commits`, параметр `major_version_zero = true` у pyproject.toml):
`type!:` або `BREAKING CHANGE:` → MAJOR (поки версія 0.y.z — MINOR); `feat` → MINOR;
`fix`, `refactor`, `perf` → PATCH; `docs`, `test`, `ci`, `chore`, `style`, `build` — без релізу.
Workflow `release.yml` рахує версію обома способами й зупиняється, якщо відповіді різні.

Вивід `git log` скрипт отримує файлом, а теги — списком: git викликає workflow, тож тут
немає ні subprocess, ні мережі. Формат файлу комітів:
    git log --no-merges --format='%H%x1f%s%x1f%b%x1e' vX.Y.Z..HEAD > commits.txt

Код виходу: 0 — порушень немає, 1 — є, 2 — не знайдено вхідних файлів.
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PYPROJECT = Path("pyproject.toml")
CHANGELOG = Path("CHANGELOG.md")
REPO_URL = "https://github.com/ukma-fin-ssdm-2026/SSDM_12"

SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
UNRELEASED = "## [Unreleased]"
RELEASE_HEADING = re.compile(r"^## \[(?P<version>[^\]]+)\] - (?P<date>\d{4}-\d{2}-\d{2})$")
ANY_RELEASE_HEADING = re.compile(r"^## \[")
LINK_DEFINITION = re.compile(r"^\[(?P<name>[^\]]+)\]: (?P<url>\S+)$")
# Шість категорій Keep a Changelog і власна категорія курсу для рефакторингу (умова Лаб 8).
CATEGORIES = ("Refactoring", "Added", "Changed", "Deprecated", "Removed", "Fixed", "Security")

HEADER = re.compile(
    r"^(?P<type>[a-z]+)(?:\((?P<scope>[^()\s]+)\))?(?P<bang>!)?: (?P<subject>\S.*)$"
)
BREAKING_FOOTER = re.compile(r"^BREAKING[ -]CHANGE: ", re.MULTILINE)
REFACTOR_TAG = " [REFACTOR]"
NO_RELEASE, PATCH, MINOR, MAJOR = 0, 1, 2, 3
# Тип коміту → приріст версії й категорія журналу. Типів поза таблицею в релізі немає.
TYPE_RULES = {
    "feat": (MINOR, "Added"),
    "fix": (PATCH, "Fixed"),
    "refactor": (PATCH, "Refactoring"),
    "perf": (PATCH, "Changed"),
}


@dataclass(frozen=True)
class Commit:
    """Розібраний заголовок коміту: тип, область і тема без префікса."""

    sha: str
    type: str
    scope: str | None
    subject: str
    breaking: bool


@dataclass(frozen=True)
class Release:
    """Розділ журналу змін одного релізу."""

    version: str
    date: str
    body: str


def parse_commits(raw: str) -> list[Commit]:
    """Розбирає вивід `git log --format='%H%x1f%s%x1f%b%x1e'`; не Conventional — пропускає."""
    commits = []
    for record in raw.split("\x1e"):
        sha, header, body = [*record.strip("\n").split("\x1f"), "", ""][:3]
        match = HEADER.match(header.strip())
        if not sha.strip() or match is None:
            continue
        commits.append(
            Commit(
                sha=sha.strip(),
                type=match["type"],
                scope=match["scope"],
                subject=match["subject"],
                breaking=bool(match["bang"]) or bool(BREAKING_FOOTER.search(body)),
            )
        )
    return commits


def increment(commits: list[Commit], *, major_version_zero: bool) -> int:
    """Найбільший приріст серед комітів за правилами Conventional Commits."""
    breaking = MINOR if major_version_zero else MAJOR
    levels = [
        breaking if c.breaking else TYPE_RULES.get(c.type, (NO_RELEASE, ""))[0] for c in commits
    ]
    return max(levels, default=NO_RELEASE)


def bump(version: str, level: int) -> str:
    """Наступна версія SemVer: старші частини +1, молодші скидаються в 0."""
    match = SEMVER.match(version)
    if match is None:
        raise ValueError(f"версія «{version}» не відповідає SemVer X.Y.Z")
    major, minor, patch = (int(part) for part in match.groups())
    if level == MAJOR:
        return f"{major + 1}.0.0"
    if level == MINOR:
        return f"{major}.{minor + 1}.0"
    if level == PATCH:
        return f"{major}.{minor}.{patch + 1}"
    return version


def project_version(pyproject: str) -> str:
    """[project].version із тексту pyproject.toml."""
    return tomllib.loads(pyproject)["project"]["version"]


def major_version_zero(pyproject: str) -> bool:
    """Параметр commitizen `major_version_zero` діє, лише поки версія 0.y.z."""
    config = tomllib.loads(pyproject)
    enabled = config.get("tool", {}).get("commitizen", {}).get("major_version_zero", False)
    return bool(enabled) and config["project"]["version"].startswith("0.")


def _section_end(lines: list[str], start: int) -> int:
    """Перший рядок після `start`, що відкриває наступний реліз або посилання внизу журналу."""
    return next(
        (
            i
            for i in range(start + 1, len(lines))
            if ANY_RELEASE_HEADING.match(lines[i]) or LINK_DEFINITION.match(lines[i])
        ),
        len(lines),
    )


def releases(changelog: str) -> list[Release]:
    """Розділи релізів у порядку появи в журналі (без «Unreleased»)."""
    lines = changelog.splitlines()
    found = []
    for start, line in enumerate(lines):
        heading = RELEASE_HEADING.match(line)
        if heading:
            body = "\n".join(lines[start + 1 : _section_end(lines, start)]).strip("\n")
            found.append(Release(heading["version"], heading["date"], body))
    return found


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def _check_body(release: Release) -> list[str]:
    """Кожен запис — у категорії з переліку, і жодна категорія не порожня."""
    problems, counts = [], {}
    category = None
    for line in release.body.splitlines():
        if line.startswith("### "):
            category = line[4:].strip()
            counts[category] = 0
        elif line.startswith("- ") and category is None:
            problems.append(f"[{release.version}]: запис поза категорією: {line[:60]}")
        elif line.startswith("- "):
            counts[category] += 1
    if not counts:
        problems.append(f"[{release.version}]: немає жодної категорії «### …»")
    problems += [
        f"[{release.version}]: категорія «{name}» — очікується одна з {', '.join(CATEGORIES)}"
        for name in counts
        if name not in CATEGORIES
    ]
    problems += [
        f"[{release.version}]: категорія «{name}» без записів"
        for name, n in counts.items()
        if not n
    ]
    return problems


def _check_structure(lines: list[str]) -> list[str]:
    """Заголовок журналу, «Unreleased» першим і лише відомі формати заголовків релізів."""
    headings = [line for line in lines if line.startswith("## ")]
    problems = []
    if not lines or not lines[0].startswith("# "):
        problems.append("перший рядок — заголовок журналу «# …»")
    if not headings or headings[0] != UNRELEASED:
        problems.append(f"перший розділ — «{UNRELEASED}» (Keep a Changelog)")
    problems += [
        f"заголовок не за форматом «## [X.Y.Z] - РРРР-ММ-ДД»: {line}"
        for line in headings
        if line != UNRELEASED and not RELEASE_HEADING.match(line)
    ]
    return problems


def _check_release(release: Release) -> list[str]:
    """Номер SemVer, справжня дата й непорожні категорії одного релізу."""
    if not SEMVER.match(release.version):
        return [f"[{release.version}]: номер не відповідає SemVer X.Y.Z"]
    try:
        date.fromisoformat(release.date)
    except ValueError:
        return [f"[{release.version}]: дата {release.date} не існує", *_check_body(release)]
    return _check_body(release)


def _check_order(found: list[Release]) -> list[str]:
    """Релізи й дати — від новішого до старішого."""
    valid = [r for r in found if SEMVER.match(r.version)]
    problems = []
    if valid != sorted(valid, key=lambda r: _version_key(r.version), reverse=True):
        problems.append("релізи не впорядковано від новішого до старішого")
    if [r.date for r in valid] != sorted((r.date for r in valid), reverse=True):
        problems.append("дати релізів не спадають від новішого до старішого")
    return problems


def _check_links(lines: list[str], found: list[Release]) -> list[str]:
    """Посилання порівняння внизу журналу є для Unreleased і кожного релізу."""
    links = {m["name"] for m in map(LINK_DEFINITION.match, lines) if m}
    names = ["Unreleased", *(r.version for r in found)]
    return [f"немає посилання «[{name}]: …» внизу журналу" for name in names if name not in links]


def _check_tags(found: list[Release], tags: set[str]) -> list[str]:
    """Кожен попередній реліз має тег, і немає тегів версій без розділу в журналі."""
    listed = {f"v{r.version}" for r in found}
    untagged = [
        f"реліз {r.version} є в CHANGELOG.md, але тегу v{r.version} немає"
        for r in found[1:]
        if f"v{r.version}" not in tags
    ]
    unlisted = [
        f"тег {tag} є, а розділу [{tag[1:]}] у CHANGELOG.md немає"
        for tag in sorted(tags - listed)
        if SEMVER.match(tag[1:])
    ]
    return untagged + unlisted


def check_changelog(changelog: str, version: str, tags: set[str] | None = None) -> list[str]:
    """Порушення формату Keep a Changelog і розбіжності з версією проєкту та тегами."""
    lines = changelog.splitlines()
    found = releases(changelog)
    problems = _check_structure(lines)
    if not found:
        return [*problems, "немає жодного релізу «## [X.Y.Z] - РРРР-ММ-ДД»"]
    for release in found:
        problems += _check_release(release)
    problems += _check_order(found)
    if found[0].version != version:
        problems.append(
            f"версія в pyproject.toml {version}, а перший реліз у CHANGELOG.md — {found[0].version}"
        )
    problems += _check_links(lines, found)
    if tags is not None:
        problems += _check_tags(found, tags)
    return problems


def _entry(commit: Commit) -> str:
    subject = commit.subject.removesuffix(REFACTOR_TAG).strip()
    subject = subject[:1].upper() + subject[1:]
    return f"- {subject} (`{commit.scope}`)" if commit.scope else f"- {subject}"


def _category(commit: Commit) -> str | None:
    if commit.type == "fix" and commit.scope == "security":
        return "Security"
    return TYPE_RULES.get(commit.type, (NO_RELEASE, None))[1]


def draft_entries(commits: list[Commit]) -> str:
    """Чернетка розділу з комітів: refactor → Refactoring, feat → Added, fix → Fixed тощо."""
    groups: dict[str, list[str]] = {name: [] for name in CATEGORIES}
    for commit in reversed(commits):  # git log — від новішого; журнал читають за порядком змін
        name = _category(commit)
        if name is not None and _entry(commit) not in groups[name]:
            groups[name].append(_entry(commit))
    return "\n\n".join(
        f"### {name}\n\n" + "\n".join(entries) for name, entries in groups.items() if entries
    )


def _update_links(lines: list[str], version: str, previous: str | None) -> list[str]:
    unreleased = f"[Unreleased]: {REPO_URL}/compare/v{version}...HEAD"
    if previous:
        released = f"[{version}]: {REPO_URL}/compare/v{previous}...v{version}"
    else:
        released = f"[{version}]: {REPO_URL}/releases/tag/v{version}"
    for index, line in enumerate(lines):
        match = LINK_DEFINITION.match(line)
        if match and match["name"] == "Unreleased":
            return [*lines[:index], unreleased, released, *lines[index + 1 :]]
    return [*lines, "", unreleased, released]


def release_changelog(changelog: str, version: str, day: str, commits: list[Commit]) -> str:
    """Переносить «Unreleased» у розділ версії й оновлює посилання порівняння внизу."""
    lines = changelog.splitlines()
    if UNRELEASED not in lines:
        raise ValueError(f"у журналі немає «{UNRELEASED}»")
    start = lines.index(UNRELEASED)
    stop = _section_end(lines, start)
    body = "\n".join(lines[start + 1 : stop]).strip("\n") or draft_entries(commits)
    if not body:
        raise ValueError("нічого випускати: Unreleased порожній, комітів із релізом немає")
    previous = releases(changelog)
    section = [UNRELEASED, "", f"## [{version}] - {day}", "", *body.splitlines(), ""]
    result = _update_links(
        lines[:start] + section + lines[stop:], version, previous[0].version if previous else None
    )
    return "\n".join(result).rstrip("\n") + "\n"


def notes(changelog: str, version: str) -> str:
    """Текст розділу версії — тіло GitHub Release."""
    for release in releases(changelog):
        if release.version == version:
            return release.body + "\n"
    raise ValueError(f"у CHANGELOG.md немає розділу [{version}]")


def release_message(current: str, new: str, commits: list[Commit]) -> str:
    """Повідомлення коміту релізу; тег [REFACTOR], якщо реліз містить рефакторинг (умова Лаб 8)."""
    tag = REFACTOR_TAG if any(c.type == "refactor" for c in commits) else ""
    return f"chore(release): {current} → {new}{tag}"


def _read(path: Path) -> str:
    if not path.is_file():
        print(f"Не знайдено {path} (запускайте з кореня репозиторію).")
        raise SystemExit(2)
    return path.read_text(encoding="utf-8")


def _cmd_version(_args: argparse.Namespace, pyproject: str) -> int:
    print(project_version(pyproject))
    return 0


def _cmd_check(args: argparse.Namespace, pyproject: str) -> int:
    tags = None
    if args.tags is not None:
        tags = {line.strip() for line in _read(args.tags).splitlines() if line.strip()}
    current = project_version(pyproject)
    problems = check_changelog(_read(CHANGELOG), current, tags)
    if problems:
        print(f"[FAIL] Метадані релізу: {len(problems)}")
        for problem in problems:
            print(f"       {problem}")
        return 1
    print(f"[ ok ] Метадані релізу: pyproject.toml і CHANGELOG.md — {current}")
    return 0


def _cmd_next(args: argparse.Namespace, pyproject: str) -> int:
    base = args.base or project_version(pyproject)
    zero = major_version_zero(pyproject) and base.startswith("0.")
    level = increment(parse_commits(_read(args.commits)), major_version_zero=zero)
    if level == NO_RELEASE:
        print("Нічого випускати: з останнього тегу немає комітів feat, fix, refactor чи perf.")
        return 1
    print(bump(base, level))
    return 0


def _cmd_message(args: argparse.Namespace, pyproject: str) -> int:
    commits = parse_commits(_read(args.commits))
    print(release_message(project_version(pyproject), args.new, commits))
    return 0


def _cmd_changelog(args: argparse.Namespace, _pyproject: str) -> int:
    # Дата релізу — календарна дата команди, тобто київська.
    day = args.date or datetime.now(ZoneInfo("Europe/Kyiv")).date().isoformat()
    commits = parse_commits(_read(args.commits))
    text = release_changelog(_read(CHANGELOG), args.version, day, commits)
    CHANGELOG.write_text(text, encoding="utf-8", newline="\n")
    print(f"CHANGELOG.md: розділ [{args.version}] - {day}")
    return 0


def _cmd_notes(args: argparse.Namespace, _pyproject: str) -> int:
    print(notes(_read(CHANGELOG), args.version), end="")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("version", help="версія з pyproject.toml")
    check = sub.add_parser("check", help="узгодженість версії, журналу й тегів")
    check.add_argument("--tags", type=Path, help="файл зі списком тегів (git tag --list 'v*')")
    for name in ("next", "message", "changelog"):
        sub.add_parser(name).add_argument("--commits", type=Path, required=True)
    sub.choices["next"].add_argument("--base", help="версія останнього тегу; типово — pyproject")
    sub.choices["message"].add_argument("--new", required=True, help="нова версія")
    sub.choices["changelog"].add_argument("--version", required=True)
    sub.choices["changelog"].add_argument("--date", help="РРРР-ММ-ДД; типово — сьогодні в Києві")
    sub.add_parser("notes", help="розділ версії для GitHub Release").add_argument(
        "--version", required=True
    )
    return parser


COMMANDS = {
    "version": _cmd_version,
    "check": _cmd_check,
    "next": _cmd_next,
    "message": _cmd_message,
    "changelog": _cmd_changelog,
    "notes": _cmd_notes,
}


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return COMMANDS[args.command](args, _read(PYPROJECT))


if __name__ == "__main__":
    sys.exit(main())
