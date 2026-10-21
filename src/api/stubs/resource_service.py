"""Заглушка `ResourceManagement` і читання каталогу (HLD §5.2) для Лаб 4.

Ресурсами володіє модуль `Availability`; адміністративні сценарії йдуть через
`Admin` і пишуть журнал аудиту (FR-066). Тут — та сама поведінка на даних у пам'яті.
"""

from __future__ import annotations

import uuid
from typing import Any

from api import clock
from api.enums import ResourceType, Role
from api.errors import ApiProblem, ErrorCode
from api.schemas.common import PersonSummary
from api.schemas.resources import ResourceCreate, ResourceOut
from api.security import CurrentUser
from api.stubs.store import ResourceRec, store


def to_out(rec: ResourceRec) -> ResourceOut:
    """Схема відповіді ресурсу; про провайдера — лише id та ім'я (SEC-004)."""
    provider = store.users[rec.provider_id]
    return ResourceOut(
        id=rec.id,
        name=rec.name,
        type=rec.type,
        capacity=rec.capacity,
        provider=PersonSummary(id=provider.id, full_name=provider.full_name),
    )


def list_resources(
    resource_type: ResourceType | None, provider_id: uuid.UUID | None, limit: int, offset: int
) -> tuple[list[ResourceRec], int]:
    """Каталог із фільтрами; порядок — за назвою, потім за id (стабільний для offset)."""
    found = [
        r
        for r in store.resources.values()
        if (resource_type is None or r.type is resource_type)
        and (provider_id is None or r.provider_id == provider_id)
    ]
    found.sort(key=lambda r: (r.name.casefold(), str(r.id)))
    return found[offset : offset + limit], len(found)


def get_resource(resource_id: uuid.UUID) -> ResourceRec:
    """Ресурс за id або 404 `RESOURCE_NOT_FOUND`."""
    rec = store.resources.get(resource_id)
    if rec is None:
        raise ApiProblem(ErrorCode.RESOURCE_NOT_FOUND)
    return rec


def _check_provider(provider_id: uuid.UUID) -> None:
    """INV-15: провайдер ресурсу — існуючий користувач із роллю «провайдер»."""
    user = store.users.get(provider_id)
    if user is None or Role.PROVIDER not in user.roles:
        raise ApiProblem(
            ErrorCode.PROVIDER_NOT_ELIGIBLE,
            "Вказаний provider_id не належить користувачу з роллю «провайдер».",
        )


def _audit(
    actor: CurrentUser, action: str, rec: ResourceRec, before: dict[str, Any] | None
) -> None:
    store.audit.append(
        {
            "actor_id": actor.id,
            "action": action,
            "object_id": rec.id,
            "before": before,
            "after": _snapshot(rec),
            "at": clock.utc_now(),
        }
    )


def _snapshot(rec: ResourceRec) -> dict[str, Any]:
    return {
        "name": rec.name,
        "type": rec.type.value,
        "capacity": rec.capacity,
        "provider_id": str(rec.provider_id),
    }


def create_resource(actor: CurrentUser, data: ResourceCreate) -> ResourceRec:
    """Створює ресурс (FR-060, FR-061) і пише запис аудиту в тому самому блокуванні (FR-066)."""
    with store.lock:
        _check_provider(data.provider_id)
        rec = ResourceRec(
            id=uuid.uuid4(),
            name=data.name,
            type=data.type,
            capacity=data.capacity,
            provider_id=data.provider_id,
        )
        store.resources[rec.id] = rec
        _audit(actor, "resource.create", rec, before=None)
        return rec


def update_resource(
    actor: CurrentUser, resource_id: uuid.UUID, changes: dict[str, Any]
) -> ResourceRec:
    """Застосовує лише передані поля (`exclude_unset`). Тип ресурсу незмінний."""
    with store.lock:
        rec = get_resource(resource_id)
        if "capacity" in changes:
            if rec.type is ResourceType.CONSULTATION and changes["capacity"] is not None:
                raise ApiProblem(
                    ErrorCode.VALIDATION_FAILED,
                    "Консультація не має місткості (INV-08).",
                    errors=[
                        {
                            "field": "body.capacity",
                            "type": "capacity_not_allowed",
                            "message": "Місткість задається лише для аудиторій",
                        }
                    ],
                )
            if rec.type is ResourceType.ROOM and changes["capacity"] is None:
                raise ApiProblem(
                    ErrorCode.VALIDATION_FAILED,
                    "Аудиторія мусить мати місткість (INV-08).",
                    errors=[
                        {
                            "field": "body.capacity",
                            "type": "capacity_required",
                            "message": "Місткість аудиторії не може бути null",
                        }
                    ],
                )
        if "provider_id" in changes:
            _check_provider(changes["provider_id"])
        before = _snapshot(rec)
        for name, value in changes.items():
            setattr(rec, name, value)
        _audit(actor, "resource.update", rec, before=before)
        return rec
