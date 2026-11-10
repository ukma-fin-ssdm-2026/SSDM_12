# Докази до Лаб 10: історія запусків конвеєра

Тут збережено 104 запуски `CI` з [`metrics-raw.md`](../metrics-raw.md) за 19.10–08.11.2026
включно за UTC. JSON отримано через GitHub REST API. Нижче наведено еквівалентні команди
`gh` для відтворення. SHA скорочено до 7 символів, унікальних у цій вибірці,
щоб уникнути спрацювання detect-secrets на повні хеші.

| Файл | Що в ньому | Як відтворити |
|---|---|---|
| `runs-main-ci.json` | 104 запуски `CI` на `main` з подією `push`: номер і ID запуску, коміт, висновок, **номер спроби** (`attempt`), моменти створення, старту й оновлення, посилання | `gh run list` (команда нижче) |
| `reruns.json` | обидва запуски з повторною спробою (№40, №56): висновок і моменти **кожної** спроби | `gh api …/actions/runs/<id>/attempts/<n>` |
| `red-runs.json` | jobs, анотації та доступні рядки `##[error]` для 8 невдалих спроб на `main`. Причину №86 видно в журналі job, анотація містить лише «The operation was canceled» | `gh api …/attempts/<n>/jobs`, `…/check-runs/<job_id>/annotations`, `…/actions/jobs/<job_id>/logs` |
| `screenshots/` | [Історія CI на `main`](screenshots/01-main-ci-runs.png), [дві спроби №40](screenshots/02-run-40-attempts.png), [помилка диска №58](screenshots/03-run-58-disk-space.png) | знімки екрана GitHub Actions |

Набір даних для автономного перерахунку DORA належить до PR‑04.

## Як отримати ще раз

```bash
# 1. усі запуски CI на main за вікно Етапу 1 (дати — UTC, обидві включно)
gh run list --repo ukma-fin-ssdm-2026/SSDM_12 --workflow CI --branch main --event push \
  --created 2026-10-19..2026-11-08 --limit 200 \
  --json number,databaseId,headSha,conclusion,status,attempt,createdAt,startedAt,updatedAt,url,displayTitle \
  --jq 'map(.headSha |= .[0:7])' > docs/ci-cd/evidence/runs-main-ci.json

# 2. запуски, що мали повторну спробу
gh run list --repo ukma-fin-ssdm-2026/SSDM_12 --workflow CI --branch main --event push \
  --created 2026-10-19..2026-11-08 --limit 200 --json databaseId,attempt \
  --jq '.[] | select(.attempt > 1) | .databaseId'

# 3. кожна спроба такого запуску
gh api repos/ukma-fin-ssdm-2026/SSDM_12/actions/runs/40672926847/attempts/1 \
  --jq '{run_attempt, conclusion, run_started_at, updated_at, triggering_actor: .triggering_actor.login}'

# 4. червона спроба: спершу ID її jobs, потім анотації й рядки помилок з логу кожного job
gh api repos/ukma-fin-ssdm-2026/SSDM_12/actions/runs/<run_id>/attempts/<n>/jobs \
  --jq '.jobs[] | {id, name, conclusion, started_at, completed_at}'
gh api repos/ukma-fin-ssdm-2026/SSDM_12/check-runs/<job_id>/annotations --jq '.[] | {message, annotation_level}'
gh api repos/ukma-fin-ssdm-2026/SSDM_12/actions/jobs/<job_id>/logs | grep '##\[error\]'
```

Для шести невдалих спроб із втратою зв’язку з раннером endpoint логів повернув
`HTTP 404`. Причини цих збоїв видно в анотаціях. Для №58 і №86 збережено
також рядки помилок із логів. У JSON результат запиту до логу вказано в полі
`log_status`.

У `runs-main-ci.json` 104 записи — 96 `success`, 6 `failure`, 2 `cancelled`.
Рівно два запуски мають `attempt` = 2. У `red-runs.json` збережено 8 невдалих
спроб, включно з першими спробами №40 і №56.
