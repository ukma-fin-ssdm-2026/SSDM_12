# Чек-лист відтворюваного нативного запуску на Windows

Це інструкція для повторення запуску з чистої копії. Вона не вимагає передавати
проєкт іншому учаснику чи перевіряти його на чужому фізичному ПК. Викладач окремо
такої перевірки не вимагав. Повний локальний результат — у [звірці FR](fr-readiness-audit.md).

## 1. Які джерела передати

Потрібна поточна реалізація feature/midterm-admin-availability із міграцією 0005.
До перевірки PR локальна гілка може відрізнятися від `main`; звичайний pull не
переносить локальні коміти. Перевіряти тільки tracked-джерела; без .env.local, .env.migrations.local,
pgdata, .venv, токенів і дампів особистих даних.

Команди нижче виконуються в PowerShell у власному каталозі учасника.
Локальна звірка проведена на Windows 10, Python 3.13.13, PostgreSQL 16.
Ціль C-001 — Python 3.12; зафіксуй версію, на якій реально запускав перевірку.
Linux/macOS цією інструкцією не засвідчуються.

## 2. Встановлення й нова БД

Попередньо потрібні Python 3.12+ та PostgreSQL 16 binaries (initdb, pg_ctl,
postgres). Node.js 22+ потрібен для повного pytest із тестами JavaScript,
але не для роботи UI. Вільні порти: 55436 для власної БД та 3000 для API.
Якщо порт зайнятий, спочатку з'ясувати, яким власним процесом; чужий сервіс не зупиняти.

Вибрати власний шлях. Папка повинна містити src, scripts, migrations і
requirements-dev.txt; це не шлях до репозиторію на ПК Дениса.

```powershell
Set-Location -LiteralPath (Read-Host 'Абсолютний шлях до своєї копії SSDM_12')
if (-not (Test-Path -LiteralPath 'scripts/manage_db.py')) { throw 'Обрано не корінь проєкту' }
python --version
python -m venv .venv
if ($LASTEXITCODE -ne 0) { throw 'Не створено venv' }
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { throw 'Не встановлено залежності' }
.\.venv\Scripts\python.exe -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Залежності несумісні' }
```

Якщо PostgreSQL 16 не знаходиться автоматично або є кілька версій, указати
його власний bin-каталог. У наступних терміналах повторити цю змінну за потреби.

```powershell
$env:UNISLOT_POSTGRES_BIN = Read-Host 'Абсолютний шлях до bin PostgreSQL 16'
& (Join-Path $env:UNISLOT_POSTGRES_BIN 'postgres.exe') --version
if ($LASTEXITCODE -ne 0) { throw 'Немає PostgreSQL binaries' }
.\.venv\Scripts\python.exe -X utf8 scripts/manage_db.py local-init
if ($LASTEXITCODE -ne 0) { throw 'Не створено локальну БД' }
.\.venv\Scripts\python.exe -X utf8 scripts/manage_db.py migrate --env-file .env.migrations.local
if ($LASTEXITCODE -ne 0) { throw 'Міграції не застосовані' }
```

Очікується head **0005**. Повтор migrate має завершитися без скидання даних.
Для перевірки оновлення наявної 0004 замість нової БД є інтеграційний тест
tests/integration/test_booking_context_migration.py; він працює на власній тестовій БД.

local-init створює синтетичні демонстраційні записи й явно вмикає старі demo-токени.
Для перевірки робочої системи вимкнути їх у власному env. Наступна команда зберігає
інші рядки й використовує UTF-8 без BOM, сумісний із load_environment на PowerShell 5.1:

```powershell
$localEnvPath = Join-Path (Get-Location).Path '.env.local'
$localEnvText = [System.IO.File]::ReadAllText($localEnvPath)
$localEnvText = [regex]::Replace($localEnvText, '(?m)^UNISLOT_DEMO_AUTH=.*$', 'UNISLOT_DEMO_AUTH=0')
[System.IO.File]::WriteAllText($localEnvPath, $localEnvText, [System.Text.UTF8Encoding]::new($false))
```

