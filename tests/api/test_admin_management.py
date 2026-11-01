"""API-сценарії ролей і версій політики; локальна реалізація до midterm #240."""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from api import clock
from api.enums import Role
from api.stubs.store import Ids, store

pytestmark = pytest.mark.req("FR-062", "FR-063", "FR-064", "FR-065", "FR-066", "SEC-002")
ADMIN = {"Authorization": "Bearer demo-admin"}
STUDENT = {"Authorization": "Bearer demo-student"}
POLICY = "/api/v1/admin/policies/current"


def role_url(user_id: uuid.UUID, role: str = "admin") -> str:
    return f"/api/v1/admin/users/{user_id}/roles/{role}"


def test_role_changes_take_effect_on_the_next_request(client: TestClient) -> None:
    url = role_url(Ids.STUDENT)
    assert client.get(POLICY, headers=STUDENT).status_code == 403
    granted = client.put(url, headers=ADMIN)
    assert granted.status_code == 200
    assert granted.json()["roles"] == ["admin", "student"]
    assert client.get(POLICY, headers=STUDENT).status_code == 200
    assert client.delete(url, headers=ADMIN).status_code == 200
    assert client.get(POLICY, headers=STUDENT).status_code == 403
    assert store.users[Ids.STUDENT].roles == {Role.STUDENT}


def test_last_admin_is_protected_without_mutation(client: TestClient) -> None:
    response = client.delete(role_url(Ids.ADMIN), headers=ADMIN)
    assert response.status_code == 409
    assert response.json()["code"] == "LAST_ADMIN"
    assert Role.ADMIN in store.users[Ids.ADMIN].roles
    assert not store.audit


