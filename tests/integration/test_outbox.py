"""Одна специфікація доставки для memory та PostgreSQL: повтори, lease, приватність."""

from __future__ import annotations

import copy
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from time import perf_counter

import pytest

from api import clock
from api.infrastructure.outbox import MemoryOutbox, PostgresOutbox, dispatch_due
from api.stubs.store import Ids, StubStore, store
from unislot.notifications.domain.model import RetryPolicy

pytestmark = pytest.mark.req("FR-050", "FR-051", "FR-052", "FR-053", "FR-054", "REL-002", "SEC-004")
STUDENT = {"Authorization": "Bearer demo-student"}
PROVIDER = {"Authorization": "Bearer demo-provider-2"}


@pytest.fixture(params=["memory", "postgres"])
def repository(request, database):
    previous = None
    if request.param == "memory":
        backend = StubStore()
        backend.reset()
        previous = store.set_backend(backend)
        result = MemoryOutbox()
    else:
        result = PostgresOutbox(database.backend.engine)
    try:
        yield result
    finally:
        if previous is not None:
            store.set_backend(previous)


def book(client):
    response = client.post(
        "/api/v1/bookings",
        headers={**STUDENT, "Idempotency-Key": "outbox-test"},
        json={"slot_id": str(Ids.SLOT_NET_D4_0900)},
    )
    assert response.status_code == 201, response.text
    return uuid.UUID(response.json()["id"])


def messages():
    with store.lock:
        return copy.deepcopy(list(store.notifications.values()))


def test_confirmation_and_provider_delivery_are_private_and_idempotent(repository, client):
    bid = book(client)
    book(client)
    assert len(messages()) == 3
    result = dispatch_due(repository, clock.utc_now())
    assert (result.claimed, result.sent) == (2, 2)
    assert dispatch_due(repository, clock.utc_now()).claimed == 0
    mine = client.get("/api/v1/me/notifications?limit=1", headers=STUDENT)
    assert mine.status_code == 200, mine.text
    assert mine.json()["pagination"]["total"] == 1
    notice = mine.json()["items"][0]
    assert notice["kind"] == "confirmation"
    assert notice["payload"]["booking_id"] == str(bid)
    assert {"starts_at", "ends_at", "resource_name", "cancel_deadline_at"} <= notice[
        "payload"
    ].keys()
    assert (
        client.get("/api/v1/me/notifications", headers=PROVIDER).json()["items"][0]["kind"]
        == "provider_created"
    )
    other = client.get(
        "/api/v1/me/notifications", headers={"Authorization": "Bearer demo-student-2"}
    )
    assert other.json()["items"] == []
    assert (
        client.get("/api/v1/me/notifications", headers=STUDENT, params={"offset": 1}).json()[
            "items"
        ]
        == []
    )
    assert client.get("/api/v1/me/notifications").status_code == 401


def test_failure_never_blocks_booking_and_survives_retry(repository, client, monkeypatch):
    monkeypatch.setenv("UNISLOT_NOTIFICATION_FAILURE", "1")
    started = perf_counter()
    book(client)
    assert perf_counter() - started <= 2
    now = clock.utc_now()
    result = dispatch_due(repository, now)
    assert result.failed == 2 and result.sent == 0
    failed = [n for n in messages() if n.kind != "reminder"]
    assert all(
        n.status == "pending" and n.attempts == 1 and n.last_error == "gateway_unavailable"
        for n in failed
    )
    assert all(n.next_attempt_at == now + timedelta(seconds=5) for n in failed)
    assert dispatch_due(repository, now + timedelta(seconds=4)).claimed == 0
    monkeypatch.delenv("UNISLOT_NOTIFICATION_FAILURE")
    assert dispatch_due(repository, now + timedelta(seconds=5)).sent == 2
    assert all(
        n.status == "sent" and n.last_error is None for n in messages() if n.kind != "reminder"
    )


def test_reminder_is_delayed_until_due(repository, client):
    bid = book(client)
    now = clock.utc_now()
    dispatch_due(repository, now)
    due = next(n.scheduled_for for n in messages() if n.kind == "reminder")
    assert dispatch_due(repository, due - timedelta(microseconds=1)).claimed == 0
    assert dispatch_due(repository, due).sent == 1
    with store.lock:
        assert bid not in store.reminders
    assert dispatch_due(repository, due).sent == 0


def test_cancellation_after_claim_prevents_late_worker_delivery(repository, client):
    bid = book(client)
    due = next(n.scheduled_for for n in messages() if n.kind == "reminder")
    claims = repository.claim(due, 100, RetryPolicy())
    notice = next(n for n in claims if n.kind == "reminder")
    response = client.post(f"/api/v1/bookings/{bid}/cancel", headers=STUDENT)
    assert response.status_code == 200, response.text
    assert repository.deliver(notice, due) is False
    repository.finish(notice, due, RetryPolicy(), error=False)
    assert next(n.status for n in messages() if n.id == notice.id) == "cancelled"
    dispatch_due(repository, clock.utc_now())
    inbox = client.get("/api/v1/me/notifications", headers=PROVIDER).json()["items"]
    assert [n["kind"] for n in inbox] == ["provider_cancelled"]


