"""Доменні помилки бронювання (HLD §9): назва класу — причина відмови.

Код кожної помилки — той самий рядок, що й у каталозі `api.errors.CATALOG`:
REST API бере звідти HTTP-статус, назву й дію для користувача. Тест
`test_booking_error_codes_exist_in_api_catalog` не дасть додати помилку, для якої
в каталозі немає опису.
"""

from __future__ import annotations

from datetime import datetime

from unislot.platform.errors import DomainError


class BookingRuleViolation(DomainError):
    """Спільний предок помилок модуля `Booking`."""


class SlotStarted(BookingRuleViolation):
    """Слот уже почався: записатися чи змінити бронювання не можна (A-006, FR-045)."""

    code = "SLOT_STARTED"


class SlotOutOfHorizon(BookingRuleViolation):
    """Слот пізніший за горизонт бронювання A-001."""

    code = "SLOT_OUT_OF_HORIZON"


class SlotBlocked(BookingRuleViolation):
    """Час слота провайдер оголосив недоступним (FR-014)."""

    code = "SLOT_BLOCKED"


class SlotAlreadyBooked(BookingRuleViolation):
    """На слот уже є чинне бронювання (FR-032, INV-01)."""

    code = "SLOT_ALREADY_BOOKED"


class BookingLimitReached(BookingRuleViolation):
    """Студент уже має максимальну кількість активних бронювань (A-002)."""

    code = "BOOKING_LIMIT_REACHED"

    def __init__(self, limit: int, active: int) -> None:
        """Передає клієнту ліміт і поточну кількість — поля `limit`, `active_bookings`."""
        super().__init__(
            f"Ліміт — {limit} активні бронювання, у вас уже {active}.",
            limit=limit,
            active_bookings=active,
        )


class BookingOverlap(BookingRuleViolation):
    """Новий слот перетинається з іншим активним бронюванням студента (FR-035)."""

    code = "BOOKING_OVERLAP"


class BookingAlreadyCancelled(BookingRuleViolation):
    """Скасоване бронювання не можна скасувати чи перенести вдруге (FR-040)."""

    code = "BOOKING_ALREADY_CANCELLED"


class CancellationDeadlinePassed(BookingRuleViolation):
    """Минув граничний час скасування, зафіксований під час бронювання (FR-041)."""

    code = "CANCELLATION_DEADLINE_PASSED"

    def __init__(self, deadline: datetime) -> None:
        """Повідомляє граничний час — поле `cancel_deadline_at` у відповіді."""
        super().__init__(
            f"Скасувати чи перенести можна було до {deadline.isoformat()}.",
            cancel_deadline_at=deadline,
        )
