"""Блокування як користувацький сценарій: пошук, бронювання, нагадування й зняття."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from api import clock
from api.enums import BookingStatus, CancellationKind
from api.stubs.store import Ids, store

pytestmark = pytest.mark.req("FR-013", "FR-014", "FR-023", "FR-045", "US-009")
STUDENT = {"Authorization": "Bearer demo-student"}
PROVIDER = {"Authorization": "Bearer demo-provider"}
PROVIDER_2 = {"Authorization": "Bearer demo-provider-2"}


def blocks_url(resource_id: uuid.UUID = Ids.RES_DB_CONSULT) -> str:
    return f"/api/v1/resources/{resource_id}/blocks"


def block_payload(slot_id: uuid.UUID = Ids.SLOT_NET_D4_0900) -> dict[str, str]:
    slot = store.slots[slot_id]
    return {
        "starts_at": slot.starts_at.isoformat(),
        "ends_at": slot.ends_at.isoformat(),
        "reason": "Засідання кафедри",
    }


def test_block_cancels_booking_and_reminder_and_unblock_frees_the_slot(client: TestClient) -> None:
    created = client.post(
        "/api/v1/bookings", headers=STUDENT, json={"slot_id": str(Ids.SLOT_NET_D4_0900)}
    )
    booking_id = uuid.UUID(created.json()["id"])
    assert booking_id in store.reminders
    url = blocks_url(Ids.RES_NET_CONSULT)
    blocked = client.post(url, headers=PROVIDER_2, json=block_payload())
    assert blocked.status_code == 201
    assert blocked.json()["cancelled_bookings"] == 1
    assert str(booking_id) not in blocked.text
    booking = store.bookings[booking_id]
    assert booking.status is BookingStatus.CANCELLED
    assert booking.cancellation_kind is CancellationKind.PROVIDER_BLOCK
    assert booking.cancellation_reason == "Засідання кафедри"
    assert booking.cancelled_by == Ids.PROVIDER_2
    assert booking_id not in store.reminders
    rejected = client.post(
        "/api/v1/bookings", headers=STUDENT, json={"slot_id": str(Ids.SLOT_NET_D4_0900)}
    )
    assert rejected.status_code == 409
    assert rejected.json()["code"] == "SLOT_BLOCKED"
    found = client.get("/api/v1/slots?limit=100", headers=STUDENT).json()["items"]
    assert str(Ids.SLOT_NET_D4_0900) not in {s["id"] for s in found}
    deleted = client.delete(f"{url}/{blocked.json()['id']}", headers=PROVIDER_2)
    assert deleted.status_code == 204 and deleted.content == b""
    assert booking.status is BookingStatus.CANCELLED
    detail = client.get(f"/api/v1/slots/{Ids.SLOT_NET_D4_0900}", headers=STUDENT)
    assert detail.json()["available"] is True


def test_block_cancels_all_overlapping_future_bookings(client: TestClient) -> None:
    booked = client.post(
        "/api/v1/bookings", headers=STUDENT, json={"slot_id": str(Ids.SLOT_DB_D1_1030)}
    )
    assert booked.status_code == 201
    payload = block_payload(Ids.SLOT_DB_D1_1000)
    payload["ends_at"] = store.slots[Ids.SLOT_DB_D1_1030].ends_at.isoformat()
    response = client.post(blocks_url(), headers=PROVIDER, json=payload)
    assert response.status_code == 201
    assert response.json()["cancelled_bookings"] == 2
    assert store.bookings[Ids.BOOKING_ACTIVE].status is BookingStatus.CONFIRMED


def test_adjacent_block_does_not_cancel_a_booking(client: TestClient) -> None:
    slot = store.slots[Ids.SLOT_DB_D2_1000]
    response = client.post(
        blocks_url(),
        headers=PROVIDER,
        json={
            "starts_at": slot.ends_at.isoformat(),
            "ends_at": (slot.ends_at + timedelta(minutes=30)).isoformat(),
            "reason": "Перерва",
        },
    )
    assert response.status_code == 201
    assert response.json()["cancelled_bookings"] == 0
    assert store.bookings[Ids.BOOKING_ACTIVE].status is BookingStatus.CONFIRMED


def test_started_booking_rejects_entire_block_without_partial_cancellation(
    client: TestClient,
) -> None:
    old = store.bookings[Ids.BOOKING_ACTIVE]
    started = replace(old, id=uuid.uuid4(), slot_id=Ids.SLOT_DB_STARTED)
    store.bookings[started.id] = started
    before_blocks, before_reminders = dict(store.blocks), dict(store.reminders)
    response = client.post(
        blocks_url(),
        headers=PROVIDER,
        json={
            "starts_at": clock.utc_now().isoformat(),
            "ends_at": (store.slots[old.slot_id].ends_at + timedelta(hours=1)).isoformat(),
            "reason": "Термінова подія",
        },
    )
    assert response.status_code == 409
    assert response.json()["code"] == "SLOT_STARTED"
    assert store.blocks == before_blocks and store.reminders == before_reminders
    assert old.status is BookingStatus.CONFIRMED and started.status is BookingStatus.CONFIRMED


def test_overlapping_blocks_keep_time_unavailable_until_both_are_removed(
    client: TestClient,
) -> None:
    url = blocks_url(Ids.RES_NET_CONSULT)
    first = client.post(url, headers=PROVIDER_2, json=block_payload()).json()["id"]
    second = client.post(url, headers=PROVIDER_2, json=block_payload()).json()["id"]
    assert client.delete(f"{url}/{first}", headers=PROVIDER_2).status_code == 204
    assert store.is_blocked(store.slots[Ids.SLOT_NET_D4_0900])
    assert client.delete(f"{url}/{second}", headers=PROVIDER_2).status_code == 204
    assert not store.is_blocked(store.slots[Ids.SLOT_NET_D4_0900])


@pytest.mark.parametrize(
    "changes",
    [
        {"reason": "   "},
        {"reason": "x" * 501},
        {"reason": None},
        {"starts_at": "2026-10-19T10:00:00"},
        {"ends_at": "2026-10-01T00:00:00Z"},
        {"extra": 1},
    ],
)
def test_invalid_block_does_not_change_state(client: TestClient, changes: dict) -> None:
    before = dict(store.blocks)
    response = client.post(
        blocks_url(Ids.RES_NET_CONSULT), headers=PROVIDER_2, json={**block_payload(), **changes}
    )
    assert response.status_code == 422
    assert store.blocks == before


def test_past_block_is_rejected(client: TestClient) -> None:
    response = client.post(
        blocks_url(),
        headers=PROVIDER,
        json={
            "starts_at": (clock.utc_now() - timedelta(minutes=1)).isoformat(),
            "ends_at": (clock.utc_now() + timedelta(hours=1)).isoformat(),
            "reason": "Подія",
        },
    )
    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "body.starts_at"


def test_block_is_normalized_to_utc(client: TestClient) -> None:
    response = client.post(
        blocks_url(),
        headers=PROVIDER,
        json={
            "starts_at": "2026-10-21T10:00:00+03:00",
            "ends_at": "2026-10-21T11:00:00+03:00",
            "reason": "  Подія  ",
        },
    )
    assert response.status_code == 201
    rec = store.blocks[uuid.UUID(response.json()["id"])]
    assert rec.starts_at.hour == 7 and rec.reason == "Подія"
    assert rec.starts_at.utcoffset() == timedelta(0)


def test_unknown_or_foreign_block_id_is_404_without_deleting_it(client: TestClient) -> None:
    url = blocks_url()
    for block_id in (uuid.uuid4(), Ids.BLOCK_317_D2):
        response = client.delete(f"{url}/{block_id}", headers=PROVIDER)
        assert response.status_code == 404
        assert response.json()["code"] == "BLOCK_NOT_FOUND"
    assert Ids.BLOCK_317_D2 in store.blocks


def test_missing_resource_is_404(client: TestClient) -> None:
    response = client.post(blocks_url(uuid.uuid4()), headers=PROVIDER, json=block_payload())
    assert response.status_code == 404
