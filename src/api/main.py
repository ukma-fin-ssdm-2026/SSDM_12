"""Точка входу REST API UniSlot.

Локальний запуск з кореня репозиторію (демо-токени діють лише з UNISLOT_DEMO_AUTH=1):

    UNISLOT_DEMO_AUTH=1 uvicorn api.main:app --app-dir src --reload --port 3000

Swagger UI — http://localhost:3000/api-docs, ReDoc — http://localhost:3000/redoc.
Під час кожного старту (і кожного перезапуску через --reload) сервер записує
згенеровану специфікацію в `docs/api/` — так зміна коду одразу оновлює документацію.
"""

from __future__ import annotations

import logging
import mimetypes
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles

from api import openapi_export, routers
from api.config import API_TITLE, API_VERSION, LOCAL_SERVER_URL, get_settings
from api.errors import PROBLEM_MEDIA_TYPE, ErrorCode, install_error_handlers, problem_responses
from api.middleware import install_middleware
from api.stubs.store import store

logger = logging.getLogger("unislot.api")

API_DESCRIPTION = """\
REST API системи бронювання консультацій та аудиторій **UniSlot** (команда SSDM_12, НаУКМА).

Специфікацію **згенеровано з коду** (FastAPI, підхід Code-First) — вручну її не редагують.
Проєктні рішення — `docs/api/api-design.md`, атрибути якості — `docs/api/quality-attributes.md`.

**Сховище.** Без `UNISLOT_DATABASE_URL` працює демо-адаптер у пам'яті. З цією
змінною API використовує мігровану PostgreSQL: дані та outbox зберігаються після
перезапуску. Окремий Worker доставляє повідомлення в локальну скриньку (C-002).

**Автентифікація.** POST `/auth/register` і `/auth/login` створюють обліковий запис і cookie-сесію.
Для змін із cookie потрібен X-CSRF-Token; demoBearer доступний лише за `UNISLOT_DEMO_AUTH=1`.

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


def _problem_ref() -> dict[str, str]:
    """Посилання на схему Problem — новий словник щоразу, щоб операції не ділили об'єкт."""
    return {"$ref": "#/components/schemas/Problem"}


def _catalog_response(code: ErrorCode, status: int) -> dict[str, Any]:
    """Опис відповіді з каталогу помилок без поля `model`, яке розуміє лише FastAPI."""
    response = problem_responses(code)[status]
    response.pop("model")
    return response


def _document_unavailable(operation: dict[str, Any]) -> None:
    """Кожна захищена операція може відповісти 503 TRANSIENT_CONFLICT (сховище зайняте)."""
    response = _catalog_response(ErrorCode.TRANSIENT_CONFLICT, 503)
    response["content"]["application/json"]["schema"] = _problem_ref()
    operation.setdefault("responses", {})["503"] = response


def _use_problem_media_type(operation: dict[str, Any]) -> None:
    """Відповіді 4xx і 5xx — `application/problem+json`, як їх і повертає обробник помилок."""
    for status, response in operation.get("responses", {}).items():
        content = response.get("content", {})
        if status[0] in "45" and "application/json" in content:
            content[PROBLEM_MEDIA_TYPE] = content.pop("application/json")


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
        for method, operation in path_item.items():
            if operation.get("security"):
                _document_unavailable(operation)
                if method in {"post", "put", "patch", "delete"}:
                    csrf_error = problem_responses(ErrorCode.CSRF_FAILED)[403]
                    csrf_error.pop("model")
                    csrf_media = csrf_error["content"]["application/json"]
                    existing = operation.setdefault("responses", {}).get("403")
                    if existing:
                        existing["description"] += "\n\n" + csrf_error["description"]
                        content = existing["content"]
                        media = content.get("application/json", content.get(PROBLEM_MEDIA_TYPE))
                        media.setdefault("examples", {}).update(csrf_media["examples"])
                    else:
                        csrf_media["schema"] = {"$ref": "#/components/schemas/Problem"}
                        operation["responses"]["403"] = csrf_error
                    operation.setdefault("parameters", []).append(
                        {
                            "name": "X-CSRF-Token",
                            "in": "header",
                            "required": False,
                            "description": "Обов'язковий для cookie-сесії; значення з /auth/login або unislot_csrf cookie. Для явно ввімкненого demoBearer не потрібний.",
                            "schema": {"type": "string", "minLength": 43, "maxLength": 43},
                        }
                    )
            _use_problem_media_type(operation)
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
    settings = get_settings()
    backend = previous = None
    previous_interval = sys.getswitchinterval()
    if sys.platform == "win32":
        sys.setswitchinterval(settings.thread_switch_interval_ms / 1000)
    try:
        if settings.database_url:
            from api.infrastructure.postgres import PostgresStore

            backend = PostgresStore(settings.database_url)
            previous = store.set_backend(backend)
        if settings.export_openapi_on_startup:
            try:
                for path in openapi_export.write_artifacts(app):
                    logger.info("OpenAPI згенеровано з коду → %s", path)
            except OSError as exc:
                # Права, файлова система лише для читання або брак місця — операційна
                # причина. Готова специфікація вже лежить у репозиторії, тож відмова
                # запису не варта того, щоб не обслуговувати запити. Дефект самої
                # генерації (не OSError) лишається фатальним — його не можна пропустити
                # в реліз (R-08, docs/reliability/scavenger-hunt.md).
                logger.warning(
                    "OpenAPI не записано (%s); чинною лишається специфікація з репозиторію",
                    type(exc).__name__,
                )
        yield
    finally:
        if sys.platform == "win32":
            sys.setswitchinterval(previous_interval)
        if backend is not None:
            store.set_backend(previous)
            backend.close()


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
        servers=[
            {"url": "/", "description": "Поточний сервер API (локальний або публічний HTTPS)"},
            {"url": LOCAL_SERVER_URL, "description": "Локальний запуск (uvicorn, порт 3000)"},
        ],
        openapi_tags=[module.TAG for module in routers.ALL],
        docs_url="/api-docs",
        redoc_url="/redoc",
        generate_unique_id_function=operation_id,
        lifespan=lifespan,
    )
    for module in routers.ALL:
        app.include_router(module.router)
    web_root = Path(__file__).with_name("web")
    # Windows registry may map .mjs to text/plain; module scripts must be JavaScript.
    mimetypes.add_type("text/javascript", ".mjs")
    app.mount("/static", StaticFiles(directory=web_root), name="web-static")

    @app.get("/", include_in_schema=False)
    def web_index() -> FileResponse:
        """Публічна оболонка UI; персональні дані надає лише захищений REST API."""
        return FileResponse(
            web_root / "index.html",
            headers={
                "Cache-Control": "no-store",
                "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "same-origin",
            },
        )

    install_error_handlers(app)
    install_middleware(app)
    if settings.cors_origins:
        # Лише явно перелічені UI origins; cookie-запити мають окремий CSRF-захист.
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
            allow_headers=[
                "Authorization",
                "Content-Type",
                "Idempotency-Key",
                "X-Request-ID",
                "X-CSRF-Token",
            ],
            expose_headers=["Location", "X-Request-ID", "API-Version"],
        )
    app.openapi = lambda: custom_openapi(app)  # type: ignore[method-assign]
    return app


app = create_app()
