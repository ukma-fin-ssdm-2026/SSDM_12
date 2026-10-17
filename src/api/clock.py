"""Джерело поточного часу (DD-11).

Код викликає `clock.utc_now()` через модуль, а не імпортує функцію напряму, щоб
тести могли підмінити час (`monkeypatch.setattr(clock, "utc_now", ...)`) і
детерміновано перевірити правила A-001, A-003, A-006.
"""

from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> datetime:
    """Поточний момент в UTC (aware datetime)."""
    return datetime.now(UTC)
