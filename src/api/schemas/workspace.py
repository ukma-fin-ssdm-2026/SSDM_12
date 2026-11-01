"""Списки для кабінетів: власна доступність провайдера та адміністраторський каталог."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from api.pagination import OffsetPagination
from api.schemas.auth import MeOut
from api.schemas.availability import TemplateOut
from api.schemas.slots import SlotDetail


class AccountOut(MeOut):
    """Видимий тільки адміністратору запис каталогу користувачів."""

    is_active: bool = Field(description="Чи дозволено парольний вхід до облікового запису.")


class AccountList(BaseModel):
    """Сторінка користувачів; не розкриває хешів, сесій чи лічильників входу."""

    items: list[AccountOut] = Field(description="Користувачі за ім'ям, потім за ID.")
    pagination: OffsetPagination = Field(description="Метадані сторінки.")


class ManagedSlot(SlotDetail):
    """Стан власного слота без особи студента чи ID його бронювання."""

    availability: Literal["available", "booked", "blocked", "started", "outside_horizon"] = Field(
        description="Причина доступності; пріоритет: started, blocked, booked, outside_horizon, available."
    )


class ManagedSlotList(BaseModel):
    """Власні активні слоти, які ще не закінчилися; не повний календар FR-015."""

    items: list[ManagedSlot] = Field(description="Слоти за початком, потім за ID.")
    pagination: OffsetPagination = Field(description="Метадані сторінки.")


class TemplateList(BaseModel):
    """Шаблони власного ресурсу з актуальними конфліктами генерації."""

    items: list[TemplateOut] = Field(description="Шаблони за днем тижня, локальним часом та ID.")
    pagination: OffsetPagination = Field(description="Метадані сторінки.")


class TimeBlockRead(BaseModel):
    """Поточний запис блокування; кількість скасувань — тільки результат створення."""

    id: uuid.UUID = Field(description="Ідентифікатор блокування.")
    resource_id: uuid.UUID = Field(description="Власний ресурс провайдера.")
    starts_at: datetime = Field(description="Початок у UTC.")
    ends_at: datetime = Field(description="Кінець у UTC, не включно.")
    reason: str = Field(description="Причина недоступності.")


class TimeBlockList(BaseModel):
    """Сторінка збережених блокувань власного ресурсу."""

    items: list[TimeBlockRead] = Field(description="Блокування від новіших до старіших.")
    pagination: OffsetPagination = Field(description="Метадані сторінки.")


class CalendarSlot(BaseModel):
    """Календар власного ресурсу без імен або ID студентів."""

    id: uuid.UUID = Field(description="ID слота.")
    starts_at: datetime = Field(description="Початок у UTC.")
    ends_at: datetime = Field(description="Кінець у UTC, не включно.")
    availability: Literal[
        "available", "booked", "blocked", "started", "completed", "outside_horizon"
    ] = Field(description="Стан інтервалу.")


class CalendarSummary(BaseModel):
    """Підрахунок усіх слотів діапазону до застосування пагінації."""

    total_slots: int = Field(description="Усі опубліковані активні слоти діапазону.")
    booked_slots: int = Field(description="Слоти з confirmed-бронюванням, включно з минулими.")
    blocked_slots: int = Field(description="Слоти, що перетинають блокування.")
    available_slots: int = Field(description="Вільні майбутні слоти в горизонті.")


class CalendarList(BaseModel):
    """Сторінка календаря із загальним навантаженням FR-015."""

    items: list[CalendarSlot] = Field(description="Інтервали за початком та ID.")
    summary: CalendarSummary = Field(description="Навантаження за весь обраний період.")
    pagination: OffsetPagination = Field(description="Метадані сторінки.")


class AuditEntry(BaseModel):
    """Адміністративна подія; читання не дозволяє її змінювати."""

    id: uuid.UUID | None = Field(description="Постійний UUID; null лише для старого демо-запису.")
    actor_id: uuid.UUID = Field(description="ID автора адміністративної дії.")
    actor_name: str = Field(description="Ім'я автора, доступне лише адміністратору.")
    action: str = Field(description="Машинна назва дії.")
    object_id: uuid.UUID | None = Field(description="ID об'єкта зміни.")
    before: dict | None = Field(description="Значення до зміни без секретів Auth.")
    after: dict | None = Field(description="Значення після зміни без секретів Auth.")
    at: datetime = Field(description="Момент події у UTC.")


class AuditList(BaseModel):
    """FR-068: відфільтровані записи від нових до старих."""

    items: list[AuditEntry] = Field(description="Події журналу.")
    pagination: OffsetPagination = Field(description="Метадані сторінки.")
