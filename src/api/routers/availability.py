"""Блокування часу власного ресурсу та його зняття (US-009; FR-013, FR-014)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Body, Path, Response
from pydantic import UUID4

from api import clock
from api.config import API_PREFIX
from api.errors import ErrorCode, problem_responses
from api.infrastructure.unit_of_work import transactional
from api.schemas.availability import TemplateOut, TemplatePut, TimeBlockCreate, TimeBlockOut
from api.security import Provider
from api.stubs import availability_service as service
from api.stubs import template_service

TAG = {
    "name": "availability",
    "description": "Тижневі шаблони й блокування власного ресурсу (US-008/009).",
}
router = APIRouter(prefix=API_PREFIX, tags=[TAG["name"]])
ResourceId = Annotated[uuid.UUID, Path(description="Власний ресурс поточного провайдера.")]
BlockId = Annotated[uuid.UUID, Path(description="Ідентифікатор блокування цього ресурсу.")]
TemplateId = Annotated[UUID4, Path(description="UUIDv4 шаблону; для створення згенеруйте новий.")]
_ERRORS = (
    ErrorCode.AUTH_REQUIRED,
    ErrorCode.FORBIDDEN_ROLE,
    ErrorCode.NOT_OWNER,
    ErrorCode.RESOURCE_NOT_FOUND,
    ErrorCode.VALIDATION_FAILED,
)


@router.post(
    "/resources/{resource_id}/blocks",
    status_code=201,
    response_model=TimeBlockOut,
    summary="Заблокувати час ресурсу",
    response_description="Блокування та кількість скасувань.",
    responses=problem_responses(*_ERRORS, ErrorCode.SLOT_STARTED),
)
@transactional
def block_resource_time(
    resource_id: ResourceId,
    payload: Annotated[
        TimeBlockCreate,
        Body(
            openapi_examples={
                "meeting": {
                    "summary": "Засідання кафедри",
                    "value": {
                        "starts_at": "2027-02-15T10:00:00+02:00",
                        "ends_at": "2027-02-15T12:00:00+02:00",
                        "reason": "Засідання кафедри",
                    },
                },
            }
        ),
    ],
    provider: Provider,
) -> TimeBlockOut:
    """Створює блокування власного ресурсу. Майбутні бронювання, що перетинаються з ним,
    скасовуються з причиною провайдера, їхні нагадування видаляються. Якщо бронювання
    вже почалося, увесь запит відхиляється без змін (FR-045).
    """
    return service.create_block(provider, resource_id, payload, clock.utc_now())


@router.delete(
    "/resources/{resource_id}/blocks/{block_id}",
    status_code=204,
    summary="Зняти блокування ресурсу",
    response_description="Блокування видалено.",
    responses=problem_responses(*_ERRORS, ErrorCode.BLOCK_NOT_FOUND),
)
@transactional
def unblock_resource_time(
    resource_id: ResourceId, block_id: BlockId, provider: Provider
) -> Response:
    """Знімає блокування лише з власного ресурсу. Слоти знову доступні, якщо немає інших
    блокувань; раніше скасовані бронювання автоматично не відновлюються (US-009).
    """
    service.remove_block(provider, resource_id, block_id)
    return Response(status_code=204)


@router.put(
    "/resources/{resource_id}/templates/{template_id}",
    response_model=TemplateOut,
    summary="Задати тижневий шаблон",
    response_description="Шаблон та звіт генерації горизонту.",
    responses={
        201: {"model": TemplateOut, "description": "Шаблон створено."},
        **problem_responses(*_ERRORS, ErrorCode.TEMPLATE_NOT_FOUND),
    },
)
@transactional
def put_availability_template(
    resource_id: ResourceId,
    template_id: TemplateId,
    payload: Annotated[
        TemplatePut,
        Body(
            openapi_examples={
                "wednesday": {
                    "summary": "Щосереди 14–16 за Києвом, по 30 хв",
                    "value": {
                        "weekday": 3,
                        "start_local": "14:00",
                        "end_local": "16:00",
                        "slot_minutes": 30,
                        "valid_from": "2026-10-19",
                        "valid_to": None,
                    },
                },
            }
        ),
    ],
    response: Response,
    provider: Provider,
) -> TemplateOut:
    """Створює (201) або змінює (200) шаблон власного ресурсу й розгортає його на A-001.
    Заброньовані слоти зберігаються; незаброньовані майбутні слоти оновлюються.
    Конфліктні кандидати не створюються й перелічені у conflicts, інші створюються.
    """
    report, created = template_service.save_template(
        provider,
        resource_id,
        template_id,
        payload,
        clock.utc_now(),
    )
    if created:
        response.status_code = 201
    return report


@router.get(
    "/resources/{resource_id}/templates/{template_id}",
    response_model=TemplateOut,
    summary="Переглянути тижневий шаблон",
    response_description="Шаблон і поточні конфлікти.",
    responses=problem_responses(*_ERRORS, ErrorCode.TEMPLATE_NOT_FOUND),
)
@transactional
def get_availability_template(
    resource_id: ResourceId,
    template_id: TemplateId,
    provider: Provider,
) -> TemplateOut:
    """Повертає шаблон власного ресурсу й актуалізує його матеріалізовані слоти на
    поточний горизонт. Повторний виклик не дублює слоти; контакти студентів не повертаються.
    """
    return template_service.get_template(provider, resource_id, template_id, clock.utc_now())
