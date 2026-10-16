"""Переліки, спільні для контракту API і заглушок даних.

Значення збігаються з `docs/architecture/data-model.md`: це ті самі рядки, що
зберігатиме PostgreSQL, тож перехід із заглушок на БД не змінить контракт.
"""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    """Роль користувача (FR-007). Користувач може мати кілька ролей (`user_role`)."""

    STUDENT = "student"
    PROVIDER = "provider"
    ADMIN = "admin"


class ResourceType(StrEnum):
    """Тип ресурсу (глосарій): консультація викладача або аудиторія."""

    CONSULTATION = "consultation"
    ROOM = "room"


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
