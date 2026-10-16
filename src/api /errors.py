"""Єдина модель помилок API (DD-07): RFC 9457 `application/problem+json`.

Кожна відмова — це тип проблеми з каталогу `CATALOG`: стабільний машинний код,
HTTP-статус, людська назва й дія для користувача (USAB-001). Тіло відповіді
містить усі складники структури помилки з Лекції 4 (§3.5), але в полях RFC 9457:

    код          → `code`          (машинозчитуваний, стабільний)
    повідомлення → `title`, `detail`
    деталі полів → `errors[]`      (`field`, `message`, `type`)
    request_id   → `request_id`    (той самий, що в заголовку X-Request-ID)
    документація → `type`          (URI у каталозі помилок на GitHub Pages)

Свідомо НЕ повертаємо значення, які надіслав клієнт (`provided_value` з прикладу
Лекції 4): саме цю вразливість (CWE-209 — тіло запиту у відповіді 422) ми знайшли
в огляді чужого коду (`docs/code-quality/review-report.md`).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.config import DOCS_BASE_URL

logger = logging.getLogger("unislot.api")

PROBLEM_MEDIA_TYPE = "application/problem+json"
MAX_FIELD_ERRORS = 20  # не віддаємо необмежений список помилок полів


class ErrorCode(StrEnum):
    """Машинні коди помилок. Значення не перейменовуються: це частина контракту."""

    VALIDATION_FAILED = "VALIDATION_FAILED"
    BAD_REQUEST = "BAD_REQUEST"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    FORBIDDEN_ROLE = "FORBIDDEN_ROLE"
    NOT_OWNER = "NOT_OWNER"
    NOT_FOUND = "NOT_FOUND"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    SLOT_NOT_FOUND = "SLOT_NOT_FOUND"
    BOOKING_NOT_FOUND = "BOOKING_NOT_FOUND"
    SLOT_ALREADY_BOOKED = "SLOT_ALREADY_BOOKED"
    SLOT_STARTED = "SLOT_STARTED"
    SLOT_OUT_OF_HORIZON = "SLOT_OUT_OF_HORIZON"
    SLOT_BLOCKED = "SLOT_BLOCKED"
    BOOKING_LIMIT_REACHED = "BOOKING_LIMIT_REACHED"
    BOOKING_OVERLAP = "BOOKING_OVERLAP"
    BOOKING_ALREADY_CANCELLED = "BOOKING_ALREADY_CANCELLED"
    CANCELLATION_DEADLINE_PASSED = "CANCELLATION_DEADLINE_PASSED"
    SLOT_OVERLAP = "SLOT_OVERLAP"
    SLOT_IN_PAST = "SLOT_IN_PAST"
    DATE_OUT_OF_HORIZON = "DATE_OUT_OF_HORIZON"
    PROVIDER_NOT_ELIGIBLE = "PROVIDER_NOT_ELIGIBLE"
    IDEMPOTENCY_KEY_REUSED = "IDEMPOTENCY_KEY_REUSED"
    TRANSIENT_CONFLICT = "TRANSIENT_CONFLICT"
    INTERNAL_ERROR = "INTERNAL_ERROR"


@dataclass(frozen=True)
class ErrorSpec:
    """Опис типу проблеми: те, що однакове для кожного випадку цієї помилки."""

    status: int
    title: str
    action: str
    when: str  # коли виникає — для каталогу й документації
    refs: str = ""  # вимоги, з яких випливає помилка


CATALOG: dict[ErrorCode, ErrorSpec] = {
    ErrorCode.VALIDATION_FAILED: ErrorSpec(
        422,
        "Некоректні дані запиту",
        "Виправте поля, перелічені в errors, і повторіть запит.",
        "Параметр, заголовок або тіло запиту не відповідає схемі: бракує поля, хибний тип, "
        "значення поза межами, зайве поле.",
        "THR-04",
    ),
    ErrorCode.BAD_REQUEST: ErrorSpec(
        400,
        "Запит не може бути оброблено",
        "Перевірте формат запиту за документацією.",
        "Запит синтаксично некоректний на рівні HTTP.",
    ),
    ErrorCode.AUTH_REQUIRED: ErrorSpec(
        401,
        "Потрібна автентифікація",
        "Увійдіть у систему. У Лаб 4 — передайте демо-токен: Authorization: Bearer demo-student.",
        "Запит без токена, з невідомим токеном або з вимкненою демо-автентифікацією.",
        "FR-007",
    ),
    ErrorCode.FORBIDDEN_ROLE: ErrorSpec(
        403,
        "Недостатньо прав для цієї операції",
        "Скористайтеся обліковим записом із потрібною роллю або зверніться до адміністратора.",
        "Роль користувача не дозволяє операцію (deny-by-default).",
        "FR-007, SEC-002",
    ),
    ErrorCode.NOT_OWNER: ErrorSpec(
        403,
        "Об'єкт належить іншому користувачу",
        "Відкрийте власний об'єкт; доступ до чужих даних заборонено.",
        "Студент звертається до чужого бронювання або провайдер — до чужого ресурсу. "
        "Відповідь не містить даних об'єкта (THR-03).",
        "SEC-004, SEC-002",
    ),
    ErrorCode.NOT_FOUND: ErrorSpec(
        404,
        "Ресурс за цією адресою не знайдено",
        "Перевірте шлях запиту за документацією.",
        "Шляху немає в API.",
    ),
    ErrorCode.METHOD_NOT_ALLOWED: ErrorSpec(
        405,
        "Метод не підтримується для цієї адреси",
        "Скористайтеся одним із методів із заголовка Allow.",
        "Шлях існує, але не підтримує цей HTTP-метод.",
    ),
    ErrorCode.RESOURCE_NOT_FOUND: ErrorSpec(
        404,
        "Ресурс не знайдено",
        "Оберіть ресурс із каталогу GET /api/v1/resources.",
        "Ресурсу (консультації чи аудиторії) з таким ідентифікатором немає.",
        "FR-060",
    ),
    ErrorCode.SLOT_NOT_FOUND: ErrorSpec(
        404,
        "Слот не знайдено",
        "Знайдіть актуальний вільний слот через пошук.",
        "Слота з таким ідентифікатором немає.",
        "FR-020",
    ),
    ErrorCode.BOOKING_NOT_FOUND: ErrorSpec(
        404,
        "Бронювання не знайдено",
        "Відкрийте список своїх бронювань.",
        "Бронювання з таким ідентифікатором немає.",
        "FR-036",
    ),
    ErrorCode.SLOT_ALREADY_BOOKED: ErrorSpec(
        409,
        "Слот уже зайнятий",
        "Оберіть інший вільний слот у пошуку.",
        "На слот уже є активне бронювання, зокрема якщо його щойно зайняв інший студент.",
        "FR-032, REL-001",
    ),
    ErrorCode.SLOT_STARTED: ErrorSpec(
        409,
        "Слот уже почався",
        "Оберіть слот, який ще не почався.",
        "Запис на слот або зміна бронювання після початку слота.",
        "FR-034, FR-045, A-006",
    ),
    ErrorCode.SLOT_OUT_OF_HORIZON: ErrorSpec(
        409,
        "Слот поза горизонтом бронювання",
        "Оберіть слот у межах горизонту бронювання (A-001).",
        "Початок слота пізніший за поточний момент плюс горизонт A-001.",
        "FR-030, A-001",
    ),
    ErrorCode.SLOT_BLOCKED: ErrorSpec(
        409,
        "Час слота заблоковано провайдером",
        "Оберіть інший слот.",
        "Слот потрапляє в проміжок, який провайдер оголосив недоступним.",
        "FR-014, FR-023",
    ),
    ErrorCode.BOOKING_LIMIT_REACHED: ErrorSpec(
        409,
        "Досягнуто ліміту активних бронювань",
        "Скасуйте одне з активних бронювань або дочекайтеся його завершення.",
        "Студент уже має максимальну кількість активних бронювань (A-002). "
        "Відповідь містить поля limit і active_bookings.",
        "FR-033, A-002",
    ),
    ErrorCode.BOOKING_OVERLAP: ErrorSpec(
        409,
        "Час перетинається з іншим вашим бронюванням",
        "Оберіть слот, що не перетинається з вашими активними бронюваннями.",
        "Новий слот перетинається в часі з активним бронюванням того самого студента.",
        "FR-035",
    ),
    ErrorCode.BOOKING_ALREADY_CANCELLED: ErrorSpec(
        409,
        "Бронювання вже скасовано",
        "Дія не потрібна: бронювання вже неактивне.",
        "Повторне скасування або перенесення скасованого бронювання.",
        "FR-040",
    ),
    ErrorCode.CANCELLATION_DEADLINE_PASSED: ErrorSpec(
        409,
        "Граничний час скасування минув",
        "Скасувати чи перенести це бронювання вже не можна; за потреби зверніться до провайдера.",
        "Зараз пізніше за граничний час скасування, зафіксований під час бронювання. "
        "Відповідь містить поле cancel_deadline_at.",
        "FR-040, FR-041, FR-044, A-003",
    ),
    ErrorCode.SLOT_OVERLAP: ErrorSpec(
        409,
        "Слот перетинається з наявним",
        "Змініть час початку або тривалість слота.",
        "Новий слот ресурсу перетинається з наявним слотом цього ресурсу; суміжні слоти дозволені.",
        "FR-011",
    ),
    ErrorCode.SLOT_IN_PAST: ErrorSpec(
        422,
        "Початок слота в минулому",
        "Вкажіть майбутній час початку.",
        "Провайдер створює слот, що починається не пізніше за поточний момент.",
        "FR-010",
    ),
    ErrorCode.DATE_OUT_OF_HORIZON: ErrorSpec(
        422,
        "Дата поза горизонтом пошуку",
        "Оберіть дату від сьогодні до кінця горизонту бронювання (A-001).",
        "Фільтр date у пошуку раніший за сьогодні або пізніший за горизонт A-001.",
        "FR-020, A-001",
    ),
    ErrorCode.PROVIDER_NOT_ELIGIBLE: ErrorSpec(
        422,
        "Користувач не може бути провайдером ресурсу",
        "Призначте користувача з роллю «провайдер».",
        "provider_id вказує на неіснуючого користувача або на користувача без ролі провайдера.",
        "FR-061, INV-15",
    ),
    ErrorCode.IDEMPOTENCY_KEY_REUSED: ErrorSpec(
        422,
        "Ключ ідемпотентності вже використано для іншого запиту",
        "Для нового запиту згенеруйте новий Idempotency-Key.",
        "Повтор із тим самим Idempotency-Key, але з іншим тілом запиту.",
    ),
    ErrorCode.TRANSIENT_CONFLICT: ErrorSpec(
        503,
        "Тимчасовий конфлікт, спробуйте ще раз",
        "Повторіть запит через кілька секунд (див. заголовок Retry-After).",
        "Взаємне блокування транзакцій не зникло після одного повтору (ADR-002, п. 6). "
        "У заглушках Лаб 4 не виникає, але є частиною контракту.",
        "REL-001",
    ),
    ErrorCode.INTERNAL_ERROR: ErrorSpec(
        500,
        "Внутрішня помилка сервера",
        "Повторіть запит пізніше; якщо помилка повторюється, повідомте request_id.",
        "Непередбачена помилка. Тіло не містить трасування стека чи назв внутрішніх класів.",
    ),
}


def problem_slug(code: ErrorCode) -> str:
    """Якір у каталозі помилок: SLOT_ALREADY_BOOKED → slot-already-booked."""
    return code.value.lower().replace("_", "-")


def problem_type_uri(code: ErrorCode) -> str:
    """URI типу проблеми (RFC 9457 §3.1.1): веде на опис помилки в каталозі."""
    return f"{DOCS_BASE_URL}/errors.html#{problem_slug(code)}"


class FieldError(BaseModel):
    """Помилка одного поля запиту. Значення, яке надіслав клієнт, не повертається (CWE-209)."""

    field: str = Field(
        description="Шлях до поля: розташування (body, query, path, header) і назва.",
        examples=["body.slot_id"],
    )
    message: str = Field(description="Що не так із полем.", examples=["Field required"])
    type: str = Field(
        description="Машинний тип помилки валідації (Pydantic).", examples=["missing"]
    )


class Problem(BaseModel):
    """Тіло відповіді-помилки за RFC 9457 із розширеннями UniSlot."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "type": f"{DOCS_BASE_URL}/errors.html#slot-already-booked",
                    "title": "Слот уже зайнятий",
                    "status": 409,
                    "detail": "Цей слот щойно забронював інший студент.",
                    "instance": "/api/v1/bookings",
                    "code": "SLOT_ALREADY_BOOKED",
                    "action": "Оберіть інший вільний слот у пошуку.",
                    "request_id": "4f6c0b9e2d7a4e51a3c8d1f0b2e47a96",
                }
            ]
        }
    )

    type: str = Field(description="URI типу проблеми; веде на опис у каталозі помилок.")
    title: str = Field(description="Коротка назва типу проблеми; однакова для всіх її випадків.")
    status: int = Field(
        description="HTTP-статус; збігається зі статусом відповіді.", ge=400, le=599
    )
    detail: str = Field(description="Пояснення саме цього випадку для людини.")
    instance: str | None = Field(default=None, description="Шлях запиту, у якому сталася помилка.")
    code: ErrorCode = Field(description="Стабільний машинний код помилки.")
    action: str = Field(description="Що користувач може зробити далі (USAB-001).")
    request_id: str = Field(
        description="Ідентифікатор запиту; той самий, що в заголовку X-Request-ID."
    )
    errors: list[FieldError] | None = Field(
        default=None, description="Помилки окремих полів; лише для VALIDATION_FAILED."
    )
    limit: int | None = Field(
        default=None, description="Поточний ліміт активних бронювань (A-002)."
    )
    active_bookings: int | None = Field(
        default=None, description="Скільки активних бронювань уже має студент."
    )
    cancel_deadline_at: datetime | None = Field(
        default=None, description="Граничний час скасування бронювання, UTC (FR-041)."
    )


