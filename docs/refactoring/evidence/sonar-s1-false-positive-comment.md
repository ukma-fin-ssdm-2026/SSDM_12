# Коментар до S-1 у SonarQube Cloud

Знахідка: https://sonarcloud.io/project/issues?open=AaF0YmGH7GRUxAPzGZBV&id=ukma-fin-ssdm-2026_SSDM_12

Рекомендована дія для власника з правами: **False Positive**. Поточний статус — **Open**.

```text
False Positive: рядок є текстом підказки в каталозі помилок із публічним тестовим
ідентифікатором demo-student, а не приватним токеном чи паролем реального користувача.
Ідентифікатор працює лише в явно ввімкненому демо-режимі. Ризик демо-автентифікації
за замовчуванням (V-01) виправлено в PR #177: UNISLOT_DEMO_AUTH вимкнено за замовчуванням.
Доказ — tests/api/test_platform.py::test_demo_auth_is_off_unless_enabled.
Це не підстава вмикати демо-режим у публічному середовищі; це розмежування прикладу
в документації та витоку приватного секрету.
```

Джерела: [V-01](../../code-quality/static-analysis.md#5-задокументована-вразливість-v-01-демо-автентифікація-ввімкнена-за-замовчуванням),
[регресійний тест](https://github.com/ukma-fin-ssdm-2026/SSDM_12/blob/main/tests/api/test_platform.py),
[налаштування](https://github.com/ukma-fin-ssdm-2026/SSDM_12/blob/main/src/api/config.py).
