"""Значення припущень A-001…A-007 (`requirements.md` §6), потрібні контракту API.

Числа живуть в одному місці: схеми й заглушки посилаються на ці константи, а не
повторюють їх. Ліміт (A-002) і вікно скасування (A-003) змінює адміністратор
(FR-064), тому тут це лише значення за замовчуванням для заглушки політики.
"""

from __future__ import annotations

from datetime import timedelta
from zoneinfo import ZoneInfo

HORIZON = timedelta(days=14)  # A-001: горизонт бронювання
DEFAULT_BOOKING_LIMIT = 3  # A-002: ліміт активних бронювань студента
DEFAULT_CANCEL_WINDOW = timedelta(hours=2)  # A-003: вікно скасування
SLOT_MIN_MINUTES = 15  # A-005: найкоротший слот
SLOT_MAX_MINUTES = 120  # A-005: найдовший слот
SLOT_STEP_MINUTES = 5  # A-005: крок тривалості
KYIV = ZoneInfo("Europe/Kyiv")  # A-007: час показу й шаблонів; зберігання — UTC
