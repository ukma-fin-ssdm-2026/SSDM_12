"""Приватні списки для UI, доступність та безпечна статична оболонка."""

import uuid

import pytest

from api.stubs.store import Ids, store

pytestmark = pytest.mark.req(
    "FR-007", "FR-010", "FR-012", "FR-013", "FR-062", "SEC-002", "SEC-004", "USAB-001"
)
ADMIN = {"Authorization": "Bearer demo-admin"}
PROVIDER = {"Authorization": "Bearer demo-provider"}


def test_user_catalog_is_filtered_paginated_and_has_no_auth_secrets(client):
    response = client.get("/api/v1/admin/users?q=коваль&limit=1", headers=ADMIN)
    assert response.status_code == 200, response.text
    user = response.json()["items"][0]
    assert user["id"] == str(Ids.STUDENT)
    assert set(user) == {"id", "full_name", "email", "roles", "is_active"}
    assert (
        client.get("/api/v1/admin/users?role=provider", headers=ADMIN).json()["pagination"]["total"]
        == 2
    )
    assert client.get("/api/v1/admin/users?q=missing", headers=ADMIN).json()["items"] == []
    page = client.get("/api/v1/admin/users?limit=2&offset=2", headers=ADMIN).json()
    assert len(page["items"]) == 2 and page["pagination"]["total"] == 5


def test_owned_slots_include_available_booked_started_and_outside_horizon(client):
    response = client.get(
        f"/api/v1/resources/{Ids.RES_DB_CONSULT}/slots?limit=100", headers=PROVIDER
    )
    assert response.status_code == 200, response.text
    rows = {r["id"]: r for r in response.json()["items"]}
    assert rows[str(Ids.SLOT_DB_D1_1000)]["availability"] == "booked"
    assert rows[str(Ids.SLOT_DB_D1_1030)]["availability"] == "available"
    assert rows[str(Ids.SLOT_DB_STARTED)]["availability"] == "started"
    assert rows[str(Ids.SLOT_DB_D20)]["availability"] == "outside_horizon"
    assert str(Ids.SLOT_DB_PAST) not in rows
    assert all("student_id" not in r for r in rows.values())
    assert (
        client.get(
            f"/api/v1/resources/{Ids.RES_DB_CONSULT}/slots?limit=1&offset=1", headers=PROVIDER
        ).json()["pagination"]["offset"]
        == 1
    )


def test_block_list_persists_reason_and_slots_show_blocked(client):
    path = f"/api/v1/resources/{Ids.RES_ROOM_3_317}"
    response = client.get(path + "/blocks", headers=PROVIDER)
    assert response.status_code == 200, response.text
    block = response.json()["items"][0]
    assert block["id"] == str(Ids.BLOCK_317_D2)
    assert "cancelled_bookings" not in block
    response = client.get(path + "/slots?limit=100", headers=PROVIDER)
    assert (
        next(
            r["availability"]
            for r in response.json()["items"]
            if r["id"] == str(Ids.SLOT_317_D2_1500)
        )
        == "blocked"
    )


def test_template_list_can_reopen_and_update_a_saved_template(client):
    path = f"/api/v1/resources/{Ids.RES_DB_CONSULT}/templates"
    tid = uuid.uuid4()
    body = {
        "weekday": 3,
        "start_local": "14:00",
        "end_local": "16:00",
        "slot_minutes": 30,
        "valid_from": "2026-10-19",
    }
    assert client.put(path + f"/{tid}", headers=PROVIDER, json=body).status_code == 201
    response = client.get(path, headers=PROVIDER)
    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert item["id"] == str(tid) and item["weekday"] == 3
    assert (
        client.put(
            path + f"/{tid}", headers=PROVIDER, json={**body, "start_local": "15:00"}
        ).status_code
        == 200
    )
    assert client.get(path, headers=PROVIDER).json()["items"][0]["start_local"] == "15:00:00"


@pytest.mark.parametrize("suffix", ["slots", "templates", "blocks"])
def test_lists_check_missing_resource(client, suffix):
    response = client.get(f"/api/v1/resources/{uuid.uuid4()}/{suffix}", headers=PROVIDER)
    assert response.status_code == 404
    assert response.json()["code"] == "RESOURCE_NOT_FOUND"


def test_ui_is_public_but_contains_no_personal_data_or_session_token(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert '<html lang="uk">' in response.text
    assert "unsafe-inline" not in response.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["cache-control"] == "no-store"
    assert store.users[Ids.STUDENT].email not in response.text
    for asset in ["app.mjs", "client.mjs", "styles.css", "mark.svg"]:
        assert client.get("/static/" + asset).status_code == 200
    assert "javascript" in client.get("/static/app.mjs").headers["content-type"]
    assert client.get("/static/../../.env.local").status_code == 404
