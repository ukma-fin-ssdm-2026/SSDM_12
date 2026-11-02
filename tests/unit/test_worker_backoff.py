"""Відступ Worker після збою БД: обмежений зверху, скидається після успіху.

Лаб 9, Етап 3, знахідка R-07 у `docs/reliability/scavenger-hunt.md`. Дефект: у
нескінченному циклі `run_worker.py` затримка між спробами була фіксованою (типово 1 с),
тож недоступна БД отримувала близько 60 спроб підключення за хвилину — цикл «не здавався»
і тиснув на сховище саме тоді, коли воно відновлюється.

Межа рішення: відступ застосовано лише до операційних помилок (`DBAPIError`, `OSError`).
`ValueError` з інваріантів сховища (наприклад «outbox records cannot be erased») лишається
фатальним: це дефект коду, і цикл не повинен його тихо переживати.
"""

from __future__ import annotations

import pytest

from scripts.run_worker import MAX_BACKOFF_FACTOR, next_delay

pytestmark = pytest.mark.req("REL-002")


def test_delay_doubles_on_each_consecutive_failure():
    """Перша невдача — подвоєння, не миттєва нова спроба."""
    assert next_delay(1.0, 1.0) == 2.0
    assert next_delay(1.0, 2.0) == 4.0
    assert next_delay(1.0, 4.0) == 8.0


def test_delay_is_bounded_from_above():
    """Без верхньої межі відступ зріс би до годин і нагадування б запізнювалися."""
    assert next_delay(1.0, 10**6) == MAX_BACKOFF_FACTOR
    assert next_delay(0.5, 10**6) == 0.5 * MAX_BACKOFF_FACTOR


@pytest.mark.parametrize("interval", [0.5, 1.0, 5.0])
def test_bound_scales_with_the_configured_interval(interval):
    """Відступ не має перевищувати налаштований інтервал більш ніж у MAX_BACKOFF_FACTOR разів."""
    delay = interval
    for _ in range(50):
        delay = next_delay(interval, delay)
    assert delay == pytest.approx(interval * MAX_BACKOFF_FACTOR)


def test_first_delay_never_shorter_than_the_configured_interval():
    """Відступ зростає, а не зменшується: нова спроба не може стати агресивнішою."""
    assert next_delay(2.0, 2.0) >= 2.0