class ApiProblem(Exception):
    """Виняток, який обробник перетворює на відповідь problem+json.

    Заглушки сервісів кидають його напряму. Коли в Лаб 5–6 з'являться доменні
    помилки модулів (HLD §9), шар REST API перекладатиме їх у `ApiProblem`.
    """

    def __init__(
        self,
        code: ErrorCode,
        detail: str | None = None,
        *,
        headers: dict[str, str] | None = None,
        **extensions: Any,
    ) -> None:
        self.code = code
        self.spec = CATALOG[code]
        self.detail = detail or self.spec.when
        self.headers = headers
        self.extensions = extensions
        super().__init__(f"{code}: {self.detail}")


def _request_id(request: Request) -> str:
    """request_id, який виставило middleware; запасний — новий UUID."""
    return getattr(request.state, "request_id", None) or uuid.uuid4().hex


def problem_response(
    request: Request,
    code: ErrorCode,
    detail: str | None = None,
    *,
    status: int | None = None,
    headers: dict[str, str] | None = None,
    errors: list[FieldError] | None = None,
    **extensions: Any,
) -> JSONResponse:
    """Будує відповідь problem+json для коду з каталогу."""
    spec = CATALOG[code]
    request_id = _request_id(request)
    body = Problem(
        type=problem_type_uri(code),
        title=spec.title,
        status=status or spec.status,
        detail=detail or spec.when,
        instance=request.url.path,
        code=code,
        action=spec.action,
        request_id=request_id,
        errors=errors,
        **extensions,
    )
    all_headers = {"X-Request-ID": request_id, **(headers or {})}
    return JSONResponse(
        body.model_dump(mode="json", exclude_none=True),
        status_code=body.status,
        media_type=PROBLEM_MEDIA_TYPE,
        headers=all_headers,
    )


