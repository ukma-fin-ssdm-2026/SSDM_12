"""Тижневий шаблон у сценаріях провайдера й студента (US-008, TC-029…032)."""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from api import clock
from api.enums import BookingStatus
from api.policy import KYIV
from api.stubs.store import Ids, store

pytestmark = pytest.mark.req("FR-012", "FR-011", "US-008", "TC-029", "TC-030", "TC-031", "TC-032")
PROVIDER = {"Authorization": "Bearer demo-provider"}
PROVIDER_2 = {"Authorization": "Bearer demo-provider-2"}
STUDENT = {"Authorization": "Bearer demo-student"}
TEMPLATE_ID = uuid.UUID("8eba871c-b5c9-4092-8d90-669f5e6f9744")
PATTERN = {
    "weekday": 3,
    "start_local": "14:00",
    "end_local": "16:00",
    "slot_minutes": 30,
    "valid_from": "2026-10-19",
    "valid_to": None,
}


def url(resource_id: uuid.UUID = Ids.RES_DB_CONSULT, template_id: uuid.UUID = TEMPLATE_ID) -> str:
    return f"/api/v1/resources/{resource_id}/templates/{template_id}"


def template_slots() -> list:
    return sorted(
        (s for s in store.slots.values() if s.template_id == TEMPLATE_ID), key=lambda s: s.starts_at
    )


def book(client: TestClient, slot_id: uuid.UUID) -> uuid.UUID:
    response = client.post("/api/v1/bookings", headers=STUDENT, json={"slot_id": str(slot_id)})
    assert response.status_code == 201, response.text
    return uuid.UUID(response.json()["id"])


def test_template_materializes_entire_horizon_and_is_searchable(client: TestClient) -> None:
    response = client.put(url(), headers=PROVIDER, json=PATTERN)
    assert response.status_code == 201
    assert response.json()["created_slots"] == 8 and not response.json()["conflicts"]
    slots = template_slots()
    found = client.get("/api/v1/slots?limit=100", headers=STUDENT).json()["items"]
    assert {str(s.id) for s in slots} <= {s["id"] for s in found}
    assert slots[0].starts_at.hour == 11 and slots[4].starts_at.hour == 12
    assert (
        slots[0].starts_at.astimezone(KYIV).hour == slots[4].starts_at.astimezone(KYIV).hour == 14
    )


def test_repeating_or_concurrent_put_does_not_duplicate_slots(client: TestClient) -> None:
    def save(_: int) -> int:
        return client.put(url(), headers=PROVIDER, json=PATTERN).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(save, range(2))) == [200, 201]
    first_ids = {s.id for s in template_slots()}
    repeated = client.put(url(), headers=PROVIDER, json=PATTERN)
    assert repeated.json()["created_slots"] == 0
    assert {s.id for s in template_slots()} == first_ids and len(first_ids) == 8
    assert client.get(url(), headers=PROVIDER).status_code == 200


def test_edit_keeps_booking_deadline_and_reminder_but_changes_unbooked_slots(
    client: TestClient,
) -> None:
    assert client.put(url(), headers=PROVIDER, json=PATTERN).status_code == 201
    old_slot, unbooked = template_slots()[:2]
    booking_id = book(client, old_slot.id)
    booking = store.bookings[booking_id]
    old_deadline, old_due = booking.cancel_deadline_at, store.reminders[booking_id]
    response = client.put(
        url(), headers=PROVIDER, json={**PATTERN, "start_local": "15:00", "end_local": "17:00"}
    )
    assert response.status_code == 200
    assert response.json()["retained_booked_slots"] == 1
    assert unbooked.id not in store.slots
    assert booking.status is BookingStatus.CONFIRMED and booking.slot_id == old_slot.id
    assert booking.cancel_deadline_at == old_deadline and store.reminders[booking_id] == old_due


def test_cancelled_history_remains_but_old_slot_cannot_be_booked_again(client: TestClient) -> None:
    client.put(url(), headers=PROVIDER, json=PATTERN)
    old_slot = template_slots()[0]
    booking_id = book(client, old_slot.id)
    assert client.post(f"/api/v1/bookings/{booking_id}/cancel", headers=STUDENT).status_code == 200
    response = client.put(url(), headers=PROVIDER, json={**PATTERN, "slot_minutes": 60})
    assert response.status_code == 200
    assert store.slots[old_slot.id].is_active is False
    assert store.bookings[booking_id].slot_id == old_slot.id
    rejected = client.post("/api/v1/bookings", headers=STUDENT, json={"slot_id": str(old_slot.id)})
    assert rejected.status_code == 409 and rejected.json()["code"] == "SLOT_WITHDRAWN"
    assert client.get(f"/api/v1/slots/{old_slot.id}", headers=STUDENT).json()["available"] is False
    assert client.put(url(), headers=PROVIDER, json=PATTERN).status_code == 200
    assert store.slots[old_slot.id].is_active is True


def test_changing_duration_reports_conflict_with_the_preserved_booking(client: TestClient) -> None:
    client.put(url(), headers=PROVIDER, json=PATTERN)
    old = template_slots()[0]
    booking_id = book(client, old.id)
    response = client.put(url(), headers=PROVIDER, json={**PATTERN, "slot_minutes": 60})
    assert response.status_code == 200
    assert response.json()["retained_booked_slots"] == 1
    assert response.json()["created_slots"] == 3
    assert [c["conflicting_slot_id"] for c in response.json()["conflicts"]] == [str(old.id)]
    assert store.bookings[booking_id].status is BookingStatus.CONFIRMED


