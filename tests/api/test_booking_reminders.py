"""Нагадування в житті бронювання (FR-051, FR-054; TP-13) — тести-специфікація.

Лаб 7, бонус 3: тести написано до реалізації й закомічено червоними. Заплановані
нагадування заглушка тримає в `store.reminders` — словнику «ID бронювання → момент
нагадування (UTC)», як журнал аудиту в `store.audit`. Надсилання й черга повторних
спроб — Лаб 9 (ADR-003); тут лише планування.

Час заморожено на `NOW` = пн 19.10.2026, 12:00 за Києвом (`tests/conftest.py`):
- SLOT_NET_D4_0900 — за чотири дні, отже нагадування планується;
- SLOT_317_D3_1600 — за три дні, теж планується;
- SLOT_DB_D1_1030 — завтра о 10:30, тобто за 22,5 год: лише підтвердження (A-004).
Демо-студент уже має 2 активні бронювання з ліміту 3, тож нове — одне на тест.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from api.stubs.store import Ids, store

pytestmark = pytest.mark.req("US-005", "FR-051", "TP-13")

STUDENT = {"Authorization": "Bearer demo-student"}
LEAD = timedelta(hours=24)  # A-004


def book(client: TestClient, slot_id: uuid.UUID) -> uuid.UUID:
    response = client.post("/api/v1/bookings", headers=STUDENT, json={"slot_id": str(slot_id)})
    assert response.status_code == 201, response.text
    return uuid.UUID(response.json()["id"])


def due(slot_id: uuid.UUID):
    return store.slots[slot_id].starts_at - LEAD


def test_demo_data_has_no_planned_reminders() -> None:
    assert store.reminders == {}


@pytest.mark.req("TC-017")
def test_booking_more_than_24_hours_ahead_plans_a_reminder(client: TestClient) -> None:
    booking_id = book(client, Ids.SLOT_NET_D4_0900)
    assert store.reminders == {booking_id: due(Ids.SLOT_NET_D4_0900)}


@pytest.mark.req("TC-018")
def test_booking_less_than_24_hours_ahead_plans_no_reminder(client: TestClient) -> None:
    book(client, Ids.SLOT_DB_D1_1030)
    assert store.reminders == {}


def test_rejected_booking_plans_nothing(client: TestClient) -> None:
    response = client.post(
        "/api/v1/bookings", headers=STUDENT, json={"slot_id": str(Ids.SLOT_DB_D1_1000)}
    )
    assert response.status_code == 409
    assert store.reminders == {}


def test_idempotent_replay_plans_one_reminder(client: TestClient) -> None:
    headers = {**STUDENT, "Idempotency-Key": "reminder-replay-01"}
    body = {"slot_id": str(Ids.SLOT_NET_D4_0900)}
    first = client.post("/api/v1/bookings", headers=headers, json=body)
    again = client.post("/api/v1/bookings", headers=headers, json=body)
    assert first.json()["id"] == again.json()["id"]
    assert list(store.reminders) == [uuid.UUID(first.json()["id"])]


@pytest.mark.req("TC-019")
def test_cancel_removes_the_planned_reminder(client: TestClient) -> None:
    booking_id = book(client, Ids.SLOT_NET_D4_0900)
    response = client.post(f"/api/v1/bookings/{booking_id}/cancel", headers=STUDENT)
    assert response.status_code == 200
    assert store.reminders == {}


@pytest.mark.req("US-003", "FR-054", "TC-016")
def test_reschedule_replaces_the_reminder(client: TestClient) -> None:
    old_id = book(client, Ids.SLOT_NET_D4_0900)
    response = client.post(
        f"/api/v1/bookings/{old_id}/reschedule",
        headers=STUDENT,
        json={"new_slot_id": str(Ids.SLOT_317_D3_1600)},
    )
    assert response.status_code == 201
    new_id = uuid.UUID(response.json()["id"])
    assert store.reminders == {new_id: due(Ids.SLOT_317_D3_1600)}


@pytest.mark.req("US-003", "FR-054", "TC-016")
def test_reschedule_into_the_last_24_hours_drops_the_reminder(client: TestClient) -> None:
    old_id = book(client, Ids.SLOT_NET_D4_0900)
    response = client.post(
        f"/api/v1/bookings/{old_id}/reschedule",
        headers=STUDENT,
        json={"new_slot_id": str(Ids.SLOT_DB_D1_1030)},
    )
    assert response.status_code == 201
    assert store.reminders == {}


@pytest.mark.req("US-003", "FR-054")
def test_failed_reschedule_keeps_the_old_reminder(client: TestClient) -> None:
    old_id = book(client, Ids.SLOT_NET_D4_0900)
    response = client.post(
        f"/api/v1/bookings/{old_id}/reschedule",
        headers=STUDENT,
        json={"new_slot_id": str(Ids.SLOT_DB_D1_1000)},  # зайнятий іншим студентом
    )
    assert response.status_code == 409
    assert store.reminders == {old_id: due(Ids.SLOT_NET_D4_0900)}
