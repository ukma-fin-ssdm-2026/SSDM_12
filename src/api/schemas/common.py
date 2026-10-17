"""Схеми, спільні для кількох модулів: короткі описи ресурсу й провайдера.

Їх вкладають у відповіді пошуку слотів і бронювань, тому вони лежать тут, а не в
модулі ресурсів: роутери різних учасників не залежать один від одного.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from api.enums import ResourceType
from api.stubs.store import Ids


class ResourceSummary(BaseModel):
    """Короткий опис ресурсу всередині слота чи бронювання."""

    id: uuid.UUID = Field(description="Ідентифікатор ресурсу.", examples=[Ids.RES_DB_CONSULT])
    name: str = Field(description="Назва ресурсу.", examples=["Консультація з баз даних"])
    type: ResourceType = Field(description="Тип ресурсу: consultation або room.")
    capacity: int | None = Field(
        description="Місткість; лише для аудиторій (INV-08), для консультацій — null.",
        examples=[None],
    )


class PersonSummary(BaseModel):
    """Ім'я користувача без контактних даних (SEC-004: мінімум персональних даних)."""

    id: uuid.UUID = Field(description="Ідентифікатор користувача.", examples=[Ids.PROVIDER])
    full_name: str = Field(description="Повне ім'я.", examples=["Ірина Шевченко"])
