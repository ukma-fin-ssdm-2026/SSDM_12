#!/usr/bin/env python3
"""Автоматична перевірка простежуваності «вимога ↔ тест» (Лаб 7).

Зіставляє ID вимог із `docs/requirements/rtm.md` з мітками тестів у коді й падає, якщо:
  1. тест не посилається на жодну вимогу (мітка `@pytest.mark.req` відсутня);
  2. мітка посилається на ID, якого немає в rtm.md чи в плані тестування;
  3. вимога не має жодного тесту і не записана в rtm.md як свідомий виняток;
  4. вимога записана як виняток, але тест на неї вже є (виняток застарів);
  5. у винятку не вказано, чим вимогу перевіряють зараз або чому автотесту немає;
  6. стовпець «Тести» в rtm.md називає тест-кейс, якого немає в плані тестування.

Мітка в тесті — на функції, класі або модулі (`pytestmark`), аргументи — рядкові літерали:

    pytestmark = pytest.mark.req("US-004")

    @pytest.mark.req("FR-040", "TC-007", "TP-01")
    def test_cancel_exactly_at_deadline_is_allowed(...): ...

Вимогою вважається US, FR, NFR (PERF, REL, SEC, MAINT, USAB, PORT) або похідна вимога з
розділу «Похідні вимоги» rtm.md (QA-xx, THR-xx, R-xxx). TC-xxx і TP-xx у мітці дозволені,
але самі вимогою не є: вони зв'язують автотест із тест-кейсом RTM і рядком плану.
Покриття рахується для FR, NFR і похідних вимог; історія покривається через свої FR.

Запуск з кореня репозиторію (лише стандартна бібліотека, pytest не потрібен):
    python scripts/check_traceability.py
    python scripts/check_traceability.py --json traceability.json   # мапа для звіту

Код виходу: 0 — порушень немає, 1 — є, 2 — не знайдено вхідних файлів.

Обмеження: скрипт перевіряє, що зв'язок «вимога ↔ тест» записано, а не що тест справді
перевіряє вимогу. Чи доводить тест те, що обіцяє мітка, вирішує рецензент PR.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeGuard

RTM = Path("docs/requirements/rtm.md")
TEST_PLAN = Path("docs/validation/test-plan.md")
TESTS = Path("tests")

# Формати ID. Якщо формат у файлах зміниться — правити тільки тут.
NFR_PREFIXES = ("PERF", "REL", "SEC", "MAINT", "USAB", "PORT")
FR_ID = r"FR-\d{3}"
NFR_ID = r"(?:" + "|".join(NFR_PREFIXES) + r")-\d{3}"
US_ID = r"US-\d{3}"
DERIVED_ID = r"(?:QA|THR)-\d{2}|R-\d{3}"
TC_ID = r"TC-\d{3}"
TP_ID = r"TP-\d{2}"
ANY_ID = re.compile(rf"^(?:{US_ID}|{FR_ID}|{NFR_ID}|{DERIVED_ID}|{TC_ID}|{TP_ID})$")

# Розділи rtm.md, які читає скрипт, — за словами в заголовку, а не за номером.
DERIVED_HEADING = "Похідні вимоги"
EXEMPT_HEADING = "свідомі винятки"
FORWARD_HEADING = "Пряма матриця"
NFR_HEADING = "Зворотне покриття"
TESTS_COLUMN = "Тести"

MARKER = "req"


@dataclass
class Registry:
    """Що відомо з rtm.md і плану тестування."""

    us: set[str] = field(default_factory=set)
    fr: set[str] = field(default_factory=set)
    nfr: set[str] = field(default_factory=set)
    derived: set[str] = field(default_factory=set)
    tc: set[str] = field(default_factory=set)
    tp: set[str] = field(default_factory=set)
    exemptions: dict[str, list[str]] = field(default_factory=dict)
    tests_column: dict[str, set[str]] = field(default_factory=dict)

    @property
    def requirements(self) -> set[str]:
        """ID, які вважаються вимогою в мітці тесту."""
        return self.us | self.fr | self.nfr | self.derived

    @property
    def must_be_covered(self) -> set[str]:
        """Вимоги, кожна з яких має мати тест або виняток."""
        return self.fr | self.nfr | self.derived

    def known(self, item: str) -> bool:
        """Чи існує ID у rtm.md або в плані тестування."""
        return item in self.requirements or item in self.tc or item in self.tp


@dataclass
class TestRef:
    """Тест і ID з його міток (функції, класу й модуля разом)."""

    node: str
    ids: frozenset[str]


@dataclass
class Scan:
    """Результат розбору тестів."""

    tests: list[TestRef] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# --- rtm.md і план -------------------------------------------------------------------


def split_sections(text: str) -> dict[str, list[str]]:
    """Ділить Markdown на розділи за заголовками рівня 2: {заголовок: рядки}."""
    sections: dict[str, list[str]] = {"": []}
    current = ""
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = []
        else:
            sections[current].append(line)
    return sections


def table_rows(lines: list[str]) -> list[list[str]]:
    """Рядки Markdown-таблиці як списки комірок, без шапки й роздільника."""
    rows = []
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if all(re.fullmatch(r":?-{3,}:?", c) for c in cells if c):
            continue
        rows.append(cells)
    return rows


def find_section(sections: dict[str, list[str]], words: str) -> list[str]:
    """Рядки першого розділу, у заголовку якого є `words`; порожньо, якщо такого немає."""
    return next((body for title, body in sections.items() if words in title), [])


def read_tests_column(lines: list[str], key_pattern: str) -> dict[str, set[str]]:
    """Значення стовпця «Тести» таблиці розділу: {ID рядка: {TP-xx, …}}."""
    rows = table_rows(lines)
    if not rows:
        return {}
    header = rows[0]
    if TESTS_COLUMN not in header:
        return {}
    index = header.index(TESTS_COLUMN)
    result = {}
    for cells in rows[1:]:
        if cells and re.fullmatch(key_pattern, cells[0]) and index < len(cells):
            result[cells[0]] = set(re.findall(TP_ID, cells[index]))
    return result


def load_registry(rtm_text: str, plan_text: str) -> Registry:
    """Збирає ID вимог, винятки й стовпець «Тести» з rtm.md, ID тест-кейсів — із плану."""
    reg = Registry()
    reg.us = set(re.findall(rf"^\|\s*({US_ID})\s*\|", rtm_text, re.M))
    reg.fr = set(re.findall(FR_ID, rtm_text))
    reg.nfr = set(re.findall(NFR_ID, rtm_text))
    reg.tc = set(re.findall(rf"^\|\s*({TC_ID})\s*\|", rtm_text, re.M))
    reg.tp = set(re.findall(rf"^\|\s*({TP_ID})\s*\|", plan_text, re.M))

    sections = split_sections(rtm_text)
    for cells in table_rows(find_section(sections, DERIVED_HEADING)):
        if cells and re.fullmatch(DERIVED_ID, cells[0]):
            reg.derived.add(cells[0])
    for cells in table_rows(find_section(sections, EXEMPT_HEADING)):
        if cells and re.fullmatch(rf"{FR_ID}|{NFR_ID}|{DERIVED_ID}", cells[0]):
            reg.exemptions[cells[0]] = cells[1:]
    for words, key in (
        (FORWARD_HEADING, US_ID),
        (NFR_HEADING, NFR_ID),
        (DERIVED_HEADING, DERIVED_ID),
    ):
        reg.tests_column.update(read_tests_column(find_section(sections, words), key))
    return reg


# --- мітки в тестах ------------------------------------------------------------------


def is_req_marker(node: ast.AST) -> TypeGuard[ast.Call]:
    """Чи є вузол викликом `pytest.mark.req(...)` або `mark.req(...)`."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if not (isinstance(func, ast.Attribute) and func.attr == MARKER):
        return False
    owner = func.value
    if isinstance(owner, ast.Attribute) and owner.attr == "mark":
        return isinstance(owner.value, ast.Name) and owner.value.id == "pytest"
    return isinstance(owner, ast.Name) and owner.id == "mark"


