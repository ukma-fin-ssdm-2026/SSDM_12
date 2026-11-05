#!/usr/bin/env python3
"""Перевірка узгодженості архітектурних артефактів UniSlot (Лаб 3).

Що перевіряє:
  1. Наявність обов'язкових артефактів Лаб 3 у docs/architecture/.
  2. Діаграми PlantUML: @startuml … @enduml; за --plantuml — ще й синтаксис.
  3. Матрицю простежуваності: рядок на кожну FR і NFR, заповнені колонки,
     лише канонічні назви компонентів із high-level-design.md §4.
  4. Правило «жодної вимоги без компонента, жодного компонента без вимоги».
  5. Зворотну матрицю (§3) — вона має збігатися з прямою.
  6. Посилання на ID: вимоги з docs/requirements/ і архітектурні ID
     (ADR, DD, AQ, THR, QAS, INV, AR, AS, TB) мають існувати.
  7. Модель загроз: щонайменше 5 загроз, категорія STRIDE, оцінка, контрзахід.
  8. ADR: обов'язкові розділи й щонайменше дві відхилені альтернативи.
  9. Сценарії атрибутів якості: щонайменше 2, усі шість частин і верифікація.
 10. Модель даних: у кожної сутності є PK; позначено персональні дані.
 11. Розділ «Використання ШІ» в кожному документі й посилання з README.
 12. Місця для автора «‹…›» заповнено: без --strict — попередження,
     з --strict (у CI) — порушення, бо неперевірене згенероване не зливаємо.

Запуск з кореня репозиторію:
    python3 scripts/check_architecture.py
    python3 scripts/check_architecture.py --plantuml /шлях/до/plantuml.jar --strict

Код виходу: 0 — порушень немає, 1 — є (придатне як quality gate у CI).

subprocess використовується лише для запуску PlantUML із фіксованими аргументами.

Обмеження: скрипт перевіряє форму й зв'язки, а не зміст. Чи правильне
архітектурне рішення і чи реалістична загроза, вирішує рецензент.
"""

import argparse
import importlib.util
import re
import subprocess  # nosec B404
import sys
from pathlib import Path

# Спільні шаблони ID вимог беремо зі scripts/check_requirements.py (Лаб 2),
# щоб формат ID був описаний в одному місці.
_spec = importlib.util.spec_from_file_location(
    "check_requirements", Path(__file__).resolve().with_name("check_requirements.py")
)
req = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(req)

ARCH = Path("docs/architecture")
DOCS = {
    "hld": ARCH / "high-level-design.md",
    "matrix": ARCH / "traceability-matrix.md",
    "data": ARCH / "data-model.md",
    "threat": ARCH / "threat-model.md",
}
UML = ARCH / "uml"
DECISIONS = ARCH / "decisions"

NFR_ALT = "|".join(req.NFR_PREFIXES)
REQ_ID = r"(?:FR|" + NFR_ALT + r")-\d{3}"
REQ_ROW = re.compile(r"^\|\s*(" + REQ_ID + r")\s*\|")
STRIDE = set("STRIDE")
RATINGS = {"висока", "середня", "низька"}
QAS_PARTS = (
    "Джерело стимулу",
    "Стимул",
    "Артефакт",
    "Середовище",
    "Реакція",
    "Міра реакції",
    "Верифікація",
)
ADR_SECTIONS = ("## Контекст", "## Рішення", "## Наслідки", "## Розглянуті альтернативи")
RANGE = re.compile(r"\b([A-Z]+)-(\d{2,3})\s*(?:…|–|\.\.\.)\s*\1-(\d{2,3})\b")


def section(text, heading_prefix):
    """Текст розділу від заголовка, що починається з heading_prefix, до наступного заголовка того ж рівня."""
    level = heading_prefix.split(" ")[0]
    lines, inside = [], False
    for line in text.splitlines():
        if line.startswith(heading_prefix):
            inside = True
            continue
        if inside and line.startswith(level + " ") and not line.startswith(level + "#"):
            break
        if inside:
            lines.append(line)
    return "\n".join(lines)


def cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def expand(ids_text, ordered):
    """Розгортає перелік на зразок «FR-001…FR-007, FR-062» у множину ID з ordered."""
    found = set(re.findall(REQ_ID, ids_text))
    for m in RANGE.finditer(ids_text):
        prefix, lo, hi = m.group(1), m.group(2), m.group(3)
        width = len(lo)
        for i in ordered:
            p, n = i.rsplit("-", 1)
            if p == prefix and len(n) == width and int(lo) <= int(n) <= int(hi):
                found.add(i)
    return found


class Report:
    """Друкує результат кожної перевірки й рахує порушення для коду виходу."""

    def __init__(self):
        self.failures = 0

    def __call__(self, title, problems):
        if problems:
            self.failures += len(problems)
            print(f"[FAIL] {title}: {len(problems)}")
            for p in problems:
                print(f"       {p}")
        else:
            print(f"[ ok ] {title}")


def missing_artifacts(pumls, adrs):
    """Перевірка 1: обов'язкові документи, щонайменше 3 діаграми й 2–3 ADR."""
    missing = [str(p) for p in DOCS.values() if not p.is_file()]
    if len(pumls) < 3:
        missing.append(f"{UML}/ — діаграм {len(pumls)}, потрібно щонайменше 3")
    if not 2 <= len(adrs) <= 3:
        missing.append(f"{DECISIONS}/ — ADR {len(adrs)}, завдання вимагає 2–3")
    return missing


def diagram_problems(pumls):
    """Перевірка 2: пара @startuml … @enduml у кожній діаграмі й наявність ER-діаграми."""
    bad_uml = []
    for p in pumls:
        body = p.read_text(encoding="utf-8")
        first = next((ln for ln in body.splitlines() if ln.strip() and not ln.startswith("'")), "")
        if not first.startswith("@startuml") or "@enduml" not in body:
            bad_uml.append(f"{p.name}: немає пари @startuml … @enduml")
    if not any("entity " in p.read_text(encoding="utf-8") for p in pumls):
        bad_uml.append("немає ER-діаграми (entity) для data-model.md")
    return bad_uml


