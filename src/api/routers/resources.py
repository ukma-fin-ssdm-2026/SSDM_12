"""Ресурси: каталог для всіх ролей і адміністрування (US-011; FR-021, FR-060, FR-061)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Body, Path, Query, Response

from api.config import API_PREFIX
from api.enums import ResourceType
from api.errors import ErrorCode, FieldError, problem_responses
from api.pagination import DEFAULT_PAGE_SIZE, Limit, Offset, OffsetPagination
from api.schemas.resources import ResourceCreate, ResourceList, ResourceOut, ResourceUpdate
from api.security import Admin, AnyUser
from api.stubs import resource_service as service
from api.stubs.store import Ids

TAG = {
    "name": "resources",
    "description": "Каталог консультацій і аудиторій (FR-021, FR-060) та керування ними "
    "адміністратором (US-011: FR-060, FR-061).",
}

router = APIRouter(prefix=API_PREFIX, tags=[TAG["name"]])

# Іменовані приклади: Swagger UI показує їх списком і підставляє значення в поле.
ResourceId = Annotated[
    uuid.UUID,
    Path(
        description="Ідентифікатор ресурсу (UUID).",
        openapi_examples={
            "room": {"summary": "Аудиторія 1-225 (місткість 30)", "value": str(Ids.RES_ROOM_1_225)},
            "consultation": {
                "summary": "Консультація з баз даних (без місткості)",
                "value": str(Ids.RES_DB_CONSULT),
            },
        },
    ),
]
_LOCATION = {
    "Location": {"description": "Адреса створеного ресурсу.", "schema": {"type": "string"}}
}


@router.get(
    "/resources",
    response_model=ResourceList,
    summary="Переглянути каталог ресурсів",
    response_description="Сторінка каталогу ресурсів.",
    responses=problem_responses(
        ErrorCode.AUTH_REQUIRED,
        ErrorCode.VALIDATION_FAILED,
        field_error=FieldError(
            field="query.limit",
            message="Input should be less than or equal to 100",
            type="less_than_equal",
        ),
    ),
)
def list_resources(
    user: AnyUser,
    resource_type: Annotated[
        ResourceType | None, Query(alias="type", description="Лише ресурси цього типу.")
    ] = None,
    provider_id: Annotated[
        uuid.UUID | None, Query(description="Лише ресурси цього провайдера.")
    ] = None,
    limit: Limit = DEFAULT_PAGE_SIZE,
    offset: Offset = 0,
) -> ResourceList:
    """Каталог ресурсів із фільтрами за типом і провайдером. Використовується для вибору
    фільтрів пошуку (FR-021). Пагінація за зсувом: каталог малий, а інтерфейсу потрібна
    загальна кількість (`total`).
    """
    items, total = service.list_resources(resource_type, provider_id, limit, offset)
    return ResourceList(
        items=[service.to_out(r) for r in items],
        pagination=OffsetPagination(
            limit=limit, offset=offset, total=total, has_more=offset + len(items) < total
        ),
    )


@router.get(
    "/resources/{resource_id}",
    response_model=ResourceOut,
    summary="Отримати ресурс",
    response_description="Ресурс із провайдером.",
    responses=problem_responses(
        ErrorCode.AUTH_REQUIRED,
        ErrorCode.RESOURCE_NOT_FOUND,
        ErrorCode.VALIDATION_FAILED,
        field_error=FieldError(
            field="path.resource_id",
            type="uuid_parsing",
            message="Input should be a valid UUID, invalid length: found 3",
        ),
    ),
)
def get_resource(resource_id: ResourceId, user: AnyUser) -> ResourceOut:
    """Повертає один ресурс каталогу з провайдером. Неіснуючий ідентифікатор — 404."""
    return service.to_out(service.get_resource(resource_id))


@router.post(
    "/admin/resources",
    status_code=201,
    response_model=ResourceOut,
    summary="Створити ресурс (адміністратор)",
    response_description="Ресурс створено; заголовок Location містить його адресу.",
    responses={
        201: {"headers": _LOCATION},
        **problem_responses(
            ErrorCode.AUTH_REQUIRED,
            ErrorCode.FORBIDDEN_ROLE,
            ErrorCode.VALIDATION_FAILED,
            ErrorCode.PROVIDER_NOT_ELIGIBLE,
            field_error=FieldError(
                field="body.capacity",
                type="value_error",
                message="Value error, для аудиторії (room) місткість обов'язкова",
            ),
        ),
    },
)
def create_resource(
    payload: Annotated[
        ResourceCreate,
        Body(
            openapi_examples={
                "room": {
                    "summary": "Аудиторія з місткістю",
                    "value": {
                        "name": "Аудиторія 2-110",
                        "type": "room",
                        "capacity": 24,
                        "provider_id": str(Ids.PROVIDER_2),
                    },
                },
                "consultation": {
                    "summary": "Консультація без місткості",
                    "value": {
                        "name": "Консультація з алгоритмів",
                        "type": "consultation",
                        "provider_id": str(Ids.PROVIDER),
                    },
                },
                "not_provider": {
                    "summary": "Помилка: провайдер — студент (422)",
                    "value": {
                        "name": "Аудиторія 2-111",
                        "type": "room",
                        "capacity": 20,
                        "provider_id": str(Ids.STUDENT),
                    },
                },
            }
        ),
    ],
    response: Response,
    admin: Admin,
) -> ResourceOut:
    """Створює консультацію або аудиторію й призначає провайдера (FR-060, FR-061).
    Місткість обов'язкова лише для аудиторії (INV-08); провайдер має мати роль
    «провайдер» (INV-15). Дія потрапляє в журнал аудиту (FR-066).
    """
    rec = service.create_resource(admin, payload)
    response.headers["Location"] = f"{API_PREFIX}/resources/{rec.id}"
    return service.to_out(rec)


@router.patch(
    "/admin/resources/{resource_id}",
    response_model=ResourceOut,
    summary="Змінити ресурс (адміністратор)",
    response_description="Ресурс після змін.",
    responses=problem_responses(
        ErrorCode.AUTH_REQUIRED,
        ErrorCode.FORBIDDEN_ROLE,
        ErrorCode.RESOURCE_NOT_FOUND,
        ErrorCode.VALIDATION_FAILED,
        ErrorCode.PROVIDER_NOT_ELIGIBLE,
        field_error=FieldError(
            field="body.name",
            type="value_error",
            message="Value error, поле не може бути null; щоб не змінювати "
            "його, не передавайте поле",
        ),
    ),
)
def update_resource(
    resource_id: ResourceId,
    payload: Annotated[
        ResourceUpdate,
        Body(
            openapi_examples={
                "capacity": {"summary": "Змінити місткість аудиторії", "value": {"capacity": 28}},
                "provider": {
                    "summary": "Призначити іншого провайдера",
                    "value": {"provider_id": str(Ids.PROVIDER)},
                },
                "null_name": {"summary": "Помилка: name = null (422)", "value": {"name": None}},
            }
        ),
    ],
    admin: Admin,
) -> ResourceOut:
    """Змінює лише передані поля (семантика PATCH): відсутнє поле не чіпається, а `null`
    для обов'язкового поля — помилка 422, а не «тихе» ігнорування. Тип ресурсу змінити
    не можна. Дія потрапляє в журнал аудиту з попередніми й новими значеннями (FR-066).
    """
    changes = payload.model_dump(exclude_unset=True)
    return service.to_out(service.update_resource(admin, resource_id, changes))
