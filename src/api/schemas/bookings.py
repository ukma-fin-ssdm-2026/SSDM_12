"""Схеми бронювань (US-001, US-002, US-003, US-014)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from api.enums import BookingState, CancellationKind
from api.pagination import OffsetPagination
from api.schemas.common import PersonSummary, ResourceSummary
from api.stubs.store import Ids


class BookingCreate(BaseModel):
    """Запит на бронювання вільного слота."""

    model_config = ConfigDict(
        extra="forbid", json_schema_extra={"examples": [{"slot_id": str(Ids.SLOT_DB_D1_1030)}]}
    )

    slot_id: uuid.UUID = Field(description="Слот, який бронює студент (з результатів пошуку).")


class BookingReschedule(BaseModel):
    """Запит на перенесення бронювання на інший слот."""

    model_config = ConfigDict(
        extra="forbid", json_schema_extra={"examples": [{"new_slot_id": str(Ids.SLOT_DB_D2_1030)}]}
    )

    new_slot_id: uuid.UUID = Field(description="Вільний слот, на який переноситься бронювання.")


class BookingSlot(BaseModel):
    """Час слота бронювання."""

    id: uuid.UUID = Field(description="Ідентифікатор слота.")
    starts_at: datetime = Field(description="Початок, UTC.")
    ends_at: datetime = Field(description="Кінець, UTC.")


class BookingOut(BaseModel):
    """Бронювання з погляду його власника-студента."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": str(Ids.BOOKING_ACTIVE),
                    "state": "active",
                    "slot": {
                        "id": str(Ids.SLOT_DB_D2_1000),
                        "starts_at": "2026-10-21T07:00:00Z",
                        "ends_at": "2026-10-21T07:30:00Z",
                    },
                    "resource": {
                        "id": str(Ids.RES_DB_CONSULT),
                        "name": "Консультація з баз даних",
                        "type": "consultation",
                        "capacity": None,
                    },
                    "provider": {"id": str(Ids.PROVIDER), "full_name": "Ірина Шевченко"},
                    "cancel_deadline_at": "2026-10-21T05:00:00Z",
                    "can_cancel": True,
                    "created_at": "2026-10-19T09:15:00Z",
                }
            ]
        }
    )

    id: uuid.UUID = Field(description="Ідентифікатор бронювання (UUID).")
    state: BookingState = Field(
        description="Похідний стан: active — слот ще не почався; in_progress — триває (AQ-05); "
        "completed — завершився; cancelled — скасоване."
    )
    slot: BookingSlot = Field(description="Слот бронювання.")
    resource: ResourceSummary = Field(description="Ресурс слота.")
    provider: PersonSummary = Field(description="Провайдер ресурсу.")
    cancel_deadline_at: datetime = Field(
        description="Граничний час скасування й перенесення, UTC. Фіксується під час "
        "бронювання й не змінюється, якщо адміністратор змінить політику (FR-041, FR-065)."
    )
    can_cancel: bool = Field(
        description="Чи можна зараз скасувати або перенести бронювання (стан active і граничний "
        "час ще не минув). Інтерфейс показує дії лише тоді, коли true (US-014)."
    )
    created_at: datetime = Field(description="Коли створено бронювання, UTC.")
    cancelled_at: datetime | None = Field(
        default=None, description="Коли скасовано; лише для cancelled."
    )
    cancellation_kind: CancellationKind | None = Field(
        default=None, description="Хто або що скасувало: student, provider_block, rescheduled."
    )
    cancellation_reason: str | None = Field(
        default=None, description="Причина від провайдера; лише для provider_block (FR-014)."
    )
    rescheduled_to_id: uuid.UUID | None = Field(
        default=None, description="Нове бронювання, якщо це бронювання перенесено (FR-043)."
    )


class BookingList(BaseModel):
    """Сторінка власних бронювань студента."""

    items: list[BookingOut] = Field(
        description="Бронювання: спершу активні й ті, що тривають (найближчі першими), "
        "потім завершені й скасовані (найновіші першими) — US-014."
    )
    pagination: OffsetPagination = Field(description="Метадані сторінки.")
