# Відтворення регресійного порівняння Лаб 8

Ці файли отримано повторним фактичним запуском 13.11.2026. Це не первинні
локальні XML із PR #340 від 12.11.2026 і не 48-тестовий запуск із відео.
Результат повторного запуску збігається з кількостями у PR #340: 705 → 743,
38 нових тестів, регресій немає.

| Параметр | Значення |
|---|---|
| ОС | Linux x86_64, glibc 2.41 |
| Python | CPython 3.12.14 |
| pytest | 9.1.1 |
| Залежності | `requirements-testing.txt` із `main` на `4dec06e1b8cb1b8b755e47e29dff157a67676bcf` |
| До | `v0.1.0` → `783b757ec4cb46ded290fa407a7eded38e98c750` |
| Після | `v0.1.1` → `2939ff78789acf2ff305f6dab0778b8d19b2f446` |
| Інструмент порівняння | `scripts/regression_compare.py` із того самого `main`; остання зміна — `3556a0a` |
| Виключення в обох прогонах | `--ignore=tests/integration` |

## Команди

Із кореня репозиторію з цими доказами створено дві окремі робочі копії
релізних тегів та спільне ізольоване Python-середовище:

```bash
git worktree add --detach ../SSDM_12_before v0.1.0
git worktree add --detach ../SSDM_12_after v0.1.1
uv venv .venv
uv pip install --python .venv/bin/python -r requirements-testing.txt
```

Із `../SSDM_12_before` виконано:

```bash
../SSDM_12/.venv/bin/python -m pytest -q --ignore=tests/integration --junitxml=../SSDM_12/docs/refactoring/evidence/before.xml > ../before-pytest.txt 2>&1
```

Із `../SSDM_12_after` виконано:

```bash
../SSDM_12/.venv/bin/python -m pytest -q --ignore=tests/integration --junitxml=../SSDM_12/docs/refactoring/evidence/after.xml > ../after-pytest.txt 2>&1
```

Обидві команди завершилися з кодом 0. Їхні stdout/stderr скопійовано без
редагування в [regression-before-pytest.txt](regression-before-pytest.txt)
та [regression-after-pytest.txt](regression-after-pytest.txt).
Єдине попередження в кожному прогоні — несумісність `record_property` з
`junit_family='xunit2'`; воно не змінює результат тесту.

Із кореня `SSDM_12` виконано:

```bash
.venv/bin/python scripts/regression_compare.py docs/refactoring/evidence/before.xml docs/refactoring/evidence/after.xml > docs/refactoring/evidence/regression-v0.1.0-v0.1.1.txt
```

Код виходу — 0. [Текстовий доказ](regression-v0.1.0-v0.1.1.txt) є саме
stdout цієї команди; заголовки, пояснення та підсумки вручну не додавалися.
Повторний запуск на [before.xml](before.xml) та [after.xml](after.xml)
має відтворити його байт у байт; тривалості й часові мітки в нових XML
можуть відрізнятися.

## Чим відрізняється відео

У сценарії відео Аксенії для Лаб 8 вибрано лише
`tests/api/test_availability_templates.py` і `tests/unit/test_weekly_patterns.py`
на тих самих тегах: 48 passed до і після. Це перевірка меншого набору,
тоді як додані тут XML охоплюють увесь набір без `tests/integration`.
Жоден із цих двох варіантів не підтверджує результат інтеграційних тестів.
