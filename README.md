# UniSlot — система бронювання консультацій та аудиторій

[![CI](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/workflows/ci.yml)

Навчальний проєкт команди **SSDM_12** у курсі «Методи розробки програмних систем»
(НаУКМА, факультет інформатики, осінь 2026).

UniSlot — вебсистема, у якій викладач або відповідальний за аудиторію публікує доступний
час, студент знаходить і бронює вільний слот, а адміністратор керує ресурсами, ролями та
політиками бронювання. Система гарантує відсутність накладок навіть за одночасних спроб
бронювання, надсилає нагадування та веде журнал аудиту адміністративних дій.

## Документи проєкту

| Документ | Що всередині |
|---|---|
| [`Project-Description.md`](Project-Description.md) | Опис ідеї, ролі користувачів, ключові функції, міні-ТЗ за шістьма пунктами |
| [`TeamCharter.md`](TeamCharter.md) | Командний статут: ролі, комунікація, робочий процес, правила використання ШІ, підписи |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Робочий процес завдань, гілок, комітів і Pull Requests |

## Артефакти вимог (Лаб 2)

| Документ | Що всередині |
|---|---|
| [`docs/requirements/requirements.md`](docs/requirements/requirements.md) | Призначення й межі, глосарій, зацікавлені сторони, функціональні вимоги FR-001…FR-068, нефункціональні вимоги за ISO/IEC 25010, припущення й обмеження, реєстр ризиків, зміни відносно міні-ТЗ, журнал валідації |
| [`docs/requirements/user-stories.md`](docs/requirements/user-stories.md) | Користувацькі історії US-001…US-014 з критеріями приймання у форматі Given/When/Then і перевіркою за INVEST |
| [`docs/requirements/rtm.md`](docs/requirements/rtm.md) | Матриця простежуваності: історія → вимога → компонент → тестовий випадок, зворотне покриття за NFR |

**Як читати разом.** Історія в `user-stories.md` описує потребу користувача,
`requirements.md` перетворює її на перевірні твердження, `rtm.md` показує,
що жодна вимога не загубилась і де саме кожну перевірятимуть.

Ідентифікатори наскрізні для всіх трьох файлів: `BN-###` — бізнес-потреба,
`US-###` — історія, `FR-###` — функціональна вимога, `PERF`/`REL`/`SEC`/`MAINT`/`USAB`/`PORT-###` —
нефункціональна, `A-###` і `C-###` — припущення й обмеження, `R-###` і `OQ-###` —
ризик і відкрите питання, `TC-###` — тестовий випадок. Конвенції й діапазони —
на початку [`requirements.md`](docs/requirements/requirements.md).

## Архітектура (Лаб 3)

| Документ | Що всередині |
|---|---|
| [`docs/architecture/high-level-design.md`](docs/architecture/high-level-design.md) | Архітектурний огляд: драйвери, стиль, компоненти, інтерфейси, шари, розгортання, проєктні рішення DD-01…DD-18, відкриті питання |
| [`docs/architecture/traceability-matrix.md`](docs/architecture/traceability-matrix.md) | Вимога → компонент → проєктне рішення → метод верифікації для всіх FR і NFR; сценарії атрибутів якості QAS-01…QAS-04 |
| [`docs/architecture/data-model.md`](docs/architecture/data-model.md) | ER-модель, інваріанти цілісності, класифікація персональних і чутливих даних |
| [`docs/architecture/threat-model.md`](docs/architecture/threat-model.md) | STRIDE над діаграмою розгортання: межі довіри TB1–TB5, реєстр загроз, прийняті ризики |
| [`docs/architecture/decisions/`](docs/architecture/decisions/) | ADR-001 стиль · ADR-002 відсутність подвійних бронювань · ADR-003 сповіщення через outbox |
| [`docs/architecture/uml/`](docs/architecture/uml/) | Діаграми PlantUML: компоненти (два рівні), послідовність (два сценарії), розгортання, ER-модель, діяльність |
| [`docs/architecture/validation/`](docs/architecture/validation/) | Доказ спайка ADR-002: скрипти, журнали прогонів і результати перевірки інваріантів на PostgreSQL |

**Як читати разом.** `high-level-design.md` — вхідна точка; матриця простежуваності
показує, що кожна вимога з `docs/requirements/` має компонент і спосіб перевірки;
ADR пояснюють, чому рішення саме такі; модель загроз дивиться на ту саму систему очима
зловмисника.

**Перевірка узгодженості:** `python3 scripts/check_requirements.py` (вимоги) і
`python3 scripts/check_architecture.py` (архітектура; з `--plantuml шлях/до/plantuml.jar`
— ще й синтаксис діаграм, з `--strict` — ще й незаповнені місця `‹…›` у нотатках ШІ).
Обидва скрипти працюють у конвеєрі CI (job `build`, issue #83).

## API (Лаб 4)

REST API UniSlot на FastAPI за підходом **Code-First**: специфікацію OpenAPI генерує код, вручну
її не пишуть і не правлять. Бізнес-логіки модулів ще немає — кінцеві точки відповідають з
демо-даних у пам'яті (заглушки), але правила бронювання вже перевіряються.

| Що | Де |
|---|---|
| Код API з анотаціями | [`src/api/`](src/api/): роутери за модулями — `routers/`, схеми — `schemas/`, заглушки — `stubs/` |
| Специфікація OpenAPI (згенерована) | [`docs/api/openapi-generated.yaml`](docs/api/openapi-generated.yaml) |
| Swagger UI на GitHub Pages | https://ukma-fin-ssdm-2026.github.io/SSDM_12/ — оновлюється на кожен push у `main` |
| Каталог помилок | [`docs/api/errors.html`](docs/api/errors.html) — на нього веде поле `type` кожної помилки |
| Проєктні рішення API | [`docs/api/api-design.md`](docs/api/api-design.md): ресурси, коди стану, помилки, пагінація, версіонування, безпека |
| Атрибути якості API | [`docs/api/quality-attributes.md`](docs/api/quality-attributes.md): цілі з умовами провалу й компроміси |
| Тести | [`tests/api/`](tests/api/) — контракт специфікації й кожна кінцева точка |

### Запуск на своєму комп'ютері

Потрібен Python 3.12 або новіший. Команди — з кореня репозиторію.

macOS або Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
export UNISLOT_DEMO_AUTH=1        # демо-токени діють лише з цією змінною (V-01)
uvicorn api.main:app --app-dir src --reload --port 3000
```

Windows (PowerShell; якщо активацію заблоковано — спершу
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`):

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
$env:UNISLOT_DEMO_AUTH = "1"      # демо-токени діють лише з цією змінною (V-01)
uvicorn api.main:app --app-dir src --reload --port 3000
```

Далі відкрийте http://localhost:3000/api-docs → **Authorize** → введіть демо-токен
`demo-student` (або `demo-student-2`, `demo-provider`, `demo-provider-2`, `demo-admin`) →
**Try it out**. Демо-токени — заглушка автентифікації Лаб 4, а не секрети. Саме тому
сервер, запущений без `UNISLOT_DEMO_AUTH=1`, їх не приймає й відповідає `401`: інакше
будь-хто з токеном `demo-admin` із цього README став би адміністратором
(V-01, [`static-analysis.md`](docs/code-quality/static-analysis.md)).

**Як код оновлює документацію.** Під час кожного старту сервера — і кожного автоматичного
перезапуску `--reload` після збереження `.py`-файлу — застосунок перезаписує
`docs/api/openapi-generated.yaml` і `docs/api/errors.html`. Змінені файли комітьте разом із
кодом: CI перевіряє, що закомічена специфікація збігається з тією, яку генерує код.

### Тести й генерація без сервера

```bash
python -m pytest                              # тести API
python scripts/export_openapi.py              # перегенерувати docs/api/ з коду
python scripts/export_openapi.py --check      # чи збігається docs/api/ з кодом
```

### Як документація потрапляє на GitHub Pages

На кожен push у `main`, що змінює `src/api/` чи `docs/api/`, конвеєр
[`api-docs.yml`](.github/workflows/api-docs.yml) генерує специфікацію з коду цього коміту й
публікує Swagger UI. Сторінка на Pages — для перегляду; запити надсилайте з локального
Swagger UI.

### MCP-сервер для агента (бонус)

[`src/api/mcp_server.py`](src/api/mcp_server.py) перетворює кожну кінцеву точку на інструмент
MCP (FastMCP): назва — `operationId`, опис і параметри — з тих самих анотацій, що й Swagger UI.
Сервер викликає застосунок напряму, тож окремо запускати API не треба.

```bash
pip install -r requirements-mcp.txt          # у тому самому .venv
python src/api/mcp_server.py                 # перевірка: сервер чекає на stdin, Ctrl+C — вихід
npx @modelcontextprotocol/inspector python src/api/mcp_server.py   # список інструментів у браузері
```

Щоб підключити до агента (Claude, Cursor, Copilot), додайте в його налаштування MCP
stdio-сервер — розділ про MCP у документації агента. Типовий запис, шляхи — абсолютні:

```json
{
  "mcpServers": {
    "unislot": {
      "command": "/шлях/до/SSDM_12/.venv/bin/python",
      "args": ["/шлях/до/SSDM_12/src/api/mcp_server.py"],
      "env": {"UNISLOT_MCP_TOKEN": "demo-student"}
    }
  }
}
```

Агент діє від імені демо-користувача з `UNISLOT_MCP_TOKEN` (за замовчуванням `demo-student`).
Приклад завдання: «Які аудиторії вільні завтра? Забронюй найранішу».

## Артефакти тестування

| Документ | Що всередині |
|---|---|
| [`docs/testing/coverage-report.md`](docs/testing/coverage-report.md) | Активність «Test-a-Thon»: підключення JaCoCo й пороги покриття, базовий стан, аналіз прогалин за класами, склад 119 доданих модульних тестів, знахідки F-1…F-8 |
| [`docs/testing/debugging-log.md`](docs/testing/debugging-log.md) | Челендж зі структурованого налагодження: правила вправи, журнал сесії за кроками, першопричина дефекту B-01, регресійні тести, розбір польотів, довідник прийомів |

**Як читати разом.** `coverage-report.md` показує, де тестів не було і чим ці прогалини
закрито; `debugging-log.md` бере одну з цих прогалин і доводить її ціну на конкретному
дефекті — помилці пагінації, яку наявний набір тестів пропускав повністю.

Обидва документи стосуються чужої кодової бази
([`Spectrum-project`](https://github.com/ukma-fin-ssdm-2026/Spectrum-project),
комміт `43da8d7`) — як і [`docs/code-quality/review-report.md`](docs/code-quality/review-report.md).

## Команда

| Учасник | GitHub | Роль у команді |
|---|---|---|
| Никита Бабаков | [@NykytaBabakov](https://github.com/NykytaBabakov) | Repo Maintainer, Documentation Lead |
| Павло Дзюбак | [@DziubakPavlo](https://github.com/DziubakPavlo) | CI Maintainer |
| Аксенія Козуліна | [@asyakozulina](https://github.com/asyakozulina)  | Issue Tracker Lead |
| Денис Пацеля |  [@dysett](https://github.com/dysett) | Project Brief Lead |

Детальні зони відповідальності — у [командному статуті](TeamCharter.md), розділ 2.

## Структура репозиторію

```
SSDM_12/
├── .github/workflows/      # CI (ci.yml) і публікація документації API на Pages (api-docs.yml)
├── docs/
│   ├── requirements/       # вимоги, користувацькі історії, матриця простежуваності
│   │   ├── requirements.md
│   │   ├── user-stories.md
│   │   └── rtm.md
│   ├── architecture/       # архітектура (Лаб 3)
│   │   ├── high-level-design.md
│   │   ├── traceability-matrix.md
│   │   ├── data-model.md
│   │   ├── threat-model.md
│   │   ├── decisions/      # ADR-001…ADR-003
│   │   ├── uml/            # діаграми PlantUML (.puml)
│   │   └── validation/     # доказ спайка ADR-002
│   ├── api/                # API (Лаб 4)
│   │   ├── api-design.md
│   │   ├── quality-attributes.md
│   │   ├── openapi-generated.yaml   # згенеровано з коду
│   │   ├── errors.html              # згенеровано з коду
│   │   └── index.html               # Swagger UI для GitHub Pages
│   ├── code-quality/       # звіт рецензування коду
│   └── testing/            # звіт про покриття, журнал налагодження
│       ├── coverage-report.md
│       ├── debugging-log.md
│       └── debug-challenge/    # патч навмисного дефекту для повтору вправи
├── src/
│   └── api/                # REST API (FastAPI): routers/, schemas/, stubs/
├── tests/
│   └── api/                # тести API
├── scripts/                # перевірки вимог і архітектури, генерація OpenAPI, вимір затримки
├── Labs/                   # посилання на індивідуальні відео за лабораторними
├── requirements.txt        # залежності API (версії закріплено)
├── requirements-dev.txt    # залежності API + тести
├── requirements-mcp.txt    # залежності API + MCP-сервер (бонус)
├── pyproject.toml          # налаштування pytest
├── README.md
├── TeamCharter.md
├── Project-Description.md
├── CONTRIBUTING.md
└── .gitignore
```

Каталоги `docs/` наповнюються поступово: `requirements/` — Лаб 2, `architecture/` — Лаб 3,
`api/` — Лаб 4, `code-quality/` і `testing/` уже наповнені, далі додаються `validation/`,
`refactoring/`, `reliability/`, `ci-cd/`.

## Технологічний стек

| Шар | Вибір |
|---|---|
| Мова, фреймворк | Python 3.12, FastAPI |
| Доступ до даних | SQLAlchemy 2.x, Alembic |
| База даних | PostgreSQL 16 |
| Тестування | pytest, pytest-cov |
| Якість коду | Ruff, Bandit, SonarCloud |
| CI/CD | GitHub Actions |
| Середовище | Docker Compose |

Обґрунтування вибору — у [`Project-Description.md`](Project-Description.md), §2.6.

## Робочий процес

Робота йде за GitHub Flow: гілка функції від `main` → Pull Request → щонайменше одне
схвалення → злиття. Прямий push у `main` заблоковано захистом гілки. Автор не мерджить
власний PR. Повні правила — у [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Використання ШІ

Команда використовує інструменти ШІ відповідно до [Політики використання ШІ](https://ssdm-2026.cs-courses.org/ai-policy.html)
курсу: розкрито, верифіковано, під відповідальність автора. Правила команди — у
[статуті](TeamCharter.md), розділ 8; кожен суттєвий артефакт містить нотатку «Використання ШІ».

- **Оновлення для Лаб 2:** розділ «Артефакти вимог» і оновлене дерево структури — чернетка з Claude (Anthropic); склад таблиці звірено з фактичним вмістом `docs/requirements/`, усі три посилання перевірено клацанням після злиття.
- **Оновлення для Test-a-Thon:** розділ «Артефакти тестування» і доповнене дерево структури — чернетка з Claude (Opus 5); склад таблиці звірено з фактичним вмістом `docs/testing/`, обидва посилання перевірено після злиття. Нотатки про використання ШІ є всередині кожного з двох документів.
- **Оновлення для Лаб 3:** розділ «Архітектура (Лаб 3)» і розгорнуте дерево `docs/architecture/` — чернетка з Claude (Anthropic); склад таблиці звірено з фактичним вмістом каталогу, усі посилання перевірено клацанням після злиття документів Лаб 3.
- **Оновлення для Лаб 4:** розділ «API (Лаб 4)» і дерево `src/api/`, `docs/api/` — чернетка з Claude (Anthropic). Команди запуску виконав сам на macOS 26, Python 3.14.5; склад таблиці звірено з фактичним вмістом `docs/api/`, усі посилання перевірено клацанням після злиття документів Лаб 4.
- **MCP-сервер (бонус Лаб 4):** `src/api/mcp_server.py` і розділ «MCP-сервер для агента» — чернетка з Claude (Anthropic). Перевірив сам клієнтом FastMCP у пам'яті, без агента (macOS 26, Python 3.14.5): `pip install -r requirements-mcp.txt` поставив `fastmcp 4.1.0` з `fastmcp-slim` і `mcp 2.3.0`, усе з готових wheels під `cp314`; сервер піднявся, у списку **14 інструментів** із назвами, що дорівнюють `operationId` специфікації. `get_me` повернув демо-студентку з роллю `student` — отже токен із `UNISLOT_MCP_TOKEN` доходить до застосунку; `search_free_slots` повернув слоти з полями `resource` і `provider` (перший — «Аудиторія 1-225», 90 хвилин). У журналі застосунку обидва виклики видно як `GET /api/v1/auth/me` і `GET /api/v1/slots` зі статусом 200: інструменти справді звертаються до кінцевих точок API, а не до окремої реалізації. Розбіжностей не виявив.

### Нотатка про цей документ

- **Згенеровано:** структура README і чернетка формулювань.
- **Інструмент:** Claude (Opus 5), веб-інтерфейс.
- **Верифікація:** дерево структури звірено з фактичним станом репозиторію; усі
  внутрішні посилання перевірено після злиття документів; таблицю технологічного
  стеку звірено з розділом 2.6 `Project-Description.md`.
- **Заповнено вручну:** склад команди, GitHub-логіни, розподіл ролей.

## Ліцензія

Навчальний проєкт. Питання ліцензування опрацьовується в межах Лабораторної 11
(професіоналізм, етика, правові аспекти).
