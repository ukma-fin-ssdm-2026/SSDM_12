"""SQL-проєкції зберігають контракт демо-адаптера, доменні відмови та атомарність."""

import secrets
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, event, func, select, update

from api import clock
from api.enums import Role
from api.errors import ApiProblem, ErrorCode
from api.infrastructure import tables as t
from api.infrastructure.booking_commands import create_booking
from api.infrastructure.postgres import LOCK_KEY
from api.infrastructure.queries import session_identity
from api.main import app
from api.security import CurrentUser
from api.stubs.store import Ids, StubStore, store
from unislot.platform.errors import DomainError

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


def test_cached_search_shape_keeps_filter_values_and_current_rows_fresh(database, client):
    parameters = [
        {"provider_id": str(Ids.PROVIDER)},
        {"provider_id": str(Ids.PROVIDER_2)},
        {"resource_type": "room"},
        {"resource_type": "consultation"},
        {"min_capacity": 10},
        {"min_capacity": 30},
        {"date": "2026-10-20"},
        {"date": "2026-10-22"},
        {"limit": 1},
        {"limit": 3},
    ]
    memory = StubStore()
    memory.reset(clock.utc_now())
    previous = store.set_backend(memory)
    try:
        expected = [
            client.get("/api/v1/slots", headers=STUDENT, params=p).json() for p in parameters
        ]
    finally:
        store.set_backend(previous)
    for params, body in zip(parameters, expected, strict=True):
        assert client.get("/api/v1/slots", headers=STUDENT, params=params).json() == body
    first = client.get("/api/v1/slots", headers=STUDENT, params={"limit": 1}).json()["items"][0][
        "id"
    ]
    with database.owner.begin() as conn:
        conn.execute(
            update(t.slots).where(t.slots.c.id == uuid.UUID(first)).values(is_active=False)
        )
    fresh = client.get("/api/v1/slots", headers=STUDENT, params={"limit": 1}).json()
    assert fresh["items"][0]["id"] != first


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
    missing = client.post("/api/v1/bookings", headers=headers, json={"slot_id": str(uuid.uuid4())})
    assert missing.status_code == 422 and missing.json()["code"] == "IDEMPOTENCY_KEY_REUSED"


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
        conn.execute(update(t.users).where(t.users.c.id == Ids.STUDENT).values(is_active=True))
        conn.execute(delete(t.roles).where(t.roles.c.user_id == Ids.STUDENT))

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


@pytest.mark.parametrize("key", [None, "disabled-after-auth"])
def test_disabled_cookie_actor_cannot_book_with_previously_resolved_identity(database, key):
    """A cached request identity must not bypass current account state in the write."""
    actor = CurrentUser(Ids.STUDENT, "Student", "test@example.com", frozenset({Role.STUDENT}))
    # The seeded demo principal is inactive: a real cookie identity must be rejected.
    with pytest.raises(ApiProblem) as refused:
        create_booking(
            database.backend.engine, actor, Ids.SLOT_NET_D4_0900, clock.utc_now(), key=key
        )
    assert refused.value.code == ErrorCode.FORBIDDEN_ROLE
    with database.owner.connect() as conn:
        assert (
            conn.scalar(
                select(func.count())
                .select_from(t.bookings)
                .where(t.bookings.c.slot_id == Ids.SLOT_NET_D4_0900)
            )
            == 0
        )


def test_dual_role_students_can_book_each_others_resources_concurrently(database):
    """Actor locks must serialize own limits without deadlocking provider FK checks."""
    actors = [Ids.STUDENT, Ids.STUDENT_2]
    slots = [Ids.SLOT_NET_D4_0900, Ids.SLOT_317_D3_1600]
    with database.owner.begin() as conn:
        conn.execute(update(t.users).where(t.users.c.id.in_(actors)).values(is_active=True))
        conn.execute(t.roles.insert(), [{"user_id": uid, "role": "provider"} for uid in actors])
        for resource, owner in [(Ids.RES_NET_CONSULT, actors[1]), (Ids.RES_ROOM_3_317, actors[0])]:
            conn.execute(
                update(t.resources).where(t.resources.c.id == resource).values(provider_id=owner)
            )
    barrier = Barrier(2)

    def wait_before_booking(conn, cursor, statement, parameters, context, executemany):
        if (
            context.compiled is not None
            and context.compiled.isinsert
            and context.compiled.statement.table is t.notifications
        ):
            barrier.wait(timeout=10)

    event.listen(database.backend.engine, "before_cursor_execute", wait_before_booking)

    def attempt(pair):
        uid, sid = pair
        actor = CurrentUser(
            uid, "Student provider", "test@example.com", frozenset({Role.STUDENT, Role.PROVIDER})
        )
        booking, replay = create_booking(database.backend.engine, actor, sid, clock.utc_now())
        assert replay is False
        return booking.slot.id

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            booked = list(pool.map(attempt, zip(actors, slots, strict=True)))
    finally:
        event.remove(database.backend.engine, "before_cursor_execute", wait_before_booking)
    assert set(booked) == set(slots)


