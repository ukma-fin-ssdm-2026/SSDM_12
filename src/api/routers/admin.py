"""Адміністративні операції HLD §5.1: ролі й версії політик (FR-062…FR-065)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Body, Path

from api.config import API_PREFIX
from api.enums import Role
from api.errors import ErrorCode, problem_responses
from api.infrastructure.unit_of_work import transactional
from api.schemas.admin import ManagedRole, PolicyOut, PolicyUpdate, UserRolesOut
from api.security import Admin
from api.stubs import admin_service as service

TAG = {"name": "admin", "description": "Ролі користувачів і політики бронювання (FR-062…065)."}
router = APIRouter(prefix=f"{API_PREFIX}/admin", tags=[TAG["name"]])
UserId = Annotated[uuid.UUID, Path(description="Ідентифікатор користувача, чиї ролі змінюються.")]
RoleId = Annotated[ManagedRole, Path(description="Керована роль: provider або admin.")]
_AUTH_ERRORS = (ErrorCode.AUTH_REQUIRED, ErrorCode.FORBIDDEN_ROLE)
_ROLE_ERRORS = (*_AUTH_ERRORS, ErrorCode.USER_NOT_FOUND, ErrorCode.VALIDATION_FAILED)


@router.put(
    "/users/{user_id}/roles/{role}",
    response_model=UserRolesOut,
    summary="Призначити керовану роль",
    response_description="Чинні ролі користувача.",
    responses=problem_responses(*_ROLE_ERRORS),
)
@transactional
def grant_user_role(user_id: UserId, role: RoleId, admin: Admin) -> UserRolesOut:
    """Додає роль provider чи admin до наявних ролей (FR-062). Повторне призначення
    не дублює роль або аудит. Нові права видимі з наступного запиту користувача.
    """
    return service.change_role(admin, user_id, Role(role), grant=True)


@router.delete(
    "/users/{user_id}/roles/{role}",
    response_model=UserRolesOut,
    summary="Відкликати керовану роль",
    response_description="Ролі після відкликання.",
    responses=problem_responses(
        *_ROLE_ERRORS, ErrorCode.LAST_ADMIN, ErrorCode.PROVIDER_HAS_RESOURCES
    ),
)
@transactional
def revoke_user_role(user_id: UserId, role: RoleId, admin: Admin) -> UserRolesOut:
    """Знімає роль, зберігаючи інші (FR-062). Останнього адміністратора захищає FR-063;
    роль провайдера не відкликається, доки за ним закріплено ресурс (INV-15, AQ-02).
    """
    return service.change_role(admin, user_id, Role(role), grant=False)


@router.get(
    "/policies/current",
    response_model=PolicyOut,
    summary="Переглянути поточну політику",
    response_description="Поточні значення A-002 і A-003.",
    responses=problem_responses(*_AUTH_ERRORS),
)
@transactional
def get_current_policy(admin: Admin) -> PolicyOut:
    """Повертає чинну версію політики з її UUID. Читання доступне лише адміністратору;
    значення використовуються під час створення нових бронювань (FR-064, FR-065).
    """
    return service.current_policy(admin)


@router.put(
    "/policies/current",
    response_model=PolicyOut,
    summary="Змінити політику бронювання",
    response_description="Чинна версія після заміни.",
    responses=problem_responses(*_AUTH_ERRORS, ErrorCode.VALIDATION_FAILED),
)
@transactional
def replace_current_policy(
    payload: Annotated[
        PolicyUpdate,
        Body(
            openapi_examples={
                "standard": {
                    "summary": "Ліміт 3, вікно 2 години",
                    "value": {"booking_limit": 3, "cancel_window_minutes": 120},
                },
                "changed": {
                    "summary": "Ліміт 5, вікно 3 години",
                    "value": {"booking_limit": 5, "cancel_window_minutes": 180},
                },
            }
        ),
    ],
    admin: Admin,
) -> PolicyOut:
    """Змінює обидва значення політики й додає аудит (FR-064). Новий UUID та значення
    застосовуються лише до наступних бронювань; старі дедлайни не перераховуються (FR-065).
    """
    return service.update_policy(admin, payload)