def _field_errors(exc: RequestValidationError) -> list[FieldError]:
    """Перетворює помилки Pydantic на FieldError, відкидаючи `input` і `ctx` (CWE-209)."""
    result = []
    for err in exc.errors()[:MAX_FIELD_ERRORS]:
        field = ".".join(str(part) for part in err.get("loc", ())) or "request"
        result.append(
            FieldError(
                field=field,
                message=str(err.get("msg", "")),
                type=str(err.get("type", "value_error")),
            )
        )
    return result


async def _on_api_problem(request: Request, exc: ApiProblem) -> JSONResponse:
    return problem_response(request, exc.code, exc.detail, headers=exc.headers, **exc.extensions)


async def _on_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    return problem_response(
        request,
        ErrorCode.VALIDATION_FAILED,
        "Запит не пройшов валідацію: перевірте поля, перелічені в errors.",
        errors=_field_errors(exc),
    )


async def _on_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    headers = dict(exc.headers or {})
    if exc.status_code == 404:
        return problem_response(request, ErrorCode.NOT_FOUND, headers=headers)
    if exc.status_code == 405:
        return problem_response(request, ErrorCode.METHOD_NOT_ALLOWED, headers=headers)
    code = ErrorCode.BAD_REQUEST if exc.status_code < 500 else ErrorCode.INTERNAL_ERROR
    return problem_response(request, code, status=exc.status_code, headers=headers)


