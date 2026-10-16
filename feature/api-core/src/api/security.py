"""Автентифікація й авторизація в API (Лаб 4: заглушка автентифікації).

Цільова схема — сесія з непрозорим токеном у cookie HttpOnly (DD-06). Swagger UI не
вміє надсилати cookie з діалогу «Authorize», а Керівник якості перевіряє валідацію
кожної кінцевої точки саме через Swagger UI. Тому в Лаб 4 автентифікація — демо-токени
в заголовку `Authorization: Bearer demo-<роль>`. Уся логіка в одному місці:
перехід на сесії змінить цей модуль, а специфікація оновиться сама.

Авторизація вже справжня: deny-by-default через `require_roles` на кожному
захищеному маршруті (FR-007, THR-04); власника об'єкта перевіряють сервіси (THR-03).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from api.config import get_settings
from api.enums import Role
from api.errors import ApiProblem, ErrorCode
from api.stubs.store import store

_WWW_AUTHENTICATE = {"WWW-Authenticate": 'Bearer realm="unislot"'}

demo_bearer = HTTPBearer(
    auto_error=False,
    scheme_name="demoBearer",
    description=(
        "**Лаб 4 — автентифікація-заглушка.** Передайте один із демо-токенів: "
        "`demo-student`, `demo-student-2`, `demo-provider`, `demo-provider-2`, `demo-admin`. "
        "Цільова схема — сесія в cookie HttpOnly (DD-06), з'явиться разом із модулем Auth."
    ),
)


@dataclass(frozen=True)
class CurrentUser:
    """Автентифікований користувач запиту."""

    id: uuid.UUID
    full_name: str
    email: str
    roles: frozenset[Role]


def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(demo_bearer)],
) -> CurrentUser:
    """Повертає користувача за токеном або відповідає 401 (AUTH_REQUIRED)."""
    if credentials is None:
        raise ApiProblem(
            ErrorCode.AUTH_REQUIRED,
            "Запит без заголовка Authorization: Bearer.",
            headers=_WWW_AUTHENTICATE,
        )
    if not get_settings().demo_auth_enabled:
        raise ApiProblem(
            ErrorCode.AUTH_REQUIRED,
            "Демо-автентифікацію вимкнено на цьому сервері.",
            headers=_WWW_AUTHENTICATE,
        )
    user = store.user_by_token(credentials.credentials)
    if user is None:
        raise ApiProblem(ErrorCode.AUTH_REQUIRED, "Невідомий токен.", headers=_WWW_AUTHENTICATE)
    request.state.user_id = str(user.id)  # для журналу запитів (middleware)
    return CurrentUser(user.id, user.full_name, user.email, user.roles)


def require_roles(*roles: Role) -> Callable[[CurrentUser], CurrentUser]:
    """Залежність маршруту: пропускає лише користувачів з однією з ролей (deny-by-default)."""
    allowed = frozenset(roles)
    names = ", ".join(sorted(r.value for r in allowed))

    def dependency(user: Annotated[CurrentUser, Depends(get_current_user)]) -> CurrentUser:
        if not user.roles & allowed:
            raise ApiProblem(ErrorCode.FORBIDDEN_ROLE, f"Операція доступна ролям: {names}.")
        return user

    return dependency


# Скорочення для сигнатур маршрутів.
AnyUser = Annotated[CurrentUser, Depends(get_current_user)]
Student = Annotated[CurrentUser, Depends(require_roles(Role.STUDENT))]
Provider = Annotated[CurrentUser, Depends(require_roles(Role.PROVIDER))]
Admin = Annotated[CurrentUser, Depends(require_roles(Role.ADMIN))]
