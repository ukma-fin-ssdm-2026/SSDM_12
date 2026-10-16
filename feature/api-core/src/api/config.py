"""Константи контракту й налаштування API.

Налаштування читаються лише зі змінних середовища (DD-09): у коді немає ні
паролів, ні адрес середовищ. Константи контракту (версія, префікс) змінюються
тільки разом із версією API — див. `docs/api/api-design.md`, «Версіонування».
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

API_TITLE = "UniSlot API"
# Семантична версія контракту. MAJOR збігається з префіксом шляху (/api/v1);
# суфікс alpha означає, що до стабільного 1.0.0 контракт ще може змінитися
# (заглушки замість модулів, автентифікація-заглушка).
API_VERSION = "1.0.0-alpha.1"
API_PREFIX = "/api/v1"

# Адреса опублікованої документації (GitHub Pages). На ній лежить каталог
# помилок errors.html, на який посилається поле `type` кожної відповіді-помилки.
DOCS_BASE_URL = "https://ukma-fin-ssdm-2026.github.io/SSDM_12"

# Порт локального запуску задано умовою Лаб 4 (localhost:3000/api-docs).
LOCAL_SERVER_URL = "http://localhost:3000"


def _flag(name: str, default: bool) -> bool:
    """Читає булеву змінну середовища: 1/true/yes/on — увімкнено."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """Налаштування процесу API."""

    # Записувати специфікацію у docs/api/ під час старту сервера (цикл Code-First
    # на локальній машині). У тестах і в майбутньому контейнері — вимкнено.
    export_openapi_on_startup: bool
    # Демо-автентифікація за токенами `demo-*` (лише Лаб 4; DD-06 — цільова схема).
    demo_auth_enabled: bool
    # Джерела, яким дозволено CORS (через кому). Порожньо — CORS вимкнено.
    cors_origins: tuple[str, ...]


@lru_cache
def get_settings() -> Settings:
    """Повертає налаштування; кешується на весь процес."""
    origins = os.environ.get("UNISLOT_CORS_ORIGINS", "")
    return Settings(
        export_openapi_on_startup=_flag("UNISLOT_EXPORT_OPENAPI", default=True),
        demo_auth_enabled=_flag("UNISLOT_DEMO_AUTH", default=True),
        cors_origins=tuple(o.strip() for o in origins.split(",") if o.strip()),
    )
