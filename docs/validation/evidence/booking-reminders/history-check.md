# Перевірка історії Git

Звірено командами Git **29.10.2026**. Наведені SHA — ідентифікатори об'єктів Git,
а не облікові дані. Перевірка стосується історичних комітів RED/GREEN і злиття #232.

| Об'єкт | SHA або результат |
|---|---|
| RED | `06c2a4458b2148425344aae7ec2d4a925e31ba78` |
| GREEN | `aa3ba4ed02739424cc423da183ec130a24e49979` |
| Безпосередній батько GREEN | `06c2a4458b2148425344aae7ec2d4a925e31ba78` |
| Дерево tests у RED | `9ebad783a1b8bb17093872fc717267fdecee0311` |
| Дерево tests у GREEN | `9ebad783a1b8bb17093872fc717267fdecee0311` |
| Змінені тести між RED і GREEN | немає |
| Merge-коміти між RED і GREEN | немає |
| Merge #232 | `883ef7aaf190fbd4e480d63f5f6b71e7dfb4c7b1` |
| Перший батько merge — main із #230 | `4567041f2b8815ae6e16cdabe0ca1e7e63f7c061` |
| Другий батько merge — GREEN | `aa3ba4ed02739424cc423da183ec130a24e49979` |

Змінені джерела між RED і GREEN — рівно чотири файли:

- `src/api/stubs/booking_service.py`
- `src/api/stubs/store.py`
- `src/unislot/notifications/domain/__init__.py`
- `src/unislot/notifications/domain/reminders.py`

Відтворення з кореня репозиторію:

```bash
git rev-parse aa3ba4e^ 06c2a44:tests aa3ba4e:tests
git diff --name-only 06c2a44 aa3ba4e -- tests
git rev-list --merges 06c2a44..aa3ba4e
git show -s --format=%P 883ef7a
git diff --name-only 06c2a44 aa3ba4e
```

Ця перевірка не засвідчує незалежний огляд або особисте відео.
