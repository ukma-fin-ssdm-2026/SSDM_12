"""Контракти управління ролями й версіями політики (FR-062…FR-065)."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from api.enums import Role

ManagedRole = Literal[Role.PROVIDER, Role.ADMIN]


class UserRolesOut(BaseModel):
    """Результат адміністративної зміни без контактних даних користувача."""

    user_id: uuid.UUID = Field(description="Користувач, ролі якого змінено.")
    roles: list[Role] = Field(description="Чинні ролі, відсортовані за назвою.")


class PolicyUpdate(BaseModel):
    """Повна заміна поточних значень A-002 і A-003 (семантика PUT)."""

    model_config = ConfigDict(extra="forbid")

    booking_limit: int = Field(
        strict=True,
        ge=1,
        le=2_147_483_647,
        description="Ліміт активних бронювань: додатне ціле число (A-002).",
    )
    cancel_window_minutes: int = Field(
        strict=True,
        ge=0,
        le=2_147_483_647,
        description="Вікно скасування у хвилинах (A-003), не від'ємне; "
        "значення має вміщатися в INTEGER моделі БД. Вікно, що вивело б дедлайн "
        "за межі підтримуваних дат, відхиляється.",
    )


class PolicyOut(PolicyUpdate):
    """Поточна версія; попередні версії лишаються прив'язаними до старих бронювань."""

    id: uuid.UUID = Field(description="Ідентифікатор версії політики (DD-04).")
