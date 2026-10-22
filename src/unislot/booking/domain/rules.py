"""Правила бронювання (FR-030…FR-045) як чисті функції.

Кожна функція отримує все потрібне параметрами: стан слота, політику, поточний момент
`now`. Годинника, сховища й HTTP тут немає: перевірка `ensure_*` або нічого не повертає,
або кидає доменну помилку, а REST API перекладає її у відповідь 409 (HLD §9).

Порядок перевірок у кожній функції — частина контракту: якщо слот і почався, і
зайнятий, клієнт отримує `SLOT_STARTED`, а не `SLOT_ALREADY_BOOKED`.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta

from unislot.booking.domain.errors import (
    BookingAlreadyCancelled,
    BookingLimitReached,
    BookingOverlap,
    CancellationDeadlinePassed,
    SlotAlreadyBooked,
    SlotBlocked,
    SlotOutOfHorizon,
    SlotStarted,
)
from unislot.booking.domain.model import BookingPolicy, BookingState, BookingStatus, Interval


def derive_state(status: BookingStatus, slot: Interval, now: datetime) -> BookingState:
    """Похідний стан для користувача (`data-model.md` §7): у сховищі лише два статуси.

    Межі: у момент початку слота бронювання вже «триває», у момент кінця — «завершене».
    """
    if status is BookingStatus.CANCELLED:
        return BookingState.CANCELLED
    if now < slot.starts_at:
        return BookingState.ACTIVE
    if now < slot.ends_at:
        return BookingState.IN_PROGRESS
    return BookingState.COMPLETED


def cancel_deadline(slot_start: datetime, policy: BookingPolicy) -> datetime:
    """Граничний час скасування фіксується під час бронювання (FR-041, DD-04)."""
    return slot_start - policy.cancel_window


def can_cancel(state: BookingState, deadline: datetime, now: datetime) -> bool:
    """Чи покаже інтерфейс кнопку «Скасувати»: активне й граничний час не минув (включно)."""
    return state is BookingState.ACTIVE and now <= deadline


def ensure_slot_bookable(
    slot: Interval, now: datetime, horizon: timedelta, *, blocked: bool, taken: bool
) -> None:
    """Слот можна забронювати: не почався, у горизонті, не заблокований, не зайнятий.

    Args:
        slot: Час слота.
        now: Поточний момент (UTC).
        horizon: Горизонт бронювання A-001; домен не читає конфігурацію сам.
        blocked: Чи перетинає слот блокування провайдера (FR-014).
        taken: Чи має слот чинне бронювання (INV-01).

    Raises:
        SlotStarted: запис закривається в момент початку слота (A-006).
        SlotOutOfHorizon: початок пізніший за `now + horizon` (A-001).
        SlotBlocked: час заблоковано провайдером.
        SlotAlreadyBooked: слот уже зайнятий.
    """
    if slot.starts_at <= now:
        raise SlotStarted("Запис на слот закривається в момент його початку.")
    if slot.starts_at > now + horizon:
        raise SlotOutOfHorizon("Слот пізніший за горизонт бронювання; він стане доступним згодом.")
    if blocked:
        raise SlotBlocked
    if taken:
        raise SlotAlreadyBooked("Цей слот щойно забронював інший студент або він уже був зайнятий.")


def ensure_within_student_limits(
    open_bookings: Iterable[Interval],
    new_slot: Interval,
    now: datetime,
    policy: BookingPolicy | None,
    *,
    counts_against_limit: bool = True,
) -> None:
    """Обмеження студента: ліміт активних бронювань (A-002) і відсутність перетинів (FR-035).

    Args:
        open_bookings: Слоти чинних бронювань студента, які ще не завершилися
            (і майбутні, і ті, що тривають). Для перенесення — без бронювання, яке замінюємо.
        new_slot: Слот, який студент хоче отримати.
        now: Поточний момент (UTC).
        policy: Чинна політика; None — ліміт не перевіряється.
        counts_against_limit: False для перенесення — воно не рахується як нове
            бронювання (FR-044).

    Raises:
        BookingLimitReached: у студента вже `policy.booking_limit` активних бронювань;
            ті, що тривають, у ліміт не входять.
        BookingOverlap: новий слот перетинається з будь-яким незавершеним бронюванням.
    """
    slots = list(open_bookings)
    if counts_against_limit and policy is not None:
        active = sum(1 for s in slots if s.starts_at > now)
        if active >= policy.booking_limit:
            raise BookingLimitReached(policy.booking_limit, active)
    if any(s.overlaps(new_slot) for s in slots):
        raise BookingOverlap


def ensure_changeable(
    status: BookingStatus, slot: Interval, deadline: datetime, now: datetime
) -> None:
    """Скасувати чи перенести можна лише чинне бронювання до граничного часу включно.

    Raises:
        BookingAlreadyCancelled: бронювання вже скасоване (FR-040).
        SlotStarted: слот почався — змінювати не можна нікому (FR-045).
        CancellationDeadlinePassed: `now` пізніше за граничний час (FR-041, FR-044).
    """
    if status is BookingStatus.CANCELLED:
        raise BookingAlreadyCancelled
    if now >= slot.starts_at:
        raise SlotStarted("Після початку слота бронювання змінювати не можна.")
    if now > deadline:
        raise CancellationDeadlinePassed(deadline)
