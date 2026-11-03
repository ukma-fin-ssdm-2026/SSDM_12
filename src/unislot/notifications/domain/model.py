"""Outbox-повідомлення та повтори; незалежні від HTTP, ORM і зовнішньої доставки."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID


@dataclass
class Notification:
    """Доставка щонайменше один раз із постійним id як ключем ідемпотентності."""

    id: UUID
    booking_id: UUID
    recipient_id: UUID
    kind: str
    payload: dict[str, Any]
    scheduled_for: datetime
    status: str = "pending"
    attempts: int = 0
    locked_until: datetime | None = None
    claim_token: UUID | None = None
    sent_at: datetime | None = None
    last_error: str | None = None
    next_attempt_at: datetime | None = None


@dataclass(frozen=True)
class RetryPolicy:
    """Параметри обмеженого повтору; Worker задає їх явно."""

    max_attempts: int = 8
    base_delay: int = 5
    max_delay: int = 3600
    lease_seconds: int = 30

    def __post_init__(self) -> None:
        """Нульові чи від'ємні значення не утворюють працездатної черги."""
        if min(self.max_attempts, self.base_delay, self.max_delay, self.lease_seconds) <= 0:
            raise ValueError("retry policy values must be positive")

    def next_attempt(self, now: datetime, attempts: int) -> datetime:
        """Зростання затримки обмежене зверху; показник теж обмежено проти переповнення."""
        delay = min(self.max_delay, self.base_delay * 2 ** min(max(attempts - 1, 0), 30))
        return now + timedelta(seconds=delay)
