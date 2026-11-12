# CI/CD: конвеєр і його аналітика (Лаб 10)

## Що в цій теці

| Файл | Що в ньому | Хто веде |
|---|---|---|
| [`dora-summary.md`](dora-summary.md) | визначення розгортання, чотири метрики DORA з рівнями DORA 2025, орієнтири CircleCI, черга й виконання, тижнева динаміка, першопричини, план покращень, дашборд, парний аналіз, «яку біль виявили метрики», бонуси | @NykytaBabakov; §3 — @DziubakPavlo |
| [`metrics-raw.md`](metrics-raw.md) | Етап 1: 104 запуски `CI` на `main` за 19.10–09.11 — черга, виконання, PR, перший коміт PR, статус, причина й клас збою | @dysett |
| [`dora-auto.md`](dora-auto.md), `dora-auto.json` | ті самі метрики, пораховані скриптом `scripts/dora_metrics.py` (бонус 1) | @asyakozulina |
| [`evidence/`](evidence/) | докази: вивантаження `gh run list`, спроби повторних запусків, анотації червоних запусків, скриншоти, набір даних скрипта, виміри бонусів | @dysett, @asyakozulina |

## Конвеєр

| Workflow | Коли запускається | Jobs і раннер | Що робить |
|---|---|---|---|
| `CI` ([`ci.yml`](../../.github/workflows/ci.yml)) | push у `main`, кожен PR у `main`, вручну | `build` і `reliability` — завжди; `integration` — лише push у `main` і ручний запуск; усі на self-hosted `SSDM12-Windows` | вимоги й простежуваність, метадані релізу; Ruff, Bandit, detect-secrets, pip-audit, import-linter; швидкий набір тестів із порогом 78 %; OpenAPI з коду; заповненість документів; PlantUML; повільний набір на PostgreSQL 16 і поріг 90 % на обох наборах |
| `API docs` ([`api-docs.yml`](../../.github/workflows/api-docs.yml)) | push у `main` зі змінами API, вручну | `generate`, `deploy` — self-hosted | специфікація OpenAPI з коду й Swagger UI на GitHub Pages |
| `Release` ([`release.yml`](../../.github/workflows/release.yml)) | вручну (`prepare`); push у `main` зі зміною версії (`publish`) | `ubuntu-latest` | версія за Conventional Commits, тег, GitHub Release (Лаб 8) |
| `Release image` ([`release-image.yml`](../../.github/workflows/release-image.yml)) | після зеленого `CI` на `main` | `publish` — `ubuntu-latest` | образ контейнера, перевірка `GET /health`, публікація в ghcr.io з тегом = SHA (бонус 5) |
| `Flaky test hunt` ([`flaky-hunt.yml`](../../.github/workflows/flaky-hunt.yml)) | лише вручну | `hunt` — self-hosted | повний набір N разів на одному коміті, перелік нестабільних тестів (бонус 4) |

Обов'язкові перевірки PR у ruleset `main-protection`: `build`, `reliability`, `SonarCloud Code Analysis`.
Середовище Python на постійному раннері кешується між запусками (`scripts/ci_venv.py`, бонус 2).

## Як відтворити

```bash
gh auth login        # один раз; скрипт робить лише GET-запити до GitHub API
python scripts/dora_metrics.py --since 2026-10-19 --until 2026-11-09 \
  --dataset docs/ci-cd/evidence/dora-dataset.json \
  --out docs/ci-cd/dora-auto.md --json docs/ci-cd/dora-auto.json
# те саме без мережі — зі збереженого набору даних
python scripts/dora_metrics.py --from-dataset docs/ci-cd/evidence/dora-dataset.json --out dora-check.md
```
