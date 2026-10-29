"""Перевірка простежуваності «вимога ↔ тест» (Лаб 7) на синтетичних rtm.md і тестах.

Скрипт `scripts/check_traceability.py` — частина конвеєра, тож його правила теж мають
тести: кожне правило з докстрінга скрипта має сценарій, де воно спрацьовує, і де ні.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import textwrap
from pathlib import Path

import pytest

pytestmark = pytest.mark.req("R-005")

# scripts/ — не пакет, тож модуль завантажуємо за шляхом. Реєстрація в sys.modules потрібна
# до виконання: dataclasses шукають модуль за назвою, коли розбирають анотації.
SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_traceability.py"
_spec = importlib.util.spec_from_file_location("check_traceability", SCRIPT)
assert _spec is not None and _spec.loader is not None
tr = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = tr
_spec.loader.exec_module(tr)

RTM = """\
# RTM

## 1. Пряма матриця

| Історія | FR | Тести |
|---|---|---|
| US-001 | FR-030, FR-031 | TP-01 |

## 2. Зворотне покриття за NFR

| NFR | Історії | Тести |
|---|---|---|
| SEC-002 | US-001 | TP-02 |

## 3. Тестові випадки

| ID | Перевіряє |
|---|---|
| TC-001 | FR-030 |

## 6. Похідні вимоги, на які посилаються тести

| ID | Джерело | Тести |
|---|---|---|
| QA-10 | quality-attributes.md | — |

## 7. Вимоги без автотесту — свідомі винятки

| ID | Чим перевіряється зараз | Чому немає автотесту | Коли |
|---|---|---|---|
| FR-031 | не перевіряється | модуля немає в коді | Лаб 9 |
"""

PLAN = """\
| ID | Компонент |
|---|---|
| TP-01 | Booking |
| TP-02 | RBAC |
"""

COVERED = """\
import pytest

pytestmark = pytest.mark.req("US-001")


@pytest.mark.req("FR-030", "TC-001", "TP-01")
def test_book():
    pass


@pytest.mark.req("SEC-002", "TP-02")
def test_rbac():
    pass


@pytest.mark.req("QA-10")
def test_contract():
    pass
"""


def make_repo(tmp_path: Path, rtm: str = RTM, plan: str = PLAN, tests: str = COVERED) -> Path:
    (tmp_path / "docs" / "requirements").mkdir(parents=True)
    (tmp_path / "docs" / "validation").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "docs" / "requirements" / "rtm.md").write_text(rtm, encoding="utf-8")
    (tmp_path / "docs" / "validation" / "test-plan.md").write_text(plan, encoding="utf-8")
    (tmp_path / "tests" / "test_sample.py").write_text(tests, encoding="utf-8")
    return tmp_path


def run_check(tmp_path: Path, **files: str):
    root = make_repo(tmp_path, **files)
    reg = tr.load_registry(
        (root / tr.RTM).read_text(encoding="utf-8"),
        (root / tr.TEST_PLAN).read_text(encoding="utf-8"),
    )
    scan = tr.scan_tests(root / tr.TESTS, root)
    return reg, scan, tr.check(reg, scan)


def test_registry_reads_all_sections():
    reg = tr.load_registry(RTM, PLAN)
    assert reg.us == {"US-001"}
    assert reg.fr == {"FR-030", "FR-031"}
    assert reg.nfr == {"SEC-002"}
    assert reg.derived == {"QA-10"}
    assert reg.tc == {"TC-001"}
    assert reg.tp == {"TP-01", "TP-02"}
    assert set(reg.exemptions) == {"FR-031"}
    assert reg.tests_column == {"US-001": {"TP-01"}, "SEC-002": {"TP-02"}, "QA-10": set()}


def test_fully_traced_repository_has_no_failures(tmp_path):
    reg, scan, rep = run_check(tmp_path)
    assert scan.errors == []
    assert rep.failures == 0
    assert rep.coverage == {
        "FR-030": ["tests/test_sample.py::test_book"],
        "SEC-002": ["tests/test_sample.py::test_rbac"],
        "QA-10": ["tests/test_sample.py::test_contract"],
    }
    assert reg.must_be_covered - set(rep.coverage) == {"FR-031"}  # закрито винятком


def test_module_class_and_function_markers_are_merged(tmp_path):
    source = """\
import pytest

pytestmark = [pytest.mark.req("US-001"), pytest.mark.slow]


@pytest.mark.req("SEC-002")
class TestRoles:
    pytestmark = pytest.mark.req("TP-02")

    @pytest.mark.req("FR-030")
    def test_one(self):
        pass
