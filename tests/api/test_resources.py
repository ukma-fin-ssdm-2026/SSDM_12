"""Ресурси: каталог і адміністрування (US-011; TC-043…TC-047 на рівні контракту, заглушки)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.stubs.store import Ids, store

STUDENT = {"Authorization": "Bearer demo-student"}
PROVIDER = {"Authorization": "Bearer demo-provider"}
ADMIN = {"Authorization": "Bearer demo-admin"}
ROOM = {
    "name": "Аудиторія 2-110",
    "type": "room",
    "capacity": 24,
    "provider_id": str(Ids.PROVIDER_2),
}


@pytest.mark.req("FR-007", "SEC-002")
def test_catalog_is_visible_to_every_role(client: TestClient) -> None:
    for headers in (STUDENT, PROVIDER, ADMIN):
        r = client.get("/api/v1/resources", headers=headers)
        assert r.status_code == 200
        assert r.json()["pagination"]["total"] == 4


@pytest.mark.req("FR-021", "QA-11")
def test_catalog_filters_and_offset_pagination(client: TestClient) -> None:
    rooms = client.get("/api/v1/resources", params={"type": "room"}, headers=STUDENT).json()
    assert {i["type"] for i in rooms["items"]} == {"room"}
    mine = client.get(
        "/api/v1/resources", params={"provider_id": str(Ids.PROVIDER)}, headers=STUDENT
    ).json()
    assert {i["provider"]["id"] for i in mine["items"]} == {str(Ids.PROVIDER)}
    page = client.get("/api/v1/resources", params={"limit": 3, "offset": 0}, headers=STUDENT).json()
    assert len(page["items"]) == 3 and page["pagination"]["has_more"] is True
    last = client.get("/api/v1/resources", params={"limit": 3, "offset": 3}, headers=STUDENT).json()
    assert len(last["items"]) == 1 and last["pagination"]["has_more"] is False


@pytest.mark.req("QA-11")
def test_page_size_is_capped(client: TestClient) -> None:
    r = client.get("/api/v1/resources", params={"limit": 101}, headers=STUDENT)
    assert r.status_code == 422
    assert r.json()["errors"][0]["field"] == "query.limit"


@pytest.mark.req("FR-060")
def test_get_resource_and_not_found(client: TestClient) -> None:
    ok = client.get(f"/api/v1/resources/{Ids.RES_ROOM_1_225}", headers=STUDENT)
    assert ok.status_code == 200 and ok.json()["capacity"] == 30
    missing = client.get(f"/api/v1/resources/{Ids.SLOT_DB_D1_1000}", headers=STUDENT)
    assert missing.status_code == 404 and missing.json()["code"] == "RESOURCE_NOT_FOUND"
    assert client.get("/api/v1/resources/not-a-uuid", headers=STUDENT).status_code == 422


@pytest.mark.req("FR-060", "FR-061", "FR-066", "SEC-005", "TC-043", "TC-046")
def test_admin_creates_room_with_location_and_audit(client: TestClient) -> None:
    r = client.post("/api/v1/admin/resources", headers=ADMIN, json=ROOM)
    assert r.status_code == 201
    created = r.json()
    assert r.headers["Location"] == f"/api/v1/resources/{created['id']}"
    assert created["provider"]["full_name"] == "Олег Бондар"
    assert store.audit[-1]["action"] == "resource.create"
    assert client.get(r.headers["Location"], headers=STUDENT).status_code == 200


@pytest.mark.req("FR-060", "QA-06", "TC-044")
def test_capacity_rules_point_to_the_field(client: TestClient) -> None:
    no_capacity = {**ROOM, "capacity": None}
    r = client.post("/api/v1/admin/resources", headers=ADMIN, json=no_capacity)
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "body.capacity"
    consultation = {**ROOM, "type": "consultation"}
    r = client.post("/api/v1/admin/resources", headers=ADMIN, json=consultation)
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "body.capacity"


@pytest.mark.req("FR-060", "QA-06", "TC-044")
def test_blank_name_and_extra_fields_are_rejected(client: TestClient) -> None:
    assert (
        client.post(
            "/api/v1/admin/resources", headers=ADMIN, json={**ROOM, "name": "   "}
        ).status_code
        == 422
    )
    r = client.post("/api/v1/admin/resources", headers=ADMIN, json={**ROOM, "id": str(Ids.ADMIN)})
    assert r.status_code == 422  # mass assignment (THR-04)
    assert r.json()["errors"][0]["type"] == "extra_forbidden"


@pytest.mark.req("FR-061")
def test_provider_must_have_provider_role(client: TestClient) -> None:
    r = client.post(
        "/api/v1/admin/resources", headers=ADMIN, json={**ROOM, "provider_id": str(Ids.STUDENT)}
    )
    assert r.status_code == 422 and r.json()["code"] == "PROVIDER_NOT_ELIGIBLE"


@pytest.mark.req("FR-007", "SEC-002", "TC-045")
def test_only_admin_manages_resources(client: TestClient) -> None:
    for headers in (STUDENT, PROVIDER):
        r = client.post("/api/v1/admin/resources", headers=headers, json=ROOM)
        assert r.status_code == 403 and r.json()["code"] == "FORBIDDEN_ROLE"
    assert len(store.resources) == 4


@pytest.mark.req("FR-060", "FR-066", "SEC-005", "TC-047", "TP-08")
def test_patch_changes_only_sent_fields(client: TestClient) -> None:
    url = f"/api/v1/admin/resources/{Ids.RES_ROOM_1_225}"
    r = client.patch(url, headers=ADMIN, json={"capacity": 28})
    assert r.status_code == 200
    assert r.json()["capacity"] == 28 and r.json()["name"] == "Аудиторія 1-225"
    audit = store.audit[-1]
    assert audit["before"]["capacity"] == 30 and audit["after"]["capacity"] == 28


@pytest.mark.req("FR-060", "QA-06", "TP-08")
def test_patch_rejects_null_empty_and_type_change(client: TestClient) -> None:
    url = f"/api/v1/admin/resources/{Ids.RES_ROOM_1_225}"
    null_name = client.patch(url, headers=ADMIN, json={"name": None})
    assert null_name.status_code == 422 and null_name.json()["errors"][0]["field"] == "body.name"
    assert client.patch(url, headers=ADMIN, json={}).status_code == 422
    assert client.patch(url, headers=ADMIN, json={"type": "consultation"}).status_code == 422
    assert client.patch(url, headers=ADMIN, json={"capacity": None}).status_code == 422
    consultation = f"/api/v1/admin/resources/{Ids.RES_DB_CONSULT}"
    assert client.patch(consultation, headers=ADMIN, json={"capacity": 5}).status_code == 422
    assert store.resources[Ids.RES_ROOM_1_225].capacity == 30


@pytest.mark.req("FR-060")
def test_patch_unknown_resource_is_404(client: TestClient) -> None:
    r = client.patch(f"/api/v1/admin/resources/{Ids.STUDENT}", headers=ADMIN, json={"capacity": 5})
    assert r.status_code == 404 and r.json()["code"] == "RESOURCE_NOT_FOUND"
