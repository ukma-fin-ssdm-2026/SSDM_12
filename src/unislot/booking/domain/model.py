"""Значення предметної області бронювання: стани, інтервал часу, політика.

Переліки перенесено сюди з `api.enums` у Лаб 5: правила домену обчислюють стан
бронювання, а домен не може імпортувати REST API. `api.enums` реекспортує їх, тож
схеми Pydantic і специфікація OpenAPI не змінилися (назви й значення ті самі).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum


class BookingStatus(StrEnum):
    """Збережений стан бронювання (`data-model.md` §7): лише два значення."""

    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


class BookingState(StrEnum):
    """Похідний стан бронювання для користувача (`data-model.md` §7, AQ-05).

    Обчислюється з `status` і часу слота; у БД не зберігається.
    """

    ACTIVE = "active"  # підтверджене, слот ще не почався
    IN_PROGRESS = "in_progress"  # слот триває (AQ-05)
    COMPLETED = "completed"  # слот завершився
    CANCELLED = "cancelled"


class CancellationKind(StrEnum):
    """Хто або що скасувало бронювання (INV-13)."""

    STUDENT = "student"
    PROVIDER_BLOCK = "provider_block"
    RESCHEDULED = "rescheduled"


@dataclass(frozen=True)
class Interval:
    """Напіввідкритий проміжок часу [starts_at, ends_at): так задано слоти (FR-011).

    Суміжні інтервали (кінець одного = початок іншого) не перетинаються.
    """

    starts_at: datetime
    ends_at: datetime

    def __post_init__(self) -> None:
        """Порожній чи «перевернутий» інтервал — дефект даних, а не порушення правила."""
        if self.ends_at <= self.starts_at:
            msg = "ends_at має бути пізніше за starts_at"
            raise ValueError(msg)

    def overlaps(self, other: Interval) -> bool:
        """Чи мають два інтервали спільний момент часу (суміжні — ні)."""
        return self.starts_at < other.ends_at and other.starts_at < self.ends_at


@dataclass(frozen=True)
class BookingPolicy:
    """Чинна політика бронювання: ліміт A-002 і вікно скасування A-003."""

    booking_limit: int
    cancel_window: timedelta
