"""Точка входу REST API UniSlot.

Локальний запуск з кореня репозиторію:

    uvicorn api.main:app --app-dir src --reload --port 3000

Swagger UI — http://localhost:3000/api-docs, ReDoc — http://localhost:3000/redoc.
Під час кожного старту (і кожного перезапуску через --reload) сервер записує
згенеровану специфікацію в `docs/api/` — так зміна коду одразу оновлює документацію.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIRoute

from api import openapi_export, routers
from api.config import API_TITLE, API_VERSION, LOCAL_SERVER_URL, get_settings
from api.errors import PROBLEM_MEDIA_TYPE, install_error_handlers
from api.middleware import install_middleware

logger = logging.getLogger("unislot.api")

API_DESCRIPTION = """\
REST API системи бронювання консультацій та аудиторій **UniSlot** (команда SSDM_12, НаУКМА).

Специфікацію **згенеровано з коду** (FastAPI, підхід Code-First) — вручну її не редагують.
Проєктні рішення — `docs/api/api-design.md`, атрибути якості — `docs/api/quality-attributes.md`.

**Лаб 4: заглушки.** Відповіді будуються з демо-даних у пам'яті; правила бронювання
перевіряються, але дані не зберігаються між перезапусками сервера.

**Автентифікація (заглушка).** Натисніть «Authorize» і введіть демо-токен:
`demo-student`, `demo-student-2`, `demo-provider`, `demo-provider-2` або `demo-admin`.

**Помилки.** Усі відмови — `application/problem+json` (RFC 9457) з полями `code`,
`action` і `request_id`; поле `type` веде в каталог помилок.

**Пагінація.** Каталоги — `limit`/`offset`; пошук слотів — курсор `next_cursor`.
Розмір сторінки — не більше 100.

**Час.** Усі моменти часу — RFC 3339 в UTC; фільтр `date` у пошуку — дата за Києвом (A-007).
"""


def operation_id(route: APIRoute) -> str:
    """operationId = ім'я функції маршруту: `create_booking`, а не
    `create_booking_api_v1_bookings_post`. З цих назв MCP-сервер робить назви інструментів."""
    return route.name


def custom_openapi(app: FastAPI) -> dict[str, Any]:
    """Генерує специфікацію й виставляє `application/problem+json` для відповідей 4xx/5xx.

    FastAPI документує додаткові відповіді як `application/json`; наш обробник
    помилок повертає `application/problem+json`, тож документація має збігатися.
    """
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        summary=app.summary,
        description=app.description,
        routes=app.routes,
        tags=app.openapi_tags,
        servers=app.servers,
        contact=app.contact,
    )
    for path_item in schema.get("paths", {}).values():
        for operation in path_item.values():
            for status, response in operation.get("responses", {}).items():
                content = response.get("content", {})
                if status[0] in "45" and "application/json" in content:
                    content[PROBLEM_MEDIA_TYPE] = content.pop("application/json")
    app.openapi_schema = schema
    return schema


def configure_logging() -> None:
    """Журнали `unislot.*` — у stderr, один рядок на подію (без налаштування — мовчать)."""
    log = logging.getLogger("unislot")
    if not log.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        log.addHandler(handler)
        log.setLevel(logging.INFO)
        log.propagate = False


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Під час старту записує специфікацію в docs/api/ (цикл Code-First)."""
    if get_settings().export_openapi_on_startup:
        for path in openapi_export.write_artifacts(app):
            logger.info("OpenAPI згенеровано з коду → %s", path)
    yield


def create_app() -> FastAPI:
    """Збирає застосунок: роутери, обробники помилок, middleware."""
    configure_logging()
    settings = get_settings()
    app = FastAPI(
        title=API_TITLE,
        version=API_VERSION,
        summary="Бронювання консультацій викладачів і навчальних аудиторій.",
        description=API_DESCRIPTION,
        contact={"name": "Команда SSDM_12", "url": "https://github.com/ukma-fin-ssdm-2026/SSDM_12"},
        servers=[{"url": LOCAL_SERVER_URL, "description": "Локальний запуск (uvicorn, порт 3000)"}],
        openapi_tags=[module.TAG for module in routers.ALL],
        docs_url="/api-docs",
        redoc_url="/redoc",
        generate_unique_id_function=operation_id,
        lifespan=lifespan,
    )
    for module in routers.ALL:
        app.include_router(module.router)
    install_error_handlers(app)
    install_middleware(app)
    if settings.cors_origins:
        # Лише явно перелічені джерела (THR-13); cookie не дозволяємо — автентифікація в заголовку.
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_methods=["GET", "POST", "PATCH"],
            allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
            expose_headers=["Location", "X-Request-ID", "API-Version"],
        )
    app.openapi = lambda: custom_openapi(app)  # type: ignore[method-assign]
    return app


app = create_app()
