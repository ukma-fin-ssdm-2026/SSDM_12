"""Бронювання: створити, переглянути, скасувати, перенести (US-001, US-002, US-003, US-014).

Скасування й перенесення — дії над бронюванням, тому це `POST .../cancel` і
`POST .../reschedule`, а не `DELETE`: скасоване бронювання не зникає, воно лишається
в історії студента зі станом `cancelled` (довідник курсу: ресурсне моделювання REST).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Body, Header, Path, Query, Response

from api import clock
from api.config import API_PREFIX
from api.enums import BookingState
from api.errors import ErrorCode, FieldError, problem_responses
from api.pagination import DEFAULT_PAGE_SIZE, Limit, Offset, OffsetPagination
from api.schemas.bookings import BookingCreate, BookingList, BookingOut, BookingReschedule
from api.security import Student
from api.stubs import booking_service as service
from api.stubs.store import Ids

TAG = {
    "name": "bookings",
    "description": "Бронювання слотів студентом (US-001), скасування (US-002), перенесення "
    "(US-003) і перегляд власних бронювань (US-014).",
}

router = APIRouter(prefix=API_PREFIX, tags=[TAG["name"]])

# Іменовані приклади: Swagger UI показує їх списком і підставляє значення в поле.
BookingId = Annotated[
    uuid.UUID,
    Path(
        description="Ідентифікатор бронювання (UUID).",
        openapi_examples={
            "active": {
                "summary": "Власне активне бронювання (demo-student)",
                "value": str(Ids.BOOKING_ACTIVE),
            },
            "deadline_passed": {
                "summary": "Власне, граничний час скасування вже минув (demo-student)",
                "value": str(Ids.BOOKING_SOON),
            },
            "foreign": {
                "summary": "Бронювання іншого студента (demo-student-2)",
                "value": str(Ids.BOOKING_OTHER),
            },
        },
    ),
]
_CREATED_HEADERS = {
    "Location": {"description": "Адреса створеного бронювання.", "schema": {"type": "string"}},
    "Idempotent-Replayed": {
        "description": "`true`, якщо це повтор запиту з тим самим "
        "Idempotency-Key і нове бронювання не створювалося.",
        "schema": {"type": "string", "enum": ["true"]},
    },
}
_BAD_BOOKING_ID = FieldError(
    field="path.booking_id",
    type="uuid_parsing",
    message="Input should be a valid UUID, invalid length: found 3",
)
_SLOT_STATE_CONFLICTS = (
    ErrorCode.SLOT_ALREADY_BOOKED,
    ErrorCode.SLOT_STARTED,
    ErrorCode.SLOT_OUT_OF_HORIZON,
    ErrorCode.SLOT_BLOCKED,
)


@router.post(
    "/bookings",
    status_code=201,
    response_model=BookingOut,
    summary="Забронювати вільний слот",
    response_description="Бронювання створено (або повернуто перше за тим самим Idempotency-Key).",
    responses={
        201: {"headers": _CREATED_HEADERS},
        **problem_responses(
            ErrorCode.AUTH_REQUIRED,
            ErrorCode.FORBIDDEN_ROLE,
            ErrorCode.SLOT_NOT_FOUND,
            *_SLOT_STATE_CONFLICTS,
            ErrorCode.BOOKING_LIMIT_REACHED,
            ErrorCode.BOOKING_OVERLAP,
            ErrorCode.VALIDATION_FAILED,
            ErrorCode.IDEMPOTENCY_KEY_REUSED,
            ErrorCode.TRANSIENT_CONFLICT,
            field_error=FieldError(field="body.slot_id", message="Field required", type="missing"),
        ),
    },
)
def create_booking(
    payload: Annotated[
        BookingCreate,
        Body(
            openapi_examples={
                "free": {
                    "summary": "Вільний слот → 201",
                    "value": {"slot_id": str(Ids.SLOT_DB_D1_1030)},
                },
                "taken": {
                    "summary": "Слот зайнятий іншим студентом → 409",
                    "value": {"slot_id": str(Ids.SLOT_DB_D1_1000)},
                },
                "started": {
                    "summary": "Слот уже почався → 409",
                    "value": {"slot_id": str(Ids.SLOT_DB_STARTED)},
                },
                "overlap": {
                    "summary": "Перетин із власним бронюванням → 409",
                    "value": {"slot_id": str(Ids.SLOT_225_D2_1000)},
                },
            }
        ),
    ],
    response: Response,
    student: Student,
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            pattern=r"^[A-Za-z0-9_-]{8,64}$",
            description="Необов'язковий ключ ідемпотентності (8–64 символи). Повтор із тим самим "
            "ключем повертає перше бронювання замість створення нового.",
        ),
    ] = None,
) -> BookingOut:
    """Бронює вільний слот для студента; бронювання активне одразу, без підтвердження
    провайдером (FR-030, FR-031). Відповідь містить граничний час скасування (FR-041).

    Відмови (409) пояснюють причину: слот зайнятий — зокрема, якщо двоє бронюють його
    одночасно, рівно один отримує 201 (FR-032, REL-001); слот почався (A-006) або поза
    горизонтом (A-001); ліміт активних бронювань (A-002, поля `limit` і
    `active_bookings`); перетин із власним бронюванням (FR-035).
    """
    now = clock.utc_now()
    booking, replayed = service.book(student, payload.slot_id, now, idempotency_key)
    response.headers["Location"] = f"{API_PREFIX}/bookings/{booking.id}"
    if replayed:
        response.headers["Idempotent-Replayed"] = "true"
    return service.to_out(booking, now)


@router.get(
    "/bookings/{booking_id}",
    response_model=BookingOut,
    summary="Отримати власне бронювання",
    response_description="Бронювання.",
    responses=problem_responses(
        ErrorCode.AUTH_REQUIRED,
        ErrorCode.FORBIDDEN_ROLE,
        ErrorCode.NOT_OWNER,
        ErrorCode.BOOKING_NOT_FOUND,
        ErrorCode.VALIDATION_FAILED,
        field_error=_BAD_BOOKING_ID,
    ),
)
def get_booking(booking_id: BookingId, student: Student) -> BookingOut:
    """Деталі бронювання для його власника. Чуже бронювання — 403 без жодних його даних
    (SEC-004, THR-03); неіснуюче — 404.
    """
    return service.to_out(service.get_owned(student, booking_id), clock.utc_now())


@router.post(
    "/bookings/{booking_id}/cancel",
    response_model=BookingOut,
    summary="Скасувати власне бронювання",
    response_description="Скасоване бронювання (state = cancelled).",
    responses=problem_responses(
        ErrorCode.AUTH_REQUIRED,
        ErrorCode.FORBIDDEN_ROLE,
        ErrorCode.NOT_OWNER,
        ErrorCode.BOOKING_NOT_FOUND,
        ErrorCode.BOOKING_ALREADY_CANCELLED,
        ErrorCode.SLOT_STARTED,
        ErrorCode.CANCELLATION_DEADLINE_PASSED,
        ErrorCode.VALIDATION_FAILED,
        ErrorCode.TRANSIENT_CONFLICT,
        field_error=_BAD_BOOKING_ID,
    ),
)
def cancel_booking(booking_id: BookingId, student: Student) -> BookingOut:
    """Скасовує активне бронювання до граничного часу скасування включно (FR-040, FR-041);
    слот одразу знову з'являється в пошуку (FR-042). Після граничного часу — 409 з полем
    `cancel_deadline_at`; після початку слота — 409 для всіх ролей (FR-045).

    Це `POST`, а не `DELETE`: бронювання не видаляється, а переходить у стан `cancelled`.
    """
    now = clock.utc_now()
    return service.to_out(service.cancel(student, booking_id, now), now)


@router.post(
    "/bookings/{booking_id}/reschedule",
    status_code=201,
    response_model=BookingOut,
    summary="Перенести бронювання на інший слот",
    response_description="Нове бронювання; старе стало cancelled з видом rescheduled.",
    responses={
        201: {"headers": {"Location": _CREATED_HEADERS["Location"]}},
        **problem_responses(
            ErrorCode.AUTH_REQUIRED,
            ErrorCode.FORBIDDEN_ROLE,
            ErrorCode.NOT_OWNER,
            ErrorCode.BOOKING_NOT_FOUND,
            ErrorCode.SLOT_NOT_FOUND,
            ErrorCode.BOOKING_ALREADY_CANCELLED,
            ErrorCode.CANCELLATION_DEADLINE_PASSED,
            *_SLOT_STATE_CONFLICTS,
            ErrorCode.BOOKING_OVERLAP,
            ErrorCode.VALIDATION_FAILED,
            ErrorCode.TRANSIENT_CONFLICT,
            field_error=FieldError(
                field="body.new_slot_id", message="Field required", type="missing"
            ),
        ),
    },
)
def reschedule_booking(
    booking_id: BookingId,
    payload: Annotated[
        BookingReschedule,
        Body(
            openapi_examples={
                "free": {
                    "summary": "На вільний слот → 201",
                    "value": {"new_slot_id": str(Ids.SLOT_DB_D2_1030)},
                },
                "taken": {
                    "summary": "На зайнятий слот → 409, старе бронювання лишається",
                    "value": {"new_slot_id": str(Ids.SLOT_DB_D1_1000)},
                },
            }
        ),
    ],
    response: Response,
    student: Student,
) -> BookingOut:
    """Атомарно замінює бронювання новим (FR-043): старе стає `cancelled` з видом
    `rescheduled` і посиланням `rescheduled_to_id`, нове повертається з кодом 201.
    Якщо новий слот зайнятий чи недоступний, нічого не змінюється. Діє те саме вікно, що
    й для скасування; перенесення не рахується як нове бронювання в ліміті A-002 (FR-044).
    """
    now = clock.utc_now()
    new = service.reschedule(student, booking_id, payload.new_slot_id, now)
    response.headers["Location"] = f"{API_PREFIX}/bookings/{new.id}"
    return service.to_out(new, now)


@router.get(
    "/me/bookings",
    response_model=BookingList,
    summary="Переглянути власні бронювання",
    response_description="Сторінка власних бронювань.",
    responses=problem_responses(
        ErrorCode.AUTH_REQUIRED,
        ErrorCode.FORBIDDEN_ROLE,
        ErrorCode.VALIDATION_FAILED,
        field_error=FieldError(
            field="query.state",
            type="enum",
            message="Input should be 'active', 'in_progress', 'completed' or 'cancelled'",
        ),
    ),
)
def list_my_bookings(
    student: Student,
    state: Annotated[
        BookingState | None, Query(description="Лише бронювання в цьому стані.")
    ] = None,
    limit: Limit = DEFAULT_PAGE_SIZE,
    offset: Offset = 0,
) -> BookingList:
    """Бронювання поточного студента (FR-036): спершу активні й ті, що тривають, потім
    завершені й скасовані (US-014). Порожній список — це 200 з `items: []`, а не помилка.
    """
    now = clock.utc_now()
    items, total = service.list_mine(student, state, limit, offset, now)
    return BookingList(
        items=[service.to_out(b, now) for b in items],
        pagination=OffsetPagination(
            limit=limit, offset=offset, total=total, has_more=offset + len(items) < total
        ),
    )
