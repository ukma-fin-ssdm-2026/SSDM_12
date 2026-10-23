"""Спільні фікстури тестів API (Лаб 4).

Час у тестах заморожено: `clock.utc_now()` повертає `NOW`, а демо-дані будуються від
нього. Так правила A-001, A-003, A-006 перевіряються детерміновано, незалежно від того,
коли й де запущено тести. Поточний «зараз» у тесті — `clock.utc_now()`.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime

# Тести не мають записувати docs/api/ — вимикаємо експорт до імпорту застосунку
# (Ruff дозволяє імпорти після зміни os.environ, тож E402 тут не спрацьовує).
os.environ["UNISLOT_EXPORT_OPENAPI"] = "0"
# Демо-автентифікацію тести вмикають явно, як і локальний запуск (V-01, static-analysis.md):
# за замовчуванням сервер демо-токенів не приймає.
os.environ["UNISLOT_DEMO_AUTH"] = "1"

import pytest
from fastapi.testclient import TestClient

from api import clock
from api.main import app
from api.stubs.store import store

# Понеділок, 12:00 за Києвом (UTC+3). Горизонт A-001 перетинає перехід на зимовий час (25.10).
NOW = datetime(2026, 10, 19, 9, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def frozen_world(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Кожен тест — із замороженим часом і свіжими демо-даними."""
    monkeypatch.setattr(clock, "utc_now", lambda: NOW)
    store.reset(NOW)
    yield
    store.reset(NOW)


@pytest.fixture
def client() -> TestClient:
    """Клієнт без lifespan: тест не запускає експорт специфікації."""
    return TestClient(app)