async def _on_unhandled(request: Request, exc: Exception) -> JSONResponse:
    # Деталі — лише в лог сервера з request_id; клієнт отримує загальне повідомлення.
    logger.exception("unhandled error", extra={"request_id": _request_id(request)})
    return problem_response(request, ErrorCode.INTERNAL_ERROR)


def install_error_handlers(app: FastAPI) -> None:
    """Реєструє обробники: усі відмови API мають один формат (problem+json)."""
    # Обробники типізовано конкретними винятками; Starlette викликає кожен лише для «свого».
    app.add_exception_handler(ApiProblem, _on_api_problem)  # type: ignore[arg-type]
    app.add_exception_handler(
        RequestValidationError,
        _on_validation_error,  # type: ignore[arg-type]
    )
    app.add_exception_handler(StarletteHTTPException, _on_http_exception)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _on_unhandled)


# --- Документування помилок в OpenAPI ------------------------------------------------

_EXAMPLE_REQUEST_ID = "4f6c0b9e2d7a4e51a3c8d1f0b2e47a96"
_EXAMPLE_DETAILS: dict[ErrorCode, dict[str, Any]] = {
    ErrorCode.VALIDATION_FAILED: {
        "detail": "Запит не пройшов валідацію: перевірте поля, перелічені в errors.",
    },
    ErrorCode.BOOKING_LIMIT_REACHED: {
        "detail": "Ліміт — 3 активні бронювання, у вас уже 3.",
        "limit": 3,
        "active_bookings": 3,
    },
    ErrorCode.CANCELLATION_DEADLINE_PASSED: {
        "detail": "Скасувати можна було до 2026-10-20T08:00:00Z.",
        "cancel_deadline_at": "2026-10-20T08:00:00Z",
    },
}
_STATUS_HEADERS: dict[int, dict[str, Any]] = {
    401: {
        "WWW-Authenticate": {
            "description": "Схема автентифікації: Bearer.",
            "schema": {"type": "string"},
        }
    },
    503: {
        "Retry-After": {
            "description": "Через скільки секунд повторити запит.",
            "schema": {"type": "integer"},
        }
    },
}


