"""Заглушка доставки C-002: власна скринька, наповнювана окремим Worker."""

from fastapi import APIRouter

from api.config import API_PREFIX
from api.errors import ErrorCode, problem_responses
from api.infrastructure.unit_of_work import transactional
from api.pagination import DEFAULT_PAGE_SIZE, Limit, Offset, OffsetPagination
from api.schemas.notifications import NotificationList, NotificationOut
from api.security import AnyUser
from api.stubs.store import store

TAG = {"name": "notifications", "description": "Особиста скринька заглушки доставки (C-002)."}
router = APIRouter(prefix=API_PREFIX, tags=[TAG["name"]])


@router.get(
    "/me/notifications",
    response_model=NotificationList,
    summary="Переглянути власні сповіщення",
    response_description="Сторінка особистої скриньки.",
    responses=problem_responses(ErrorCode.AUTH_REQUIRED, ErrorCode.VALIDATION_FAILED),
)
@transactional
def list_my_notifications(
    user: AnyUser, limit: Limit = DEFAULT_PAGE_SIZE, offset: Offset = 0
) -> NotificationList:
    """Повертає лише доставлені Worker повідомлення поточному адресату. Скринька —
    контрольована заглушка замість e-mail за C-002; перегляд чужої черги не дозволено.
    """
    messages = sorted(
        (d for d in store.deliveries.values() if d["recipient_id"] == user.id),
        key=lambda d: (d["delivered_at"], str(d["id"])),
        reverse=True,
    )
    page = messages[offset : offset + limit]
    return NotificationList(
        items=[
            NotificationOut(**{k: v for k, v in item.items() if k != "recipient_id"})
            for item in page
        ],
        pagination=OffsetPagination(
            limit=limit,
            offset=offset,
            total=len(messages),
            has_more=offset + len(page) < len(messages),
        ),
    )
