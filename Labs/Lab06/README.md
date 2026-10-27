# Лаб6 — тести й налагодження UniSlot

Умова: [Лаб6](https://ssdm-2026.cs-courses.org/labs/lab06/lab06.html).
Актуально на 26.10.2026, main `870df7a3f1a343969c1a7aa3bb1691750119065d`.
Матеріали опубліковано в репозиторії послідовними PR; локальні підготовчі результати замінено фактичними.

| Учасник | Роль Лаб6 |
|---|---|
| Денис Пацеля | Рецензент і керівник налагодження |
| Аксенія Козуліна | Керівниця якості, unit-тестів і покриття |
| Павло Дзюбак | Аналітик безпеки та керівник CI/інтеграції |
| Никита Бабаков | Керівник документації та стратегії тестування |

- [Стратегія](../../docs/testing/testing-strategy.md).
- [Покриття](../../docs/testing/coverage-report.md), [HTML](../../docs/testing/lab06/htmlcov/index.html).
- [Журнал](../../docs/testing/debugging-log.md).
- [Контрольний список](requirements-checklist.md).

## Відтворення

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade "pip>=26.2"
.\.venv\Scripts\python.exe -m pip install -r requirements-testing.txt
.\.venv\Scripts\python.exe scripts/run_lab06.py
.\.venv\Scripts\python.exe scripts/debug_lab06.py
.\.venv\Scripts\python.exe scripts/check_lab06.py
```

Для необов'язкового mutation testing установити `requirements-mutation.txt`,
потім виконати `python scripts/mutation_lab06.py --label after`.
Звіт `before` — контрольний набір без доданих mutation-регресій, не особиста TDD-історія.
Вебредактор не запускає локальні хуки: треба доче­катися фактичного CI на останньому коміті.

## Особисті результати

Кожен сам виконує 6–12 малих комітів `[RED]`, `[GREEN]`, `[REFACTOR]`,
без squash, і записує **два окремі Loom-відео, кожне ≤5 хв**.
У `video_denys_patselia.txt`, `video_akseniia_kozulina.txt`,
`video_pavlo_dziubak.txt`, `video_nykyta_babakov.txt`:
перший рядок — URL TDD-відео; другий — URL відео про внесок. Створювати файли лише з реальними URL.
Підготовлені AI-матеріали не підтверджують особисті дії, відвідування чи огляд іншою людиною.

## Використання ШІ

Codex адаптував попередні локальні заготовки до поточного main, дописав код,
тести та документи, виконав локальні перевірки. Командна перевірка, студентські
TDD-коміти й відео подаються окремо за фактом виконання.
