"""Бронювання на заглушках: US-001, US-002, US-003, US-014
(TC-001…TC-009, TC-013…TC-015, TC-056, TC-058).

Це перевірка контракту, а не REL-001: справжню відсутність подвійних бронювань доведе
інтеграційний тест на PostgreSQL у Лаб 6 (TC-004). Тут конкурентний тест показує, що й
заглушка відповідає за контрактом: один 201, решта 409.
"""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from api import clock
from api.enums import BookingStatus
from api.stubs.store import Ids, store

STUDENT = {"Authorization": "Bearer demo-student"}  # має 2 активні бронювання з ліміту 3
STUDENT_2 = {"Authorization": "Bearer demo-student-2"}
PROVIDER = {"Authorization": "Bearer demo-provider"}


def book(client: TestClient, slot_id: uuid.UUID, headers=STUDENT, **kwargs):
    return client.post(
        "/api/v1/bookings", headers=headers, json={"slot_id": str(slot_id)}, **kwargs
    )


def at(iso: str) -> datetime:
    return datetime.fromisoformat(iso)


def test_booking_a_free_slot(client: TestClient) -> None:
    r = book(client, Ids.SLOT_DB_D1_1030)
    assert r.status_code == 201
    body = r.json()
    assert r.headers["Location"] == f"/api/v1/bookings/{body['id']}"
    assert body["state"] == "active" and body["can_cancel"] is True
    slot = store.slots[Ids.SLOT_DB_D1_1030]
    assert at(body["cancel_deadline_at"]) == slot.starts_at - timedelta(hours=2)  # FR-041, A-003


@pytest.mark.parametrize(
    ("slot_id", "code"),
    [
        (Ids.SLOT_DB_D1_1000, "SLOT_ALREADY_BOOKED"),
        (Ids.SLOT_DB_STARTED, "SLOT_STARTED"),
        (Ids.SLOT_DB_D20, "SLOT_OUT_OF_HORIZON"),
        (Ids.SLOT_317_D2_1500, "SLOT_BLOCKED"),
        (Ids.SLOT_225_D2_1000, "BOOKING_OVERLAP"),
    ],
)
def test_unbookable_slots_give_409_with_reason(client: TestClient, slot_id, code) -> None:
    before = len(store.bookings)
    r = book(client, slot_id)
    assert r.status_code == 409
    assert r.json()["code"] == code and r.json()["action"]  # USAB-001: причина й дія
    assert len(store.bookings) == before


def test_unknown_slot_is_404(client: TestClient) -> None:
    r = book(client, uuid.uuid4())
    assert r.status_code == 404 and r.json()["code"] == "SLOT_NOT_FOUND"


def test_limit_reached_names_limit_and_count(client: TestClient) -> None:
    assert book(client, Ids.SLOT_DB_D1_1030).status_code == 201  # третє активне
    r = book(client, Ids.SLOT_NET_D4_0900)
    assert r.status_code == 409
    assert r.json()["code"] == "BOOKING_LIMIT_REACHED"
    assert (r.json()["limit"], r.json()["active_bookings"]) == (3, 3)


def test_only_students_book(client: TestClient) -> None:
    r = book(client, Ids.SLOT_DB_D1_1030, headers=PROVIDER)
    assert r.status_code == 403 and r.json()["code"] == "FORBIDDEN_ROLE"


def test_concurrent_requests_give_one_201(client: TestClient) -> None:
    def attempt(_: int) -> int:
        return book(client, Ids.SLOT_DB_D1_1030, headers=STUDENT_2).status_code

    with ThreadPoolExecutor(max_workers=20) as pool:
        codes = list(pool.map(attempt, range(40)))
    assert codes.count(201) == 1 and codes.count(409) == 39
    assert (
        sum(
            1
            for b in store.bookings.values()
            if b.slot_id == Ids.SLOT_DB_D1_1030 and b.status is BookingStatus.CONFIRMED
        )
        == 1
    )


def test_idempotency_key_replays_first_booking(client: TestClient) -> None:
    key = {"Idempotency-Key": "retry-after-timeout-01"}
    first = book(client, Ids.SLOT_DB_D1_1030, headers={**STUDENT, **key})
    again = book(client, Ids.SLOT_DB_D1_1030, headers={**STUDENT, **key})
    assert first.status_code == again.status_code == 201
    assert again.json()["id"] == first.json()["id"]
    assert again.headers["Idempotent-Replayed"] == "true"
    other_slot = book(client, Ids.SLOT_NET_D4_0900, headers={**STUDENT, **key})
    assert other_slot.status_code == 422 and other_slot.json()["code"] == "IDEMPOTENCY_KEY_REUSED"
    short = book(client, Ids.SLOT_NET_D4_0900, headers={**STUDENT, "Idempotency-Key": "x"})
    assert short.status_code == 422


def test_owner_sees_booking_others_get_403_without_data(client: TestClient) -> None:
    own = client.get(f"/api/v1/bookings/{Ids.BOOKING_ACTIVE}", headers=STUDENT)
    assert own.status_code == 200 and own.json()["resource"]["name"] == "Консультація з баз даних"
    foreign = client.get(f"/api/v1/bookings/{Ids.BOOKING_OTHER}", headers=STUDENT)
    assert foreign.status_code == 403 and foreign.json()["code"] == "NOT_OWNER"
    assert str(Ids.SLOT_DB_D1_1000) not in foreign.text  # THR-03: без даних об'єкта
    missing = client.get(f"/api/v1/bookings/{uuid.uuid4()}", headers=STUDENT)
    assert missing.status_code == 404