def test_concurrent_self_revocation_always_keeps_one_admin(client: TestClient) -> None:
    assert client.put(role_url(Ids.STUDENT_2), headers=ADMIN).status_code == 200

    def revoke(pair: tuple[uuid.UUID, str]) -> int:
        user_id, token = pair
        return client.delete(
            role_url(user_id), headers={"Authorization": f"Bearer {token}"}
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(
            pool.map(revoke, [(Ids.ADMIN, "demo-admin"), (Ids.STUDENT_2, "demo-student-2")])
        )
    assert sorted(statuses) == [200, 409]
    assert sum(Role.ADMIN in u.roles for u in store.users.values()) == 1


def test_role_put_and_delete_are_idempotent(client: TestClient) -> None:
    url = role_url(Ids.STUDENT, "provider")
    first = client.put(url, headers=ADMIN)
    assert client.put(url, headers=ADMIN).json() == first.json()
    assert len(store.audit) == 1
    removed = client.delete(url, headers=ADMIN)
    assert client.delete(url, headers=ADMIN).json() == removed.json()
    assert len(store.audit) == 2
    assert store.audit[0]["before"] == {"roles": ["student"]}
    assert store.audit[1]["after"] == {"roles": ["student"]}


def test_provider_role_requires_reassignment_of_owned_resources(client: TestClient) -> None:
    url = role_url(Ids.PROVIDER, "provider")
    response = client.delete(url, headers=ADMIN)
    assert response.status_code == 409
    assert response.json()["code"] == "PROVIDER_HAS_RESOURCES"
    assert not store.audit
    for rec in list(store.resources.values()):
        if rec.provider_id == Ids.PROVIDER:
            assert (
                client.patch(
                    f"/api/v1/admin/resources/{rec.id}",
                    headers=ADMIN,
                    json={"provider_id": str(Ids.PROVIDER_2)},
                ).status_code
                == 200
            )
    assert client.delete(url, headers=ADMIN).json()["roles"] == []


@pytest.mark.parametrize("role", ["student", "superadmin", "PROVIDER"])
def test_only_managed_roles_can_be_changed(client: TestClient, role: str) -> None:
    assert client.put(role_url(Ids.STUDENT, role), headers=ADMIN).status_code == 422
    assert not store.audit


def test_missing_user_is_404(client: TestClient) -> None:
    response = client.put(role_url(uuid.uuid4()), headers=ADMIN)
    assert response.status_code == 404
    assert response.json()["code"] == "USER_NOT_FOUND"


def test_policy_versions_keep_existing_bookings_unchanged(client: TestClient) -> None:
    old = store.bookings[Ids.BOOKING_ACTIVE]
    old_policy, old_deadline = old.policy_id, old.cancel_deadline_at
    payload = {"booking_limit": 5, "cancel_window_minutes": 60}
    response = client.put(POLICY, headers=ADMIN, json=payload)
    assert response.status_code == 200
    new_policy = uuid.UUID(response.json()["id"])
    assert new_policy != old_policy
    assert old.policy_id == old_policy and old.cancel_deadline_at == old_deadline
    assert store.policies[old_policy].cancel_window == timedelta(hours=2)
    booked = client.post(
        "/api/v1/bookings", headers=STUDENT, json={"slot_id": str(Ids.SLOT_NET_D4_0900)}
    )
    assert booked.status_code == 201
    new = store.bookings[uuid.UUID(booked.json()["id"])]
    assert new.policy_id == new_policy
    assert new.cancel_deadline_at == store.slots[new.slot_id].starts_at - timedelta(hours=1)
    assert client.put(POLICY, headers=ADMIN, json=payload).json() == response.json()
    assert len(store.policies) == 2 and len(store.audit) == 1


def test_lowering_limit_preserves_bookings_and_blocks_new_ones(client: TestClient) -> None:
    before = dict(store.bookings)
    assert (
        client.put(
            POLICY, headers=ADMIN, json={"booking_limit": 1, "cancel_window_minutes": 0}
        ).status_code
        == 200
    )
    assert store.bookings == before
    response = client.post(
        "/api/v1/bookings", headers=STUDENT, json={"slot_id": str(Ids.SLOT_NET_D4_0900)}
    )
    assert response.status_code == 409
    assert response.json()["code"] == "BOOKING_LIMIT_REACHED"
    assert response.json()["limit"] == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"booking_limit": 0},
        {"booking_limit": -1},
        {"booking_limit": True},
        {"booking_limit": "3"},
        {"booking_limit": None},
        {"cancel_window_minutes": -1},
        {"cancel_window_minutes": False},
        {"cancel_window_minutes": 2_147_483_647},
        {"extra": 1},
    ],
)
def test_bad_policy_is_422_and_does_not_change_state(client: TestClient, changes: dict) -> None:
    payload = {"booking_limit": 3, "cancel_window_minutes": 120, **changes}
    before = client.get(POLICY, headers=ADMIN).json()
    assert client.put(POLICY, headers=ADMIN, json=payload).status_code == 422
    assert client.get(POLICY, headers=ADMIN).json() == before
    assert not store.audit


def test_policy_put_requires_both_fields(client: TestClient) -> None:
    assert client.put(POLICY, headers=ADMIN, json={"booking_limit": 3}).status_code == 422


def test_policy_noop_does_not_create_an_audit_event(client: TestClient) -> None:
    before = client.get(POLICY, headers=ADMIN).json()
    payload = {k: v for k, v in before.items() if k != "id"}
    assert client.put(POLICY, headers=ADMIN, json=payload).json() == before
    assert not store.audit


def test_old_cancel_window_still_applies_after_policy_change(client: TestClient) -> None:
    slot = store.slots[Ids.SLOT_DB_D1_1030]
    slot.starts_at = clock.utc_now() + timedelta(hours=3)
    slot.ends_at = slot.starts_at + timedelta(minutes=30)
    created = client.post("/api/v1/bookings", headers=STUDENT, json={"slot_id": str(slot.id)})
    assert created.status_code == 201
    assert (
        client.put(
            POLICY, headers=ADMIN, json={"booking_limit": 5, "cancel_window_minutes": 360}
        ).status_code
        == 200
    )
    response = client.post(f"/api/v1/bookings/{created.json()['id']}/cancel", headers=STUDENT)
    assert response.status_code == 200
