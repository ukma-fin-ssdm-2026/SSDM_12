"""Заглушка `BookingService` (HLD §5.2): сценарії бронювання на даних у пам'яті.

З Лаб 5 правила бронювання живуть у доменному шарі `unislot.booking.domain.rules`,
а тут лишилася роль майбутнього шару application: знайти записи, зібрати для правил
значення (інтервали, політику, «чи зайнятий слот»), застосувати зміну під
`store.lock`, як у транзакції. Порушення правил домен кидає як `DomainError`, і
REST API перекладає їх у 409 (HLD §9). Справжню гарантію REL-001 дасть PostgreSQL
(ADR-002).
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
from unislot.booking.domain import rules
from unislot.booking.domain.model import BookingPolicy, Interval

_STATE_ORDER = {
    BookingState.ACTIVE: 0,
    BookingState.IN_PROGRESS: 1,
    BookingState.COMPLETED: 2,
    BookingState.CANCELLED: 3,
}


def _interval(slot: SlotRec) -> Interval:
    return Interval(slot.starts_at, slot.ends_at)


def _policy() -> BookingPolicy | None:
    policy = store.policy
    if policy is None:
        return None
    return BookingPolicy(policy.booking_limit, policy.cancel_window)


def booking_state(booking: BookingRec, slot: SlotRec, now: datetime) -> BookingState:
    """Похідний стан (`data-model.md` §7): обчислює доменне правило `derive_state`."""
    return rules.derive_state(booking.status, _interval(slot), now)


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
        can_cancel=rules.can_cancel(state, booking.cancel_deadline_at, now),
        created_at=booking.created_at,
        cancelled_at=booking.cancelled_at,
        cancellation_kind=booking.cancellation_kind,
        cancellation_reason=booking.cancellation_reason,
        rescheduled_to_id=booking.rescheduled_to_id,
    )


def _check_slot_bookable(slot: SlotRec, now: datetime) -> None:
    """Збирає стан слота зі сховища й передає доменному правилу (A-006, A-001, FR-014)."""
    rules.ensure_slot_bookable(
        _interval(slot),
        now,
        HORIZON,
        blocked=store.is_blocked(slot),
        taken=store.confirmed_booking_for_slot(slot.id) is not None,
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
    open_slots = [_interval(s) for b, s in _open_bookings(student.id, now) if b.id != replacing]
    rules.ensure_within_student_limits(
        open_slots, _interval(slot), now, _policy(), counts_against_limit=replacing is None
    )


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
        cancel_deadline_at=rules.cancel_deadline(
            slot.starts_at, BookingPolicy(policy.booking_limit, policy.cancel_window)
        ),
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
    (FR-040, FR-044, FR-045): рішення ухвалює доменне правило `ensure_changeable`."""
    slot = store.slots[booking.slot_id]
    rules.ensure_changeable(booking.status, _interval(slot), booking.cancel_deadline_at, now)


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
