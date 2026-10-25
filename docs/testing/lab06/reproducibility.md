# Відтворюваність Лаб6

`requirements-testing.txt` розширює чинний `requirements-dev.txt`, без заміни
версій Hypothesis, Ruff чи інших інструментів Лаб5. Встановлення:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade "pip>=26.2"
.\.venv\Scripts\python.exe -m pip install -r requirements-testing.txt
```

`python scripts/run_lab06.py` запускає всі тести з branch coverage для `api` та
`unislot`, gate 90%, HTML/JSON/JUnit/XML. HTML комітиться лише в
`docs/testing/lab06/htmlcov/`. Тимчасові копії, кеші та віртуальні середовища не комітяться.
`run.json` містить версії, час реального запуску та SHA-256 нормалізованих LF файлів
коду/тестів. Після зміни цих файлів звіт треба перегенерувати.

Спільна unit-fixture користується наявною fixture `frozen_world`: фіксує час,
скидає синтетичні демо-дані й надає CurrentUser для тестів без HTTP.
Тести явно вмикають demo auth; стандартне вимкнення демо-автентифікації в застосунку збережено.

`requirements-mutation.txt` — додаткове локальне середовище Cosmic Ray, не обов'язкова
залежність звичайного PR CI. Для швидких TDD-циклів запускати окремий тестовий файл;
повний набір та повний звіт — після завершення функції.

## Аудит сканера секретів

Нові спрацювання Hex High Entropy у `run.json`, `htmlcov/status.json`,
`evidence/debug-results.json`, `debug.txt`, `mutation-before.json`,
`mutation-after.json`, `quality-results.json` перевірені: це SHA-256 коду,
контрольні хеші coverage та SHA Git-коміту. Значення відтворюються з локальних
файлів або є ідентифікаторами коміту; вони не є обліковими даними.
У `.secrets.baseline` вони позначені `is_secret: false`; старі аудити збережені,
шляхи записані з `/` для Windows/macOS. Немає нового широкого виключення файлів
і немає вимкнення сканера. Інше нове спрацювання слід дослідити окремо.

Використання ШІ: Codex підготував інструменти, локально перевірив відтворюваність
та звірив хеші спрацювань із відповідними рядками згенерованих звітів.
