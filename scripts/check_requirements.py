#!/usr/bin/env python3
"""Перевірка узгодженості артефактів вимог UniSlot (Лаб 2).

Що перевіряє:
  1. Дублікати визначень ID.
  2. Посилання на ID, яких не існує у вихідних файлах.
  3. Повноту полів кожної NFR.
  4. Числа, вписані в текст FR замість посилання на A-###.
  5. Кількість критеріїв прийняття на історію (мінімум курсу — 3).
  6. Наявність рядка прямої матриці RTM для кожної історії.
  7. Покриття: FR і NFR, на які не посилається жодна історія.

Запуск з кореня репозиторію:
    python3 scripts/check_requirements.py

Код виходу: 0 — порушень немає, 1 — є (придатне як quality gate у CI).

Обмеження: перевіряються лише механічні властивості — існування ID,
повнота полів, формат. Чи правильна вимога по суті, чи реалістичний поріг
і чи відповідає артефакт потребам користувачів, скрипт не знає. Це
інструмент для рецензента, а не заміна рецензії.
"""

import re
import sys
from pathlib import Path

DOCS = Path("docs/requirements")
FILES = {name: DOCS / f"{name}.md" for name in ("requirements", "user-stories", "rtm")}

NFR_PREFIXES = ("PERF", "REL", "SEC", "MAINT", "USAB", "PORT")
NFR_FIELDS = ("Характеристика", "Метрика", "Умови", "Перевірка", "Джерело", "Пріоритет")
MIN_CRITERIA = 3

# Як ID оголошується. Якщо формат у файлах зміниться — правити тільки тут.
DEFINITION_PATTERNS = {
    "FR": (r"^- \*\*(FR-\d{3})\*\*", "requirements"),
    "A": (r"^- \*\*(A-\d{3})\*\*", "requirements"),
    "C": (r"^- \*\*(C-\d{3})\*\*", "requirements"),
    "BN": (r"\*\*(BN-\d{3})\*\*", "requirements"),
    "R": (r"^\|\s*(R-\d{3})\s*\|", "requirements"),
    "OQ": (r"^\|\s*(OQ-\d{3})\s*\|", "requirements"),
    "US": (r"^### (US-\d{3}):", "user-stories"),
    "TC": (r"^\|\s*(TC-\d{3})\s*\|", "rtm"),
}
NFR_DEFINITION = r"^#### ((?:%s)-\d{3})" % "|".join(NFR_PREFIXES)

ANY_ID = r"(?:FR|US|TC|BN|A|C|R|OQ|%s)-\d{3}" % "|".join(NFR_PREFIXES)

# Заголовки функцій оголошують зарезервований діапазон ID,
# наприклад «### F1. Автентифікація та авторизація (FR-001…FR-009)».
# Межі такого діапазону — оголошення, а не посилання на наявну вимогу.
RANGE_DECLARATION = re.compile(r"^#{2,4}\s*F\d+\.")


def load():
    text, missing = {}, [p for p in FILES.values() if not p.is_file()]
    if missing:
        print("Не знайдено файлів (запускайте з кореня репозиторію):")
        for p in missing:
            print(f"  {p}")
        sys.exit(2)
    for name, path in FILES.items():
        text[name] = path.read_text(encoding="utf-8")
    return text


def collect_definitions(text):
    defined, duplicates = {}, []
    for prefix, (pattern, source) in DEFINITION_PATTERNS.items():
        found = re.findall(pattern, text[source], re.M)
        defined[prefix] = set(found)
        duplicates += [(i, found.count(i)) for i in set(found) if found.count(i) > 1]
    nfr = re.findall(NFR_DEFINITION, text["requirements"], re.M)
    for prefix in NFR_PREFIXES:
        defined[prefix] = {i for i in nfr if i.startswith(prefix)}
    duplicates += [(i, nfr.count(i)) for i in set(nfr) if nfr.count(i) > 1]
    return defined, duplicates


def check_references(text, defined):
    bad = []
    for name, body in text.items():
        for lineno, line in enumerate(body.splitlines(), 1):
            if RANGE_DECLARATION.match(line):
                continue
            for found in re.findall(ANY_ID, line):
                prefix = found.rsplit("-", 1)[0]
                if found not in defined.get(prefix, set()):
                    bad.append((f"{name}.md", lineno, found))
    return bad


