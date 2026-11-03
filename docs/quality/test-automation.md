# Додаткові перевірки якості тестів

Це налаштування для майбутніх розробницьких перевірок, **не звіт і не стратегія Лаб 6**.
Поточні HTTP-контрактні тести залишаються; ізольовані тести містяться в `tests/unit/`.

## Локальний запуск (PowerShell)

```powershell
cd C:\SSDM_12
.\.venv\Scripts\python.exe -m pip install -r requirements-testing.txt
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe scripts\run_lab06.py
```

HTML-звіт: `docs/testing/lab06/htmlcov/index.html`. Сукупний поріг — **90%** для `api`
і `unislot` разом (Лаб6, #207); його застосовує той самий `scripts/run_lab06.py`,
який запускає CI. Поріг не знижуємо для проходження: регресія означає дописати тести
або узгодити зміну за §11.5 статуту.

CI виконує ту саму команду й публікує `coverage.xml`, HTML, JSON і JUnit як артефакти.
Назва обов'язкової перевірки `build` та Windows runner не змінені.

## Мутаційне тестування (опційно, окреме локальне середовище)

Виконано **Cosmic Ray 8.7.0** по одному модулю — `src/api/resource_rules.py` — цільовими
тестами з `tests/unit/test_resource_rules.py`. Інструмент не входить до звичайного
PR CI: він живе в окремому файлі залежностей, щоб не подовжувати кожен прогін.

```powershell
python -m venv .venv-mutation
.\.venv-mutation\Scripts\Activate.ps1
python -m pip install -r requirements-mutation.txt
python scripts\mutation_lab06.py --label after
```

`requirements-mutation.txt` підтягує `requirements-testing.txt` і `cosmic-ray==8.7.0`.
Скрипт копіює модуль у тимчасовий каталог і мутує копію: робоче джерело не змінюється,
його SHA-256 фіксується у звіті до і після. Cosmic Ray виконується в тому самому процесі
(`commands.init`, `commands.execute`), тому `fork` не потрібен і WSL не обов'язковий.

**Результати** — у [`docs/testing/lab06/mutation-report.md`](../testing/lab06/mutation-report.md):
контрольний набір 34 убито / 4 вижило (89.47%), після додавання регресій 38 / 0
(100.00%). Сто відсотків стосуються лише цього малого модуля й стандартного набору
операторів, а не проєкту в цілому.

**Що дав експеримент.** Вижив мутант `if kind is ResourceType.ROOM` →
`if kind == ResourceType.ROOM`: `StrEnum` дорівнює рядку `"room"`, тож підміна `is` на
`==` не ламала жодного тесту. Тести перевіряли Enum і `"unknown"`, але не рядок із
допустимим значенням. Регресія `test_strict_resource_type_requires_enum_not_raw_string`
убиває цього мутанта й ще три вцілілі порівняння.

Попередній план використати `mutmut` не реалізовано: він потребує системного виклику
`fork`, якого немає у Windows-середовищі команди. Конфігурацію `[tool.mutmut]` прибрано
з `pyproject.toml` разом із цим розділом.

## Property-based тести

`tests/unit/test_pagination.py` містить Hypothesis-перевірку:
для згенерованого UTC часу та UUID виконується
`decode_cursor(encode_cursor(time, id)) == (time, id)`.
Вона запускається разом зі звичайним `pytest` у CI.

## Використання ШІ

Мутаційний прогін і його оснащення — робота Павла Дзюбака: `requirements-mutation.txt`,
`scripts/mutation_lab06.py` і `docs/testing/lab06/mutation-report.md` створені ним
25.10.2026; скрипт і регресійні тести готував Codex. Розділи «Локальний запуск
(PowerShell)» і «Property-based тести» писав Денис Пацеля. Цей розділ про мутаційне
тестування переписав Никита Бабаков із Claude (Opus 5) 03.11.2026, замінивши
нереалізований план із `mutmut` описом фактичного прогону.

**Перевірка (Никита).** Числа звірено з
[`lab06/evidence/mutation-before.json`](../testing/lab06/evidence/mutation-before.json)
(`mutation_score` 89.47, `total` 38) і
[`mutation-after.json`](../testing/lab06/evidence/mutation-after.json)
(`mutation_score` 100.0, `total` 38). SHA-256 модуля `src/api/resource_rules.py`
однаковий у звіті та в обох прогонах, а обидва прогони містять
`working_source_unchanged: true` — робоче джерело не змінювалося.

**Компроміси, закладені при оснащенні.** Один невеликий модуль замість усього проєкту,
бо мутаційний прогін множить число запусків усього набору тестів на кількість мутантів;
і окремий `requirements-mutation.txt` замість `requirements-dev.txt`, щоб Cosmic Ray не
встановлювався й не виконувався в CI кожного PR.
