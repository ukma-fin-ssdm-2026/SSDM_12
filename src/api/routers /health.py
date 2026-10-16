"""Службова кінцева точка перевірки стану (поза версією контракту /api/v1)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from api.config import API_VERSION

TAG = {
    "name": "service",
    "description": "Службові операції: перевірка, що процес API живий. Не потребує автентифікації.",
}

router = APIRouter(tags=[TAG["name"]])


class HealthOut(BaseModel):
    """Стан процесу API."""

    status: Literal["ok"] = Field(description="`ok`, якщо процес приймає запити.")
    version: str = Field(description="Версія контракту API.", examples=[API_VERSION])


@router.get(
    "/health",
    response_model=HealthOut,
    summary="Перевірити, що API працює",
    response_description="Процес API працює й приймає запити.",
)
def get_health() -> HealthOut:
    """Повертає `ok` і версію контракту. Використовується моніторингом і healthcheck
    контейнера; не звертається до сховища, тож відповідає навіть за проблем із даними.
    """
    return HealthOut(status="ok", version=API_VERSION)
