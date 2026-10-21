"""Заглушка `BookingService` (HLD §5.2) для Лаб 4: правила бронювання на даних у пам'яті.

Порядок перевірок повторює майбутній доменний модуль: спершу стан слота (існує,
не почався, у горизонті, не заблокований, не зайнятий), потім обмеження студента
(ліміт A-002, перетин FR-035). Усі зміни — під `store.lock`, як у транзакції;
справжню гарантію REL-001 дасть PostgreSQL (ADR-002).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from api.enums import BookingState, BookingStatus, CancellationKind
from api.errors import ApiProblem, ErrorCode
from api.policy import HORIZON
from api.schemas.bookings import BookingOut, BookingSlot
from api.schemas.common import PersonSummary, ResourceSummary
from api.security import CurrentUser
from api.stubs.store import BookingRec, SlotRec, store

_STATE_ORDER = {
    BookingState.ACTIVE: 0,
    BookingState.IN_PROGRESS: 1,
    BookingState.COMPLETED: 2,
    BookingState.CANCELLED: 3,
}


def booking_state(booking: BookingRec, slot: SlotRec, now: datetime) -> BookingState:
    """Похідний стан (`data-model.md` §7): у сховищі лише confirmed/cancelled."""
    if booking.status is BookingStatus.CANCELLED:
        return BookingState.CANCELLED
    if now < slot.starts_at:
        return BookingState.ACTIVE
    if now < slot.ends_at:
        return BookingState.IN_PROGRESS
    return BookingState.COMPLETED


def to_out(booking: BookingRec, now: datetime) -> BookingOut:
    """Схема відповіді: похідний стан, слот, ресурс і провайдер (лише ім'я, SEC-004)."""
    slot = store.slots[booking.slot_id]
    resource = store.resources[slot.resource_id]
    provider = store.users[resource.provider_id]
    state = booking_state(booking, slot, now)
    return BookingOut(
        id=booking.id,
        state=state,
        slot=BookingSlot(id=slot.id, starts_at=slot.starts_at, ends_at=slot.ends_at),
        resource=ResourceSummary(
            id=resource.id, name=resource.name, type=resource.type, capacity=resource.capacity
        ),
        provider=PersonSummary(id=provider.id, full_name=provider.full_name),
        cancel_deadline_at=booking.cancel_deadline_at,
        can_cancel=state is BookingState.ACTIVE and now <= booking.cancel_deadline_at,
        created_at=booking.created_at,
        cancelled_at=booking.cancelled_at,
        cancellation_kind=booking.cancellation_kind,
        cancellation_reason=booking.cancellation_reason,
        rescheduled_to_id=booking.rescheduled_to_id,
    )


def _check_slot_bookable(slot: SlotRec, now: datetime) -> None:
    """Стан слота: не почався (A-006), у горизонті (A-001), не заблокований, не зайнятий."""
    if slot.starts_at <= now:
        raise ApiProblem(
            ErrorCode.SLOT_STARTED, "Запис на слот закривається в момент його початку."
        )
    if slot.starts_at > now + HORIZON:
        raise ApiProblem(
            ErrorCode.SLOT_OUT_OF_HORIZON,
            "Слот пізніший за горизонт бронювання; він стане доступним згодом.",
        )
    if store.is_blocked(slot):
        raise ApiProblem(ErrorCode.SLOT_BLOCKED)
    if store.confirmed_booking_for_slot(slot.id) is not None:
        raise ApiProblem(
            ErrorCode.SLOT_ALREADY_BOOKED,
            "Цей слот щойно забронював інший студент або він уже був зайнятий.",
        )


def _open_bookings(student_id: uuid.UUID, now: datetime) -> list[tuple[BookingRec, SlotRec]]:
    """Підтверджені бронювання студента, які ще не завершилися (активні й ті, що тривають)."""
    result = []
    for booking in store.bookings.values():
        if booking.student_id == student_id and booking.status is BookingStatus.CONFIRMED:
            slot = store.slots[booking.slot_id]
            if slot.ends_at > now:
                result.append((booking, slot))
    return result


def _check_student_limits(
    student: CurrentUser, slot: SlotRec, now: datetime, *, replacing: uuid.UUID | None = None
) -> None:
    """Ліміт A-002 (крім перенесення, FR-044) і перетин з власними бронюваннями (FR-035)."""
    open_bookings = [(b, s) for b, s in _open_bookings(student.id, now) if b.id != replacing]
    if replacing is None:
        policy = store.policy
        active = sum(1 for _, s in open_bookings if s.starts_at > now)
        if policy is not None and active >= policy.booking_limit:
            raise ApiProblem(
                ErrorCode.BOOKING_LIMIT_REACHED,
                f"Ліміт — {policy.booking_limit} активні бронювання, у вас уже {active}.",
                limit=policy.booking_limit,
                active_bookings=active,
            )
    if any(s.starts_at < slot.ends_at and slot.starts_at < s.ends_at for _, s in open_bookings):
        raise ApiProblem(ErrorCode.BOOKING_OVERLAP)


def _new_booking(student: CurrentUser, slot: SlotRec, now: datetime) -> BookingRec:
    policy = store.policy
    if policy is None:  # pragma: no cover — reset() завжди створює політику
        raise ApiProblem(ErrorCode.INTERNAL_ERROR)
    booking = BookingRec(
        id=uuid.uuid4(),
        slot_id=slot.id,
        student_id=student.id,
        status=BookingStatus.CONFIRMED,
        policy_id=policy.id,
        cancel_deadline_at=slot.starts_at - policy.cancel_window,
        created_at=now,
    )
    store.bookings[booking.id] = booking
    return booking


def book(
    student: CurrentUser, slot_id: uuid.UUID, now: datetime, idempotency_key: str | None = None
) -> tuple[BookingRec, bool]:
    """Створює бронювання (FR-030…FR-035). Повертає (бронювання, чи це повтор за ключем).

    Повтор із тим самим `Idempotency-Key` і тим самим слотом повертає перше бронювання,
    не створюючи нового: клієнт може безпечно повторити POST після обриву зв'язку.
    """
    with store.lock:
        if idempotency_key is not None:
            seen = store.idempotency.get((student.id, idempotency_key))
            if seen is not None:
                if seen["slot_id"] != slot_id:
                    raise ApiProblem(ErrorCode.IDEMPOTENCY_KEY_REUSED)
                return store.bookings[seen["booking_id"]], True
        slot = store.slots.get(slot_id)
        if slot is None:
            raise ApiProblem(ErrorCode.SLOT_NOT_FOUND)
        _check_slot_bookable(slot, now)
        _check_student_limits(student, slot, now)
        booking = _new_booking(student, slot, now)
        if idempotency_key is not None:
            store.idempotency[(student.id, idempotency_key)] = {
                "slot_id": slot_id,
                "booking_id": booking.id,
            }
        return booking, False


def get_owned(student: CurrentUser, booking_id: uuid.UUID) -> BookingRec:
    """Бронювання лише свого власника: чуже — 403 без даних об'єкта (THR-03, SEC-004)."""
    booking = store.bookings.get(booking_id)
    if booking is None:
        raise ApiProblem(ErrorCode.BOOKING_NOT_FOUND)
    if booking.student_id != student.id:
        raise ApiProblem(ErrorCode.NOT_OWNER, "Бронювання належить іншому студенту.")
    return booking


def _check_changeable(booking: BookingRec, now: datetime) -> None:
    """Скасувати чи перенести можна лише активне бронювання до граничного часу
    (FR-040, FR-044, FR-045)."""
    slot = store.slots[booking.slot_id]
    if booking.status is BookingStatus.CANCELLED:
        raise ApiProblem(ErrorCode.BOOKING_ALREADY_CANCELLED)
    if now >= slot.starts_at:
        raise ApiProblem(
            ErrorCode.SLOT_STARTED, "Після початку слота бронювання змінювати не можна."
        )
    if now > booking.cancel_deadline_at:
        raise ApiProblem(
            ErrorCode.CANCELLATION_DEADLINE_PASSED,
            f"Скасувати чи перенести можна було до {booking.cancel_deadline_at.isoformat()}.",
            cancel_deadline_at=booking.cancel_deadline_at,
        )


def cancel(student: CurrentUser, booking_id: uuid.UUID, now: datetime) -> BookingRec:
    """Скасування студентом (FR-040…FR-042): слот одразу знову вільний."""
    with store.lock:
        booking = get_owned(student, booking_id)
        _check_changeable(booking, now)
        booking.status = BookingStatus.CANCELLED
        booking.cancelled_at = now
        booking.cancelled_by = student.id
        booking.cancellation_kind = CancellationKind.STUDENT
        return booking


def reschedule(
    student: CurrentUser, booking_id: uuid.UUID, new_slot_id: uuid.UUID, now: datetime
) -> BookingRec:
    """Перенесення як атомарна заміна (FR-043, FR-044): або нове бронювання й скасоване
    старе, або без змін. Перенесення не рахується в ліміт A-002."""
    with store.lock:
        old = get_owned(student, booking_id)
        _check_changeable(old, now)
        if new_slot_id == old.slot_id:
            raise ApiProblem(
                ErrorCode.VALIDATION_FAILED,
                "Новий слот збігається з поточним.",
                errors=[
                    {
                        "field": "body.new_slot_id",
                        "type": "same_slot",
                        "message": "Оберіть інший слот",
                    }
                ],
            )
        new_slot = store.slots.get(new_slot_id)
        if new_slot is None:
            raise ApiProblem(ErrorCode.SLOT_NOT_FOUND)
        _check_slot_bookable(new_slot, now)
        _check_student_limits(student, new_slot, now, replacing=old.id)
        new = _new_booking(student, new_slot, now)
        old.status = BookingStatus.CANCELLED
        old.cancelled_at = now
        old.cancelled_by = student.id
        old.cancellation_kind = CancellationKind.RESCHEDULED
        old.rescheduled_to_id = new.id
        return new


def list_mine(
    student: CurrentUser, state: BookingState | None, limit: int, offset: int, now: datetime
) -> tuple[list[BookingRec], int]:
    """Власні бронювання (FR-036): активні першими (US-014)."""
    rows = []
    for booking in store.bookings.values():
        if booking.student_id != student.id:
            continue
        slot = store.slots[booking.slot_id]
        booking_st = booking_state(booking, slot, now)
        if state is None or booking_st is state:
            rows.append((booking, slot, booking_st))

    def order(row: tuple[BookingRec, SlotRec, BookingState]) -> tuple[int, float]:
        _, slot, st = row
        ts = slot.starts_at.timestamp()
        upcoming = st in (BookingState.ACTIVE, BookingState.IN_PROGRESS)
        return _STATE_ORDER[st], ts if upcoming else -ts

    rows.sort(key=order)
    return [b for b, _, _ in rows[offset : offset + limit]], len(rows)