def test_failed_reschedule_keeps_notice_success_replaces_it(repository, client):
    old = book(client)
    before = {n.id for n in messages()}
    assert (
        client.post(
            f"/api/v1/bookings/{old}/reschedule",
            headers=STUDENT,
            json={"new_slot_id": str(Ids.SLOT_DB_D1_1000)},
        ).status_code
        == 409
    )
    assert {n.id for n in messages()} == before
    response = client.post(
        f"/api/v1/bookings/{old}/reschedule",
        headers=STUDENT,
        json={"new_slot_id": str(Ids.SLOT_317_D3_1600)},
    )
    assert response.status_code == 201, response.text
    new = uuid.UUID(response.json()["id"])
    assert (
        next(n.status for n in messages() if n.booking_id == old and n.kind == "reminder")
        == "cancelled"
    )
    assert (
        next(n.status for n in messages() if n.booking_id == new and n.kind == "reminder")
        == "pending"
    )


def test_provider_block_delivers_reason_to_student_even_if_gateway_is_down(
    repository, client, monkeypatch
):
    book(client)
    with store.lock:
        slot = store.slots[Ids.SLOT_NET_D4_0900]
        starts, ends = slot.starts_at, slot.ends_at
    monkeypatch.setenv("UNISLOT_NOTIFICATION_FAILURE", "1")
    response = client.post(
        f"/api/v1/resources/{Ids.RES_NET_CONSULT}/blocks",
        headers=PROVIDER,
        json={"starts_at": starts.isoformat(), "ends_at": ends.isoformat(), "reason": "Хвороба"},
    )
    assert response.status_code == 201, response.text
    assert dispatch_due(repository, clock.utc_now()).failed == 3
    notices = messages()
    assert not any(n.kind == "provider_cancelled" for n in notices)
    assert next(n for n in notices if n.kind == "cancelled").payload["reason"] == "Хвороба"
    assert next(n.status for n in notices if n.kind == "reminder") == "cancelled"
    monkeypatch.delenv("UNISLOT_NOTIFICATION_FAILURE")
    assert dispatch_due(repository, clock.utc_now() + timedelta(seconds=5)).sent == 3


def test_crash_between_send_and_ack_retries_without_duplicate_delivery(repository, client):
    book(client)
    policy, now = RetryPolicy(lease_seconds=2), clock.utc_now()
    claim = repository.claim(now, 1, policy)[0]
    assert repository.deliver(claim, now)
    # No finish: model process death after transmission, before acknowledgment.
    assert dispatch_due(repository, now + timedelta(seconds=1), policy=policy).sent == 1
    assert dispatch_due(repository, now + timedelta(seconds=2), policy=policy).sent == 1
    with store.lock:
        assert len(store.deliveries) == 2
    assert next(n.attempts for n in messages() if n.id == claim.id) == 2


def test_stale_claim_cannot_deliver_or_ack_new_lease(repository, client):
    book(client)
    policy, now = RetryPolicy(lease_seconds=2), clock.utc_now()
    initial = repository.claim(now, 100, policy)
    stale = initial[0]
    fresh = repository.claim(now + timedelta(seconds=2), 100, policy)
    assert {n.id for n in initial} == {n.id for n in fresh}
    assert repository.deliver(stale, now + timedelta(seconds=2)) is False
    repository.finish(stale, now, policy, error=False)
    assert next(n.status for n in messages() if n.id == stale.id) == "sending"
    current = next(n for n in fresh if n.id == stale.id)
    assert repository.deliver(current, now + timedelta(seconds=2)) is True
    repository.finish(current, now, policy, error=False)


def test_exhausted_errors_and_crashed_leases_stop_retrying(repository, client, monkeypatch):
    book(client)
    policy, now = RetryPolicy(max_attempts=1, lease_seconds=2), clock.utc_now()
    monkeypatch.setenv("UNISLOT_NOTIFICATION_FAILURE", "1")
    assert dispatch_due(repository, now, batch=1, policy=policy).failed == 1
    repository.claim(now, 1, policy)  # remaining immediate message: process crashes
    assert repository.claim(now + timedelta(seconds=2), 10, policy) == []
    assert {n.last_error for n in messages() if n.status == "failed"} == {
        "gateway_unavailable",
        "lease_expired",
    }
    assert dispatch_due(repository, now + timedelta(seconds=20), policy=policy).claimed == 0


def test_concurrent_workers_claim_distinct_messages(repository, client):
    book(client)
    with ThreadPoolExecutor(max_workers=4) as pool:
        groups = list(
            pool.map(lambda _: repository.claim(clock.utc_now(), 1, RetryPolicy()), range(4))
        )
    ids = [n.id for group in groups for n in group]
    assert len(ids) == len(set(ids)) == 2
