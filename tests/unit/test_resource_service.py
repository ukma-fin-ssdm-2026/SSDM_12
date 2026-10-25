"""Resource rules and the audit boundary, directly tested without HTTP.

Local AI draft: Codex; fixtures include synthetic users/resources only.
"""

from __future__ import annotations

import copy
import uuid

import pytest

from api.enums import ResourceType
from api.errors import ApiProblem, ErrorCode
from api.schemas.resources import ResourceCreate
from api.stubs import resource_service as service
from api.stubs.store import Ids, store


def test_create_records_actor_and_independent_audit_snapshot(admin, now):
    data = ResourceCreate(
        name="New room", type=ResourceType.ROOM, capacity=20, provider_id=Ids.PROVIDER
    )
    result = service.create_resource(admin, data)
    entry = store.audit[-1]
    assert entry["actor_id"] == admin.id and entry["at"] == now
    assert entry["before"] is None and entry["object_id"] == result.id
    service.update_resource(admin, result.id, {"name": "Changed"})
    assert entry["after"]["name"] == "New room"


@pytest.mark.parametrize("provider_id", [Ids.STUDENT, uuid.UUID(int=0)])
def test_invalid_provider_neither_creates_nor_audits(admin, provider_id):
    before = copy.deepcopy(store.resources)
    data = ResourceCreate(name="Room", type=ResourceType.ROOM, capacity=20, provider_id=provider_id)
    with pytest.raises(ApiProblem) as error:
        service.create_resource(admin, data)
    assert error.value.code is ErrorCode.PROVIDER_NOT_ELIGIBLE
    assert store.resources == before and store.audit == []


@pytest.mark.parametrize(
    ("resource_id", "changes"),
    [
        (Ids.RES_ROOM_1_225, {"capacity": None}),
        (Ids.RES_DB_CONSULT, {"capacity": 10}),
        (Ids.RES_ROOM_1_225, {"provider_id": Ids.STUDENT}),
    ],
)
def test_invalid_update_does_not_partially_rename(admin, resource_id, changes):
    before = copy.deepcopy(store.resources)
    with pytest.raises(ApiProblem):
        service.update_resource(admin, resource_id, {"name": "Must not stick", **changes})
    assert store.resources == before and store.audit == []


def test_valid_update_keeps_omitted_fields(admin):
    rec = store.resources[Ids.RES_ROOM_1_225]
    before = copy.deepcopy(rec)
    service.update_resource(admin, rec.id, {"name": "Updated"})
    assert rec.name == "Updated"
    assert (rec.capacity, rec.type, rec.provider_id) == (
        before.capacity,
        before.type,
        before.provider_id,
    )
    assert store.audit[-1]["before"]["name"] == before.name


def test_consultation_explicit_null_capacity_is_allowed(admin):
    rec = service.update_resource(admin, Ids.RES_DB_CONSULT, {"capacity": None})
    assert rec.capacity is None


@pytest.mark.parametrize("value", [0, 1001, True, "20"])
def test_service_boundary_rejects_invalid_capacity_without_http(admin, value):
    before = copy.deepcopy(store.resources)
    with pytest.raises(ApiProblem) as error:
        service.update_resource(admin, Ids.RES_ROOM_1_225, {"capacity": value})
    assert error.value.extensions["errors"][0]["field"] == "body.capacity"
    assert store.resources == before and store.audit == []


def test_catalog_total_is_filtered_before_offset():
    rows, total = service.list_resources(ResourceType.ROOM, None, 1, 1)
    assert total == 2 and len(rows) == 1
    assert rows[0].type is ResourceType.ROOM
    assert service.list_resources(None, uuid.UUID(int=0), 10, 0) == ([], 0)
