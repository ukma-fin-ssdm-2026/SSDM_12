"""Явна транзакція навколо синхронного маршруту, включно з формуванням відповіді."""

import inspect
from contextlib import nullcontext
from functools import wraps
from typing import get_type_hints

from sqlalchemy.exc import DBAPIError

from api.errors import ApiProblem, ErrorCode
from api.stubs.store import store


def transactional(function=None, *, direct=False):
    """Повертає атомарний маршрут з тією самою сигнатурою FastAPI й OpenAPI."""

    if function is None:
        return lambda target: transactional(target, direct=direct)

    @wraps(function)
    def wrapped(*args, **kwargs):
        try:
            context = nullcontext() if direct and store.persistent else store.lock
            with context:
                return function(*args, **kwargs)
        except DBAPIError:
            raise ApiProblem(ErrorCode.TRANSIENT_CONFLICT, headers={"Retry-After": "1"}) from None

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
