"""Роутери API. Кожен модуль має власний файл і власника (див. `.github/CODEOWNERS`).

`ALL` визначає порядок підключення роутерів, а отже й порядок шляхів у
згенерованій специфікації. Новий роутер додається сюди окремим рядком.
"""

from __future__ import annotations

from api.routers import (
    admin,
    auth,
    availability,
    bookings,
    health,
    notifications,
    resources,
    slots,
    workspace,
)

ALL = (health, auth, resources, slots, bookings, admin, availability, notifications, workspace)
