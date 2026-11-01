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

from fastapi import FastAPI
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from api.config import API_VERSION
from api.log_paths import route_template
from api.request_ids import normalize_request_id

access_log = logging.getLogger("unislot.access")


class RequestContextMiddleware:
    """ASGI-обгортка без зайвих task group і буферизації тіла відповіді."""

    def __init__(self, app: ASGIApp) -> None:
        """Зберігає тільки наступний ASGI-застосунок, не стан окремого запиту."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Додає заголовки й один знеособлений запис після передачі відповіді."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = normalize_request_id(Headers(scope=scope).get("x-request-id"))
        state = scope.setdefault("state", {})
        state["request_id"] = request_id
        started, status = time.perf_counter(), 500

        async def send_response(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
                headers["API-Version"] = API_VERSION
                if scope["path"].startswith("/api/"):
                    headers.setdefault("Cache-Control", "no-store")
            await send(message)

        try:
            await self.app(scope, receive, send_response)
        finally:
            access_log.info(
                json.dumps(
                    {
                        "event": "request",
                        "request_id": request_id,
                        "method": scope["method"],
                        "path": route_template(scope["path"]),
                        "status": status,
                        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                        "user_id": state.get("user_id"),
                    },
                    ensure_ascii=False,
                )
            )


def install_middleware(app: FastAPI) -> None:
    """Підключає middleware до застосунку."""
    app.add_middleware(RequestContextMiddleware)
