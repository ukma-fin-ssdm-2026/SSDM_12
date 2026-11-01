"""Перезапуск, цілісність БД, конкурентні транзакції та append-only аудит."""

from __future__ import annotations

import copy
import os
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, insert, select
from sqlalchemy.exc import DBAPIError

from api.enums import Role
from api.infrastructure import tables as t
from api.infrastructure.postgres import PostgresStore
from api.main import app
from api.stubs.store import Ids, store
from scripts.manage_db import seed_demo

pytestmark = pytest.mark.req("FR-030", "FR-033", "FR-067", "REL-002", "QA-06")
STUDENT = {"Authorization": "Bearer demo-student"}
ADMIN = {"Authorization": "Bearer demo-admin"}
PROVIDER = {"Authorization": "Bearer demo-provider"}


def book(client, slot=Ids.SLOT_NET_D4_0900, key=None):
    headers = {**STUDENT, **({"Idempotency-Key": key} if key else {})}
    return client.post("/api/v1/bookings", headers=headers, json={"slot_id": str(slot)})


def test_booking_and_outbox_survive_adapter_restart(database, client):
    response = book(client, key="durable-key")
    assert response.status_code == 201, response.text
    bid = uuid.UUID(response.json()["id"])
    old = store.set_backend(PostgresStore(database.app_url))
    try:
        replay = book(client, key="durable-key")
        assert replay.json()["id"] == str(bid)
        with store.lock:
            assert len(store.notifications) == 3
            assert bid in store.reminders
            assert store.bookings[bid].student_id == Ids.STUDENT
    finally:
        store.set_backend(old).close()
    assert seed_demo(database.app_url) is False
    with pytest.raises(RuntimeError, match="cannot be reset"):
        database.backend.reset()


def test_policy_roles_templates_blocks_and_audit_round_trip(database, client):
    assert (
        client.put(f"/api/v1/admin/users/{Ids.STUDENT}/roles/provider", headers=ADMIN).status_code
        == 200
    )
    policy = client.put(
        "/api/v1/admin/policies/current",
        headers=ADMIN,
        json={"booking_limit": 4, "cancel_window_minutes": 180},
    )
    assert policy.status_code == 200, policy.text
    path = f"/api/v1/resources/{Ids.RES_DB_CONSULT}/templates/{uuid.uuid4()}"
    response = client.put(
        path,
        headers=PROVIDER,
        json={
            "weekday": 3,
            "start_local": "14:00",
            "end_local": "16:00",
            "slot_minutes": 30,
            "valid_from": "2026-10-19",
        },
    )
    assert response.status_code == 201, response.text
    blockpath = f"/api/v1/resources/{Ids.RES_DB_CONSULT}/blocks"
    response = client.post(
        blockpath,
        headers=PROVIDER,
        json={
            "starts_at": "2026-10-22T10:00:00+03:00",
            "ends_at": "2026-10-22T11:00:00+03:00",
            "reason": "Засідання",
        },
    )
    assert response.status_code == 201, response.text
    blockid = response.json()["id"]
    with store.lock:
        assert Role.PROVIDER in store.users[Ids.STUDENT].roles
        assert store.policy.booking_limit == 4
        assert len(store.templates) == 1
        assert all(isinstance(a["id"], uuid.UUID) for a in store.audit)
    assert client.delete(blockpath + "/" + blockid, headers=PROVIDER).status_code == 204
    assert (
        client.delete(
            f"/api/v1/admin/users/{Ids.STUDENT}/roles/provider", headers=ADMIN
        ).status_code
        == 200
    )
    with store.lock:
        assert uuid.UUID(blockid) not in store.blocks
        assert Role.PROVIDER not in store.users[Ids.STUDENT].roles


