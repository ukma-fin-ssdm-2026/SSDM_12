"""Момент нагадування про бронювання за правилом A-004 (FR-051)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

REMINDER_LEAD = timedelta(hours=24)


def reminder_due_at(
    slot_start: datetime, booked_at: datetime, *, lead: timedelta = REMINDER_LEAD
) -> datetime | None:
    """Обчислює момент нагадування в UTC, якщо бронювання створене завчасно.

    Інтервал відраховується в абсолютному часі, зокрема через зміну часового поясу.
    Бронювання рівно за `lead` до початку також отримує нагадування (A-004).

    Args:
        slot_start: Початок слота з часовим поясом.
        booked_at: Момент створення бронювання з часовим поясом.
        lead: Додатний інтервал між нагадуванням і початком слота.

    Returns:
        Момент нагадування в UTC або None, якщо бронювання створене пізніше.

    Raises:
        ValueError: Час не має часового поясу або `lead` не додатний.
    """
    if slot_start.utcoffset() is None or booked_at.utcoffset() is None:
        raise ValueError("Початок слота й момент бронювання мають містити часовий пояс.")
    if lead <= timedelta(0):
        raise ValueError("lead має бути додатним інтервалом.")
    due_at = slot_start.astimezone(UTC) - lead
    return due_at if booked_at.astimezone(UTC) <= due_at else None
