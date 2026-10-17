"""Модуль Auth у REST API: поточний користувач (FR-007).

Реєстрація й вхід (FR-001…FR-006) з'являться разом із модулем Auth; у Лаб 4 особу
визначає демо-токен (див. `api.security`).
"""

from __future__ import annotations

from fastapi import APIRouter

from api.config import API_PREFIX
from api.errors import ErrorCode, problem_responses
from api.schemas.auth import MeOut
from api.security import AnyUser

TAG = {
    "name": "auth",
    "description": "Хто я і які маю ролі (FR-007). Реєстрація й вхід — разом із модулем Auth.",
}

router = APIRouter(prefix=f"{API_PREFIX}/auth", tags=[TAG["name"]])


@router.get(
    "/me",
    response_model=MeOut,
    summary="Отримати поточного користувача",
    response_description="Поточний користувач і його ролі.",
    responses=problem_responses(ErrorCode.AUTH_REQUIRED),
)
def get_me(user: AnyUser) -> MeOut:
    """Повертає ідентифікатор, ім'я, e-mail і ролі користувача, від імені якого надіслано
    запит. Клієнт використовує ролі, щоб показати лише доступні дії; перевіряє права
    все одно сервер (deny-by-default).
    """
    return MeOut(
        id=user.id,
        full_name=user.full_name,
        email=user.email,
        roles=sorted(user.roles, key=lambda r: r.value),
    )
