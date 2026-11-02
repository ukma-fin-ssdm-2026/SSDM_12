# Контроль вимог Лаб6

| Вимога | Доказ / стан |
|---|---|
| ≥10 unit-тестів для ≥2 модулів, fixtures/mocks, межі, AAA | tests/unit/, junit.xml, coverage-report.md |
| HTML-покриття саме UniSlot | docs/testing/lab06/htmlcov/index.html — опубліковано в #206, перезнято в #213 після TDD-циклу; scope api+unislot, 97.53% при порозі 90% |
| Навмисна помилка, причина, виправлення, регресія | debugging-log.md, evidence/debug-red.txt і debug-green.txt |
| Реальна помилка курсора | evidence/cursor-before.txt, cursor-after.txt, tests/api/test_lab06_regressions.py |
| Стратегія на одну сторінку | testing-strategy.md: основна частина; бонуси окремим додатком |
| Особисті 6–12 TDD-комітів | Никита — 12 комітів у PR #212 (5×RED, 5×GREEN, 1×REFACTOR, 1 тест закріплення), без squash, перевіряється через `git log`; Денис, Аксенія, Павло ще виконують. Готові файли не заміняють процес |
| 2 Loom-відео ≤5 хв від кожного | Є: Никита (#215), Денис, Аксенія (#228). Лишається Павло — файлу `video_pavlo_dziubak.txt` немає ні в Лаб5, ні в Лаб6 |
| Mutation bonus | mutation-before.json / mutation-after.json; **не зараховано**: пояснити мав Павло, відео немає |
| Property bonus | tests/property/test_cursor_shapes.py; обґрунтування «для будь-якого входу» — у testing-strategy.md; чи пояснив Денис у своєму відео — підтвердити |
| CI coverage bonus | Поріг 90% діє в CI з #207, обґрунтування — у testing-strategy.md; докази воріт — evidence/gate-positive.txt і gate-negative.txt; зелений прогін `actions/runs/40872612185`; пояснює Никита у відео про внесок |
| Особиста присутність | Не відновлюється готовими файлами; не заявляється |

Issue #129 — контроль викладача, не закривати автоматично при першому PR.
Готовність технічних файлів не є твердженням про повну здачу всіма учасниками.
