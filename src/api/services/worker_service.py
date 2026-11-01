"""Фонове розширення горизонту незалежно від відвідування Web UI."""

from datetime import datetime

from sqlalchemy import exists, select
from sqlalchemy.dialects.postgresql import insert

from api.infrastructure import tables as t
from api.policy import KYIV
from api.stubs.store import store
from api.stubs.template_service import extend_horizon


def refresh_horizon(now: datetime) -> int:
    """Одна транзакція; паралельні Worker не дублюють слоти шаблонів."""
    with store.lock:
        before = set(store.slots)
        extend_horizon(now)
        if store.persistent:
            store.lock.connection.execute(
                insert(t.maintenance)
                .values(name="weekly_horizon", completed_at=now)
                .on_conflict_do_update(
                    index_elements=[t.maintenance.c.name], set_={"completed_at": now}
                )
            )
        return len(set(store.slots) - before)


def ensure_horizon(now: datetime) -> None:
    """Fallback без Worker: один refresh за київську дату, не повний знімок на кожен GET."""
    boundary = now.astimezone(KYIV).replace(hour=0, minute=0, second=0, microsecond=0)
    needed = select(
        exists(select(t.templates.c.id))
        & ~exists(
            select(t.maintenance.c.name).where(
                t.maintenance.c.name == "weekly_horizon", t.maintenance.c.completed_at >= boundary
            )
        )
    )
    with store.engine.connect() as conn:
        stale = conn.scalar(needed)
    if stale:
        with store.lock:
            # A preceding request may already have refreshed while this one waited.
            if store.lock.connection.scalar(needed):
                refresh_horizon(now)