Створити першого реального адміністратора один раз. Ввести свій тестовий пароль
двічі в прихованому запиті; не додавати його до команд, PR чи журналу результатів.

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/create_admin.py --env-file .env.local --email admin-review@example.com --full-name 'Review Administrator'
if ($LASTEXITCODE -ne 0) { throw 'Адміністратора не створено' }
```

Якщо його вже створювали на цій БД, використовувати чинний вхід; команда навмисно
не перезаписує пароль або чужого адміністратора. Secure=0 задає local-init тільки
для loopback HTTP; значення за замовчуванням для HTTPS лишається Secure=1.

## 3. API та Worker

Перший термінал, із кореня цієї ж копії:

```powershell
$env:UNISLOT_DEMO_AUTH = '0'
$env:UNISLOT_THREAD_SWITCH_INTERVAL_MS = '1'
.\.venv\Scripts\python.exe -m uvicorn api.main:app --app-dir src --env-file .env.local --workers 2 --host 127.0.0.1 --port 3000
```

У журналі мають бути **два Started server process** і два завершені startup.
Режим --reload тут не використовувати. Профіль має до 64 API-з'єднань із БД
(по 32 на процес); для Worker та службових команд потрібен резерв.

Другий термінал:

```powershell
Set-Location -LiteralPath (Read-Host 'Шлях до тієї самої копії SSDM_12')
.\.venv\Scripts\python.exe -X utf8 scripts/run_worker.py --env-file .env.local
```

Очікуються horizon_refresh і записи claimed/sent/failed без URL, паролів і
вмісту сповіщень. Третій термінал для базової перевірки:

```powershell
Invoke-RestMethod -Uri 'http://127.0.0.1:3000/health'
```

Має повернути status=ok. UI: http://127.0.0.1:3000/.
Swagger: http://127.0.0.1:3000/api-docs. /health поза /api/v1.

## 4. Пройти сценарій у браузері

Використовувати різні профілі браузера або виходити при зміні користувача.
Усі імена й адреси — синтетичні. Demo Authorize не потрібен: вхід через форму
створює реальну cookie-сесію, а клієнт додає X-CSRF-Token.

| Крок | Хто й що робить | Що перевірити |
|---|---|---|
| 1 | Зареєструвати студентський акаунт і окремий майбутній акаунт провайдера | Після самореєстрації обидва мають тільки student; увійти/вийти можливо |
| 2 | Admin: «Користувачі», надати другому акаунту provider; «Ресурси», створити консультацію з цим провайдером | Роль діє без нового login; ресурс є в каталозі |
| 3 | Provider: «Доступність», вибрати свій ресурс, створити три неперетинні слоти через 3 дні | Тривалість 30 хв; власник може створити, студент не має цієї операції |
| 4 | Student: «Знайти час», вибрати провайдера та дату, забронювати перший слот | У «Мої бронювання» active, час Europe/Kyiv, дедлайн; слот зникає з пошуку |
| 5 | Student і provider: «Сповіщення», оновити | У студента confirmation, у провайдера provider_created, без ручного dispatch через API |
| 6 | Provider: «Календар ресурсу» | Зайнятий слот у календарі й підсумку; імен та ID студентів немає |
| 7 | Student: перенести бронь на другий вільний слот | Старий запис cancelled/rescheduled із посиланням на новий; перший слот вільний, другий зайнятий; provider отримує скасування старого й створення нового |
| 8 | Student: скасувати новий запис | Стан cancelled; другий слот знову можна забронювати; provider має відповідне повідомлення |
| 9 | Admin: «Журнал аудиту», відфільтрувати resource.create | Є автор, час, об'єкт і before/after; студент не має доступу до журналу |
| 10 | Зупинити тільки API Ctrl+C, знову запустити командою з кроку 3 | Сесія та історія бронювань збережені; Worker і БД окремі; вихід відкликає поточну сесію |

Нагадування заплановане за 24 години; при цьому короткому сценарії його доставка
ще не настала. Включну межу, UTC/DST, відхилення naive datetime та перенесення
нагадувань доводять тести, а не очікування 24 годин під час демонстрації.
Для ручного негативного перенесення другий студент може зайняти третій слот:
спроба перенести туди має дати 409 і зберегти попередню бронь та нагадування.

## 5. Автоматичні перевірки й результат

З окремого термінала в корені своєї копії; результати поза Git:

```powershell
New-Item -ItemType Directory -Path '..\native-review-results' -Force | Out-Null
.\.venv\Scripts\python.exe -X utf8 scripts/check_requirements.py
.\.venv\Scripts\python.exe -X utf8 scripts/check_traceability.py --json '..\native-review-results\traceability.json'
.\.venv\Scripts\python.exe -X utf8 -m pytest -q --cov=api --cov=unislot --cov-branch --cov-fail-under=90 --cov-report=term --junitxml='..\native-review-results\junit.xml'
```

На перевіреному джерелі — 684 passed. На новішому коміті число може змінитися;
важливі код завершення 0, відсутність failed/error/skipped і покриття ≥90%.
Тести створюють власні PostgreSQL БД, не скидають pgdata/dev. Якщо Node.js чи
PostgreSQL відсутні, це треба виправити, а не приховувати пропуском тестів.

Зберегти фактичний результат у текстовий файл:

```text
Дата:
Учасник / комп'ютер (не ПК Дениса):
Коміт або ідентифікатор source ZIP:
ОС / Python / PostgreSQL / Node.js:
Встановлення з нового venv: результат і час:
Міграція 0005, повтор migrate: результат:
Два API server PID / окремий Worker: результат:
Кроки 1–10: пройдені кроки; помилки з request_id, якщо були:
Бронь → перенос → скасування → скринька: результат:
Перезапуск API / збереження даних / logout: результат:
pytest: фактичне число, exit code, coverage; шлях до JUnit:
Невиконані перевірки та причини:
```

Не вписувати наперед успішні результати. Цей чек-лист сам по собі не є доказом
PORT-001: збережи фактичний час і результат сценарію з чистої копії. Linux/macOS
не входять до поточного критерію запуску.

Після роботи зупинити API та Worker через Ctrl+C; у власному корені проєкту:

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/manage_db.py stop-local
```

Команда зберігає власні дані. Робочі pgdata та env не видаляти для повторного запуску.

## Використання ШІ

Codex підготував послідовність за фактичними CLI, UI та локальними перевірками.
Інструкція передає завдання учаснику; виконання на його ПК не приписується.
