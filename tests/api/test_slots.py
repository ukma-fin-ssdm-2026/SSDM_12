"""Слоти: пошук (US-004; TC-010…TC-012) і публікація (US-007; TC-025…TC-028) на заглушках."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from api import clock
from api.enums import BookingStatus
from api.policy import KYIV
from api.stubs.store import BookingRec, Ids, store

STUDENT = {"Authorization": "Bearer demo-student"}
PROVIDER = {"Authorization": "Bearer demo-provider"}  # провайдер консультації з БД і ауд. 3-317
SEARCH = "/api/v1/slots"
TAKEN_OR_UNAVAILABLE = {
    Ids.SLOT_DB_D1_1000,
    Ids.SLOT_DB_D2_1000,
    Ids.SLOT_NET_SOON,
    Ids.SLOT_317_D2_1500,
    Ids.SLOT_DB_STARTED,
    Ids.SLOT_DB_D20,
    Ids.SLOT_DB_PAST,
}


def ids(response) -> list[str]:
    return [item["id"] for item in response.json()["items"]]


@pytest.mark.req("FR-020", "FR-023", "TC-010", "TP-05")
def test_search_returns_only_free_slots_in_time_order(client: TestClient) -> None:
    r = client.get(SEARCH, headers=STUDENT)
    assert r.status_code == 200
    found = ids(r)
    assert len(found) == 9
    assert not {str(i) for i in TAKEN_OR_UNAVAILABLE} & set(found)
    starts = [item["starts_at"] for item in r.json()["items"]]
    assert starts == sorted(starts)


@pytest.mark.req("FR-021", "TC-011", "TP-05")
def test_filters_combine(client: TestClient) -> None:
    tomorrow = (clock.utc_now().astimezone(KYIV) + timedelta(days=1)).date().isoformat()
    r = client.get(
        SEARCH, params={"provider_id": str(Ids.PROVIDER), "date": tomorrow}, headers=STUDENT
    )
    assert set(ids(r)) == {
        str(Ids.SLOT_DB_D1_1030),
        str(Ids.SLOT_DB_D1_1100),
        str(Ids.SLOT_317_D1_1600),
    }
    rooms = client.get(SEARCH, params={"resource_type": "room"}, headers=STUDENT).json()["items"]
    assert rooms and {i["resource"]["type"] for i in rooms} == {"room"}


@pytest.mark.req("FR-022", "TC-012")
def test_min_capacity_applies_to_rooms_only(client: TestClient) -> None:
    r = client.get(SEARCH, params={"min_capacity": 20}, headers=STUDENT)
    items = r.json()["items"]
    assert items and all(
        i["resource"]["type"] == "room" and i["resource"]["capacity"] >= 20 for i in items
    )


@pytest.mark.req("FR-020", "QA-06")
def test_date_outside_horizon_is_rejected(client: TestClient) -> None:
    today = clock.utc_now().astimezone(KYIV).date()
    for day in (today - timedelta(days=1), today + timedelta(days=16)):
        r = client.get(SEARCH, params={"date": day.isoformat()}, headers=STUDENT)
        assert r.status_code == 422 and r.json()["code"] == "DATE_OUT_OF_HORIZON"


@pytest.mark.req("FR-020", "QA-11")
def test_cursor_pagination_walks_all_pages_without_duplicates(client: TestClient) -> None:
    seen, cursor = [], None
    while True:
        params = {"limit": 4, **({"cursor": cursor} if cursor else {})}
        page = client.get(SEARCH, params=params, headers=STUDENT).json()
        seen += [i["id"] for i in page["items"]]
        cursor = page["pagination"]["next_cursor"]
        if not page["pagination"]["has_more"]:
            assert cursor is None
            break
    assert len(seen) == len(set(seen)) == 9


@pytest.mark.req("QA-06")
def test_broken_cursor_is_422(client: TestClient) -> None:
    r = client.get(SEARCH, params={"cursor": "not-a-cursor"}, headers=STUDENT)
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "query.cursor"


@pytest.mark.req("FR-007", "SEC-002")
def test_search_is_for_students(client: TestClient) -> None:
    r = client.get(SEARCH, headers=PROVIDER)
    assert r.status_code == 403 and r.json()["code"] == "FORBIDDEN_ROLE"


@pytest.mark.req("FR-023", "TC-010")
def test_booked_slot_disappears_from_search(client: TestClient) -> None:
    """US-004, четвертий критерій: щойно заброньований слот зникає з результатів."""
    free = str(Ids.SLOT_DB_D1_1030)
    assert free in ids(client.get(SEARCH, headers=STUDENT))
    booking_id = uuid.uuid4()  # бронювання іншого студента — напряму в сховищі,
    store.bookings[booking_id] = BookingRec(  # щоб тест не залежав від роутера бронювань
        id=booking_id,
        slot_id=Ids.SLOT_DB_D1_1030,
        student_id=Ids.STUDENT_2,
        status=BookingStatus.CONFIRMED,
        policy_id=Ids.POLICY_V1,
        cancel_deadline_at=clock.utc_now(),
        created_at=clock.utc_now(),
    )
    assert free not in ids(client.get(SEARCH, headers=STUDENT))


@pytest.mark.req("SEC-004")
def test_get_slot_shows_availability_but_not_who_booked(client: TestClient) -> None:
    taken = client.get(f"/api/v1/slots/{Ids.SLOT_DB_D1_1000}", headers=STUDENT).json()
    assert taken["available"] is False and "student" not in str(taken).lower()
    free = client.get(f"/api/v1/slots/{Ids.SLOT_DB_D1_1030}", headers=STUDENT).json()
    assert free["available"] is True
    assert client.get(f"/api/v1/slots/{Ids.STUDENT}", headers=STUDENT).status_code == 404


def new_slot(client: TestClient, resource=Ids.RES_DB_CONSULT, headers=PROVIDER, **body):
    payload = {"starts_at": "2027-02-15T10:00:00+02:00", "duration_minutes": 30, **body}
    return client.post(f"/api/v1/resources/{resource}/slots", headers=headers, json=payload)


@pytest.mark.req("FR-010", "TC-025")
def test_provider_publishes_slot_on_own_resource(client: TestClient) -> None:
    r = new_slot(client)
    assert r.status_code == 201
    assert r.headers["Location"] == f"/api/v1/slots/{r.json()['id']}"
    assert r.json()["starts_at"] == "2027-02-15T08:00:00Z"  # збережено в UTC (A-007)


@pytest.mark.req("FR-011", "TC-026", "TP-06")
def test_overlap_rejected_adjacent_allowed(client: TestClient) -> None:
    assert new_slot(client).status_code == 201
    overlap = new_slot(client, starts_at="2027-02-15T10:15:00+02:00")
    assert overlap.status_code == 409 and overlap.json()["code"] == "SLOT_OVERLAP"
    assert new_slot(client, starts_at="2027-02-15T10:30:00+02:00").status_code == 201


@pytest.mark.req("FR-010", "QA-06", "TC-027")
def test_duration_and_time_validation(client: TestClient) -> None:
    for minutes in (10, 17, 125):
        r = new_slot(client, duration_minutes=minutes)
        assert r.status_code == 422 and r.json()["errors"][0]["field"] == "body.duration_minutes"
    naive = new_slot(client, starts_at="2027-02-15T10:00:00")
    assert naive.status_code == 422 and naive.json()["errors"][0]["type"] == "timezone_aware"
    past = new_slot(client, starts_at="2026-10-01T10:00:00+03:00")
    assert past.status_code == 422 and past.json()["code"] == "SLOT_IN_PAST"


@pytest.mark.req("FR-007", "SEC-002", "TC-028")
def test_only_owner_provider_creates_slots(client: TestClient) -> None:
    foreign = new_slot(client, resource=Ids.RES_NET_CONSULT)
    assert foreign.status_code == 403 and foreign.json()["code"] == "NOT_OWNER"
    student = new_slot(client, headers=STUDENT)
    assert student.status_code == 403 and student.json()["code"] == "FORBIDDEN_ROLE"
    missing = new_slot(client, resource=Ids.STUDENT)
    assert missing.status_code == 404 and missing.json()["code"] == "RESOURCE_NOT_FOUND"
