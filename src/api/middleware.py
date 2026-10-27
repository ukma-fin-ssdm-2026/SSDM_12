"""Наскрізна обробка запитів: ідентифікатор запиту, версія API, кешування, журнал.

- `X-Request-ID`: приймаємо від клієнта, якщо він безпечного формату, інакше генеруємо.
  Той самий ідентифікатор потрапляє в тіло помилки (`request_id`) і в журнал —
  так звернення користувача знаходять у логах (Лекція 4, §3.2).
- `API-Version`: версія контракту у кожній відповіді (версіонування в коді).
- `Cache-Control: no-store` для `/api/`: відповіді містять персональні дані, а кешу
  немає, доки вимір PERF-001 не покаже потреби (DD-12).
- Журнал — один рядок JSON на запит: метод, шаблон маршруту, статус, тривалість,
  користувач. Ідентифікатори зі шляху замінено на `{id}` (THR-09, CWE-532).
  Тіла запитів, токени й рядок запиту не журналюються (THR-02, THR-09).
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response

from api.config import API_VERSION
from api.log_paths import route_template
from api.request_ids import normalize_request_id

access_log = logging.getLogger("unislot.access")


def _incoming_request_id(request: Request) -> str:
    candidate = request.headers.get("X-Request-ID", "")
    return normalize_request_id(candidate)


def install_middleware(app: FastAPI) -> None:
    """Підключає middleware до застосунку."""

    @app.middleware("http")
    async def request_context(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = _incoming_request_id(request)
        request.state.request_id = request_id
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["API-Version"] = API_VERSION
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        access_log.info(
            json.dumps(
                {
                    "event": "request",
                    "request_id": request_id,
                    "method": request.method,
                    "path": route_template(request.url.path),
                    "status": response.status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                    "user_id": getattr(request.state, "user_id", None),
                },
                ensure_ascii=False,
            )
        )
        return response
