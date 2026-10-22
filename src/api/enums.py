"""Переліки, спільні для контракту API і заглушок даних.

Значення збігаються з `docs/architecture/data-model.md`: це ті самі рядки, що
зберігатиме PostgreSQL, тож перехід із заглушок на БД не змінить контракт.

Переліки бронювання з Лаб 5 живуть у доменному шарі (`unislot.booking.domain.model`):
правила домену обчислюють стан, а домен не імпортує REST API. Тут їх реекспортовано,
тож імпорти `from api.enums import BookingState` і специфікація OpenAPI не змінилися.
"""

from __future__ import annotations

from enum import StrEnum

from unislot.booking.domain.model import BookingState, BookingStatus, CancellationKind

__all__ = ["BookingState", "BookingStatus", "CancellationKind", "ResourceType", "Role"]


class Role(StrEnum):
    """Роль користувача (FR-007). Користувач може мати кілька ролей (`user_role`)."""

    STUDENT = "student"
    PROVIDER = "provider"
    ADMIN = "admin"


class ResourceType(StrEnum):
    """Тип ресурсу (глосарій): консультація викладача або аудиторія."""

    CONSULTATION = "consultation"
    ROOM = "room"
