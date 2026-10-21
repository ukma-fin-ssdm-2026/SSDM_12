"""Схеми ресурсів: каталог (FR-021, FR-060) і адміністрування (FR-060, FR-061)."""

from __future__ import annotations

import uuid
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from api.enums import ResourceType
from api.pagination import OffsetPagination
from api.schemas.common import PersonSummary
from api.stubs.store import Ids

NAME_MAX = 120
CAPACITY_MAX = 1000


class ResourceOut(BaseModel):
    """Ресурс каталогу: консультація викладача або аудиторія."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": str(Ids.RES_ROOM_1_225),
                    "name": "Аудиторія 1-225",
                    "type": "room",
                    "capacity": 30,
                    "provider": {"id": str(Ids.PROVIDER_2), "full_name": "Олег Бондар"},
                }
            ]
        }
    )

    id: uuid.UUID = Field(description="Ідентифікатор ресурсу (UUID, DD-13).")
    name: str = Field(description="Назва ресурсу.")
    type: ResourceType = Field(description="Тип: consultation або room.")
    capacity: int | None = Field(
        description="Місткість аудиторії; для консультацій — null (INV-08)."
    )
    provider: PersonSummary = Field(
        description="Провайдер, який керує доступністю ресурсу (FR-061)."
    )


class ResourceList(BaseModel):
    """Сторінка каталогу ресурсів."""

    items: list[ResourceOut] = Field(description="Ресурси, упорядковані за назвою.")
    pagination: OffsetPagination = Field(description="Метадані сторінки.")


class ResourceCreate(BaseModel):
    """Новий ресурс (лише адміністратор, FR-060, FR-061)."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        json_schema_extra={
            "examples": [
                {
                    "name": "Аудиторія 2-110",
                    "type": "room",
                    "capacity": 24,
                    "provider_id": str(Ids.PROVIDER_2),
                }
            ]
        },
    )

    name: str = Field(
        min_length=1, max_length=NAME_MAX, description="Назва; пробіли на краях обрізаються."
    )
    type: ResourceType = Field(description="Тип ресурсу; після створення не змінюється.")
    capacity: int | None = Field(
        default=None,
        ge=1,
        le=CAPACITY_MAX,
        validate_default=True,
        description="Місткість: обов'язкова для room, заборонена для consultation (INV-08).",
    )
    provider_id: uuid.UUID = Field(description="Користувач із роллю «провайдер» (INV-15).")

    @field_validator("capacity")
    @classmethod
    def capacity_matches_type(cls, value: int | None, info: ValidationInfo) -> int | None:
        """INV-08: місткість обов'язкова для аудиторії й заборонена для консультації."""
        # Поля перевіряються в порядку оголошення, тож `type` уже перевірено.
        # Помилка прив'язана до поля body.capacity, а не до всього тіла.
        resource_type = info.data.get("type")
        if resource_type is ResourceType.ROOM and value is None:
            raise ValueError("для аудиторії (room) місткість обов'язкова")
        if resource_type is ResourceType.CONSULTATION and value is not None:
            raise ValueError("для консультації (consultation) місткість не задається")
        return value


class ResourceUpdate(BaseModel):
    """Часткове оновлення ресурсу: змінюються лише передані поля (PATCH)."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        json_schema_extra={"examples": [{"capacity": 28}, {"name": "Аудиторія 1-225 (оновлена)"}]},
    )

    name: str | None = Field(
        default=None, min_length=1, max_length=NAME_MAX, description="Нова назва."
    )
    capacity: int | None = Field(
        default=None, ge=1, le=CAPACITY_MAX, description="Нова місткість; лише для аудиторій."
    )
    provider_id: uuid.UUID | None = Field(default=None, description="Новий провайдер (INV-15).")

    @field_validator("name", "provider_id", mode="before")
    @classmethod
    def reject_explicit_null(cls, value: Any) -> Any:
        """Явний `null` у `name` чи `provider_id` — помилка 422, а не «очистити поле»."""
        # Відрізняємо «поле не передали» (не змінювати) від «передали null» (помилка):
        # саме цю різницю загубив PATCH у коді, який ми рецензували (review-report.md, п. 1).
        # Валідатор не викликається для пропущених полів, бо validate_default вимкнено.
        if value is None:
            raise ValueError("поле не може бути null; щоб не змінювати його, не передавайте поле")
        return value

    @model_validator(mode="after")
    def not_empty(self) -> Self:
        """Порожній PATCH `{}` відхиляємо: він нічого не змінює й найчастіше є помилкою клієнта."""
        if not self.model_fields_set:
            raise ValueError("передайте хоча б одне поле: порожнє оновлення нічого не змінює")
        return self
