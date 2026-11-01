"""SQL-проєкції зберігають контракт демо-адаптера, доменні відмови та атомарність."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, update

from api import clock
from api.enums import Role
from api.infrastructure import tables as t
from api.infrastructure.booking_commands import create_booking
from api.infrastructure.queries import session_identity
from api.main import app
from api.security import CurrentUser
from api.stubs.store import Ids, StubStore, store

pytestmark = pytest.mark.req(
    "FR-007",
    "FR-020",
    "FR-021",
    "FR-022",
    "FR-023",
    "FR-030",
    "FR-032",
    "FR-033",
    "FR-035",
    "REL-001",
    "QA-04",
)
STUDENT = {"Authorization": "Bearer demo-student"}
ADMIN = {"Authorization": "Bearer demo-admin"}


@pytest.mark.parametrize(
    "query",
    [
        {},
        {"resource_type": "room"},
        {"min_capacity": 20},
        {"provider_id": str(Ids.PROVIDER)},
        {"date": "2026-10-20"},
        {"limit": 1},
    ],
)
def test_sql_search_matches_memory_filters_and_cursor(database, client, query):
    memory = StubStore()
    memory.reset(clock.utc_now())
    previous = store.set_backend(memory)
    try:
        expected = client.get("/api/v1/slots", headers=STUDENT, params=query).json()
    finally:
        store.set_backend(previous)
    response = client.get("/api/v1/slots", headers=STUDENT, params=query)
    assert response.status_code == 200, response.text
    assert response.json() == expected
    if expected["pagination"]["has_more"]:
        cursor = expected["pagination"]["next_cursor"]
        second = client.get(
            "/api/v1/slots", headers=STUDENT, params={**query, "cursor": cursor}
        ).json()
        assert {r["id"] for r in second["items"]}.isdisjoint({r["id"] for r in expected["items"]})


def test_invalid_cursor_and_expired_search_date_remain_422(database, client):
    for params in [{"cursor": "broken"}, {"date": "2026-10-18"}]:
        assert client.get("/api/v1/slots", headers=STUDENT, params=params).status_code in (409, 422)


def test_sql_idempotency_replays_cancelled_booking_and_rejects_new_slot(database, client):
    headers = {**STUDENT, "Idempotency-Key": "sql-key-replay"}
    response = client.post(
        "/api/v1/bookings", headers=headers, json={"slot_id": str(Ids.SLOT_NET_D4_0900)}
    )
    assert response.status_code == 201, response.text
    bid = response.json()["id"]
    assert client.post(f"/api/v1/bookings/{bid}/cancel", headers=STUDENT).status_code == 200
    replay = client.post(
        "/api/v1/bookings", headers=headers, json={"slot_id": str(Ids.SLOT_NET_D4_0900)}
    )
    assert replay.json()["id"] == bid and replay.json()["state"] == "cancelled"
    conflict = client.post(
        "/api/v1/bookings", headers=headers, json={"slot_id": str(Ids.SLOT_317_D3_1600)}
    )
    assert conflict.status_code == 422 and conflict.json()["code"] == "IDEMPOTENCY_KEY_REUSED"


@pytest.mark.parametrize(
    ("slot", "code"),
    [
        (Ids.SLOT_DB_D1_1000, "SLOT_ALREADY_BOOKED"),
        (Ids.SLOT_DB_STARTED, "SLOT_STARTED"),
        (Ids.SLOT_DB_D20, "SLOT_OUT_OF_HORIZON"),
        (Ids.SLOT_317_D2_1500, "SLOT_BLOCKED"),
        (Ids.SLOT_225_D2_1000, "BOOKING_OVERLAP"),
    ],
)
def test_sql_booking_preserves_domain_rejections(database, client, slot, code):
    response = client.post("/api/v1/bookings", headers=STUDENT, json={"slot_id": str(slot)})
    assert response.status_code == 409 and response.json()["code"] == code


def test_sql_missing_and_withdrawn_slot_and_revoked_role(database, client):
    assert (
        client.post(
            "/api/v1/bookings", headers=STUDENT, json={"slot_id": str(uuid.uuid4())}
        ).status_code
        == 404
    )
    with database.owner.begin() as conn:
        conn.execute(
            update(t.slots).where(t.slots.c.id == Ids.SLOT_NET_D4_0900).values(is_active=False)
        )
    assert (
        client.post(
            "/api/v1/bookings", headers=STUDENT, json={"slot_id": str(Ids.SLOT_NET_D4_0900)}
        ).json()["code"]
        == "SLOT_WITHDRAWN"
    )
    actor = CurrentUser(Ids.STUDENT, "Student", "test@example.com", frozenset({Role.STUDENT}))
    with database.owner.begin() as conn:
        conn.execute(delete(t.roles).where(t.roles.c.user_id == Ids.STUDENT))
    from api.errors import ApiProblem

    with pytest.raises(ApiProblem):
        create_booking(database.backend.engine, actor, Ids.SLOT_NET_D4_0900, clock.utc_now())
    assert session_identity(database.backend.engine, "bad token", clock.utc_now()) is None


def test_parallel_student_limit_is_preserved(database, client):
    client.put(
        "/api/v1/admin/policies/current",
        headers=ADMIN,
        json={"booking_limit": 2, "cancel_window_minutes": 120},
    )
    barrier = Barrier(2)

    # Use TestClient without lifespan: context manager would switch the global backend.
    def request(slot):
        web = TestClient(app)
        barrier.wait(timeout=15)
        return web.post(
            "/api/v1/bookings",
            headers={"Authorization": "Bearer demo-student-2"},
            json={"slot_id": str(slot)},
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(request, [Ids.SLOT_NET_D4_0900, Ids.SLOT_317_D3_1600]))
    assert sorted(results) == [201, 409]
