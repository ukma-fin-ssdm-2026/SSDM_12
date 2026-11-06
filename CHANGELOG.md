# Журнал змін UniSlot

Усі помітні зміни продукту записуємо тут. Формат — [Keep a Changelog 1.1.0](https://keepachangelog.com/uk/1.1.0/),
нумерація — [семантичне версіювання 2.0.0](https://semver.org/lang/uk/). Номер версії однаковий у
`pyproject.toml` (`[project].version`), у заголовку розділу нижче й у git-тегі `vX.Y.Z`; це перевіряє
`python scripts/release.py check` на кожен PR.

Категорії — шість стандартних (`Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`, `Security`) і
`Refactoring` для змін структури без зміни поведінки (умова Лаб 8). Записи — для того, хто
користується продуктом чи кодом, а не для автора: що змінилося й навіщо, а для рефакторингу — ще
й техніка з каталогу. Версія контракту API (`API_VERSION`, `info.version` = `1.0.0-alpha.1`) —
окрема: її змінює лише зміна контракту, див. `docs/api/api-design.md` §4.9.

## [Unreleased]

## [0.1.1] - 2026-11-06

### Refactoring

- Replace the nested report closure with a Report object (`scripts`)
- Extract the artifact, diagram, matrix and reference checks (`scripts`)
- Extract the threat, ADR, scenario, data model and slot checks (`scripts`)
- Rename _declared to is_declared for clarity (`scripts`)
- Name the flush table order and extract the audit append (`store`)
- Extract delete and upsert steps from PostgresStore.flush (`store`)
- Extract stale slot withdrawal from template generation (`availability`)
- Extract slot lookup, overlap conflicts and publishing from _generate (`availability`)
- Extract the 503 and problem media type steps from custom_openapi (`openapi`)
- Extract CSRF documentation and name the unsafe methods (`openapi`)

### Fixed

- Make run_lab06.py console-encoding safe on Windows (`scripts`)
- Keep forward slashes in check_architecture.py output on Windows (`scripts`)

### Security

- Accept only an existing .jar for check_architecture --plantuml (`security`)
- Keep export_openapi --out-dir inside the repository (`security`)
- Restrict regression XML inputs to working directory (`security`)

## [0.1.0] - 2026-11-05

Перша записана версія. Номера раніше не було: за умовою Лаб 8 поточний стан записано як `0.1.0`, а
рефакторинг Лаб 8 вийде як `0.1.1`.

### Added

- REST API `/api/v1` (FastAPI, Code-First): пошук вільних слотів із фільтрами й курсором,
  бронювання з ключем ідемпотентності, скасування й перенесення за доменними правилами.
- Реєстрація та вхід із паролями (Argon2id), cookie-сесія з токеном CSRF; демо-токени — лише з
  `UNISLOT_DEMO_AUTH=1`.
- Кабінети студента, провайдера й адміністратора у вебінтерфейсі.
- Тижневі шаблони доступності, блокування часу з причиною, календар і завантаження ресурсу.
- Керування ролями й політиками бронювання; незмінний журнал аудиту.
- Сповіщення через outbox і окремий фоновий процес із повторами.
- Зберігання в PostgreSQL з міграціями; обмеження цілісності бронювань на рівні бази даних.
- Специфікація OpenAPI та каталог помилок RFC 9457, згенеровані з коду; MCP-сервер з API.

### Refactoring

- Пошук вільних слотів: `search_free` розкладено на іменовані перевірки фільтра, курсора й
  нарізання сторінки — *Extract Method* ×3 і *Decompose Conditional*; когнітивна складність 23 → 10
  (Лаб 8, цикл 1, #196).
- Відповідь 422 з помилками полів збирає один конструктор `validation_problem()` замість п'яти
  копій літерала — *Extract Method*; тіло відповіді не змінилося (Лаб 8, цикл 1, #196).
- Перевірки місткості в `update_resource` винесено у дві функції зі збереженням порядку
  перевірок — *Extract Method* ×2; когнітивна складність 11 → 4 (Лаб 8, цикл 1, #196).

[Unreleased]: https://github.com/ukma-fin-ssdm-2026/SSDM_12/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/ukma-fin-ssdm-2026/SSDM_12/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/ukma-fin-ssdm-2026/SSDM_12/releases/tag/v0.1.0
