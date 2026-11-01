"""Календар власника й фільтрований незмінний аудит, без розкриття ПД студентів."""

import pytest

from api.stubs.store import Ids, store

pytestmark = pytest.mark.req("FR-015", "FR-068", "SEC-002", "SEC-004", "QA-06", "QA-11")
ADMIN = {"Authorization": "Bearer demo-admin"}
PROVIDER = {"Authorization": "Bearer demo-provider"}


def test_calendar_has_whole_range_totals_and_page_without_student_data(client):
    path = f"/api/v1/resources/{Ids.RES_DB_CONSULT}/calendar"
    body = client.get(path, headers=PROVIDER, params={"limit": 1}).json()
    assert len(body["items"]) == 1 and body["pagination"]["has_more"]
    assert body["summary"]["total_slots"] == body["pagination"]["total"]
    assert body["summary"]["booked_slots"] >= 1
    assert "student_id" not in str(body) and "booking_id" not in str(body)
    second = client.get(path, headers=PROVIDER, params={"limit": 1, "offset": 1}).json()
    assert second["items"][0]["id"] != body["items"][0]["id"]
    assert second["summary"] == body["summary"]


@pytest.mark.parametrize(
    "params",
    [
        {"date_from": "2026-10-20", "date_to": "2026-10-19"},
        {"date_from": "2026-10-01", "date_to": "2026-11-01"},
    ],
)
def test_read_date_range_is_validated_on_both_views(client, params):
    for path, actor in [
        ("/api/v1/admin/audit", ADMIN),
        (f"/api/v1/resources/{Ids.RES_DB_CONSULT}/calendar", PROVIDER),
    ]:
        response = client.get(path, headers=actor, params=params)
        assert response.status_code == 422, response.text
        assert response.json()["errors"][0]["field"] == "query.date_to"


def test_audit_filter_pagination_before_after_and_read_only(client):
    for name in ["Edited resource A", "Edited resource B"]:
        assert (
            client.patch(
                f"/api/v1/admin/resources/{Ids.RES_DB_CONSULT}", headers=ADMIN, json={"name": name}
            ).status_code
            == 200
        )
    params = {"action": "resource.update", "actor_id": str(Ids.ADMIN), "limit": 1}
    response = client.get("/api/v1/admin/audit", headers=ADMIN, params=params)
    body = response.json()
    assert response.status_code == 200 and body["pagination"]["total"] == 2
    assert body["items"][0]["after"]["name"] == "Edited resource B"
    assert body["items"][0]["before"]["name"] == "Edited resource A"
    assert (
        client.get("/api/v1/admin/audit", headers=ADMIN, params={**params, "offset": 1}).json()[
            "items"
        ][0]["after"]["name"]
        == "Edited resource A"
    )
    assert client.get("/api/v1/admin/audit?action=missing", headers=ADMIN).json()["items"] == []
    count = len(store.audit)
    assert client.delete("/api/v1/admin/audit", headers=ADMIN).status_code == 405
    assert len(store.audit) == count


def test_audit_never_exposes_nested_auth_secrets(client):
    client.patch(
        f"/api/v1/admin/resources/{Ids.RES_DB_CONSULT}", headers=ADMIN, json={"name": "Safe"}
    )
    store.audit[-1]["after"]["nested"] = {
        "password_hash": "synthetic private marker",  # pragma: allowlist secret -- deliberately fake value to verify redaction
        "label": "allowed",
    }
    body = client.get("/api/v1/admin/audit", headers=ADMIN).json()
    assert body["items"][0]["after"]["nested"] == {"label": "allowed"}