def example_problem(code: ErrorCode, field_error: FieldError | None = None) -> dict[str, Any]:
    """Приклад тіла помилки для документації. Значення сталі, щоб специфікація
    генерувалася однаково на будь-якій машині (перевірка розходження в CI)."""
    spec = CATALOG[code]
    body: dict[str, Any] = {
        "type": problem_type_uri(code),
        "title": spec.title,
        "status": spec.status,
        "detail": spec.when,
        "code": code.value,
        "action": spec.action,
        "request_id": _EXAMPLE_REQUEST_ID,
    }
    body.update(_EXAMPLE_DETAILS.get(code, {}))
    if code is ErrorCode.VALIDATION_FAILED and field_error is not None:
        body["errors"] = [field_error.model_dump()]
    return body


def problem_responses(
    *codes: ErrorCode, field_error: FieldError | None = None
) -> dict[int | str, dict[str, Any]]:
    """Описи відповідей-помилок для параметра `responses=` маршруту.

    Групує коди за HTTP-статусом: для кожного статусу — перелік можливих причин
    в описі й приклад на кожну причину. `field_error` — реалістичний приклад помилки
    поля саме цієї операції для VALIDATION_FAILED. Схема — `Problem`; медіатип
    `application/problem+json` виставляє `api.main.custom_openapi`.
    """
    grouped: dict[int, list[ErrorCode]] = {}
    for code in codes:
        grouped.setdefault(CATALOG[code].status, []).append(code)
    responses: dict[int | str, dict[str, Any]] = {}
    for status in sorted(grouped):
        status_codes = grouped[status]
        lines = [f"- `{c.value}` — {CATALOG[c].title}" for c in status_codes]
        response: dict[str, Any] = {
            "model": Problem,
            "description": "Можливі причини:\n\n" + "\n".join(lines),
            "content": {
                "application/json": {
                    "examples": {
                        c.value: {
                            "summary": CATALOG[c].title,
                            "value": example_problem(c, field_error),
                        }
                        for c in status_codes
                    }
                }
            },
        }
        if status in _STATUS_HEADERS:
            response["headers"] = _STATUS_HEADERS[status]
        responses[status] = response
    return responses