def test_outbox_insert_failure_rolls_back_booking_idempotency_and_audit(database, client):
    with database.owner.begin() as conn:
        conn.exec_driver_sql("""CREATE FUNCTION fail_notice() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'test outbox failure'; END $$;
            CREATE TRIGGER fail_notice BEFORE INSERT ON notification
            FOR EACH ROW EXECUTE FUNCTION fail_notice();""")
    before = len(store.bookings)
    response = book(client, key="must-rollback")
    assert response.status_code == 503, response.text
    assert "test outbox failure" not in response.text
    assert response.headers["Retry-After"] == "1"
    with store.lock:
        assert len(store.bookings) == before
        assert not store.notifications
        assert (Ids.STUDENT, "must-rollback") not in store.idempotency
    with database.owner.begin() as conn:
        conn.exec_driver_sql("DROP TRIGGER fail_notice ON notification")
    assert book(client, key="must-rollback").status_code == 201


def test_nested_error_marks_entire_transaction_for_rollback(database):
    def operation():
        with store.lock:
            store.resources[Ids.RES_DB_CONSULT].name = "must not persist"
            try:
                with store.lock:
                    raise ValueError("inner")
            except ValueError:
                pass

    with pytest.raises(RuntimeError, match="rollback-only"):
        operation()
    with store.lock:
        assert store.resources[Ids.RES_DB_CONSULT].name != "must not persist"


def test_erasing_outbox_or_rewriting_audit_is_rejected(database, client):
    assert book(client).status_code == 201
    with pytest.raises(ValueError, match="cannot be erased"), store.lock:
        store.notifications.clear()
    response = client.patch(
        f"/api/v1/admin/resources/{Ids.RES_DB_CONSULT}", headers=ADMIN, json={"name": "Нова назва"}
    )
    assert response.status_code == 200
    with pytest.raises(ValueError, match="cannot be rewritten"), store.lock:
        store.audit[0]["action"] = "rewritten"


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE audit_log SET action='tampered'",
        "DELETE FROM audit_log",
        "TRUNCATE audit_log",
        "ALTER TABLE audit_log DISABLE TRIGGER ALL",
    ],
)
def test_runtime_cannot_change_audit(database, client, statement):
    assert (
        client.patch(
            f"/api/v1/admin/resources/{Ids.RES_DB_CONSULT}",
            headers=ADMIN,
            json={"name": "Audit record"},
        ).status_code
        == 200
    )
    with pytest.raises(DBAPIError), database.backend.engine.begin() as conn:
        conn.exec_driver_sql(statement)
    with store.lock:
        assert len(store.audit) == 1


@pytest.mark.parametrize(
    "statement",
    ["UPDATE audit_log SET action='tampered'", "DELETE FROM audit_log", "TRUNCATE audit_log"],
)
def test_owner_triggers_also_reject_audit_mutation(database, client, statement):
    assert (
        client.patch(
            f"/api/v1/admin/resources/{Ids.RES_DB_CONSULT}",
            headers=ADMIN,
            json={"name": "Audit record"},
        ).status_code
        == 200
    )
    with pytest.raises(DBAPIError, match="append-only"), database.owner.begin() as conn:
        conn.exec_driver_sql(statement)


def test_api_refuses_owner_credentials(database):
    with pytest.raises(ValueError, match="restricted runtime role"):
        PostgresStore(database.owner_url)


