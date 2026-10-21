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


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--plantuml", help="шлях до plantuml.jar для перевірки синтаксису діаграм")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="незаповнені місця «‹…›» для автора вважати порушенням (для CI)",
    )
    args = parser.parse_args()

    failures = 0

    def report(title, problems, fmt=str):
        nonlocal failures
        if problems:
            failures += len(problems)
            print(f"[FAIL] {title}: {len(problems)}")
            for p in problems:
                print(f"       {fmt(p)}")
        else:
            print(f"[ ok ] {title}")

    # --- 1. Наявність артефактів -------------------------------------------------
    missing = [str(p) for p in DOCS.values() if not p.is_file()]
    pumls = sorted(UML.glob("*.puml")) if UML.is_dir() else []
    adrs = sorted(DECISIONS.glob("ADR-[0-9][0-9][0-9].md")) if DECISIONS.is_dir() else []
    if len(pumls) < 3:
        missing.append(f"{UML}/ — діаграм {len(pumls)}, потрібно щонайменше 3")
    if not 2 <= len(adrs) <= 3:
        missing.append(f"{DECISIONS}/ — ADR {len(adrs)}, завдання вимагає 2–3")
    report("Обов'язкові артефакти Лаб 3", missing)
    if any(not p.is_file() for p in DOCS.values()):
        print("\nБез основних документів подальші перевірки неможливі.")
        return 1

    text = {k: p.read_text(encoding="utf-8") for k, p in DOCS.items()}
    req_text = req.load()
    defined, _ = req.collect_definitions(req_text)
    fr_ids = sorted(defined["FR"])
    nfr_ids = sorted(set().union(*(defined[p] for p in req.NFR_PREFIXES)))
    ordered = fr_ids + nfr_ids

    # --- 2. Діаграми ---------------------------------------------------------------
    bad_uml = []
    for p in pumls:
        body = p.read_text(encoding="utf-8")
        first = next((ln for ln in body.splitlines() if ln.strip() and not ln.startswith("'")), "")
        if not first.startswith("@startuml") or "@enduml" not in body:
            bad_uml.append(f"{p.name}: немає пари @startuml … @enduml")
    if not any("entity " in p.read_text(encoding="utf-8") for p in pumls):
        bad_uml.append("немає ER-діаграми (entity) для data-model.md")
    report(f"Діаграми PlantUML ({len(pumls)} файлів)", bad_uml)
    if args.plantuml:
        # Команда фіксована, аргументи — шлях до jar і шляхи файлів репозиторію; shell не використовується.
        run = subprocess.run(  # nosec B603 B607  # noqa: S603
            ["java", "-jar", args.plantuml, "--check-syntax", *map(str, pumls)],  # noqa: S607
            capture_output=True,
            text=True,
            check=False,
        )
        errors = [
            ln
            for ln in (run.stdout + run.stderr).splitlines()
            if ln.strip() and "JAVA_TOOL_OPTIONS" not in ln
        ]
        report("Синтаксис PlantUML (--check-syntax)", errors if run.returncode else [])
    else:
        print("[skip] Синтаксис PlantUML: передайте --plantuml шлях/до/plantuml.jar")

    # --- 3–4. Матриця простежуваності ------------------------------------------
    components = re.findall(r"^\|\s*`([^`]+)`\s*\|", section(text["hld"], "## 4."), re.MULTILINE)
    rows, row_problems = {}, []
    forward = section(text["matrix"], "## 1.") + "\n" + section(text["matrix"], "## 2.")
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
    report("Рядки матриці: заповненість і канонічні компоненти", row_problems)

    no_row = [i for i in ordered if i not in rows]
    extra = [i for i in rows if i not in ordered]
    report(
        "Кожна FR і NFR має рядок у матриці", no_row + [f"{i}: такої вимоги немає" for i in extra]
    )
    used = {c for comps in rows.values() for c in comps}
    report(
        f"Кожен компонент HLD §4 ({len(components)}) покриває вимогу",
        [f"{c}: жодної вимоги" for c in components if c not in used],
    )

    # --- 5. Зворотна матриця -----------------------------------------------------
    computed = {c: {r for r, comps in rows.items() if c in comps} for c in components}
    reverse_problems = []
    for line in section(text["matrix"], "## 3.").splitlines():
        m = re.match(r"^\|\s*`([^`]+)`\s*\|", line)
        if not m:
            continue
        comp, c = m.group(1), cells(line)
        listed = expand(c[1], ordered)
        if comp not in computed:
            reverse_problems.append(f"{comp}: немає в HLD §4")
            continue
        if listed != computed[comp]:
            lack = sorted(computed[comp] - listed)
            more = sorted(listed - computed[comp])
            reverse_problems.append(f"{comp}: бракує {lack or '—'}, зайві {more or '—'}")
        if len(c) > 2 and c[2].isdigit() and int(c[2]) != len(computed[comp]):
            reverse_problems.append(
                f"{comp}: у колонці «Скільки» {c[2]}, а за прямою матрицею {len(computed[comp])}"
            )
    report("Зворотна матриця збігається з прямою", reverse_problems)

    # --- 6. Посилання на ID --------------------------------------------------------
    arch_defined = {
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
    id_pattern = re.compile(
        r"\b(?:(?:ADR-\d{3})|(?:DD|AQ|THR|QAS|INV)-\d{2}|(?:AR|AS)-\d|TB\d"
        r"|(?:FR|US|TC|BN|A|C|R|OQ|" + NFR_ALT + r")-\d{3})\b"
    )
    files = list(DOCS.values()) + adrs + [DECISIONS / "README.md"] + pumls
    bad_refs = []
    for path in files:
        if not path.is_file():
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for found in id_pattern.findall(line):
                prefix = "TB" if found.startswith("TB") else found.rsplit("-", 1)[0]
                pool = arch_defined.get(prefix, defined.get(prefix))
                if pool is None or found not in pool:
                    bad_refs.append(f"{path}:{lineno}: {found}")
    report("Посилання на неіснуючі ID", bad_refs)

    # --- 7. Модель загроз ----------------------------------------------------------
    threat_rows = [
        cells(ln)
        for ln in section(text["threat"], "## 5.").splitlines()
        if re.match(r"^\|\s*THR-\d{2}\s*\|", ln)
    ]
    threat_problems = (
        [] if len(threat_rows) >= 5 else [f"загроз {len(threat_rows)}, потрібно щонайменше 5"]
    )
    for c in threat_rows:
        letters = {x.strip() for x in c[2].split(",")}
        rating = re.sub(r"[*]", "", c[4]).split(" ")[0]
        if not letters or not letters <= STRIDE:
            threat_problems.append(f"{c[0]}: категорія STRIDE «{c[2]}»")
        if rating not in RATINGS:
            threat_problems.append(
                f"{c[0]}: оцінка «{c[4]}» — очікується висока / середня / низька"
            )
        if len(c[5]) < 10:
            threat_problems.append(f"{c[0]}: немає контрзаходу чи рішення прийняти ризик")
    report(f"Модель загроз ({len(threat_rows)} загроз)", threat_problems)

    # --- 8. ADR --------------------------------------------------------------------
    adr_problems = []
    for p in adrs:
        body = p.read_text(encoding="utf-8")
        adr_problems.extend(
            f"{p.name}: немає розділу «{s[3:]}»" for s in ADR_SECTIONS if s not in body
        )
        if "**Статус:**" not in body:
            adr_problems.append(f"{p.name}: немає статусу")
        alts = [
            ln
            for ln in section(body, "## Розглянуті альтернативи").splitlines()
            if ln.startswith("|") and not re.match(r"^\|\s*(Альтернатива|-+)", ln)
        ]
        if len(alts) < 2:
            adr_problems.append(f"{p.name}: альтернатив {len(alts)}, потрібно щонайменше 2")
    report(f"ADR ({len(adrs)})", adr_problems)

    # --- 9. Сценарії атрибутів якості ----------------------------------------------
    qas_problems = []
    qas_blocks = re.split(r"^### (QAS-\d{2})", text["matrix"], flags=re.MULTILINE)
    qas = {qas_blocks[i]: qas_blocks[i + 1] for i in range(1, len(qas_blocks), 2)}
    if len(qas) < 2:
        qas_problems.append(f"сценаріїв {len(qas)}, потрібно щонайменше 2")
    for qid, body in qas.items():
        lack = [p for p in QAS_PARTS if not re.search(rf"^\|\s*{p}\s*\|", body, re.MULTILINE)]
        if lack:
            qas_problems.append(f"{qid}: бракує частин {lack}")
    report(f"Сценарії атрибутів якості ({len(qas)})", qas_problems)

    # --- 10. Модель даних ----------------------------------------------------------
    data_problems = []
    er = next((p for p in pumls if "entity " in p.read_text(encoding="utf-8")), None)
    if er:
        er_text = er.read_text(encoding="utf-8")
        for name, body in re.findall(
            r'entity\s+"[^"]*"\s+as\s+(\w+)\s*\{(.*?)\n\}', er_text, re.DOTALL
        ):
            if "<<PK>>" not in body:
                data_problems.append(f"{er.name}: сутність {name} без <<PK>>")
        if "<<ПД>>" not in er_text:
            data_problems.append(f"{er.name}: не позначено персональні дані <<ПД>>")
        tables = re.findall(r'entity\s+"(\w+)', er_text)
        data_problems += [
            f"data-model.md: не описано сутність {t}"
            for t in tables
            if f"`{t}`" not in text["data"]
        ]
    report("Модель даних: PK, персональні дані, опис сутностей", data_problems)

    # --- 11. Використання ШІ й README -----------------------------------------------
    fence = re.compile(r"^```.*?^```", re.MULTILINE | re.DOTALL)
    ai_missing = [
        str(p)
        for p in list(DOCS.values()) + adrs + [DECISIONS / "README.md"]
        if "## Використання ШІ" not in fence.sub("", p.read_text(encoding="utf-8"))
    ]
    readme = Path("README.md")
    if readme.is_file() and "docs/architecture/" not in readme.read_text(encoding="utf-8"):
        ai_missing.append("README.md: немає посилання на docs/architecture/")
    report("Розділ «Використання ШІ» і посилання з README", ai_missing)

    # --- 12. Місця для автора ‹…› ---------------------------------------------------
    # Місце — «‹» зі словами всередині; сама позначка «‹…›» у тексті місцем не є.
    slot = re.compile(r"‹(?![\s…]*›)")
    slots = [
        f"{p}:{n}: {ln.strip()[:70]}"
        for p in list(DOCS.values()) + adrs
        for n, ln in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if slot.search(ln)
    ]
    if args.strict or not slots:
        report("Місця для автора ‹…› заповнено", slots)
    else:
        print(f"[warn] Місця для автора ‹…› не заповнено: {len(slots)} (з --strict це порушення)")
        for s in slots:
            print(f"       {s}")

    print(
        f"\nВимог у матриці: {len(rows)} з {len(ordered)} · компонентів: {len(components)} · "
        f"діаграм: {len(pumls)} · ADR: {len(adrs)} · загроз: {len(threat_rows)} · QAS: {len(qas)}"
    )
    if failures:
        print(f"Порушень: {failures}")
        return 1
    print("Порушень немає.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
