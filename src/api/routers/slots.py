"""Слоти — місце для модуля Аксенії (PR-4). Поки це порожній роутер, щоб каркас запускався.

PR модуля замінює цей файл повністю й додає кінцеві точки:
GET /slots, GET /slots/{slot_id}, POST /resources/{resource_id}/slots.
"""

from __future__ import annotations

from fastapi import APIRouter

from api.config import API_PREFIX

TAG = {
    "name": "slots",
    "description": "Пошук вільних слотів із фільтрами (US-004) і публікація разових слотів "
    "провайдером (US-007).",
}

router = APIRouter(prefix=API_PREFIX, tags=[TAG["name"]])
