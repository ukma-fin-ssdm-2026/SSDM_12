"""Схеми модуля Auth: публічний обліковий запис, вхід і секретний пароль."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, field_validator

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


class RegisterIn(BaseModel):
    """Роль та інші зайві поля ігноруються за FR-002; пароль не обрізається."""

    model_config = ConfigDict(extra="ignore")
    full_name: str = Field(min_length=1, max_length=160, description="Повне ім'я користувача.")
    email: EmailStr = Field(max_length=254, description="Адреса без перевірки володіння (C-002).")
    password: SecretStr = Field(
        min_length=15,
        max_length=1024,
        description="15–1024 символи; без обрізання чи зміни пробілів.",
    )

    @field_validator("full_name")
    @classmethod
    def name_not_blank(cls, value: str) -> str:
        """Видаляє лише зовнішні пробіли імені, не пароля."""
        value = value.strip()
        if not value:
            raise ValueError("Full name must not be blank")
        return value


class LoginIn(BaseModel):
    """Вхід із повним паролем; неправильні значення не потрапляють у відповіді."""

    model_config = ConfigDict(extra="forbid")
    email: EmailStr = Field(max_length=254, description="Адреса облікового запису без регістру.")
    password: SecretStr = Field(min_length=1, max_length=1024, description="Повний пароль.")


class LoginOut(BaseModel):
    """Сесійний токен — лише в HttpOnly cookie; CSRF не є токеном входу."""

    user: MeOut = Field(description="Поточний користувач із чинними ролями.")
    csrf_token: str = Field(description="Передайте як X-CSRF-Token для POST/PUT/PATCH/DELETE.")
    expires_at: datetime = Field(description="Абсолютний строк дії сесії на сервері, UTC.")
