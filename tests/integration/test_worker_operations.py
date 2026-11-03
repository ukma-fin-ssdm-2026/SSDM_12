"""Фоновий горизонт та безпечне відновлення failed на справжній PostgreSQL."""

import json
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import insert, select, update

from api import clock
from api.infrastructure import tables as t
from api.infrastructure.notification_ops import RetryRejected, failed_messages, retry_failed
from api.infrastructure.outbox import PostgresOutbox, dispatch_due
from api.services.worker_service import ensure_horizon, refresh_horizon
from api.stubs.store import Ids, store
from unislot.notifications.domain.model import RetryPolicy

pytestmark = pytest.mark.req("FR-012", "FR-050", "FR-051", "FR-053", "FR-066", "REL-002")


def prepare_failed(database, client, monkeypatch):
    result = client.post(
        "/api/v1/bookings",
        headers={"Authorization": "Bearer demo-student"},
        json={"slot_id": str(Ids.SLOT_NET_D4_0900)},
    )
    assert result.status_code == 201, result.text
    monkeypatch.setenv("UNISLOT_NOTIFICATION_FAILURE", "1")
    repository = PostgresOutbox(database.backend.engine)
    assert dispatch_due(repository, clock.utc_now(), policy=RetryPolicy(max_attempts=1)).failed == 2
    monkeypatch.delenv("UNISLOT_NOTIFICATION_FAILURE")
    with database.owner.begin() as conn:
        conn.execute(update(t.users).where(t.users.c.id == Ids.ADMIN).values(is_active=True))
    return repository


def test_operator_lists_minimal_fields_and_retries_one_failed_message(
    database, client, monkeypatch
):
    repo = prepare_failed(database, client, monkeypatch)
    rows = failed_messages(database.backend.engine, limit=1)
    assert len(rows) == 1 and set(rows[0]) == {
        "id",
        "kind",
        "attempts",
        "last_error",
        "scheduled_for",
    }
    nid = rows[0]["id"]
    assert (
        retry_failed(database.backend.engine, nid, Ids.ADMIN, "Gateway restored", clock.utc_now())
        == "pending"
    )
    with pytest.raises(RetryRejected, match="not_failed"):
        retry_failed(database.backend.engine, nid, Ids.ADMIN, "Duplicate click", clock.utc_now())
    assert dispatch_due(repo, clock.utc_now()).sent == 1
    with store.lock:
        assert store.notifications[nid].status == "sent"
        assert store.audit[-1]["action"] == "notification.retry"


def test_retry_requires_active_admin_and_a_reason(database, client, monkeypatch):
    prepare_failed(database, client, monkeypatch)
    nid = failed_messages(database.backend.engine)[0]["id"]
    for actor, reason, code in [
        (Ids.STUDENT, "Restored", "active_admin"),
        (Ids.ADMIN, " ", "reason_required"),
    ]:
        with pytest.raises(RetryRejected, match=code):
            retry_failed(database.backend.engine, nid, actor, reason, clock.utc_now())
    assert len(failed_messages(database.backend.engine)) == 2


@pytest.mark.parametrize("obsolete", ["cancelled", "started"])
def test_obsolete_reminder_is_not_requeued(database, client, monkeypatch, obsolete):
    prepare_failed(database, client, monkeypatch)
    with database.owner.begin() as conn:
        notice = (
            conn.execute(select(t.notifications).where(t.notifications.c.kind == "reminder"))
            .mappings()
            .one()
        )
        conn.execute(
            update(t.notifications)
            .where(t.notifications.c.id == notice["id"])
            .values(status="failed")
        )
    now = clock.utc_now()
    if obsolete == "cancelled":
        client.post(
            f"/api/v1/bookings/{notice['booking_id']}/cancel",
            headers={"Authorization": "Bearer demo-student"},
        )
    else:
        with store.lock:
            now = store.slots[Ids.SLOT_NET_D4_0900].starts_at
    assert (
        retry_failed(database.backend.engine, notice["id"], Ids.ADMIN, "Manual check", now)
        == "cancelled"
    )


def test_retry_and_audit_roll_back_together(database, client, monkeypatch):
    from sqlalchemy.exc import DBAPIError

    prepare_failed(database, client, monkeypatch)
    nid = failed_messages(database.backend.engine)[0]["id"]
    with database.owner.begin() as conn:
        conn.exec_driver_sql("""CREATE FUNCTION reject_retry_audit() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'test audit failure'; END $$;
            CREATE TRIGGER reject_retry BEFORE INSERT ON audit_log FOR EACH ROW EXECUTE FUNCTION reject_retry_audit();""")
    with pytest.raises(DBAPIError):
        retry_failed(database.backend.engine, nid, Ids.ADMIN, "Restored", clock.utc_now())
    assert nid in {r["id"] for r in failed_messages(database.backend.engine)}


def test_horizon_extends_without_a_browser_and_refresh_is_idempotent(database):
    now, tid = clock.utc_now(), uuid.uuid4()
    with database.owner.begin() as conn:
        conn.execute(
            insert(t.templates).values(
                id=tid,
                resource_id=Ids.RES_DB_CONSULT,
                weekday=3,
                start_local="14:00",
                end_local="16:00",
                slot_minutes=30,
                valid_from=now.date(),
            )
        )
    assert refresh_horizon(now) == 8
    assert refresh_horizon(now) == 0
    assert refresh_horizon(now + timedelta(days=7)) == 4
    with store.lock:
        assert len([s for s in store.slots.values() if s.template_id == tid]) == 12
    ensure_horizon(now + timedelta(days=7))


def test_worker_cli_refreshes_horizon_on_startup(database, tmp_path):
    tid = uuid.uuid4()
    with database.owner.begin() as conn:
        conn.execute(
            insert(t.templates).values(
                id=tid,
                resource_id=Ids.RES_DB_CONSULT,
                weekday=3,
                start_local="14:00",
                end_local="16:00",
                slot_minutes=30,
                valid_from=(datetime.now(UTC) - timedelta(days=7)).date(),
            )
        )
    env = {
        key: os.environ[key]
        for key in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATH")
        if key in os.environ
    }
    env.update(
        {"PYTHONPATH": "src", "UNISLOT_DATABASE_URL": database.app_url, "PYTHONIOENCODING": "utf-8"}
    )
    result = subprocess.run(
        [sys.executable, "scripts/run_worker.py", "--once"],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, "worker CLI failed"
    assert json.loads(result.stdout.splitlines()[0])["event"] == "horizon_refresh"
    with database.owner.connect() as conn:
        assert conn.execute(select(t.slots.c.id).where(t.slots.c.template_id == tid)).first()


def test_notification_cli_lists_and_retries_without_credentials_in_output(
    database, client, monkeypatch
):
    prepare_failed(database, client, monkeypatch)
    env = {**os.environ, "UNISLOT_DATABASE_URL": database.app_url}
    command = [sys.executable, "scripts/manage_notifications.py"]
    listing = subprocess.run(  # noqa: S603 -- fixed local CLI and isolated test database
        [*command, "failed", "--limit", "1"],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
        check=False,
    )
    assert listing.returncode == 0
    nid = json.loads(listing.stdout)["items"][0]["id"]
    retry = subprocess.run(  # noqa: S603 -- ID returned by the same isolated test CLI
        [*command, "retry", nid, "--actor-id", str(Ids.ADMIN), "--reason", "Gateway restored"],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
        check=False,
    )
    assert retry.returncode == 0 and json.loads(retry.stdout)["status"] == "pending"
    assert database.app_url not in listing.stdout + retry.stdout + listing.stderr + retry.stderr
