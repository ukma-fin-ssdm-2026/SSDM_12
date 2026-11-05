"""Характеризаційні тести `scripts/check_architecture.py` перед рефакторингом (Лаб 8, бонус 2).

До Лаб 8 тестів на цей модуль не було, а `main()` — 260 рядків із когнітивною складністю 146.
Тести фіксують **поточну** поведінку — повний текст виводу й код виходу — на синтетичному
репозиторії, а не на живих документах: інакше кожна правка docs/ ламала б тест, хоча скрипт
не змінювався. Кожен сценарій ламає один вид артефакту, тож разом вони проходять усі 12
перевірок і обидві гілки кожної. Очікуваний вивід записано з коду на коміті перед
рефакторингом і не редаговано вручну: незвичні місця (повтор «з --strict», порожній рядок
перед підсумком) — теж поведінка, яку рефакторинг має зберегти.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import check_architecture

pytestmark = pytest.mark.req("QA-18")

FILES = {
    "docs/requirements/requirements.md": """# Вимоги

- **FR-001** Студент бронює вільний слот.
- **FR-002** Студент скасовує власне бронювання.

#### SEC-001: Захист сесії
""",
    "docs/requirements/user-stories.md": "# Історії\n\n### US-001: Бронювання слота\n",
    "docs/requirements/rtm.md": "# RTM\n\n| TC-001 | system | бронювання |\n",
    "docs/architecture/high-level-design.md": """# HLD

## 4. Компоненти

| Компонент | Відповідальність |
|---|---|
| `Booking` | бронювання |
| `Auth` | сесії |

## 5. Рішення

| DD-01 | Моноліт із модулями |
| AQ-01 | Чи потрібна черга |

## Використання ШІ

Чернетка — Claude.
""",
    "docs/architecture/traceability-matrix.md": """# Матриця

## 1. Функціональні вимоги

| ID | Історія | Компонент | Тест | Примітка |
|---|---|---|---|---|
| FR-001 | US-001 | `Booking` | TC-001 | ADR-001 |
| FR-002 | US-001 | `Booking` | TC-001 | DD-01 |

## 2. Нефункціональні вимоги

| SEC-001 | — | `Auth` | TC-001 | QAS-01 |

## 3. Зворотна матриця

| `Booking` | FR-001…FR-002 | 2 |
| `Auth` | SEC-001 | 1 |

## 4. Сценарії

### QAS-01

| Джерело стимулу | студент |
| Стимул | запит |
| Артефакт | API |
| Середовище | норма |
| Реакція | відповідь |
| Міра реакції | 400 мс |
| Верифікація | TC-001 |

### QAS-02

| Джерело стимулу | адміністратор |
| Стимул | зміна ролі |
| Артефакт | Auth |
| Середовище | норма |
| Реакція | аудит |
| Міра реакції | 100% |
| Верифікація | TC-001 |

## Використання ШІ

Перевірено вручну.
""",
    "docs/architecture/data-model.md": """# Модель даних

Сутності `users` і `bookings`.

| INV-01 | одне активне бронювання на слот |

## Використання ШІ

Перевірено вручну.
""",
    "docs/architecture/threat-model.md": """# Загрози

| TB1 | браузер ↔ API |
| AR-1 | прийнятий ризик |
| AS-1 | актив |

## 5. Реєстр загроз

| ID | Межа | STRIDE | Опис | Оцінка | Контрзахід |
|---|---|---|---|---|---|
| THR-01 | TB1 | S | перебір паролів | **висока** (x) | обмеження спроб входу |
| THR-02 | TB1 | S, I | викрадення сесії | **висока** (x) | cookie HttpOnly і Secure |
| THR-03 | TB1 | I, T | чужий об'єкт | **середня** (x) | перевірка власника в сервісі |
| THR-04 | TB1 | E | підвищення прав | **висока** (x) | deny-by-default для ролей |
| THR-05 | TB1 | D | флуд запитами | **низька** (x) | обмеження частоти на nginx |

## Використання ШІ

Перевірено вручну.
""",
    "docs/architecture/decisions/README.md": "# Рішення\n\n## Використання ШІ\n\nВручну.\n",
    "docs/architecture/uml/component.puml": "@startuml\n[Booking]\n@enduml\n",
    "docs/architecture/uml/deployment.puml": "' розгортання\n@startuml\nnode api\n@enduml\n",
    "docs/architecture/uml/data-model.puml": """@startuml