def check_nfr_fields(text):
    gaps = []
    blocks = re.split(NFR_DEFINITION, text["requirements"], flags=re.M)
    for i in range(1, len(blocks), 2):
        nfr_id, body = blocks[i], blocks[i + 1]
        missing = [f for f in NFR_FIELDS if f"**{f}" not in body]
        metric = re.search(r"\*\*Метрика:?\*\*(.*)", body)
        # Поріг може бути числовим (p95 ≤ 400 мс, ≥ 70%) або категоріальним
        # (Security Rating A). Обидва перевірні, тому приймаємо і літерну оцінку.
        if not metric or not re.search(r"\d|\b[A-E]\b", metric.group(1)):
            missing.append("поріг у метриці")
        if missing:
            gaps.append((nfr_id, missing))
    return gaps


def check_hardcoded_numbers(text):
    unit = r"(?:годин\w*|хвилин\w*|дн\w+|активн\w+|символ\w*|раз\w*|відсотк\w*|%)"
    hits = []
    for lineno, line in enumerate(text["requirements"].splitlines(), 1):
        if not re.match(r"^- \*\*FR-\d{3}\*\*", line):
            continue
        for m in re.finditer(r"(?<![\w-])(\d+)\s*" + unit, line):
            hits.append((lineno, m.group(0), line.strip()[:80]))
    return hits


def check_stories(text, defined):
    thin, missing_rows = [], []
    blocks = re.split(r"^### (US-\d{3}):", text["user-stories"], flags=re.M)
    for i in range(1, len(blocks), 2):
        story_id = blocks[i]
        body = blocks[i + 1].split("## Перевірка")[0]
        count = len(re.findall(r"^- \[[ x]\] \*\*Given\*\*", body, re.M))
        if count < MIN_CRITERIA:
            thin.append((story_id, count))
    for story_id in sorted(defined["US"]):
        if not re.search(rf"^\|\s*{story_id}\s*\|", text["rtm"], re.M):
            missing_rows.append(story_id)
    return thin, missing_rows


def check_coverage(text, defined):
    referenced_fr, referenced_nfr = set(), set()
    for line in text["rtm"].splitlines():
        if not re.match(r"^\|\s*US-\d{3}\s*\|", line):
            continue
        cells = [c.strip() for c in line.split("|")]
        if len(cells) < 8:
            continue
        referenced_fr |= set(re.findall(r"FR-\d{3}", cells[5]))
        referenced_nfr |= set(re.findall(r"(?:%s)-\d{3}" % "|".join(NFR_PREFIXES), cells[6]))
    nfr_defined = set().union(*(defined[p] for p in NFR_PREFIXES))
    return sorted(defined["FR"] - referenced_fr), sorted(nfr_defined - referenced_nfr)


def main():
    text = load()
    defined, duplicates = collect_definitions(text)
    failures = 0

    counts = ", ".join(f"{p} {len(v)}" for p, v in sorted(defined.items()) if v)
    print(f"Знайдено визначень: {counts}\n")

    def report(title, problems, fmt):
        nonlocal failures
        if problems:
            failures += len(problems)
            print(f"[FAIL] {title}: {len(problems)}")
            for item in problems:
                print(f"       {fmt(item)}")
        else:
            print(f"[ ok ] {title}")

    report("Дублікати визначень ID", duplicates, lambda d: f"{d[0]} визначено {d[1]} разів")
    report("Посилання на неіснуючі ID", check_references(text, defined),
           lambda b: f"{b[0]} р.{b[1]}: {b[2]}")
    report("Повнота полів NFR", check_nfr_fields(text),
           lambda g: f"{g[0]}: бракує {', '.join(g[1])}")
    report("Числа, вписані в текст FR", check_hardcoded_numbers(text),
           lambda h: f"р.{h[0]}: «{h[1]}» у «{h[2]}…»")

    thin, missing_rows = check_stories(text, defined)
    report(f"Критеріїв на історію (мінімум {MIN_CRITERIA})", thin,
           lambda t: f"{t[0]}: {t[1]}")
    report("Рядок RTM для кожної історії", missing_rows, lambda s: f"{s}: рядка немає")

    fr_gap, nfr_gap = check_coverage(text, defined)
    print(f"[info] FR, на які не посилається жодна історія: {', '.join(fr_gap) or 'немає'}")
    print(f"[info] NFR, на які не посилається жодна історія: {', '.join(nfr_gap) or 'немає'}")

    print()
    if failures:
        print(f"Порушень: {failures}")
        return 1
    print("Порушень немає.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
