# Парольна автентифікація та cookie-сесії — локальний етап

**Дата:** 31.10.2026. **Гілка:** feature/midterm-admin-availability.
Продовження [PostgreSQL/outbox](postgres-outbox.md) на базі main
7e384d251c3c267d340a6f2e9aece704241a56a7. Push, PR і GitHub CI не виконувалися.

## Вимоги та джерела рішень

| Рішення | Документація проєкту | Виконання |
|---|---|---|
| Реєстрація тільки student, ігнорування переданої ролі | FR-001/002, US-010 | POST /api/v1/auth/register; role/roles/is_admin не потрапляють у модель користувача |
| Унікальна адреса без регістру | FR-003, INV-09 | нормалізація на сервері, транзакція та lower(email) unique у PostgreSQL |
| Argon2id, повний пароль | FR-004, SEC-001 | 15–1024 символи без trim/truncate; RFC 9106 LOW_MEMORY (64 MiB, t=3, p=4); rehash після успішного входу |
| Однакова помилка входу | FR-005 | 401 INVALID_CREDENTIALS для відсутньої адреси, відсутнього пароля та неправильного пароля; dummy Argon2-перевірка для відсутнього хеша |
| Обмеження невдалих входів | FR-006, OQ-001, AQ-04 | стійкі лічильники, тимчасовий cooldown, 429 і Retry-After; під час cooldown запити його не продовжують |
| Cookie-сесія та актуальні ролі | DD-06, FR-007, THR-02 | випадковий токен 256 біт, у БД SHA-256; HttpOnly, Secure, SameSite=Lax; строк перевіряється сервером |
| CSRF | HLD §5.1, THR-13 | X-CSRF-Token, хеш якого прив'язаний до сесії; перевірка точного Origin; login/register приймають JSON |
| Повний стан Auth | data-model.md і ER | password_hash та лічильник у app_user; session з UUIDv4 id і bytea token_hash |