def marker_ids(node: ast.Call, where: str, errors: list[str]) -> set[str]:
    """ID з одного виклику мітки; не-літерали й порожні мітки — помилка."""
    ids = set()
    if not node.args:
        errors.append(f"{where}: мітка {MARKER} без жодного ID")
    for arg in node.args:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            ids.add(arg.value.strip())
        else:
            errors.append(f"{where}: аргумент мітки {MARKER} має бути рядковим літералом")
    return ids


def ids_from_pytestmark(value: ast.AST, where: str, errors: list[str]) -> set[str]:
    """ID з присвоєння `pytestmark = …` (одна мітка або список/кортеж міток)."""
    items = value.elts if isinstance(value, ast.List | ast.Tuple) else [value]
    ids: set[str] = set()
    for item in items:
        if is_req_marker(item):
            ids |= marker_ids(item, where, errors)
    return ids


def ids_from_decorators(decorators: list[ast.expr], where: str, errors: list[str]) -> set[str]:
    """ID з декораторів функції чи класу."""
    ids: set[str] = set()
    for deco in decorators:
        if is_req_marker(deco):
            ids |= marker_ids(deco, where, errors)
        elif isinstance(deco, ast.Attribute) and deco.attr == MARKER:
            errors.append(f"{where}: мітка {MARKER} без дужок і без жодного ID")
    return ids