def plantuml_syntax_errors(jar, pumls):
    """Перевірка 2 за --plantuml: рядки помилок `--check-syntax`, якщо PlantUML їх знайшов."""
    # Команда фіксована, аргументи — шлях до jar і шляхи файлів репозиторію; shell не використовується.
    run = subprocess.run(  # nosec B603 B607  # noqa: S603
        ["java", "-jar", jar, "--check-syntax", *map(str, pumls)],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    errors = [
        ln
        for ln in (run.stdout + run.stderr).splitlines()
        if ln.strip() and "JAVA_TOOL_OPTIONS" not in ln
    ]
    return errors if run.returncode else []


def matrix_rows(matrix_text, components):
    """Перевірка 3: рядки прямої матриці — вимога → компоненти — і їхні вади."""
    rows, row_problems = {}, []
    forward = section(matrix_text, "## 1.") + "\n" + section(matrix_text, "## 2.")
    for line in forward.splitlines():
        m = REQ_ROW.match(line)
        if not m:
            continue
        rid, c = m.group(1), cells(line)
        if rid in rows:
            row_problems.append(f"{rid}: рядок повторюється")
        if len(c) < 5 or not all(c[:5]):
            row_problems.append(f"{rid}: не заповнено всі 5 колонок")
            continue
        comps = re.findall(r"`([^`]+)`", c[2])
        unknown = [x for x in comps if x not in components]
        if not comps:
            row_problems.append(f"{rid}: не вказано компонент")
        if unknown:
            row_problems.append(f"{rid}: невідомі компоненти {unknown} (канон — HLD §4)")
        rows[rid] = comps
    return rows, row_problems


def reverse_matrix_problems(matrix_text, rows, components, ordered):
    """Перевірка 5: зворотна матриця (§3) збігається з прямою, і числа в «Скільки» теж."""
    computed = {c: {r for r, comps in rows.items() if c in comps} for c in components}
    problems = []
    for line in section(matrix_text, "## 3.").splitlines():
        m = re.match(r"^\|\s*`([^`]+)`\s*\|", line)
        if not m:
            continue
        comp, c = m.group(1), cells(line)
        listed = expand(c[1], ordered)
        if comp not in computed:
            problems.append(f"{comp}: немає в HLD §4")
            continue
        if listed != computed[comp]:
            lack = sorted(computed[comp] - listed)
            more = sorted(listed - computed[comp])
            problems.append(f"{comp}: бракує {lack or '—'}, зайві {more or '—'}")
        if len(c) > 2 and c[2].isdigit() and int(c[2]) != len(computed[comp]):
            problems.append(
                f"{comp}: у колонці «Скільки» {c[2]}, а за прямою матрицею {len(computed[comp])}"
            )
    return problems


def architecture_ids(text, adrs):
    """Архітектурні ID, оголошені в документах Лаб 3: ADR, DD, AQ, THR, AR, AS, TB, QAS, INV."""
    return {
        "ADR": {p.stem for p in adrs},
        "DD": set(re.findall(r"^\|\s*(DD-\d{2})\s*\|", text["hld"], re.MULTILINE)),
        "AQ": set(re.findall(r"^\|\s*(AQ-\d{2})\s*\|", text["hld"], re.MULTILINE)),
        "THR": set(re.findall(r"^\|\s*(THR-\d{2})\s*\|", text["threat"], re.MULTILINE)),
        "AR": set(re.findall(r"^\|\s*(AR-\d)\s*\|", text["threat"], re.MULTILINE)),
        "AS": set(re.findall(r"^\|\s*(AS-\d)\s*\|", text["threat"], re.MULTILINE)),
        "TB": set(re.findall(r"^\|\s*(TB\d)\s*\|", text["threat"], re.MULTILINE)),
        "QAS": set(re.findall(r"^### (QAS-\d{2})\b", text["matrix"], re.MULTILINE)),
        "INV": set(re.findall(r"^\|\s*(INV-\d{2})\s*\|", text["data"], re.MULTILINE)),
    }


ID_PATTERN = re.compile(
    r"\b(?:(?:ADR-\d{3})|(?:DD|AQ|THR|QAS|INV)-\d{2}|(?:AR|AS)-\d|TB\d"
    r"|(?:FR|US|TC|BN|A|C|R|OQ|" + NFR_ALT + r")-\d{3})\b"
)


def _declared(found, arch_defined, defined):
    """ID оголошено: архітектурний — у документах Лаб 3, вимоги — у docs/requirements/."""
    prefix = "TB" if found.startswith("TB") else found.rsplit("-", 1)[0]
    pool = arch_defined.get(prefix, defined.get(prefix))
    return pool is not None and found in pool


def unknown_references(files, arch_defined, defined):
    """Перевірка 6: кожен ID у документах, ADR і діаграмах оголошено у своєму джерелі."""
    bad_refs = []
    for path in (p for p in files if p.is_file()):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            bad_refs += [
                f"{path}:{lineno}: {found}"
                for found in ID_PATTERN.findall(line)
                if not _declared(found, arch_defined, defined)
            ]
    return bad_refs


def threat_model_problems(threat_text):
    """Перевірка 7: щонайменше 5 загроз; у кожної — літери STRIDE, оцінка й контрзахід."""
    threat_rows = [
        cells(ln)
        for ln in section(threat_text, "## 5.").splitlines()
        if re.match(r"^\|\s*THR-\d{2}\s*\|", ln)
    ]
    problems = (
        [] if len(threat_rows) >= 5 else [f"загроз {len(threat_rows)}, потрібно щонайменше 5"]
    )
    for c in threat_rows:
        letters = {x.strip() for x in c[2].split(",")}
        rating = re.sub(r"[*]", "", c[4]).split(" ")[0]
        if not letters or not letters <= STRIDE:
            problems.append(f"{c[0]}: категорія STRIDE «{c[2]}»")
        if rating not in RATINGS:
            problems.append(f"{c[0]}: оцінка «{c[4]}» — очікується висока / середня / низька")
        if len(c[5]) < 10:
            problems.append(f"{c[0]}: немає контрзаходу чи рішення прийняти ризик")
    return threat_rows, problems


def adr_problems(adrs):
    """Перевірка 8: у кожному ADR — обов'язкові розділи, статус і щонайменше 2 альтернативи."""
    problems = []
    for p in adrs:
        body = p.read_text(encoding="utf-8")
        problems.extend(f"{p.name}: немає розділу «{s[3:]}»" for s in ADR_SECTIONS if s not in body)
        if "**Статус:**" not in body:
            problems.append(f"{p.name}: немає статусу")
        alts = [
            ln
            for ln in section(body, "## Розглянуті альтернативи").splitlines()
            if ln.startswith("|") and not re.match(r"^\|\s*(Альтернатива|-+)", ln)
        ]
        if len(alts) < 2:
            problems.append(f"{p.name}: альтернатив {len(alts)}, потрібно щонайменше 2")
    return problems


def quality_scenario_problems(matrix_text):
    """Перевірка 9: щонайменше 2 сценарії атрибутів якості, у кожному — усі сім частин."""
    blocks = re.split(r"^### (QAS-\d{2})", matrix_text, flags=re.MULTILINE)
    qas = {blocks[i]: blocks[i + 1] for i in range(1, len(blocks), 2)}
    problems = [] if len(qas) >= 2 else [f"сценаріїв {len(qas)}, потрібно щонайменше 2"]
    for qid, body in qas.items():
        lack = [p for p in QAS_PARTS if not re.search(rf"^\|\s*{p}\s*\|", body, re.MULTILINE)]
        if lack:
            problems.append(f"{qid}: бракує частин {lack}")
    return qas, problems


def data_model_problems(pumls, text):
    """Перевірка 10: у сутностей ER-діаграми є PK, позначено ПД, кожну описано в data-model.md."""
    er = next((p for p in pumls if "entity " in p.read_text(encoding="utf-8")), None)
    if not er:
        return []
    er_text = er.read_text(encoding="utf-8")
    problems = [
        f"{er.name}: сутність {name} без <<PK>>"
        for name, body in re.findall(
            r'entity\s+"[^"]*"\s+as\s+(\w+)\s*\{(.*?)\n\}', er_text, re.DOTALL
        )
        if "<<PK>>" not in body
    ]
    if "<<ПД>>" not in er_text:
        problems.append(f"{er.name}: не позначено персональні дані <<ПД>>")
    tables = re.findall(r'entity\s+"(\w+)', er_text)
    problems += [
        f"data-model.md: не описано сутність {t}" for t in tables if f"`{t}`" not in text["data"]
    ]
    return problems


FENCE = re.compile(r"^```.*?^```", re.MULTILINE | re.DOTALL)


def ai_section_problems(adrs):
    """Перевірка 11: розділ «Використання ШІ» поза блоками коду й посилання з README."""
    problems = [
        str(p)
        for p in list(DOCS.values()) + adrs + [DECISIONS / "README.md"]
        if "## Використання ШІ" not in FENCE.sub("", p.read_text(encoding="utf-8"))
    ]
    readme = Path("README.md")
    if readme.is_file() and "docs/architecture/" not in readme.read_text(encoding="utf-8"):
        problems.append("README.md: немає посилання на docs/architecture/")
    return problems


# Місце — «‹» зі словами всередині; сама позначка «‹…›» у тексті місцем не є.
SLOT = re.compile(r"‹(?![\s…]*›)")


def author_slots(adrs):
    """Перевірка 12: незаповнені місця для автора «‹…›» у документах і ADR."""
    return [
        f"{p}:{n}: {ln.strip()[:70]}"
        for p in list(DOCS.values()) + adrs
        for n, ln in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if SLOT.search(ln)
    ]


def report_author_slots(report, slots, *, strict):
    """Без --strict незаповнені місця — попередження, з --strict (у CI) — порушення."""
    if strict or not slots:
        report("Місця для автора ‹…› заповнено", slots)
        return
    print(f"[warn] Місця для автора ‹…› не заповнено: {len(slots)} (з --strict це порушення)")
    for s in slots:
        print(f"       {s}")


def requirement_ids():
    """Оголошені ID вимог і перелік FR, а за ним NFR — у порядку рядків прямої матриці."""
    defined, _ = req.collect_definitions(req.load())
    fr_ids = sorted(defined["FR"])
    nfr_ids = sorted(set().union(*(defined[p] for p in req.NFR_PREFIXES)))
    return defined, fr_ids + nfr_ids


def row_coverage_problems(ordered, rows):
    """Перевірка 4, перша половина: кожна FR і NFR має рядок, і зайвих рядків немає."""
    no_row = [i for i in ordered if i not in rows]
    extra = [i for i in rows if i not in ordered]
    return no_row + [f"{i}: такої вимоги немає" for i in extra]


def unused_components(components, rows):
    """Перевірка 4, друга половина: кожен компонент HLD §4 покриває хоча б одну вимогу."""
    used = {c for comps in rows.values() for c in comps}
    return [f"{c}: жодної вимоги" for c in components if c not in used]


def report_plantuml(report, jar, pumls):
    """Синтаксис діаграм перевіряє лише справжній PlantUML; без --plantuml — пропуск."""
    if jar:
        report("Синтаксис PlantUML (--check-syntax)", plantuml_syntax_errors(jar, pumls))
    else:
        print("[skip] Синтаксис PlantUML: передайте --plantuml шлях/до/plantuml.jar")


def report_summary(report, counts):
    """Підсумковий рядок і код виходу: 0 — порушень немає, 1 — є."""
    print(
        f"\nВимог у матриці: {counts['rows']} з {counts['ordered']} · "
        f"компонентів: {counts['components']} · діаграм: {counts['pumls']} · "
        f"ADR: {counts['adrs']} · загроз: {counts['threats']} · QAS: {counts['qas']}"
    )
    if report.failures:
        print(f"Порушень: {report.failures}")
        return 1
    print("Порушень немає.")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--plantuml", help="шлях до plantuml.jar для перевірки синтаксису діаграм")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="незаповнені місця «‹…›» для автора вважати порушенням (для CI)",
    )
    args = parser.parse_args()
    report = Report()

    # --- 1. Наявність артефактів; без основних документів далі перевіряти нічого -------
    pumls = sorted(UML.glob("*.puml")) if UML.is_dir() else []
    adrs = sorted(DECISIONS.glob("ADR-[0-9][0-9][0-9].md")) if DECISIONS.is_dir() else []
    report("Обов'язкові артефакти Лаб 3", missing_artifacts(pumls, adrs))
    if any(not p.is_file() for p in DOCS.values()):
        print("\nБез основних документів подальші перевірки неможливі.")
        return 1
    text = {k: p.read_text(encoding="utf-8") for k, p in DOCS.items()}
    defined, ordered = requirement_ids()

    # --- 2. Діаграми ---------------------------------------------------------------
    report(f"Діаграми PlantUML ({len(pumls)} файлів)", diagram_problems(pumls))
    report_plantuml(report, args.plantuml, pumls)

    # --- 3–5. Пряма й зворотна матриці простежуваності -------------------------------
    components = re.findall(r"^\|\s*`([^`]+)`\s*\|", section(text["hld"], "## 4."), re.MULTILINE)
    rows, row_problems = matrix_rows(text["matrix"], components)
    report("Рядки матриці: заповненість і канонічні компоненти", row_problems)
    report("Кожна FR і NFR має рядок у матриці", row_coverage_problems(ordered, rows))
    report(
        f"Кожен компонент HLD §4 ({len(components)}) покриває вимогу",
        unused_components(components, rows),
    )
    report(
        "Зворотна матриця збігається з прямою",
        reverse_matrix_problems(text["matrix"], rows, components, ordered),
    )

    # --- 6. Посилання на ID --------------------------------------------------------
    files = list(DOCS.values()) + adrs + [DECISIONS / "README.md"] + pumls
    report(
        "Посилання на неіснуючі ID",
        unknown_references(files, architecture_ids(text, adrs), defined),
    )

    # --- 7–12. Загрози, ADR, сценарії якості, модель даних, ШІ, місця для автора ------
    threat_rows, threat_problems = threat_model_problems(text["threat"])
    report(f"Модель загроз ({len(threat_rows)} загроз)", threat_problems)
    report(f"ADR ({len(adrs)})", adr_problems(adrs))
    qas, qas_problems = quality_scenario_problems(text["matrix"])
    report(f"Сценарії атрибутів якості ({len(qas)})", qas_problems)
    report("Модель даних: PK, персональні дані, опис сутностей", data_model_problems(pumls, text))
    report("Розділ «Використання ШІ» і посилання з README", ai_section_problems(adrs))
    report_author_slots(report, author_slots(adrs), strict=args.strict)

    counts = {
        "rows": len(rows),
        "ordered": len(ordered),
        "components": len(components),
        "pumls": len(pumls),
        "adrs": len(adrs),
        "threats": len(threat_rows),
        "qas": len(qas),
    }
    return report_summary(report, counts)


if __name__ == "__main__":
    sys.exit(main())