def test_cancel_frees_the_slot(client: TestClient) -> None:
    r = client.post(f"/api/v1/bookings/{Ids.BOOKING_ACTIVE}/cancel", headers=STUDENT)
    assert r.status_code == 200
    assert r.json()["state"] == "cancelled" and r.json()["cancellation_kind"] == "student"
    # FR-042: слот одразу вільний — інший студент може його забронювати.
    # Перевіряємо через бронювання, а не через пошук: тест не залежить від роутера слотів.
    assert store.confirmed_booking_for_slot(Ids.SLOT_DB_D2_1000) is None
    assert book(client, Ids.SLOT_DB_D2_1000, headers=STUDENT_2).status_code == 201


def test_cancel_exactly_at_deadline_is_allowed(client: TestClient, monkeypatch) -> None:
    deadline = store.bookings[Ids.BOOKING_ACTIVE].cancel_deadline_at
    monkeypatch.setattr(clock, "utc_now", lambda: deadline)
    assert (
        client.post(f"/api/v1/bookings/{Ids.BOOKING_ACTIVE}/cancel", headers=STUDENT).status_code
        == 200
    )


def test_cancel_after_deadline_names_the_deadline(client: TestClient) -> None:
    r = client.post(f"/api/v1/bookings/{Ids.BOOKING_SOON}/cancel", headers=STUDENT)
    assert r.status_code == 409 and r.json()["code"] == "CANCELLATION_DEADLINE_PASSED"
    expected = store.bookings[Ids.BOOKING_SOON].cancel_deadline_at
    assert at(r.json()["cancel_deadline_at"]) == expected
    assert store.bookings[Ids.BOOKING_SOON].status is BookingStatus.CONFIRMED


def test_cancel_twice_and_foreign_cancel(client: TestClient) -> None:
    url = f"/api/v1/bookings/{Ids.BOOKING_ACTIVE}/cancel"
    assert client.post(url, headers=STUDENT).status_code == 200
    again = client.post(url, headers=STUDENT)
    assert again.status_code == 409 and again.json()["code"] == "BOOKING_ALREADY_CANCELLED"
    foreign = client.post(f"/api/v1/bookings/{Ids.BOOKING_OTHER}/cancel", headers=STUDENT)
    assert foreign.status_code == 403
    assert store.bookings[Ids.BOOKING_OTHER].status is BookingStatus.CONFIRMED


def reschedule(client: TestClient, booking_id: uuid.UUID, new_slot: uuid.UUID):
    return client.post(
        f"/api/v1/bookings/{booking_id}/reschedule",
        headers=STUDENT,
        json={"new_slot_id": str(new_slot)},
    )


def test_reschedule_is_atomic_replacement(client: TestClient) -> None:
    r = reschedule(client, Ids.BOOKING_ACTIVE, Ids.SLOT_DB_D2_1030)
    assert r.status_code == 201
    old = store.bookings[Ids.BOOKING_ACTIVE]
    assert old.status is BookingStatus.CANCELLED
    assert str(old.rescheduled_to_id) == r.json()["id"]
    assert r.headers["Location"] == f"/api/v1/bookings/{r.json()['id']}"


def test_reschedule_to_taken_slot_keeps_old_booking(client: TestClient) -> None:
    r = reschedule(client, Ids.BOOKING_ACTIVE, Ids.SLOT_DB_D1_1000)
    assert r.status_code == 409 and r.json()["code"] == "SLOT_ALREADY_BOOKED"
    assert store.bookings[Ids.BOOKING_ACTIVE].status is BookingStatus.CONFIRMED


def test_reschedule_at_limit_is_allowed(client: TestClient) -> None:
    assert book(client, Ids.SLOT_DB_D1_1030).status_code == 201  # ліміт 3 із 3
    assert reschedule(client, Ids.BOOKING_ACTIVE, Ids.SLOT_NET_D4_0900).status_code == 201


def test_reschedule_after_deadline_or_to_same_slot(client: TestClient) -> None:
    late = reschedule(client, Ids.BOOKING_SOON, Ids.SLOT_NET_D4_0900)
    assert late.status_code == 409 and late.json()["code"] == "CANCELLATION_DEADLINE_PASSED"
    same = reschedule(client, Ids.BOOKING_ACTIVE, Ids.SLOT_DB_D2_1000)
    assert same.status_code == 422


def test_my_bookings_active_first(client: TestClient) -> None:
    r = client.get("/api/v1/me/bookings", headers=STUDENT)
    assert r.status_code == 200
    states = [i["state"] for i in r.json()["items"]]
    assert states == ["active", "active", "completed", "cancelled"]
    first_two = [i["slot"]["starts_at"] for i in r.json()["items"][:2]]
    assert first_two == sorted(first_two)  # найближчі першими


def test_my_bookings_filter_and_empty_result(client: TestClient) -> None:
    done = client.get("/api/v1/me/bookings", params={"state": "completed"}, headers=STUDENT).json()
    assert [i["id"] for i in done["items"]] == [str(Ids.BOOKING_PAST)]
    empty = client.get("/api/v1/me/bookings", params={"state": "in_progress"}, headers=STUDENT)
    assert empty.status_code == 200 and empty.json()["items"] == []
    other = client.get("/api/v1/me/bookings", headers=STUDENT_2).json()
    assert [i["id"] for i in other["items"]] == [str(Ids.BOOKING_OTHER)]  # лише власні