def test_separate_api_and_worker_processes_share_durable_state(database, client):
    response = book(client)
    assert response.status_code == 201
    environment = {
        **os.environ,
        "UNISLOT_DATABASE_URL": database.app_url,
        "UNISLOT_DEMO_AUTH": "1",
        "UNISLOT_EXPORT_OPENAPI": "0",
        "PYTHONPATH": "src",
    }
    code = """
from fastapi.testclient import TestClient
from api.main import app
with TestClient(app) as client:
    result=client.get('/api/v1/me/bookings', headers={'Authorization':'Bearer demo-student'})
    assert result.status_code == 200
    assert any(b['id'] == __import__('os').environ['TEST_BOOKING_ID'] for b in result.json()['items'])
print('persistent-api-ok')
"""
    environment["TEST_BOOKING_ID"] = response.json()["id"]
    result = subprocess.run(  # noqa: S603 -- fixed Python interpreter and literal script
        [sys.executable, "-c", code],
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, "separate API process failed"
    assert "persistent-api-ok" in result.stdout
    result = subprocess.run(
        [sys.executable, "scripts/run_worker.py", "--once"],
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, "separate Worker process failed"
    with store.lock:
        assert len(store.deliveries) >= 2


def test_audit_failure_rolls_back_admin_change(database, client):
    with database.owner.begin() as conn:
        conn.exec_driver_sql("""CREATE FUNCTION fail_audit() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'test audit failure'; END $$;
            CREATE TRIGGER fail_audit BEFORE INSERT ON audit_log
            FOR EACH ROW EXECUTE FUNCTION fail_audit();""")
    original = store.resources[Ids.RES_DB_CONSULT].name
    response = client.patch(
        f"/api/v1/admin/resources/{Ids.RES_DB_CONSULT}",
        headers=ADMIN,
        json={"name": "must roll back"},
    )
    assert response.status_code == 503, response.text
    with store.lock:
        assert not store.audit
        assert store.resources[Ids.RES_DB_CONSULT].name == original


def test_database_connect_failure_is_a_sanitized_api_response_and_lock_recovers(
    database, client, monkeypatch
):
    connect = database.backend.engine.connect

    def unavailable():
        raise DBAPIError(None, None, RuntimeError("test connection failure"))

    monkeypatch.setattr(database.backend.engine, "connect", unavailable)
    response = client.get("/api/v1/auth/me", headers=STUDENT)
    assert response.status_code == 503, response.text
    assert "test connection failure" not in response.text
    monkeypatch.setattr(database.backend.engine, "connect", connect)
    assert client.get("/api/v1/auth/me", headers=STUDENT).status_code == 200


def test_slot_exclusion_and_inactive_history(database):
    original = store.slots[Ids.SLOT_NET_D4_0900]
    duplicate = {
        "id": uuid.uuid4(),
        "resource_id": original.resource_id,
        "starts_at": original.starts_at,
        "ends_at": original.ends_at,
        "is_active": True,
    }
    with pytest.raises(DBAPIError), database.backend.engine.begin() as conn:
        conn.execute(insert(t.slots).values(**duplicate))
    with database.backend.engine.begin() as conn:
        conn.execute(insert(t.slots).values(**{**duplicate, "is_active": False}))
    with store.lock:
        assert store.slots[duplicate["id"]].is_active is False


def test_database_constraints_reject_duplicate_confirmed_booking(database):
    record = copy.deepcopy(store.bookings[Ids.BOOKING_ACTIVE])
    from dataclasses import asdict

    with pytest.raises(DBAPIError), database.backend.engine.begin() as conn:
        conn.execute(insert(t.bookings).values(**{**asdict(record), "id": uuid.uuid4()}))


def test_parallel_independent_connections_have_one_booking_winner(database):
    # Same API process with independent DB connections/backends, as separate replicas do.
    def attempt(_):
        backend = PostgresStore(database.app_url)
        try:
            with backend.lock:
                if any(
                    b.slot_id == Ids.SLOT_NET_D4_0900 and b.status == "confirmed"
                    for b in backend.bookings.values()
                ):
                    return "conflict"
                record = copy.deepcopy(backend.bookings[Ids.BOOKING_ACTIVE])
                record.id, record.slot_id = uuid.uuid4(), Ids.SLOT_NET_D4_0900
                backend.bookings[record.id] = record
                return "created"
        finally:
            backend.close()

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(attempt, range(12)))
    assert results.count("created") == 1
    assert results.count("conflict") == 11
    with database.owner.connect() as conn:
        assert (
            conn.scalar(
                select(func.count())
                .select_from(t.bookings)
                .where(
                    t.bookings.c.slot_id == Ids.SLOT_NET_D4_0900, t.bookings.c.status == "confirmed"
                )
            )
            == 1
        )


def test_lifespan_selects_postgres_and_restores_previous_backend(database, monkeypatch):
    monkeypatch.setenv("UNISLOT_DATABASE_URL", database.app_url)
    from api.config import get_settings

    get_settings.cache_clear()
    try:
        with TestClient(app) as connection:
            assert connection.get("/api/v1/me/bookings", headers=STUDENT).status_code == 200
            assert store.persistent
        assert store._backend is database.backend
    finally:
        get_settings.cache_clear()
