"""Числові змінні середовища: некоректне значення не стає робочою конфігурацією.

Лаб 9, Етап 3, знахідка R-01 у `docs/reliability/scavenger-hunt.md`. Дефект: `config.py`
віддавав значення змінної середовища прямо в `int()`, тож порожній рядок (типова ситуація
в панелі Render) чи одруківка (`5min`) валили процес на імпорті `api.main` з повідомленням
`invalid literal for int() with base 10: ''`, яке не називає змінної.

Рішення розділяє два випадки:
  - порожнє значення — fail-safe: беремо задокументоване типове (змінну «не задано»);
  - нечислове або позамежне — fail-fast: помилка, що називає змінну, бо `5min` не має
    тихо перетворитися на 5 і змінити межу безпеки.
"""

from __future__ import annotations

import pytest

from api.config import get_settings

pytestmark = pytest.mark.req("QA-15")

NUMERIC_VARIABLES = [
    ("UNISLOT_SESSION_TTL_SECONDS", "session_ttl_seconds", 28800),
    ("UNISLOT_LOGIN_MAX_FAILURES", "login_max_failures", 5),
    ("UNISLOT_LOGIN_COOLDOWN_SECONDS", "login_cooldown_seconds", 300),
    ("UNISLOT_THREAD_SWITCH_INTERVAL_MS", "thread_switch_interval_ms", 1),
]


@pytest.fixture(autouse=True)
def _isolated_settings_cache():
    """`get_settings` кешується на процес — тест не має впливати на сусідні."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.parametrize(("name", "attribute", "default"), NUMERIC_VARIABLES)
@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_numeric_variable_falls_back_to_documented_default(
    monkeypatch, name, attribute, default, blank
):
    """Порожня змінна в панелі розгортання не має валити процес."""
    monkeypatch.setenv(name, blank)
    assert getattr(get_settings(), attribute) == default


@pytest.mark.parametrize(("name", "attribute", "default"), NUMERIC_VARIABLES)
@pytest.mark.parametrize("value", ["5min", "8h", "abc", "1.5", "-"])
def test_non_numeric_variable_is_rejected_with_its_own_name(
    monkeypatch, name, attribute, default, value
):
    """Повідомлення має називати змінну, інакше причину шукають у чужих логах."""
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=name):
        get_settings()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("UNISLOT_SESSION_TTL_SECONDS", "0"),
        ("UNISLOT_SESSION_TTL_SECONDS", "-1"),
        ("UNISLOT_LOGIN_MAX_FAILURES", "0"),
        ("UNISLOT_LOGIN_COOLDOWN_SECONDS", "0"),
        ("UNISLOT_THREAD_SWITCH_INTERVAL_MS", "0"),
        ("UNISLOT_THREAD_SWITCH_INTERVAL_MS", "21"),
    ],
)
def test_out_of_range_numeric_variable_is_rejected_with_its_own_name(monkeypatch, name, value):
    """`__post_init__` ловить межі й далі; тут перевіряємо, що помилка називає джерело."""
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=name):
        get_settings()


@pytest.mark.parametrize(("name", "attribute", "default"), NUMERIC_VARIABLES)
def test_valid_value_still_overrides_the_default(monkeypatch, name, attribute, default):
    """Регресія: виправлення не має зламати звичайне перевизначення межі."""
    monkeypatch.setenv(name, "2")
    assert getattr(get_settings(), attribute) == 2
