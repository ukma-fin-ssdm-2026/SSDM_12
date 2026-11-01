"""Особиста скринька C-002: лише доставлені поточному користувачу повідомлення."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from api.pagination import OffsetPagination


class NotificationOut(BaseModel):
    """Одне повідомлення без доступу до адресатів чи черги інших людей."""

    id: uuid.UUID = Field(description="Ключ ідемпотентності доставки.")
    kind: str = Field(description="Вид: confirmation, reminder, cancelled або подія провайдера.")
    payload: dict[str, Any] = Field(description="Дата, час, ресурс і причина події за потреби.")
    delivered_at: datetime = Field(description="Момент доставки у заглушку скриньки, UTC.")


class NotificationList(BaseModel):
    """Сторінка особистої скриньки, нові повідомлення першими."""

    items: list[NotificationOut] = Field(description="Лише повідомлення поточного адресата.")
    pagination: OffsetPagination = Field(description="Параметри сторінки та загальна кількість.")
