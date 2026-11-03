# Докази RED/GREEN: планування нагадувань

Власник: @dysett, аналітик якості Лаб 7. Реалізація — [PR #232](https://github.com/ukma-fin-ssdm-2026/SSDM_12/pull/232),
доповнення документації після злиття — [issue #233](https://github.com/ukma-fin-ssdm-2026/SSDM_12/issues/233).
Вимоги: FR-051, FR-054, A-004; тест-план: [TP-12 і TP-13](../../test-plan.md).

## Походження файлів

| Файл | Що містить |
|---|---|
| [agent-prompt.txt](agent-prompt.txt) | Основний запит, переданий агенту перед реалізацією; технічні умови запуску наведено в журналі |
| [iteration-log.md](iteration-log.md) | Фактичний перебіг: один раунд змін коду, три прогони pytest загалом; обмеження й ручні правки |
| [01-pytest-baseline-red.txt](01-pytest-baseline-red.txt) | Збережений локальний RED-вивід до змін: відсутній доменний модуль, exit 2 |
| [02-pytest-reminders-green.txt](02-pytest-reminders-green.txt) | Збережений локальний цільовий GREEN-вивід: 22 passed, exit 0 |
| [03-pytest-full-coverage.txt](03-pytest-full-coverage.txt) | Збережений локальний повний GREEN-вивід: 264 passed, 97,57%, exit 0 |
| [history-check.md](history-check.md) | Повторно звірені 29.10.2026 SHA, дерево тестів, прямий зв'язок RED → GREEN і батьки merge-коміту |

Три файли виводу pytest скопійовано без редагування зі збереженої локальної сесії.
Їхні заголовки «Ітерація 01/02/03» означають номери **прогонів**, а не три спроби
реалізації. Зміни коду були лише перед другим прогоном. Локальні шляхи в цих файлах
належать середовищу виконання; для запуску на іншому комп'ютері вони не потрібні.

## Незалежні від локальних журналів докази

- RED: [`06c2a44`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/commit/06c2a4458b2148425344aae7ec2d4a925e31ba78),
  [CI 40926504244](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/40926504244/job/123633325459) — тестовий крок упав через відсутній `unislot.notifications.domain`.
- GREEN: [`aa3ba4e`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/commit/aa3ba4ed02739424cc423da183ec130a24e49979),
  [CI 40933020550](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/40933020550/job/123656158437) — 264 passed, покриття 97,57%.
- `main` після #230 і #232: [`883ef7a`](https://github.com/ukma-fin-ssdm-2026/SSDM_12/commit/883ef7aaf190fbd4e480d63f5f6b71e7dfb4c7b1),
  [CI 40941948739](https://github.com/ukma-fin-ssdm-2026/SSDM_12/actions/runs/40941948739/job/123687318803) — 282 passed, покриття 97,57%, ворота простежуваності пройдено.

Покриття тут — спільна метрика pytest-cov для рядків і гілок `api` та `unislot`;
це не окреме покриття лише гілок. Десять локальних попереджень на GREEN стосувалися
ще не зареєстрованої на цій базі мітки `pytest.mark.req`; реєстрація надійшла з #230.

## Як звірити історію та повторити перевірку

З кореня актуального клону, після встановлення `requirements-testing.txt`:

```bash
git rev-parse 06c2a44:tests aa3ba4e:tests
git diff --exit-code 06c2a44 aa3ba4e -- tests
git show -s --format=%P aa3ba4e
git show -s --format=%P 883ef7a
python scripts/check_requirements.py
python scripts/check_traceability.py
python -m pytest -q tests/unit/test_reminders.py tests/api/test_booking_reminders.py
```

Перші два SHA дерев однакові, diff порожній. Батько GREEN — RED. Merge `883ef7a`
має батьків `4567041` (main із #230) та `aa3ba4e` (GREEN).
Повний набір на `883ef7a` дає 282 випадки; на самому GREEN — 264. У майбутніх комітах
кількість тестів може зрости, тому історичний результат звіряємо з відповідним SHA.
Ці команди не відтворюють нову сесію агента і не замінюють незалежний огляд.

## Перевірка цього доповнення

29.10.2026 на базі `883ef7a`, Windows, Python 3.13.13:

- `pre-commit run --all-files` — усі 9 хуків пройдено.
- `python scripts/check_requirements.py` — порушень немає.
- `python scripts/check_traceability.py` — порушень немає; 41 з 66 вимог мають тести,
  25 — свідомі винятки. Це перевірка повноти зв'язків, а не виконання всіх 66 вимог.
- `python -m pytest -q --cov=api --cov=unislot --cov-branch --cov-fail-under=90 --cov-report=term-missing`
  — 282 passed, 97,57%.
- `git diff --cached --check` — успішно; відносні посилання існують; три виводи pytest
  збігаються зі збереженими оригіналами побайтово; код і тести не змінено.

Сканер спочатку помилково визначив повні Git SHA у JSON як потенційні секрети.
Перевірку історії оформлено Markdown-таблицею з тими самими SHA; повторний прогін
успішний, baseline та налаштування сканера не змінено.

## Умови, які цей пакет не засвідчує

Наявні Approve в #232 не є заповненим контрольним списком з відповідями автора.
Повний незалежний огляд веде @asyakozulina в [issue #225](https://github.com/ukma-fin-ssdm-2026/SSDM_12/issues/225).
Особисте відео @dysett із поясненням внеску й бонусу подається через `Labs/Lab07/`
([issue #227](https://github.com/ukma-fin-ssdm-2026/SSDM_12/issues/227)). Запису відео
або завершеного огляду цей пакет не приписує.

## Використання ШІ

Тести: початкова чернетка Claude (Anthropic), доопрацювання й перевірки RED — Codex.
Реалізація: окрема сесія Codex зі свіжим контекстом; точний ідентифікатор моделі
інструмент не повернув. Текст цього доказу підготовлено з Codex за збереженими
журналами, історією Git, результатами CI й фактичними рецензіями GitHub.