def test_manual_slot_can_replace_withdrawn_time_without_reviving_old_history(
    client: TestClient,
) -> None:
    client.put(url(), headers=PROVIDER, json=PATTERN)
    old = template_slots()[0]
    booking_id = book(client, old.id)
    client.post(f"/api/v1/bookings/{booking_id}/cancel", headers=STUDENT)
    client.put(
        url(), headers=PROVIDER, json={**PATTERN, "start_local": "15:00", "end_local": "17:00"}
    )
    manual = client.post(
        f"/api/v1/resources/{Ids.RES_DB_CONSULT}/slots",
        headers=PROVIDER,
        json={"starts_at": old.starts_at.isoformat(), "duration_minutes": 30},
    )
    assert manual.status_code == 201
    restored = client.put(url(), headers=PROVIDER, json=PATTERN)
    assert manual.json()["id"] in {c["conflicting_slot_id"] for c in restored.json()["conflicts"]}
    assert store.slots[old.id].is_active is False


def test_preserved_booking_slot_is_withdrawn_when_later_cancelled(client: TestClient) -> None:
    client.put(url(), headers=PROVIDER, json=PATTERN)
    old = template_slots()[0]
    booking_id = book(client, old.id)
    client.put(
        url(), headers=PROVIDER, json={**PATTERN, "start_local": "15:00", "end_local": "17:00"}
    )
    assert client.post(f"/api/v1/bookings/{booking_id}/cancel", headers=STUDENT).status_code == 200
    rejected = client.post("/api/v1/bookings", headers=STUDENT, json={"slot_id": str(old.id)})
    assert rejected.status_code == 409 and rejected.json()["code"] == "SLOT_WITHDRAWN"


def test_manual_slot_conflicts_are_listed_without_modifying_manual_slots(
    client: TestClient,
) -> None:
    before = {Ids.SLOT_DB_D2_1000, Ids.SLOT_DB_D2_1030}
    response = client.put(
        url(),
        headers=PROVIDER,
        json={
            **PATTERN,
            "weekday": 3,
            "start_local": "10:00",
            "end_local": "12:00",
            "slot_minutes": 120,
        },
    )
    assert response.status_code == 201
    conflicts = response.json()["conflicts"]
    assert {uuid.UUID(c["conflicting_slot_id"]) for c in conflicts} == before
    assert response.json()["created_slots"] == 1
    assert all(store.slots[s].template_id is None for s in before)


def test_search_extends_horizon_as_time_advances(client: TestClient, monkeypatch) -> None:
    client.put(url(), headers=PROVIDER, json=PATTERN)
    old_ids = {s.id for s in template_slots()}
    now = clock.utc_now() + timedelta(days=7)
    monkeypatch.setattr(clock, "utc_now", lambda: now)
    found = client.get("/api/v1/slots?date=2026-11-04&limit=100", headers=STUDENT)
    assert found.status_code == 200
    assert len(found.json()["items"]) == 4
    assert len(template_slots()) == 12 and old_ids <= {s.id for s in template_slots()}
    client.get("/api/v1/slots?date=2026-11-04&limit=100", headers=STUDENT)
    assert len(template_slots()) == 12


def test_invalid_dst_candidates_are_visible_to_provider(client: TestClient) -> None:
    response = client.put(
        url(),
        headers=PROVIDER,
        json={**PATTERN, "weekday": 7, "start_local": "03:00", "end_local": "04:00"},
    )
    assert response.status_code == 201
    assert {c["code"] for c in response.json()["conflicts"]} == {"ambiguous_local_time"}
    assert client.get(url(), headers=PROVIDER).json()["conflicts"] == response.json()["conflicts"]


def test_foreign_template_id_cannot_be_moved_to_an_owned_resource(client: TestClient) -> None:
    assert client.put(url(Ids.RES_NET_CONSULT), headers=PROVIDER_2, json=PATTERN).status_code == 201
    before = set(store.slots)
    response = client.put(url(), headers=PROVIDER, json=PATTERN)
    assert response.status_code == 404 and response.json()["code"] == "TEMPLATE_NOT_FOUND"
    assert set(store.slots) == before


def test_unknown_template_and_resource_are_404(client: TestClient) -> None:
    assert client.get(url(), headers=PROVIDER).status_code == 404
    assert client.put(url(uuid.uuid4()), headers=PROVIDER, json=PATTERN).status_code == 404


def test_template_creation_requires_a_v4_identifier(client: TestClient) -> None:
    response = client.put(url(template_id=uuid.UUID(int=0)), headers=PROVIDER, json=PATTERN)
    assert response.status_code == 422
    assert not store.templates


@pytest.mark.parametrize(
    "changes",
    [
        {"weekday": 0},
        {"weekday": 8},
        {"weekday": True},
        {"weekday": "3"},
        {"slot_minutes": 17},
        {"slot_minutes": 0},
        {"slot_minutes": True},
        {"start_local": "14:00:01"},
        {"start_local": "14:00+03:00"},
        {"start_local": 50},
        {"end_local": "14:00"},
        {"end_local": "13:00"},
        {"end_local": "15:01"},
        {"valid_to": "2026-10-18"},
        {"extra": True},
    ],
)
def test_invalid_template_never_changes_existing_state(client: TestClient, changes: dict) -> None:
    before = set(store.slots)
    response = client.put(url(), headers=PROVIDER, json={**PATTERN, **changes})
    assert response.status_code == 422
    assert not store.templates and set(store.slots) == before