def render_error_catalog_html() -> str:
    """HTML-каталог помилок для GitHub Pages; на нього посилається поле `type`."""
    rows = []
    for code, spec in CATALOG.items():
        rows.append(
            f'<tr id="{problem_slug(code)}"><td><code>{code.value}</code></td>'
            f"<td>{spec.status}</td><td>{spec.title}</td><td>{spec.when}</td>"
            f"<td>{spec.action}</td><td>{spec.refs or '—'}</td></tr>"
        )
    body = "\n".join(rows)
    return (
        "<!DOCTYPE html>\n<!-- ЗГЕНЕРОВАНО з src/api/errors.py (python scripts/export_openapi.py). "
        "Не редагуйте вручну. -->\n"
        '<html lang="uk">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>UniSlot API — каталог помилок</title>\n"
        "<style>body{font-family:system-ui,sans-serif;margin:2rem;max-width:72rem}"
        "table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccc;padding:.4rem;"
        "vertical-align:top;text-align:left}tr:target{background:#fff3c4}</style>\n"
        "</head>\n<body>\n<h1>Каталог помилок UniSlot API</h1>\n"
        "<p>Кожна відповідь-помилка має формат <code>application/problem+json</code> (RFC 9457). "
        'Поле <code>type</code> веде на рядок цієї таблиці. <a href="./">Документація API</a></p>\n'
        "<table>\n<thead><tr><th>code</th><th>HTTP</th><th>title</th><th>Коли виникає</th>"
        "<th>action</th><th>Вимоги</th></tr></thead>\n<tbody>\n"
        f"{body}\n</tbody>\n</table>\n</body>\n</html>\n"
    )
