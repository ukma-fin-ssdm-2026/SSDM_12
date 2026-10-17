"""Схеми модуля Auth (Лаб 4: лише поточний користувач)."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from api.enums import Role
from api.stubs.store import Ids


class MeOut(BaseModel):
    """Поточний користувач і його ролі (FR-007)."""

    id: uuid.UUID = Field(description="Ідентифікатор користувача.", examples=[Ids.STUDENT])
    full_name: str = Field(description="Повне ім'я.", examples=["Олена Коваль"])
    email: str = Field(
        description="Адреса електронної пошти (лише власна).",
        examples=["olena.koval@unislot.example"],
    )
    roles: list[Role] = Field(
        description="Ролі користувача; їх може бути кілька (AQ-01). Відсортовано за назвою.",
        examples=[["student"]],
    )
