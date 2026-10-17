"""Слоти: пошук вільних (US-004; FR-020…FR-023) і публікація разових (US-007; FR-010, FR-011)."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Body, Path, Query, Response

from api import clock
from api.config import API_PREFIX
from api.enums import ResourceType
from api.errors import ErrorCode, FieldError, problem_responses
from api.pagination import DEFAULT_PAGE_SIZE, CursorPagination, Limit
from api.schemas.slots import SlotCreate, SlotDetail, SlotList
from api.security import AnyUser, Provider, Student
from api.stubs import slot_service as service
from api.stubs.store import Ids

TAG = {
    "name": "slots",
    "description": "Пошук вільних слотів із фільтрами (US-004) і публікація разових слотів "
    "провайдером (US-007).",
}

router = APIRouter(prefix=API_PREFIX, tags=[TAG["name"]])

_LOCATION = {"Location": {"description": "Адреса створеного слота.", "schema": {"type": "string"}}}


@router.get(
    "/slots",
    response_model=SlotList,
    summary="Знайти вільні слоти",
    response_description="Сторінка вільних слотів і курсор наступної сторінки.",
    responses=problem_responses(
        ErrorCode.AUTH_REQUIRED,
        ErrorCode.FORBIDDEN_ROLE,
        ErrorCode.VALIDATION_FAILED,
        ErrorCode.DATE_OUT_OF_HORIZON,
        field_error=FieldError(
            field="query.limit",
            message="Input should be less than or equal to 100",
            type="less_than_equal",
        ),
    ),
)
def search_free_slots(
    student: Student,
    provider_id: Annotated[
        uuid.UUID | None,
        Query(
            description="Лише слоти ресурсів цього провайдера.",
            openapi_examples={
                "provider": {
                    "summary": "Ірина Шевченко (demo-provider)",
                    "value": str(Ids.PROVIDER),
                },
                "provider_2": {
                    "summary": "Олег Бондар (demo-provider-2)",
                    "value": str(Ids.PROVIDER_2),
                },
            },
        ),
    ] = None,
    resource_type: Annotated[
        ResourceType | None, Query(description="Лише слоти ресурсів цього типу.")
    ] = None,
    day: Annotated[
        date | None,
        Query(
            alias="date",
            description="Дата за київським часом (A-007), від сьогодні до кінця горизонту A-001.",
        ),
    ] = None,
    min_capacity: Annotated[
        int | None,
        Query(
            ge=1,
            le=1000,
            description="Мінімальна місткість. Застосовується лише до аудиторій: "
            "якщо задано, консультації в результати не потрапляють (FR-022).",
        ),
    ] = None,
    limit: Limit = DEFAULT_PAGE_SIZE,
    cursor: Annotated[
        str | None,
        Query(
            max_length=256, description="Курсор із `pagination.next_cursor` попередньої сторінки."
        ),
    ] = None,
) -> SlotList:
    """Повертає лише **вільні** слоти в межах горизонту A-001: без зайнятих, заблокованих
    і тих, що вже почалися (FR-020, FR-023). Фільтри комбінуються через «і» (FR-021).
    Порядок — за часом початку. Пагінація курсором: набір вільних слотів змінюється,
    поки користувач гортає, і зсув пропускав би або дублював слоти.
    """
    items, next_cursor = service.search_free(
        now=clock.utc_now(),
        provider_id=provider_id,
        resource_type=resource_type,
        day=day,
        min_capacity=min_capacity,
        limit=limit,
        cursor=cursor,
    )
    return SlotList(
        items=[service.to_out(s) for s in items],
        pagination=CursorPagination(
            limit=limit, next_cursor=next_cursor, has_more=next_cursor is not None
        ),
    )


@router.get(
    "/slots/{slot_id}",
    response_model=SlotDetail,
    summary="Отримати слот",
    response_description="Слот і ознака, чи можна його забронювати зараз.",
    responses=problem_responses(
        ErrorCode.AUTH_REQUIRED,
        ErrorCode.SLOT_NOT_FOUND,
        ErrorCode.VALIDATION_FAILED,
        field_error=FieldError(
            field="path.slot_id",
            type="uuid_parsing",
            message="Input should be a valid UUID, invalid length: found 3",
        ),
    ),
)
def get_slot(
    slot_id: Annotated[
        uuid.UUID,
        Path(
            description="Ідентифікатор слота (UUID).",
            openapi_examples={
                "free": {"summary": "Вільний слот", "value": str(Ids.SLOT_DB_D1_1030)},
                "taken": {
                    "summary": "Зайнятий слот (available = false)",
                    "value": str(Ids.SLOT_DB_D1_1000),
                },
            },
        ),
    ],
    user: AnyUser,
) -> SlotDetail:
    """Повертає слот і поле `available` — чи можна забронювати його зараз. Чи зайнятий
    слот, видно, а ким — ні (SEC-004).
    """
    return service.to_detail(service.get_slot(slot_id), clock.utc_now())


@router.post(
    "/resources/{resource_id}/slots",
    status_code=201,
    response_model=SlotDetail,
    summary="Опублікувати разовий слот (провайдер)",
    response_description="Слот створено; заголовок Location містить його адресу.",
    responses={
        201: {"headers": _LOCATION},
        **problem_responses(
            ErrorCode.AUTH_REQUIRED,
            ErrorCode.FORBIDDEN_ROLE,
            ErrorCode.NOT_OWNER,
            ErrorCode.RESOURCE_NOT_FOUND,
            ErrorCode.SLOT_OVERLAP,
            ErrorCode.VALIDATION_FAILED,
            ErrorCode.SLOT_IN_PAST,
            field_error=FieldError(
                field="body.duration_minutes",
                type="multiple_of",
                message="Input should be a multiple of 5",
            ),
        ),
    },
)
def create_slot(
    resource_id: Annotated[
        uuid.UUID,
        Path(
            description="Ресурс провайдера, на якому створюється слот.",
            openapi_examples={
                "own": {
                    "summary": "Власний ресурс demo-provider: консультація з баз даних",
                    "value": str(Ids.RES_DB_CONSULT),
                },
                "foreign": {
                    "summary": "Ресурс іншого провайдера (demo-provider-2) → 403",
                    "value": str(Ids.RES_NET_CONSULT),
                },
            },
        ),
    ],
    payload: Annotated[
        SlotCreate,
        Body(
            openapi_examples={
                "ok": {
                    "summary": "30 хвилин, київський час",
                    "value": {"starts_at": "2027-02-15T10:00:00+02:00", "duration_minutes": 30},
                },
                "bad_duration": {
                    "summary": "Помилка: тривалість 17 хв (422)",
                    "value": {"starts_at": "2027-02-15T10:00:00+02:00", "duration_minutes": 17},
                },
                "naive_time": {
                    "summary": "Помилка: час без часового поясу (422)",
                    "value": {"starts_at": "2027-02-15T10:00:00", "duration_minutes": 30},
                },
            }
        ),
    ],
    response: Response,
    provider: Provider,
) -> SlotDetail:
    """Створює разовий слот на **власному** ресурсі провайдера (FR-010). Тривалість —
    у межах A-005, початок — у майбутньому. Слот, що перетинається з наявним слотом
    ресурсу, відхиляється (409, FR-011); суміжні слоти дозволені.
    """
    now = clock.utc_now()
    slot = service.create_slot(provider, resource_id, payload, now)
    response.headers["Location"] = f"{API_PREFIX}/slots/{slot.id}"
    return service.to_detail(slot, now)