def pytestmark_of(body: list[ast.stmt], where: str, errors: list[str]) -> set[str]:
    """ID з `pytestmark` у тілі модуля чи класу."""
    ids: set[str] = set()
    for stmt in body:
        if isinstance(stmt, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "pytestmark" for t in stmt.targets
        ):
            ids |= ids_from_pytestmark(stmt.value, where, errors)
    return ids


def scan_module(path: Path, root: Path) -> Scan:
    """Тести одного файлу з об'єднаними ID міток модуля, класу й функції."""
    scan = Scan()
    rel = path.relative_to(root).as_posix()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
    except SyntaxError as err:
        scan.errors.append(f"{rel}: файл не розбирається ({err.msg}, рядок {err.lineno})")
        return scan
    module_ids = pytestmark_of(tree.body, rel, scan.errors)
    for stmt in tree.body:
        if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef) and stmt.name.startswith(
            "test"
        ):
            node = f"{rel}::{stmt.name}"
            own = ids_from_decorators(stmt.decorator_list, node, scan.errors)
            scan.tests.append(TestRef(node, frozenset(module_ids | own)))
        elif isinstance(stmt, ast.ClassDef) and stmt.name.startswith("Test"):
            where = f"{rel}::{stmt.name}"
            class_ids = ids_from_decorators(stmt.decorator_list, where, scan.errors)
            class_ids |= pytestmark_of(stmt.body, where, scan.errors)
            for item in stmt.body:
                if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef) and (
                    item.name.startswith("test")
                ):
                    node = f"{where}::{item.name}"
                    own = ids_from_decorators(item.decorator_list, node, scan.errors)
                    scan.tests.append(TestRef(node, frozenset(module_ids | class_ids | own)))
    return scan


def scan_tests(tests_dir: Path, root: Path) -> Scan:
    """Усі тести в теці за правилами збору pytest (`test_*.py`, `*_test.py`)."""
    total = Scan()
    files = sorted({*tests_dir.rglob("test_*.py"), *tests_dir.rglob("*_test.py")})
    for path in files:
        part = scan_module(path, root)
        total.tests.extend(part.tests)
        total.errors.extend(part.errors)
    return total


# --- перевірки -----------------------------------------------------------------------


@dataclass
class Report:
    """Знахідки за категоріями й мапа покриття для звіту."""

    orphans: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)
    uncovered: list[str] = field(default_factory=list)
    stale: list[str] = field(default_factory=list)
    empty_reason: list[str] = field(default_factory=list)
    unknown_tp_in_rtm: list[str] = field(default_factory=list)
    coverage: dict[str, list[str]] = field(default_factory=dict)

    @property
    def failures(self) -> int:
        """Кількість порушень у всіх категоріях."""
        return sum(
            len(x)
            for x in (
                self.orphans,
                self.unknown,
                self.uncovered,
                self.stale,
                self.empty_reason,
                self.unknown_tp_in_rtm,
            )
        )