Шляхи, cookie та модель даних звірено з актуальними GitHub
[HLD](https://github.com/ukma-fin-ssdm-2026/SSDM_12/blob/main/docs/architecture/high-level-design.md),
[моделлю даних](https://github.com/ukma-fin-ssdm-2026/SSDM_12/blob/main/docs/architecture/data-model.md)
і відкритими питаннями requirements.md. Параметри OQ-001 не знайдено як ухвалені;
DD-06 залишається пропозицією для командного огляду, її статус не підмінено.

Матеріали Obsidian використано як обґрунтування, а не джерело нових продуктових порогів:

- [Лекція 3](https://ssdm-2026.cs-courses.org/lectures/lecture03-full.html), шари:
  чисті моделі/правила відділено від HTTP та SQL-адаптера.
- [Лекція 4 §3.4–3.5](https://ssdm-2026.cs-courses.org/lectures/lecture04-full.html):
  Pydantic-валидація, 429/Retry-After і зрозумілі машинні помилки RFC 9457.
- [Лекція 5 §3.2, §4.4, §5](https://ssdm-2026.cs-courses.org/lectures/lecture05-full.html):
  fail closed, використання бібліотек, оновлення документації разом із кодом.
- [Лекція 6 §4–5](https://ssdm-2026.cs-courses.org/lectures/lecture06-full.html):
  окремі модульні, API та інтеграційні перевірки. Цей етап не видається за новий
  історичний RED/GREEN-цикл Лаб6; матеріали здачі не перезаписано.

Технічні параметри звірено з
[argon2-cffi](https://argon2-cffi.readthedocs.io/en/stable/api.html) та
[OWASP про сесії](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html).

## Контракт і зберігання

Реєстрація повертає 201 і публічні поля користувача, без пароля/хеша/сесії.
Вхід повертає user, csrf_token, expires_at; raw-токен входу тільки в HttpOnly
cookie unislot_session. Друга cookie unislot_csrf доступна UI для CSRF-заголовка.
Токени не пишуться в localStorage, відповіді /me, аудит чи журнал доступу.
Після виходу поточний токен відкликається, інші пристрої залишаються активними.
Повторний вхід змінює поточні session і CSRF; старі токени більше не працюють.

Міграція 0003 додає поля Auth до app_user, таблицю session і допоміжну
auth_login_attempt для невідомих адрес. Ключ останньої — хеш нормалізованої адреси,
це псевдонімізовані ПД, не анонімізація. Відомі користувачі мають лічильник саме
app_user. Оновлено data-model.md та поля діаграми; csrf_hash/locked_until — явні
розширення для THR-13/FR-006. Паролі зберігаються лише як Argon2id NOT NULL.
Історичні синтетичні користувачі не отримують відомого парольного входу.

Відмова входу повертається із сервісу як результат; маршрут будує problem+json
без винятку до commit. Завдяки цьому 401/429 не відкочують лічильник невдалих входів.
Помилка запису сесії, навпаки, відкочує транзакцію та зберігає попередню сесію.

## Запуск і перший адміністратор

Після встановлення requirements-dev.txt, із кореня репозиторію:

```powershell
.\.venv\Scripts\python.exe scripts/manage_db.py local-init
.\.venv\Scripts\python.exe scripts/manage_db.py migrate --env-file .env.migrations.local
.\.venv\Scripts\python.exe scripts/create_admin.py --env-file .env.local --email admin@example.com --full-name 'Initial Administrator'
.\.venv\Scripts\python.exe -m uvicorn api.main:app --app-dir src --env-file .env.local --port 3000
```

У create_admin пароль вводиться двічі приховано; його немає в аргументах командного
рядка чи коді. Використайте свою адресу й пароль. Команда одноразова, записується
в аудит; повтор не перезаписує адміністратора. Наявний синтетичний admin повторно
використовується, зберігаючи FK аудиту й захист останнього адміністратора.
Команда підготовлена й протестована на ізольованій БД; особистий пароль користувача
в робочій локальній БД не встановлювався автоматично.

Для звичайного студента викличте register і login через Swagger /api-docs або UI.
Cookie після login зберігає браузер автоматично; для зміни скопіюйте csrf_token
в поле X-CSRF-Token. Кнопка Authorize потрібна лише для явно ввімкненого demoBearer.
local-init зберігає наявні дані й явно додає UNISLOT_SESSION_COOKIE_SECURE=0 у .env.local для HTTP
на своєму комп'ютері. У .env.example і налаштуваннях за замовчуванням Secure=1.
Для перевірки лише реальних сесій задайте UNISLOT_DEMO_AUTH=0 у локальному env.

| Змінна | Поточне значення за замовчуванням | Статус |
|---|---|---|
| UNISLOT_LOGIN_MAX_FAILURES | 5 | тимчасова конфігурація, OQ-001 не закрито |
| UNISLOT_LOGIN_COOLDOWN_SECONDS | 300 | тимчасова конфігурація, OQ-001 не закрито |
| UNISLOT_SESSION_TTL_SECONDS | 28800 | тимчасовий абсолютний TTL, AQ-06 не закрито |
| UNISLOT_SESSION_COOKIE_SECURE | 1 | local-init задає 0 лише для loopback HTTP |

## Перевірки й межі

Фінальний повний локальний прогін: **584 passed**, 87,91 с; покриття рядків і гілок
api + unislot — **98,44%**, поріг 90% збережено. Код працює на Windows 10,
Python 3.13.13, PostgreSQL 16. Тести перевіряють підвищення ролі через реєстрацію,
унікальність без регістру, Unicode/довгі паролі, cookie/CSRF, ротацію, відкликання,
строк дії, тимчасове блокування, збереження стану та rollback на справжній БД.
Із восьми конкурентних реєстрацій однієї адреси створюється одна.
Усі 13 локальних воріт у checks.json завершилися кодом 0: pytest, Ruff, формат,
Bandit, вимоги, простежуваність, strict-архітектура/PlantUML, import-linter,
OpenAPI, pip check, pip-audit, whitespace та detect-secrets. У baseline додано
тільки перевірений штучний пароль прикладу OpenAPI; тестові значення позначено
точковими allowlist-коментарями. Продуктових паролів за замовчуванням немає,
сканування файлів і плагіни не вимикалися.
Аудит установленого середовища з новими залежностями: No known vulnerabilities found.

Артефакти — Midterm_features_2026-10-31/password-auth поза репозиторієм.
Автотести нових вимог дозволили прибрати сім застарілих винятків RTM §7;
це не означає закриття питання OQ-001 чи готовність усього продукту.

Залишкові межі: адреса не підтверджується (C-002), немає password reset/MFA,
мережевого rate limit та автоматичного очищення прострочених сесій/невідомих адрес.
Тимчасовий cooldown зменшує перебір, але не вирішує повністю цільове блокування
чужого запису — саме це лишається у OQ-001. Idle timeout не реалізовано.
Auth використовує перехідний транзакційний адаптер попереднього етапу; повне
перенесення всіх сценаріїв у модульні repository/application порти та цілі PERF
не заявляються. Cookie Secure=0 допустимі лише для локального HTTP-демо.

Матеріали Лаб8, версія API, релізи й теги не змінювалися.

## Використання ШІ

Codex підготував код, тести, міграцію та документацію; джерела й локальні перевірки
наведено вище. Незалежне командне рев'ю та ручний внесок іншого учасника не заявляються.
