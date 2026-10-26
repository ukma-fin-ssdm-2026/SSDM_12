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
і `unislot` разом (Лаб6, PR-08); його застосовує той самий `scripts/run_lab06.py`,
який запускає CI. Поріг не знижуємо для проходження: регресія означає дописати тести
або узгодити зміну за §11.5 статуту.

CI виконує ту саму команду й публікує `coverage.xml`, HTML, JSON і JUnit як артефакти.
Назва обов'язкової перевірки `build` та Windows runner не змінені.

## Мутаційне тестування (опційно, лише Linux / WSL)

`mutmut` 3.x потребує системного виклику `fork`; **у звичайному Windows
PowerShell ця команда не працюватиме**. Запускати всередині WSL із
власним Linux-віртуальним середовищем і доступом до клону репозиторію.

```bash
python3 -m venv .venv-mutation
source .venv-mutation/bin/activate
python -m pip install -r requirements-dev.txt mutmut==3.8.0
python -m pytest tests/unit -q
mutmut run "api.pagination*"
mutmut results
```

Конфігурація `[tool.mutmut]` у `pyproject.toml` спрямовує мутації на
`src/api/` і використовує ізольовані тести з `tests/unit/`.
Починати потрібно з модуля пагінації, щоб обмежити тривалість експерименту.
Показники мутаційного тестування **не заявляються**, доки цей прогін
не буде реально виконано.

## Property-based тести

`tests/unit/test_pagination.py` містить Hypothesis-перевірку:
для згенерованого UTC часу та UUID виконується
`decode_cursor(encode_cursor(time, id)) == (time, id)`.
Вона запускається разом зі звичайним `pytest` у CI.
