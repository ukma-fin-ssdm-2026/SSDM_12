"""Ресурси — місце для модуля Павла (PR-5). Поки це порожній роутер, щоб каркас запускався.

PR модуля замінює цей файл повністю й додає кінцеві точки:
GET /resources, GET /resources/{resource_id}, POST /admin/resources,
PATCH /admin/resources/{resource_id}.
"""

from __future__ import annotations

from fastapi import APIRouter

from api.config import API_PREFIX

TAG = {
    "name": "resources",
    "description": "Каталог консультацій і аудиторій (FR-021, FR-060) та керування ними "
    "адміністратором (US-011: FR-060, FR-061).",
}

router = APIRouter(prefix=API_PREFIX, tags=[TAG["name"]])
