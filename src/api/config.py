"""Константи контракту й налаштування API.

Налаштування читаються лише зі змінних середовища (DD-09): у коді немає ні
паролів, ні адрес середовищ. Константи контракту (версія, префікс) змінюються
тільки разом із версією API — див. `docs/api/api-design.md`, «Версіонування».
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
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


# Числові налаштування: змінна → (типове, мінімум, максимум). Самі числа тимчасові
# (OQ-001), але діапазон обов'язковий: він відсікає і одруківки, і значення, що фактично
# вимикають захист. Межі 1..20 для інтервалу перемикання дублює `__post_init__` —
# захист у два шари лишаємо свідомо (R-01, docs/reliability/scavenger-hunt.md).
NUMERIC_SETTINGS: dict[str, tuple[int, int, int]] = {
    "UNISLOT_SESSION_TTL_SECONDS": (28800, 1, 30 * 24 * 3600),
    "UNISLOT_LOGIN_MAX_FAILURES": (5, 1, 1000),
    "UNISLOT_LOGIN_COOLDOWN_SECONDS": (300, 1, 24 * 3600),
    "UNISLOT_THREAD_SWITCH_INTERVAL_MS": (1, 1, 20),
}


def _bounded_int(name: str) -> int:
    """Читає цілу змінну середовища в межах із `NUMERIC_SETTINGS`.

    Порожнє значення — fail-safe: змінну вважаємо незаданою й беремо типове, бо порожнє
    поле в панелі розгортання означає саме «не задано». Нечислове або позамежне —
    fail-fast із назвою змінної: `5min` не має тихо стати `5` і змінити межу безпеки,
    а `invalid literal for int()` без назви змінної не вказує, що саме виправляти.
    """
    default, low, high = NUMERIC_SETTINGS[name]
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        raise ValueError(f"{name} must be a whole number, got {raw.strip()!r}") from None
    if not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}, got {value}")
    return value


@dataclass(frozen=True)
class Settings:
    """Налаштування процесу API."""

    # Записувати специфікацію у docs/api/ під час старту сервера (цикл Code-First
    # на локальній машині). У тестах і в майбутньому контейнері — вимкнено.
    export_openapi_on_startup: bool
    # Демо-автентифікація за токенами `demo-*` (DD-18; DD-06 — цільова схема).
    # Вимкнена, доки її не ввімкнули явно (V-01 у static-analysis.md).
    demo_auth_enabled: bool
    # Джерела, яким дозволено CORS (через кому). Порожньо — CORS вимкнено.
    cors_origins: tuple[str, ...]
    database_url: str | None = field(default=None, repr=False)
    session_cookie_secure: bool = True
    session_ttl_seconds: int = 28800
    login_max_failures: int = 5
    login_cooldown_seconds: int = 300
    thread_switch_interval_ms: int = 1

    def __post_init__(self) -> None:
        """Додатні конфігуровані межі не можна вимкнути випадковим нулем."""
        if min(self.session_ttl_seconds, self.login_max_failures, self.login_cooldown_seconds) < 1:
            raise ValueError("auth configuration values must be positive")
        if "*" in self.cors_origins:
            raise ValueError("cookie CORS requires explicit origins")
        if not 1 <= self.thread_switch_interval_ms <= 20:
            raise ValueError("thread switch interval must be between 1 and 20 milliseconds")


@lru_cache
def get_settings() -> Settings:
    """Повертає налаштування; кешується на весь процес."""
    origins = os.environ.get("UNISLOT_CORS_ORIGINS", "")
    return Settings(
        export_openapi_on_startup=_flag("UNISLOT_EXPORT_OPENAPI", default=True),
        # Безпечний збій (OWASP): токени `demo-*` відкрито описані в README й OpenAPI,
        # серед них `demo-admin`. Сервер, запущений без змінної, їх не приймає (V-01).
        demo_auth_enabled=_flag("UNISLOT_DEMO_AUTH", default=False),
        cors_origins=tuple(o.strip() for o in origins.split(",") if o.strip()),
        database_url=os.environ.get("UNISLOT_DATABASE_URL") or None,
        session_cookie_secure=_flag("UNISLOT_SESSION_COOKIE_SECURE", default=True),
        session_ttl_seconds=_bounded_int("UNISLOT_SESSION_TTL_SECONDS"),
        login_max_failures=_bounded_int("UNISLOT_LOGIN_MAX_FAILURES"),
        login_cooldown_seconds=_bounded_int("UNISLOT_LOGIN_COOLDOWN_SECONDS"),
        thread_switch_interval_ms=_bounded_int("UNISLOT_THREAD_SWITCH_INTERVAL_MS"),
    )