def check(reg: Registry, scan: Scan) -> Report:
    """Застосовує правила 1–6 з докстрінга модуля."""
    rep = Report()
    for test in scan.tests:
        if not test.ids & reg.requirements:
            rep.orphans.append(test.node)
        rep.unknown.extend(f"{test.node}: {i}" for i in sorted(test.ids) if not reg.known(i))
        for item in test.ids & reg.must_be_covered:
            rep.coverage.setdefault(item, []).append(test.node)
    covered = set(rep.coverage)
    rep.uncovered = sorted(reg.must_be_covered - covered - set(reg.exemptions))
    rep.stale = sorted(covered & set(reg.exemptions))
    rep.empty_reason = sorted(
        item
        for item, cells in reg.exemptions.items()
        if len(cells) < 2 or not all(c and c not in {"—", "-"} for c in cells[:2])
    )
    rep.unknown_tp_in_rtm = sorted(
        f"{row}: {tp}" for row, tps in reg.tests_column.items() for tp in tps if tp not in reg.tp
    )
    return rep


def print_report(reg: Registry, scan: Scan, rep: Report) -> None:
    """Друкує підсумок і кожну знахідку; формат — як у check_requirements.py."""
    files = len({t.node.split("::", 1)[0] for t in scan.tests})
    print("Простежуваність «вимога ↔ тест» (Лаб 7)")
    print(
        f"rtm.md: US {len(reg.us)}, FR {len(reg.fr)}, NFR {len(reg.nfr)}, "
        f"похідних {len(reg.derived)}, винятків {len(reg.exemptions)}; "
        f"тест-кейсів плану: {len(reg.tp)}; тестів: {len(scan.tests)} у {files} файлах\n"
    )

    def section(title: str, items: list[str]) -> None:
        if items:
            print(f"[FAIL] {title}: {len(items)}")
            for item in items:
                print(f"       {item}")
        else:
            print(f"[ ok ] {title}")

    section("Файли тестів розбираються, мітки записано літералами", scan.errors)
    section("Тести без жодної вимоги", rep.orphans)
    section("Мітки з ID, яких немає в rtm.md чи в плані", rep.unknown)
    section("Вимоги без жодного тесту і без винятку в rtm.md", rep.uncovered)
    section("Винятки, на які вже є тест (приберіть виняток)", rep.stale)
    section("Винятки без способу перевірки чи причини", rep.empty_reason)
    section("Стовпець «Тести» rtm.md: тест-кейси, яких немає в плані", rep.unknown_tp_in_rtm)

    covered = len(rep.coverage)
    total = len(reg.must_be_covered)
    print(
        f"\n[info] Покрито тестами: {covered} з {total} вимог; "
        f"свідомих винятків: {len(reg.exemptions)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path("."), help="корінь репозиторію")
    parser.add_argument("--json", type=Path, help="записати мапу «вимога → тести» у JSON")
    args = parser.parse_args(argv)

    root = args.root
    rtm, plan, tests = root / RTM, root / TEST_PLAN, root / TESTS
    missing = [p for p in (rtm, tests) if not p.exists()]
    if missing:
        print("Не знайдено (запускайте з кореня репозиторію): " + ", ".join(map(str, missing)))
        return 2
    plan_text = plan.read_text(encoding="utf-8") if plan.is_file() else ""

    reg = load_registry(rtm.read_text(encoding="utf-8"), plan_text)
    scan = scan_tests(tests, root)
    rep = check(reg, scan)
    print_report(reg, scan, rep)

    if args.json:
        payload = {
            "requirement_to_tests": {k: sorted(v) for k, v in sorted(rep.coverage.items())},
            "test_to_ids": {t.node: sorted(t.ids) for t in scan.tests},
            "exemptions": sorted(reg.exemptions),
            "failures": rep.failures + len(scan.errors),
        }
        args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    failures = rep.failures + len(scan.errors)
    print()
    if failures:
        print(f"Порушень: {failures}")
        print(f"::error title=Traceability (Lab 7)::{failures} порушень простежуваності")
        return 1
    print("Порушень немає.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
