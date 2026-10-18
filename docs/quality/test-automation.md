# Додаткові перевірки якості тестів

Це налаштування для майбутніх розробницьких перевірок, **не звіт і не стратегія Лаб 6**.
Поточні HTTP-контрактні тести залишаються; ізольовані тести містяться в `tests/unit/`.

## Локальний запуск (PowerShell)

```powershell
cd C:\SSDM_12
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m pytest --cov=api --cov-branch --cov-report=term-missing --cov-report=html:htmlcov --cov-fail-under=50
```

HTML-звіт: `htmlcov/index.html`. Порогове значення 50% тимчасове,
вихідна точка для контролю регресій, **не ціль курсу**. Його потрібно
підвищувати лише після аналізу фактичного покриття.

CI використовує ту саму команду для покриття й додає `coverage.xml` як артефакт.
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
