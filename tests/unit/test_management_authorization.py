"""Повторна авторизація в момент зміни, коли HTTP-залежність уже виконалася."""

import uuid

import pytest

from api import clock
from api.enums import Role
from api.errors import ApiProblem, ErrorCode
from api.schemas.availability import TimeBlockCreate
from api.schemas.resources import ResourceCreate
from api.schemas.slots import SlotCreate
from api.security import CurrentUser
from api.stubs import admin_service, availability_service, resource_service, slot_service
from api.stubs.store import Ids, store

pytestmark = pytest.mark.req("FR-062", "FR-064", "FR-013", "SEC-002")


def actor(user_id: uuid.UUID) -> CurrentUser:
    user = store.users[user_id]
    return CurrentUser(user.id, user.full_name, user.email, user.roles)


def test_admin_role_snapshot_does_not_authorize_after_revocation() -> None:
    stale = actor(Ids.ADMIN)
    store.users[Ids.ADMIN].roles = frozenset()
    with pytest.raises(ApiProblem) as error:
        admin_service.change_role(stale, Ids.STUDENT, Role.PROVIDER, grant=True)
    assert error.value.code is ErrorCode.FORBIDDEN_ROLE
    assert not store.audit


def test_service_also_rejects_changes_to_unmanaged_roles() -> None:
    with pytest.raises(ApiProblem) as error:
        admin_service.change_role(actor(Ids.ADMIN), Ids.STUDENT, Role.STUDENT, grant=False)
    assert error.value.code is ErrorCode.FORBIDDEN_ROLE


def test_missing_policy_does_not_return_a_fabricated_default() -> None:
    store.policy = None
    with pytest.raises(ApiProblem) as error:
        admin_service.current_policy(actor(Ids.ADMIN))
    assert error.value.code is ErrorCode.INTERNAL_ERROR


def test_provider_role_snapshot_does_not_authorize_after_revocation() -> None:
    stale = actor(Ids.PROVIDER)
    store.users[Ids.PROVIDER].roles = frozenset()
    slot = store.slots[Ids.SLOT_DB_D1_1030]
    data = TimeBlockCreate(starts_at=slot.starts_at, ends_at=slot.ends_at, reason="Подія")
    before = dict(store.blocks)
    with pytest.raises(ApiProblem) as error:
        availability_service.create_block(stale, slot.resource_id, data, clock.utc_now())
    assert error.value.code is ErrorCode.FORBIDDEN_ROLE
    assert store.blocks == before


@pytest.mark.parametrize("operation", ["create", "update"])
def test_admin_resource_action_rechecks_live_role(operation):
    stale = actor(Ids.ADMIN)
    store.users[Ids.ADMIN].roles = frozenset()

    def action():
        if operation == "create":
            return resource_service.create_resource(
                stale,
                ResourceCreate(name="Консультація", type="consultation", provider_id=Ids.PROVIDER),
            )
        return resource_service.update_resource(stale, Ids.RES_DB_CONSULT, {"name": "Зміна"})

    with pytest.raises(ApiProblem) as error:
        action()
    assert error.value.code is ErrorCode.FORBIDDEN_ROLE


def test_create_slot_rechecks_live_provider_role():
    stale = actor(Ids.PROVIDER)
    store.users[Ids.PROVIDER].roles = frozenset()
    slot = store.slots[Ids.SLOT_DB_D1_1030]
    with pytest.raises(ApiProblem) as error:
        slot_service.create_slot(
            stale,
            slot.resource_id,
            SlotCreate(starts_at=slot.starts_at, duration_minutes=30),
            clock.utc_now(),
        )
    assert error.value.code is ErrorCode.FORBIDDEN_ROLE