"""
    _, scan, _ = run_check(tmp_path, tests=source)
    assert [(t.node, t.ids) for t in scan.tests] == [
        (
            "tests/test_sample.py::TestRoles::test_one",
            frozenset({"US-001", "SEC-002", "TP-02", "FR-030"}),
        )
    ]


def test_test_without_requirement_is_an_orphan(tmp_path):
    source = COVERED + "\n\ndef test_forgotten():\n    pass\n"
    source = source.replace('pytestmark = pytest.mark.req("US-001")\n', "")
    _, _, rep = run_check(tmp_path, tests=source)
    assert rep.orphans == ["tests/test_sample.py::test_forgotten"]


def test_case_and_plan_ids_alone_do_not_make_a_requirement(tmp_path):
    source = 'import pytest\n\n\n@pytest.mark.req("TC-001", "TP-01")\ndef test_x():\n    pass\n'
    _, _, rep = run_check(tmp_path, tests=source)
    assert rep.orphans == ["tests/test_sample.py::test_x"]


def test_unknown_id_in_marker_is_reported(tmp_path):
    source = COVERED.replace('"QA-10"', '"QA-10", "FR-999", "TP-77"')
    _, _, rep = run_check(tmp_path, tests=source)
    assert rep.unknown == [
        "tests/test_sample.py::test_contract: FR-999",
        "tests/test_sample.py::test_contract: TP-77",
    ]


def test_requirement_without_test_and_exemption_is_uncovered(tmp_path):
    source = COVERED.replace('@pytest.mark.req("QA-10")\n', "")
    _, _, rep = run_check(tmp_path, tests=source)
    assert rep.uncovered == ["QA-10"]


def test_exemption_with_a_test_is_stale(tmp_path):
    source = COVERED.replace('"FR-030", "TC-001"', '"FR-030", "FR-031", "TC-001"')
    _, _, rep = run_check(tmp_path, tests=source)
    assert rep.stale == ["FR-031"]


@pytest.mark.parametrize(
    "row",
    [
        "| FR-031 | — | модуля немає в коді | Лаб 9 |",
        "| FR-031 | не перевіряється |  | Лаб 9 |",
        "| FR-031 |",
    ],
)
def test_exemption_needs_method_and_reason(tmp_path, row):
    rtm = RTM.replace("| FR-031 | не перевіряється | модуля немає в коді | Лаб 9 |", row)
    _, _, rep = run_check(tmp_path, rtm=rtm)
    assert rep.empty_reason == ["FR-031"]


def test_tests_column_must_name_existing_plan_cases(tmp_path):
    rtm = RTM.replace("| US-001 | FR-030, FR-031 | TP-01 |", "| US-001 | FR-030, FR-031 | TP-09 |")
    _, _, rep = run_check(tmp_path, rtm=rtm)
    assert rep.unknown_tp_in_rtm == ["US-001: TP-09"]


@pytest.mark.parametrize(
    ("decorator", "message"),
    [
        ("@pytest.mark.req(REQUIREMENT)", "має бути рядковим літералом"),
        ("@pytest.mark.req()", "без жодного ID"),
        ("@pytest.mark.req", "без дужок"),
    ],
)
def test_malformed_markers_are_errors(tmp_path, decorator, message):
    source = f"import pytest\n\nREQUIREMENT = 'FR-030'\n\n\n{decorator}\ndef test_x():\n    pass\n"
    _, scan, _ = run_check(tmp_path, tests=source)
    assert len(scan.errors) == 1
    assert message in scan.errors[0]


def test_syntax_error_in_test_file_is_reported(tmp_path):
    _, scan, _ = run_check(tmp_path, tests="def test_broken(:\n")
    assert scan.errors and "не розбирається" in scan.errors[0]


def test_main_exit_codes_and_json_report(tmp_path, capsys):
    root = make_repo(tmp_path)
    out = tmp_path / "trace.json"
    assert tr.main(["--root", str(root), "--json", str(out)]) == 0
    assert "Порушень немає." in capsys.readouterr().out
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["failures"] == 0
    assert payload["requirement_to_tests"]["SEC-002"] == ["tests/test_sample.py::test_rbac"]

    (root / "tests" / "test_sample.py").write_text(
        textwrap.dedent(
            """\
            def test_forgotten():
                pass
            """
        ),
        encoding="utf-8",
    )
    assert tr.main(["--root", str(root)]) == 1
    assert "Тести без жодної вимоги: 1" in capsys.readouterr().out


def test_missing_rtm_is_a_usage_error(tmp_path, capsys):
    assert tr.main(["--root", str(tmp_path)]) == 2
    assert "Не знайдено" in capsys.readouterr().out
