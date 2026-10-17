"""Схеми слотів: пошук вільних (US-004) і публікація разових слотів (US-007)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from api.pagination import CursorPagination
from api.policy import SLOT_MAX_MINUTES, SLOT_MIN_MINUTES, SLOT_STEP_MINUTES
from api.schemas.common import PersonSummary, ResourceSummary
from api.stubs.store import Ids

_SLOT_EXAMPLE = {
    "id": str(Ids.SLOT_DB_D1_1030),
    "starts_at": "2026-10-20T07:30:00Z",
    "ends_at": "2026-10-20T08:00:00Z",
    "duration_minutes": 30,
    "resource": {
        "id": str(Ids.RES_DB_CONSULT),
        "name": "Консультація з баз даних",
        "type": "consultation",
        "capacity": None,
    },
    "provider": {"id": str(Ids.PROVIDER), "full_name": "Ірина Шевченко"},
}


class SlotOut(BaseModel):
    """Слот у результатах пошуку."""

    model_config = ConfigDict(json_schema_extra={"examples": [_SLOT_EXAMPLE]})

    id: uuid.UUID = Field(description="Ідентифікатор слота (UUID).")
    starts_at: datetime = Field(description="Початок слота, UTC (A-007).")
    ends_at: datetime = Field(description="Кінець слота, UTC; не належить слоту (півінтервал).")
    duration_minutes: int = Field(description="Тривалість у хвилинах (A-005).")
    resource: ResourceSummary = Field(description="Ресурс, на якому слот.")
    provider: PersonSummary = Field(description="Провайдер ресурсу.")


class SlotDetail(SlotOut):
    """Один слот із ознакою, чи можна його забронювати зараз."""

    model_config = ConfigDict(
        json_schema_extra={"examples": [{**_SLOT_EXAMPLE, "available": True}]}
    )

    available: bool = Field(
        description="Чи вільний слот для бронювання зараз: не зайнятий, не заблокований, ще не "
        "почався й у межах горизонту A-001. Хто забронював слот, не розкривається."
    )


class SlotList(BaseModel):
    """Сторінка результатів пошуку вільних слотів."""

    items: list[SlotOut] = Field(description="Вільні слоти за зростанням часу початку.")
    pagination: CursorPagination = Field(description="Курсор наступної сторінки.")


class SlotCreate(BaseModel):
    """Новий разовий слот на ресурсі провайдера (FR-010)."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [{"starts_at": "2027-02-15T10:00:00+02:00", "duration_minutes": 30}]
        },
    )

    starts_at: AwareDatetime = Field(
        description="Початок слота з часовим поясом (RFC 3339), наприклад +02:00 для Києва взимку. "
        "Час без поясу відхиляється."
    )
    duration_minutes: int = Field(
        ge=SLOT_MIN_MINUTES,
        le=SLOT_MAX_MINUTES,
        multiple_of=SLOT_STEP_MINUTES,
        description=f"Тривалість: {SLOT_MIN_MINUTES}–{SLOT_MAX_MINUTES} хв із кроком "
        f"{SLOT_STEP_MINUTES} хв (A-005).",
    )
