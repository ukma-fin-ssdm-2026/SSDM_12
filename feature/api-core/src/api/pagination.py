"""Пагінація списків: зсув (offset) для малих каталогів, курсор для пошуку слотів.

Правило вибору — Лекція 4, §3.3:
- каталог ресурсів і «мої бронювання» малі, а інтерфейсу потрібна загальна кількість →
  `limit` + `offset`, у відповіді `total`;
- пошук слотів — найбільший і найчастіший запит (PERF-001), а набір вільних слотів
  змінюється, поки користувач гортає (слоти бронюють) → курсор за `(starts_at, id)`:
  зсув на такому наборі пропускав би або дублював рядки.

В обох випадках розмір сторінки обмежено: щонайбільше 100 елементів.
"""

from __future__ import annotations

import base64
import binascii
import json
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import Query
from pydantic import BaseModel, Field

from api.errors import ApiProblem, ErrorCode

MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 20

Limit = Annotated[
    int,
    Query(ge=1, le=MAX_PAGE_SIZE, description=f"Скільки елементів повернути (1–{MAX_PAGE_SIZE})."),
]
Offset = Annotated[
    int, Query(ge=0, le=10_000, description="Скільки елементів пропустити від початку списку.")
]


class OffsetPagination(BaseModel):
    """Метадані сторінки за зсувом."""

    limit: int = Field(description="Розмір сторінки, який застосовано.", examples=[20])
    offset: int = Field(description="Скільки елементів пропущено.", examples=[0])
    total: int = Field(description="Скільки елементів у списку загалом.", examples=[4])
    has_more: bool = Field(description="Чи є ще елементи після цієї сторінки.", examples=[False])


class CursorPagination(BaseModel):
    """Метадані сторінки за курсором."""

    limit: int = Field(description="Розмір сторінки, який застосовано.", examples=[20])
    next_cursor: str | None = Field(
        description="Непрозорий курсор наступної сторінки; null, якщо сторінка остання.",
        examples=["eyJzIjoiMjAyNi0xMC0yMFQwODozMDowMCswMDowMCIsImkiOiIuLi4ifQ"],
    )
    has_more: bool = Field(description="Чи є наступна сторінка.", examples=[True])


def encode_cursor(starts_at: datetime, item_id: uuid.UUID) -> str:
    """Курсор = base64url від позиції останнього елемента сторінки. Клієнт його не розбирає."""
    raw = json.dumps({"s": starts_at.isoformat(), "i": str(item_id)}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    """Розбирає курсор; зіпсований курсор — помилка валідації параметра `cursor` (422)."""
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode()))
        starts_at, item_id = datetime.fromisoformat(data["s"]), uuid.UUID(data["i"])
        if starts_at.tzinfo is None:
            raise ValueError("cursor time without timezone")
        return starts_at, item_id
    except (ValueError, KeyError, TypeError, binascii.Error) as exc:
        raise ApiProblem(
            ErrorCode.VALIDATION_FAILED,
            "Курсор пошкоджений або отриманий не з цього API.",
            errors=[
                {"field": "query.cursor", "message": "Invalid cursor", "type": "cursor_invalid"}
            ],
        ) from exc
