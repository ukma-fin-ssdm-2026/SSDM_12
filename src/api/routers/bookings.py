"""Бронювання — місце для модуля Дениса (PR-3). Поки це порожній роутер, щоб каркас запускався.

PR модуля замінює цей файл повністю й додає кінцеві точки:
POST /bookings, GET /bookings/{booking_id}, POST /bookings/{booking_id}/cancel,
POST /bookings/{booking_id}/reschedule, GET /me/bookings.
"""

from __future__ import annotations

from fastapi import APIRouter

from api.config import API_PREFIX

TAG = {
    "name": "bookings",
    "description": "Бронювання слотів студентом (US-001), скасування (US-002), перенесення "
    "(US-003) і перегляд власних бронювань (US-014).",
}

router = APIRouter(prefix=API_PREFIX, tags=[TAG["name"]])