@pytest.mark.parametrize("key", [None, "near-future-slot"])
def test_near_future_booking_has_confirmation_and_provider_notice_without_reminder(
    database, client, key
):
    sid = uuid.uuid4()
    with database.owner.begin() as conn:
        conn.execute(
            t.slots.insert().values(
                id=sid,
                resource_id=Ids.RES_NET_CONSULT,
                starts_at=clock.utc_now() + timedelta(hours=3),
                ends_at=clock.utc_now() + timedelta(hours=4),
                is_active=True,
            )
        )
    headers = {**STUDENT, **({"Idempotency-Key": key} if key else {})}
    response = client.post("/api/v1/bookings", headers=headers, json={"slot_id": str(sid)})
    assert response.status_code == 201, response.text
    with database.owner.connect() as conn:
        kinds = conn.scalars(
            select(t.notifications.c.kind).where(
                t.notifications.c.booking_id == uuid.UUID(response.json()["id"])
            )
        ).all()
    assert sorted(kinds) == ["confirmation", "provider_created"]


@pytest.mark.parametrize("different_payload", [False, True])
def test_parallel_idempotency_reads_the_committed_winner_after_actor_lock(
    database, different_payload
):
    with database.owner.begin() as conn:
        conn.execute(update(t.users).where(t.users.c.id == Ids.STUDENT).values(is_active=True))
    actor = CurrentUser(Ids.STUDENT, "Student", "test@example.com", frozenset({Role.STUDENT}))
    slots = [
        Ids.SLOT_NET_D4_0900,
        Ids.SLOT_317_D3_1600 if different_payload else Ids.SLOT_NET_D4_0900,
    ]
    barrier = Barrier(2)

    def attempt(sid):
        barrier.wait(timeout=10)
        try:
            result, replay = create_booking(
                database.backend.engine, actor, sid, clock.utc_now(), key="parallel-key"
            )
            return result.id, replay
        except ApiProblem as refused:
            return refused.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, slots))
    successes = [r for r in results if isinstance(r, tuple)]
    if different_payload:
        assert len(successes) == 1 and successes[0][1] is False
        assert ErrorCode.IDEMPOTENCY_KEY_REUSED in results
    else:
        assert successes[0][0] == successes[1][0]
        assert sorted(r[1] for r in successes) == [False, True]
    with database.owner.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(t.idempotency)) == 1
        assert conn.scalar(select(func.count()).select_from(t.notifications)) == 3


def test_single_read_does_not_make_later_writes_autocommit(database):
    assert (
        session_identity(database.backend.engine, secrets.token_urlsafe(32), clock.utc_now())
        is None
    )
    with database.owner.connect() as conn:
        original = conn.scalar(
            select(t.resources.c.name).where(t.resources.c.id == Ids.RES_NET_CONSULT)
        )

    def change_then_fail():
        with database.backend.engine.begin() as conn:
            conn.execute(
                update(t.resources)
                .where(t.resources.c.id == Ids.RES_NET_CONSULT)
                .values(name="must roll back")
            )
            raise RuntimeError("intentional rollback")

    with pytest.raises(RuntimeError, match="intentional rollback"):
        change_then_fail()
    with database.owner.connect() as conn:
        assert (
            conn.scalar(select(t.resources.c.name).where(t.resources.c.id == Ids.RES_NET_CONSULT))
            == original
        )


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ("role", ErrorCode.FORBIDDEN_ROLE),
        ("policy", ErrorCode.BOOKING_LIMIT_REACHED),
        ("block", ErrorCode.SLOT_BLOCKED),
    ],
)
def test_waiting_for_admin_gate_reads_changes_committed_before_gate_release(
    database, change, expected
):
    """Taking a lock inside a CTE must not preserve a pre-admin statement snapshot."""
    with database.owner.begin() as conn:
        conn.execute(update(t.users).where(t.users.c.id == Ids.STUDENT).values(is_active=True))
        slot = (
            conn.execute(select(t.slots).where(t.slots.c.id == Ids.SLOT_NET_D4_0900))
            .mappings()
            .one()
        )
    actor = CurrentUser(Ids.STUDENT, "Student", "test@example.com", frozenset({Role.STUDENT}))

    def attempt():
        try:
            create_booking(database.backend.engine, actor, slot["id"], clock.utc_now())
            return "created"
        except (ApiProblem, DomainError) as refused:
            return ErrorCode(refused.code)

    with ThreadPoolExecutor(max_workers=1) as pool:
        with database.owner.begin() as admin:
            admin.exec_driver_sql("SELECT pg_advisory_xact_lock(%s)", (LOCK_KEY,))
            if change == "role":
                admin.execute(delete(t.roles).where(t.roles.c.user_id == actor.id))
            elif change == "policy":
                policy = uuid.uuid4()
                admin.execute(
                    t.policies.insert().values(
                        id=policy, booking_limit=2, cancel_window_minutes=120
                    )
                )
                admin.execute(update(t.current_policy).values(policy_id=policy))
            else:
                admin.execute(
                    t.blocks.insert().values(
                        id=uuid.uuid4(),
                        resource_id=slot["resource_id"],
                        starts_at=slot["starts_at"],
                        ends_at=slot["ends_at"],
                        reason="scheduled block",
                    )
                )
            future = pool.submit(attempt)
            deadline = time.monotonic() + 3
            while not admin.exec_driver_sql(
                "SELECT EXISTS(SELECT 1 FROM pg_locks WHERE locktype='advisory' AND objid=%s::oid AND NOT granted)",
                (LOCK_KEY,),
            ).scalar_one():
                assert time.monotonic() < deadline, "booking did not wait for the admin gate"
                time.sleep(0.01)
        assert future.result(timeout=10) == expected
