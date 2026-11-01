"""ADR-002: повтор лише повної транзакції й точне відображення SQL-конфліктів."""

import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, update

from api.enums import Role
from api.errors import ApiProblem, ErrorCode
from api.infrastructure import tables as t
from api.infrastructure.postgres import LOCK_KEY
from api.infrastructure.unit_of_work import transactional
from api.main import app
from api.security import CurrentUser, get_current_user
from api.stubs.store import Ids, store

pytestmark = pytest.mark.req("FR-030", "FR-032", "FR-033", "REL-001", "REL-002", "QA-04")
STUDENT = {"Authorization": "Bearer demo-student", "Idempotency-Key": "deadlock-retry-key"}


@pytest.mark.parametrize("always", [False, True])
def test_booking_retries_deadlock_once_after_complete_rollback(database, client, always):
    # A sequence survives rollback and counts attempts; SQLSTATE is injected, not
    # claimed to be an actual two-transaction deadlock in this focused test.
    condition = "true" if always else "attempt = 1"
    with database.owner.begin() as conn:
        conn.exec_driver_sql("CREATE SEQUENCE deadlock_attempt")
        role = conn.dialect.identifier_preparer.quote(database.role)
        conn.exec_driver_sql(f"GRANT USAGE ON SEQUENCE deadlock_attempt TO {role}")
        conn.exec_driver_sql(
            """CREATE FUNCTION simulate_deadlock() RETURNS trigger LANGUAGE plpgsql AS $$
                DECLARE attempt bigint;
                BEGIN
                    attempt := nextval('deadlock_attempt');
                    IF """
            + condition
            + """ THEN
                        RAISE EXCEPTION 'injected transaction conflict' USING ERRCODE = '40P01';
                    END IF;
                    RETURN NEW;
                END $$;
                CREATE TRIGGER simulated_deadlock BEFORE INSERT ON booking
                FOR EACH ROW EXECUTE FUNCTION simulate_deadlock();"""
        )
    response = client.post(
        "/api/v1/bookings", headers=STUDENT, json={"slot_id": str(Ids.SLOT_NET_D4_0900)}
    )
    assert response.status_code == (503 if always else 201), response.text
    assert "injected transaction conflict" not in response.text
    if always:
        assert response.json()["code"] == "TRANSIENT_CONFLICT"
        assert response.headers["Retry-After"] == "1"
    with database.owner.connect() as conn:
        assert conn.exec_driver_sql("SELECT last_value FROM deadlock_attempt").scalar_one() == 2
        count = conn.scalar(
            select(func.count())
            .select_from(t.bookings)
            .where(t.bookings.c.slot_id == Ids.SLOT_NET_D4_0900)
        )
        assert count == (0 if always else 1)
        assert conn.scalar(select(func.count()).select_from(t.notifications)) == (
            0 if always else 3
        )
        assert conn.scalar(select(func.count()).select_from(t.idempotency)) == (0 if always else 1)


@pytest.mark.parametrize("kind", ["booking", "slot"])
def test_actual_named_database_constraint_maps_to_domain_conflict(database, kind):
    if kind == "booking":
        record = asdict(store.bookings[Ids.BOOKING_ACTIVE])
        table, expected = t.bookings, ErrorCode.SLOT_ALREADY_BOOKED
    else:
        record = asdict(store.slots[Ids.SLOT_NET_D4_0900])
        table, expected = t.slots, ErrorCode.SLOT_OVERLAP
    record["id"] = uuid.uuid4()

    @transactional(direct=True)
    def insert_duplicate():
        with database.backend.engine.begin() as conn:
            conn.execute(table.insert().values(**record))

    with pytest.raises(ApiProblem) as refused:
        insert_duplicate()
    assert refused.value.code == expected


@pytest.mark.req("FR-007", "SEC-002")
def test_legacy_admin_write_rechecks_role_after_waiting_for_gate(database):
    with database.owner.begin() as conn:
        conn.execute(update(t.users).where(t.users.c.id == Ids.ADMIN).values(is_active=True))
    # Model an identity already resolved before a second administrator revoked it.
    identity = CurrentUser(Ids.ADMIN, "Administrator", "test@example.com", frozenset({Role.ADMIN}))
    app.dependency_overrides[get_current_user] = lambda: identity

    def request():
        return TestClient(app).put(
            "/api/v1/admin/policies/current",
            json={"booking_limit": 4, "cancel_window_minutes": 120},
        )

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            with database.owner.begin() as admin:
                admin.exec_driver_sql("SELECT pg_advisory_xact_lock(%s)", (LOCK_KEY,))
                admin.execute(delete(t.roles).where(t.roles.c.user_id == Ids.ADMIN))
                future = pool.submit(request)
                deadline = time.monotonic() + 3
                while not admin.exec_driver_sql(
                    "SELECT EXISTS(SELECT 1 FROM pg_locks WHERE locktype='advisory' AND objid=%s::oid AND NOT granted)",
                    (LOCK_KEY,),
                ).scalar_one():
                    assert time.monotonic() < deadline, "admin request did not wait for the gate"
                    time.sleep(0.01)
            response = future.result(timeout=10)
        assert response.status_code == 403, response.text
        with database.owner.connect() as conn:
            assert conn.scalar(select(func.count()).select_from(t.audit)) == 0
    finally:
        app.dependency_overrides.pop(get_current_user, None)
