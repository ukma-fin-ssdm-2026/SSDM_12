# Спайк ADR-002 — 12.10.2026

Перевірки виконав Codex на окремому PostgreSQL 16.15 у Windows 10,
Python 3.12.14, psycopg 3.3.6; `max_connections = 200`.

- `adr002_spike.py` — індекс, блокування, EXCLUDE, аудит і контрольні гонки.
- `verify_additional.py` — FK/UNIQUE/CHECK перенесення, відкат, конкурентні перенесення,
  взаємне блокування з повтором та UUIDv4 журналу аудиту.
- [Основний журнал](spike-run.txt), [JSON усіх прогонів](spike-results.json).
- [Додатковий журнал](additional-run.txt), [додаткові результати](additional-results.json).

Обидва скрипти завершилися кодом 0. Для кожного захищеного конкурентного сценарію:
20 прогонів × 100 спроб, 1 успіх і 99 конфліктів на прогін. Негативні контрольні
сценарії навмисно показують гонку; `[RACE]` у них — очікуваний результат.

## Відтворення

Скрипти створюють і пересоздають схеми `spike`, `spike_extra` та роль `spike_app`.
Запускати в окремій тестовій БД. Наприклад, PowerShell з Docker і Python:

```powershell
docker run --rm -d --name unislot-adr002 -p 127.0.0.1:5433:5432 -e POSTGRES_PASSWORD=spike postgres:16.15 -c max_connections=200
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install "psycopg[binary]==3.3.6"
$env:SPIKE_DSN = "host=127.0.0.1 port=5433 user=postgres password=spike dbname=postgres"
$env:SPIKE_CONCURRENCY = "100"
$env:SPIKE_RUNS = "20"
$env:SPIKE_REPORT = "spike-results.json"
$env:SPIKE_EXTRA_REPORT = "additional-results.json"
.\.venv\Scripts\python.exe -u adr002_spike.py
.\.venv\Scripts\python.exe -u verify_additional.py
docker stop unislot-adr002
```

Перед запуском скриптів дочекайся готовності PostgreSQL (`docker logs unislot-adr002`).
Кількість дублікатів у контрольному сценарії залежить від планування потоків.
Сценарії перевіряють SQL-модель і транзакції; прикладні HTTP-тести та PERF-002
належать до тестування реалізації системи.
