"""Явна транзакція навколо синхронного маршруту, включно з формуванням відповіді."""

import inspect
from contextlib import nullcontext
from functools import wraps
from typing import get_type_hints

from sqlalchemy.exc import DBAPIError
from sqlalchemy.exc import TimeoutError as PoolTimeout

from api.errors import ApiProblem, ErrorCode
from api.stubs.store import store


def transactional(function=None, *, direct=False, retry_deadlock=False):
    """Повертає атомарний маршрут з тією самою сигнатурою FastAPI й OpenAPI."""

    if function is None:
        return lambda target: transactional(target, direct=direct, retry_deadlock=retry_deadlock)

    @wraps(function)
    def wrapped(*args, **kwargs):
        for attempt in range(2 if retry_deadlock else 1):
            try:
                context = nullcontext() if direct and store.persistent else store.lock
                with context:
                    return function(*args, **kwargs)
            except DBAPIError as exc:
                state = getattr(exc.orig, "sqlstate", None)
                if retry_deadlock and attempt == 0 and state == "40P01":
                    # The inner transaction has rolled back; retry the complete command.
                    continue
                constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
                if state == "23505" and constraint == "uq_booking_slot_confirmed":
                    raise ApiProblem(ErrorCode.SLOT_ALREADY_BOOKED) from None
                if state == "23P01" and constraint == "ex_slot_active_overlap":
                    raise ApiProblem(ErrorCode.SLOT_OVERLAP) from None
                raise ApiProblem(
                    ErrorCode.TRANSIENT_CONFLICT, headers={"Retry-After": "1"}
                ) from None
            except PoolTimeout:
                raise ApiProblem(
                    ErrorCode.TRANSIENT_CONFLICT, headers={"Retry-After": "1"}
                ) from None
        # Недосяжно: кожна ітерація завершується return або raise, а `continue` можливий
        # лише на першій спробі. Guard лишає явну відмову, якщо межу циклу колись змінять:
        # без нього `wrapped` повернув би None і FastAPI віддала б 500 без причини (R-05).
        raise ApiProblem(  # pragma: no cover — страховка від майбутньої зміни range()
            ErrorCode.TRANSIENT_CONFLICT, headers={"Retry-After": "1"}
        )

    hints = get_type_hints(function, include_extras=True)
    signature = inspect.signature(function)
    wrapped.__signature__ = signature.replace(
        parameters=[
            p.replace(annotation=hints.get(p.name, p.annotation))
            for p in signature.parameters.values()
        ],
        return_annotation=hints.get("return", signature.return_annotation),
    )
    return wrapped
