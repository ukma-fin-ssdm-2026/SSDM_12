"""Схеми блокування часу провайдером (FR-013, FR-014)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time
from typing import Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from api.policy import SLOT_MAX_MINUTES, SLOT_MIN_MINUTES, SLOT_STEP_MINUTES
from unislot.availability.domain.templates import WeeklyPattern


class TimeBlockCreate(BaseModel):
    """Непорожній напіввідкритий проміжок із обов'язковою причиною."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    starts_at: AwareDatetime = Field(description="Початок блокування з часовим поясом.")
    ends_at: AwareDatetime = Field(description="Кінець блокування, пізніше за початок.")
    reason: str = Field(min_length=1, max_length=500, description="Причина скасування бронювань.")

    @model_validator(mode="after")
    def increasing_interval(self) -> Self:
        """Порожній чи перевернутий проміжок не блокує жодного часу."""
        if self.ends_at.astimezone(UTC) <= self.starts_at.astimezone(UTC):
            raise ValueError("ends_at має бути пізніше за starts_at")
        return self


class TimeBlockOut(BaseModel):
    """Блокування без персональних даних студентів у скасованих бронюваннях."""

    id: uuid.UUID = Field(description="Ідентифікатор блокування для подальшого зняття.")
    resource_id: uuid.UUID = Field(description="Ресурс провайдера.")
    starts_at: datetime = Field(description="Початок у UTC.")
    ends_at: datetime = Field(description="Кінець у UTC; не належить проміжку.")
    reason: str = Field(description="Причина недоступності ресурсу.")
    cancelled_bookings: int = Field(description="Кількість скасованих бронювань; без їхніх ID.")


class TemplatePut(BaseModel):
    """Один тижневий проміжок, який складається з цілих слотів (US-008)."""

    model_config = ConfigDict(extra="forbid")

    weekday: int = Field(strict=True, ge=1, le=7, description="День ISO: понеділок 1, неділя 7.")
    start_local: time = Field(description="Початок за Europe/Kyiv, без UTC-зсуву, HH:MM.")
    end_local: time = Field(description="Кінець того самого локального дня, HH:MM.")
    slot_minutes: int = Field(
        strict=True,
        ge=SLOT_MIN_MINUTES,
        le=SLOT_MAX_MINUTES,
        multiple_of=SLOT_STEP_MINUTES,
        description="Тривалість слота за A-005.",
    )
    valid_from: date = Field(description="Перша локальна дата дії шаблону, включно.")
    valid_to: date | None = Field(
        default=None, description="Остання дата дії включно; null — без кінця."
    )

    @field_validator("start_local", "end_local", mode="before")
    @classmethod
    def local_time_format(cls, value: object) -> object:
        """Число секунд від опівночі не є прийнятим форматом цього API."""
        if not isinstance(value, str | time):
            raise ValueError("час має бути рядком HH:MM")
        return value

    @model_validator(mode="after")
    def valid_pattern(self) -> Self:
        """Перевіряє локальний проміжок тими самими правилами, що й генератор."""
        self.to_pattern()
        return self

    def to_pattern(self) -> WeeklyPattern:
        """Передає домену перевірені значення без залежності домену від Pydantic."""
        return WeeklyPattern(
            self.weekday,
            self.start_local,
            self.end_local,
            self.slot_minutes,
            self.valid_from,
            self.valid_to,
        )


class TemplateConflict(BaseModel):
    """Негенерований кандидат: перетин зі слотом або неоднозначний локальний час."""

    code: str = Field(
        description="slot_overlap, ambiguous_local_time, nonexistent_local_time або dst_duration."
    )
    day: date = Field(description="Дата кандидата за Києвом.")
    start_local: time = Field(description="Початок кандидата в локальному часі.")
    conflicting_slot_id: uuid.UUID | None = Field(
        default=None, description="Слот, що заважає; без даних бронювання."
    )


class TemplateOut(TemplatePut):
    """Шаблон і звіт генерації поточного горизонту."""

    id: uuid.UUID = Field(description="Ідентифікатор шаблону, який задав клієнт.")
    resource_id: uuid.UUID = Field(description="Ресурс провайдера.")
    created_slots: int = Field(description="Кількість слотів, доданих цим прогоном.")
    withdrawn_slots: int = Field(
        description="Кількість майбутніх незаброньованих слотів, відкликаних зміною."
    )
    retained_booked_slots: int = Field(
        description="Кількість збережених майбутніх заброньованих слотів шаблону."
    )
    conflicts: list[TemplateConflict] = Field(
        description="Кандидати, що не створені; інші слоти згенеровано."
    )
