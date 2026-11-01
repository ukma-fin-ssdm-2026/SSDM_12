# Публічне розгортання UniSlot на Render

> **Стан:** конфігурацію підготовлено локально; Render-сервіс ще не створено, URL API
> немає. Секрети й облікові дані в репозиторій не додавати. Публічні посилання на API
> і відео додаються після фактичного розгортання та запису.

GitHub Pages публікує статичні файли й не виконує Python/FastAPI. Тому на сторінці
`ukma-fin-ssdm-2026.github.io/SSDM_12/` залишається Swagger-документація, а API, база та
Worker мають працювати на окремому хостингу. Для цього підготовлено кореневий
[`render.yaml`](../../render.yaml): нативний Python Web Service, окремий Worker і PostgreSQL 16.

## Передумови й вартість

- Web Service налаштований на Render Free: він засинає після 15 хвилин без запитів і може
  запускатися близько хвилини.
- Worker потребує план `0.5c-512mb`, який у Render є платним. Створення Blueprint створить
  цей сервіс і може спричинити оплату за тарифом акаунта. Не створюй Blueprint, доки не
  перевіриш актуальну вартість у Render Dashboard.
- Free PostgreSQL має 1 GB і стає недоступним через 30 днів після створення. Після
  додаткового 14-денного пільгового періоду Render видаляє базу. Для короткої демонстрації
  цього може вистачити; для постійного використання потрібен тариф зі збереженням даних.
- Render підтримує нативний Python runtime, але не надає безкоштовного плану для Background
  Worker. Документація: [FastAPI](https://render.com/docs/deploy-fastapi),
  [worker plans](https://render.com/docs/compute-plans),
  [free services](https://render.com/docs/free).

## Порядок налаштування

Виконуй кроки після того, як гілка з `render.yaml` буде схвалена та злита в `main`.
Наразі ці файли лише локальні.

### 1. Створи PostgreSQL

У Render Dashboard створи PostgreSQL зі значеннями, що відповідають `render.yaml`:

- Name: `unislot-midterm-db`
- Database: `unislot`
- User: `unislot_owner`
- Version: PostgreSQL 16
- Region: Frankfurt
- Plan: Free для короткої демонстрації або потрібний платний план

Збережи зовнішній URL власника лише локально. Якщо створиш БД перед Blueprint з тими самими
ім'ям і параметрами, Blueprint підхопить наявний ресурс.

### 2. Створи окрему runtime-роль

Відкрий зовнішнє PostgreSQL-з'єднання власника через `psql` із власного комп'ютера. На
сторінці БД Render спочатку обмеж IP allowlist адресою свого комп'ютера, якщо можеш.
У `psql` виконай:

```sql
CREATE ROLE unislot_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
\password unislot_app
```

`\password` запросить пароль без його показу. Використай випадковий довгий пароль; якщо в
URL він містить зарезервовані символи, URL-кодуй пароль. Якщо Render не дозволяє створити
окрему звичайну роль, не підставляй роль-власника замість неї: код навмисно відхиляє
власника БД при запуску API.

### 3. Застосуй міграції

Використай зовнішній URL власника для одноразових міграцій. Схему секретного файла:

```text
UNISLOT_ADMIN_DATABASE_URL=postgresql+psycopg://unislot_owner:<пароль>@<зовнішній-хост>:5432/unislot?sslmode=require
UNISLOT_APP_ROLE=unislot_app
```

Збережи цей файл у корені локальної копії як `.env.migrations.render`. Шаблон `.gitignore`
вже ігнорує `.env.*`; ніколи не додавай файл у Git. Із кореня репозиторію запусти:

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/manage_db.py migrate --env-file .env.migrations.render
```

Для подальших релізів із новими міграціями виконуй цю команду до оновлення сервісів.
Owner URL використовується тільки міграціями, не API і не Worker.

### 4. Створи Blueprint та додай runtime URL

У Render Dashboard обери **New → Blueprint**, під'єднай `ukma-fin-ssdm-2026/SSDM_12`
і гілку `main`. На першому створенні введи secret `UNISLOT_DATABASE_URL` для API.
Використай внутрішній URL бази в тому самому регіоні та облікові дані `unislot_app`:

```text
postgresql+psycopg://unislot_app:<пароль>@<внутрішній-хост>:5432/unislot
```

Worker отримає той самий secret з Web Service через посилання в Blueprint. Не передавай
`UNISLOT_ADMIN_DATABASE_URL` сервісам. Render питає `sync: false` secret під час першого
створення Blueprint; нові secrets при наступному оновленні додаються у Dashboard вручну.

У Blueprint передбачено:

- `UNISLOT_DEMO_AUTH=0` — відкриті demo-токени відхиляються;
- `UNISLOT_SESSION_COOKIE_SECURE=1` — Secure cookie для HTTPS;
- `UNISLOT_EXPORT_OPENAPI=0` — процес сервера не змінює файли репозиторію;
- `GET /health` — health check;
- UI на `/`, Swagger UI на `/api-docs`.

### 5. Створи адміністратора й підготуй демо

Після успішного розгортання збережи внутрішній або зовнішній runtime URL окремо в
ігнорованому локальному `.env.render.local`:

```text
UNISLOT_DATABASE_URL=postgresql+psycopg://unislot_app:<пароль>@<хост>:5432/unislot
```

Для локального створення першого адміністратора можна використати зовнішній URL тієї ж
runtime-ролі:

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/create_admin.py --env-file .env.render.local --email admin@example.invalid --full-name "Demo Administrator"
```

Пароль вводиться приховано в терміналі. Увійди в UI, створи синтетичний акаунт провайдера,
признач йому роль через адміністративний кабінет, додай ресурс та слоти; окремо створи
студента для демонстрації пошуку, бронювання, скасування/перенесення й відмов 401/403/409.
Не використовуй реальні персональні дані.

### 6. Перевір і зафіксуй адресу

Після стану **Live** відкрий:

- `https://<render-service>.onrender.com/health` — має повернути `{"status":"ok"}`;
- `https://<render-service>.onrender.com/` — Web UI;
- `https://<render-service>.onrender.com/api-docs` — Swagger UI.

Після фактичної перевірки внеси адресу сервісу до README та заміни TODO в
[`Labs/midterm-presentation.txt`](../../Labs/midterm-presentation.txt) на справжнє
посилання на відео 4–5 хвилин. Сам файл конфігурації не є доказом розгортання.

## Межі підготовленого

`render.yaml` описує цільові сервіси, але не створює їх у Render і не виконує публічну
перевірку. Поки немає фактичного URL, успішного `/health`, перевірки трьох ролей та
записаного відео, публічний запуск і вимога до демонстрації залишаються незакритими.