entity "users" as users {
  * id <<PK>>
  email <<ПД>>
}
entity "bookings" as bookings {
  * id <<PK>>
}
@enduml
""",
    "README.md": "# UniSlot\n\nАрхітектура — docs/architecture/.\n",
}

ADR = """# ADR-00{n}

**Статус:** прийнято

## Контекст

Потрібне рішення.

## Рішення

Обрали варіант.

## Наслідки

Зрозумілі.

## Розглянуті альтернативи

| Альтернатива | Чому ні |
|---|---|
| перша | дорожча |
| друга | складніша |

## Використання ШІ

Перевірено вручну.
"""

ARCH = "docs/architecture"


def build(root: Path) -> Path:
    """Мінімальний репозиторій, на якому всі 12 перевірок проходять."""
    for name, text in FILES.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    for n in (1, 2):
        (root / ARCH / "decisions" / f"ADR-00{n}.md").write_text(ADR.format(n=n), "utf-8")
    return root


def edit(root: Path, name: str, old: str, new: str) -> None:
    path = root / name
    text = path.read_text(encoding="utf-8")
    assert old in text, f"{name}: немає «{old}»"
    path.write_text(text.replace(old, new), encoding="utf-8")


def run(root: Path, monkeypatch, capsys, *args: str) -> tuple[int, str]:
    monkeypatch.chdir(root)
    monkeypatch.setattr(sys, "argv", ["check_architecture.py", *args])
    code = check_architecture.main()
    return code, capsys.readouterr().out


@pytest.fixture
def repo(tmp_path):
    return build(tmp_path)


SUMMARY = "\nВимог у матриці: 3 з 3 · компонентів: 2 · діаграм: 3 · ADR: 2 · загроз: 5 · QAS: 2\n"

PASSING = (
    "[ ok ] Обов'язкові артефакти Лаб 3\n"
    "[ ok ] Діаграми PlantUML (3 файлів)\n"
    "[skip] Синтаксис PlantUML: передайте --plantuml шлях/до/plantuml.jar\n"
    "[ ok ] Рядки матриці: заповненість і канонічні компоненти\n"
    "[ ok ] Кожна FR і NFR має рядок у матриці\n"
    "[ ok ] Кожен компонент HLD §4 (2) покриває вимогу\n"
    "[ ok ] Зворотна матриця збігається з прямою\n"
    "[ ok ] Посилання на неіснуючі ID\n"
    "[ ok ] Модель загроз (5 загроз)\n"
    "[ ok ] ADR (2)\n"
    "[ ok ] Сценарії атрибутів якості (2)\n"
    "[ ok ] Модель даних: PK, персональні дані, опис сутностей\n"
    "[ ok ] Розділ «Використання ШІ» і посилання з README\n"
    "[ ok ] Місця для автора ‹…› заповнено\n" + SUMMARY + "Порушень немає.\n"
)


def lines_with(output: str, *markers: str) -> list[str]:
    return [line for line in output.splitlines() if line.startswith(markers)]


def test_consistent_artifacts_pass_with_the_exact_report(repo, monkeypatch, capsys):
    assert run(repo, monkeypatch, capsys) == (0, PASSING)


def test_strict_mode_changes_nothing_when_every_slot_is_filled(repo, monkeypatch, capsys):
    assert run(repo, monkeypatch, capsys, "--strict") == (0, PASSING)


def test_missing_core_document_stops_before_the_other_checks(repo, monkeypatch, capsys):
    (repo / ARCH / "threat-model.md").unlink()
    assert run(repo, monkeypatch, capsys) == (
        1,
        "[FAIL] Обов'язкові артефакти Лаб 3: 1\n"
        "       docs/architecture/threat-model.md\n"
        "\nБез основних документів подальші перевірки неможливі.\n",
    )


def test_too_few_diagrams_and_adrs_are_reported_but_checks_continue(repo, monkeypatch, capsys):
    (repo / ARCH / "uml" / "component.puml").unlink()
    (repo / ARCH / "decisions" / "ADR-002.md").unlink()
    code, out = run(repo, monkeypatch, capsys)
    assert code == 1
    assert out.splitlines()[:3] == [
        "[FAIL] Обов'язкові артефакти Лаб 3: 2",
        "       docs/architecture/uml/ — діаграм 2, потрібно щонайменше 3",
        "       docs/architecture/decisions/ — ADR 1, завдання вимагає 2–3",
    ]
    assert "[ ok ] Діаграми PlantUML (2 файлів)\n" in out
    assert "[ ok ] ADR (1)\n" in out
    assert out.endswith(
        "\nВимог у матриці: 3 з 3 · компонентів: 2 · діаграм: 2 · ADR: 1 · загроз: 5 · QAS: 2\n"
        "Порушень: 2\n"
    )


def test_broken_diagram_and_missing_er_diagram(repo, monkeypatch, capsys):
    edit(repo, f"{ARCH}/uml/component.puml", "@enduml\n", "")
    edit(repo, f"{ARCH}/uml/data-model.puml", "entity ", "class ")
    code, out = run(repo, monkeypatch, capsys)
    assert code == 1
    assert lines_with(out, "[FAIL] Діаграми", "       component", "       немає ER") == [
        "[FAIL] Діаграми PlantUML (3 файлів): 2",
        "       component.puml: немає пари @startuml … @enduml",
        "       немає ER-діаграми (entity) для data-model.md",
    ]
    assert "[ ok ] Модель даних: PK, персональні дані, опис сутностей\n" in out


def test_forward_matrix_rows_are_checked_one_by_one(repo, monkeypatch, capsys):
    """Пінує й дивне: «3 з 3» рахує зайвий рядок FR-009, хоча FR-002 бракує.

    Другий рядок SEC-001 перезаписує перший, тому `Auth` лишається без вимоги. Це кандидати на
    окремий `fix:`, а не на рефакторинг: рефакторинг цю поведінку зберігає.
    """
    matrix = f"{ARCH}/traceability-matrix.md"
    edit(repo, matrix, "| FR-002 | US-001 | `Booking` | TC-001 | DD-01 |", "| FR-002 | | | | |")
    edit(
        repo,
        matrix,
        "| SEC-001 | — | `Auth` | TC-001 | QAS-01 |",
        "| SEC-001 | — | `Auth`, `Mailer` | TC-001 | QAS-01 |\n"
        "| SEC-001 | — | без компонента | TC-001 | QAS-01 |\n"
        "| FR-009 | — | `Booking` | TC-001 | — |",
    )
    code, out = run(repo, monkeypatch, capsys)
    assert code == 1
    assert out == (
        "[ ok ] Обов'язкові артефакти Лаб 3\n"
        "[ ok ] Діаграми PlantUML (3 файлів)\n"
        "[skip] Синтаксис PlantUML: передайте --plantuml шлях/до/plantuml.jar\n"
        "[FAIL] Рядки матриці: заповненість і канонічні компоненти: 4\n"
        "       FR-002: не заповнено всі 5 колонок\n"
        "       SEC-001: невідомі компоненти ['Mailer'] (канон — HLD §4)\n"
        "       SEC-001: рядок повторюється\n"
        "       SEC-001: не вказано компонент\n"
        "[FAIL] Кожна FR і NFR має рядок у матриці: 2\n"
        "       FR-002\n"
        "       FR-009: такої вимоги немає\n"
        "[FAIL] Кожен компонент HLD §4 (2) покриває вимогу: 1\n"
        "       Auth: жодної вимоги\n"
        "[FAIL] Зворотна матриця збігається з прямою: 3\n"
        "       Booking: бракує ['FR-009'], зайві ['FR-002']\n"
        "       Auth: бракує —, зайві ['SEC-001']\n"
        "       Auth: у колонці «Скільки» 1, а за прямою матрицею 0\n"
        "[FAIL] Посилання на неіснуючі ID: 1\n"
        "       docs/architecture/traceability-matrix.md:14: FR-009\n"
        "[ ok ] Модель загроз (5 загроз)\n"
        "[ ok ] ADR (2)\n"
        "[ ok ] Сценарії атрибутів якості (2)\n"
        "[ ok ] Модель даних: PK, персональні дані, опис сутностей\n"
        "[ ok ] Розділ «Використання ШІ» і посилання з README\n"
        "[ ok ] Місця для автора ‹…› заповнено\n" + SUMMARY + "Порушень: 11\n"
    )


def test_reverse_matrix_must_match_the_forward_one(repo, monkeypatch, capsys):
    matrix = f"{ARCH}/traceability-matrix.md"
    edit(repo, matrix, "| `Booking` | FR-001…FR-002 | 2 |", "| `Booking` | FR-001 | 3 |")
    edit(repo, matrix, "| `Auth` | SEC-001 | 1 |", "| `Auth` | SEC-001 | 1 |\n| `Mailer` | — | 0 |")
    code, out = run(repo, monkeypatch, capsys)
    assert code == 1
    assert lines_with(out, "[FAIL] Зворотна", "       Booking", "       Mailer") == [
        "[FAIL] Зворотна матриця збігається з прямою: 3",
        "       Booking: бракує ['FR-002'], зайві —",
        "       Booking: у колонці «Скільки» 3, а за прямою матрицею 2",
        "       Mailer: немає в HLD §4",
    ]


def test_references_to_undefined_ids_name_the_file_and_line(repo, monkeypatch, capsys):
    edit(repo, f"{ARCH}/high-level-design.md", "Чернетка — Claude.", "Див. ADR-007, US-404, TB9.")
    edit(repo, f"{ARCH}/uml/component.puml", "[Booking]", "[Booking] ' THR-99")
    code, out = run(repo, monkeypatch, capsys)
    assert code == 1
    assert lines_with(out, "[FAIL] Посилання", "       docs/") == [
        "[FAIL] Посилання на неіснуючі ID: 4",
        "       docs/architecture/high-level-design.md:17: ADR-007",
        "       docs/architecture/high-level-design.md:17: US-404",
        "       docs/architecture/high-level-design.md:17: TB9",
        "       docs/architecture/uml/component.puml:2: THR-99",
    ]


def test_threat_model_rows_need_stride_rating_and_countermeasure(repo, monkeypatch, capsys):
    threat = f"{ARCH}/threat-model.md"
    edit(repo, threat, "| THR-01 | TB1 | S |", "| THR-01 | TB1 | X |")
    edit(repo, threat, "**середня** (x)", "помірна")
    edit(repo, threat, "deny-by-default для ролей", "немає")
    edit(
        repo,
        threat,
        "| THR-05 | TB1 | D | флуд запитами | **низька** (x) | обмеження частоти на nginx |\n",
        "",
    )
    code, out = run(repo, monkeypatch, capsys)
    assert code == 1
    assert lines_with(out, "[FAIL] Модель", "       THR", "       загроз") == [
        "[FAIL] Модель загроз (4 загроз): 4",
        "       загроз 4, потрібно щонайменше 5",
        "       THR-01: категорія STRIDE «X»",
        "       THR-03: оцінка «помірна» — очікується висока / середня / низька",
        "       THR-04: немає контрзаходу чи рішення прийняти ризик",
    ]


def test_adr_needs_sections_status_and_two_alternatives(repo, monkeypatch, capsys):
    adr = f"{ARCH}/decisions/ADR-002.md"
    edit(repo, adr, "**Статус:** прийнято\n", "")
    edit(repo, adr, "## Наслідки\n", "## Підсумок\n")
    edit(repo, adr, "| друга | складніша |\n", "")
    code, out = run(repo, monkeypatch, capsys)
    assert code == 1
    assert lines_with(out, "[FAIL] ADR", "       ADR") == [
        "[FAIL] ADR (2): 3",
        "       ADR-002.md: немає розділу «Наслідки»",
        "       ADR-002.md: немає статусу",
        "       ADR-002.md: альтернатив 1, потрібно щонайменше 2",
    ]


def test_quality_scenarios_need_all_parts(repo, monkeypatch, capsys):
    matrix = f"{ARCH}/traceability-matrix.md"
    edit(repo, matrix, "| Міра реакції | 100% |\n| Верифікація | TC-001 |\n", "")
    code, out = run(repo, monkeypatch, capsys)
    assert code == 1
    assert lines_with(out, "[FAIL] Сценарії", "       QAS") == [
        "[FAIL] Сценарії атрибутів якості (2): 1",
        "       QAS-02: бракує частин ['Міра реакції', 'Верифікація']",
    ]
    text = (repo / matrix).read_text(encoding="utf-8")
    (repo / matrix).write_text(text.split("### QAS-02")[0], encoding="utf-8")
    edit(repo, matrix, "QAS-01 |\n", "— |\n")
    code, out = run(repo, monkeypatch, capsys)
    assert lines_with(out, "[FAIL] Сценарії", "       сценаріїв") == [
        "[FAIL] Сценарії атрибутів якості (1): 1",
        "       сценаріїв 1, потрібно щонайменше 2",
    ]


def test_data_model_needs_keys_personal_data_and_descriptions(repo, monkeypatch, capsys):
    er = f"{ARCH}/uml/data-model.puml"
    edit(repo, er, "  * id <<PK>>\n}\n@enduml", '  * id\n}\nentity "slots" as slots {\n}\n@enduml')
    edit(repo, er, "email <<ПД>>", "email")
    code, out = run(repo, monkeypatch, capsys)
    assert code == 1
    assert lines_with(out, "[FAIL] Модель даних", "       data") == [
        "[FAIL] Модель даних: PK, персональні дані, опис сутностей: 4",
        "       data-model.puml: сутність bookings без <<PK>>",
        "       data-model.puml: сутність slots без <<PK>>",
        "       data-model.puml: не позначено персональні дані <<ПД>>",
        "       data-model.md: не описано сутність slots",
    ]


def test_ai_section_inside_a_code_fence_does_not_count(repo, monkeypatch, capsys):
    edit(
        repo,
        f"{ARCH}/data-model.md",
        "## Використання ШІ\n\nПеревірено вручну.\n",
        "```\n## Використання ШІ\n```\n",
    )
    edit(repo, "README.md", "docs/architecture/", "docs/")
    code, out = run(repo, monkeypatch, capsys)
    assert code == 1
    assert lines_with(out, "[FAIL] Розділ", "       docs", "       README") == [
        "[FAIL] Розділ «Використання ШІ» і посилання з README: 2",
        "       docs/architecture/data-model.md",
        "       README.md: немає посилання на docs/architecture/",
    ]


def test_author_slots_warn_by_default_and_fail_in_strict_mode(repo, monkeypatch, capsys):
    edit(repo, f"{ARCH}/high-level-design.md", "Чернетка — Claude.", "‹перевірив: хто›, ‹…›")
    code, out = run(repo, monkeypatch, capsys)
    slot = "       docs/architecture/high-level-design.md:17: ‹перевірив: хто›, ‹…›"
    assert code == 0
    assert out.endswith(
        "[warn] Місця для автора ‹…› не заповнено: 1 (з --strict це порушення)\n"
        + slot
        + "\n"
        + SUMMARY
        + "Порушень немає.\n"
    )
    code, out = run(repo, monkeypatch, capsys, "--strict")
    assert code == 1
    assert out.endswith(
        "[FAIL] Місця для автора ‹…› заповнено: 1\n" + slot + "\n" + SUMMARY + "Порушень: 1\n"
    )


def test_plantuml_syntax_check_runs_java_and_filters_its_noise(repo, monkeypatch, capsys):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(
            returncode=calls[-1][0][2] == "broken.jar",
            stdout="Error line 2 in file: component.puml\n\n",
            stderr="Picked up JAVA_TOOL_OPTIONS: -Dx=y\n",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    code, out = run(repo, monkeypatch, capsys, "--plantuml", "plantuml.jar")
    assert code == 0
    assert "[ ok ] Синтаксис PlantUML (--check-syntax)\n" in out
    command, kwargs = calls[0]
    assert command[:4] == ["java", "-jar", "plantuml.jar", "--check-syntax"]
    assert [Path(p).name for p in command[4:]] == [
        "component.puml",
        "data-model.puml",
        "deployment.puml",
    ]
    assert kwargs == {"capture_output": True, "text": True, "check": False}

    code, out = run(repo, monkeypatch, capsys, "--plantuml", "broken.jar")
    assert code == 1
    assert lines_with(out, "[FAIL] Синтаксис", "       Error", "       Picked") == [
        "[FAIL] Синтаксис PlantUML (--check-syntax): 1",
        "       Error line 2 in file: component.puml",
    ]
    assert out.endswith(SUMMARY + "Порушень: 1\n")


def test_missing_decisions_readme_crashes_the_ai_section_check(repo, monkeypatch, capsys):
    """Пінує дефект: перевірка посилань пропускає відсутній README.md, а перевірка ШІ — ні.

    Скрипт падає з FileNotFoundError замість рядка [FAIL]. Виправлення змінює поведінку, тож
    іде окремим `fix:` після рефакторингу, а не в ньому.
    """
    (repo / ARCH / "decisions" / "README.md").unlink()
    with pytest.raises(FileNotFoundError):
        run(repo, monkeypatch, capsys)
