"""Адміністративні сценарії на обраному через StoreProxy сховищі (FR-062…FR-066).

Зміни та аудит охоплює store.lock: блокування memory-адаптера або транзакція
PostgreSQL з exclusive advisory gate. Ролі перевіряються повторно всередині межі.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from api import clock
from api.enums import Role
from api.errors import ApiProblem, ErrorCode, validation_problem
from api.schemas.admin import PolicyOut, PolicyUpdate, UserRolesOut
from api.security import CurrentUser
from api.stubs.store import PolicyRec, store
from unislot.admin.domain.rules import ensure_role_revocable


def _check_admin(actor: CurrentUser) -> None:
    # Повторна перевірка під lock: роль могли відкликати після HTTP-залежності.
    user = store.users.get(actor.id)
    if user is None or Role.ADMIN not in user.roles:
        raise ApiProblem(ErrorCode.FORBIDDEN_ROLE)


def _audit(
    actor: CurrentUser,
    action: str,
    object_id: uuid.UUID,
    before: dict[str, Any],
    after: dict[str, Any],
) -> None:
    store.audit.append(
        {
            "actor_id": actor.id,
            "action": action,
            "object_id": object_id,
            "before": before,
            "after": after,
            "at": clock.utc_now(),
        }
    )


def change_role(
    actor: CurrentUser,
    user_id: uuid.UUID,
    role: Role,
    *,
    grant: bool,
) -> UserRolesOut:
    """Додає або знімає керовану роль; повтор того самого PUT/DELETE ідемпотентний."""
    with store.lock:
        _check_admin(actor)
        if role not in (Role.ADMIN, Role.PROVIDER):
            raise ApiProblem(ErrorCode.FORBIDDEN_ROLE)
        user = store.users.get(user_id)
        if user is None:
            raise ApiProblem(ErrorCode.USER_NOT_FOUND)
        before = sorted(user.roles)
        if (role in user.roles) == grant:
            return UserRolesOut(user_id=user.id, roles=before)
        if not grant:
            ensure_role_revocable(
                role.value,
                admin_count=sum(Role.ADMIN in u.roles for u in store.users.values()),
                resource_count=sum(r.provider_id == user_id for r in store.resources.values()),
            )
        user.roles = user.roles | {role} if grant else user.roles - {role}
        after = sorted(user.roles)
        _audit(
            actor,
            "role.grant" if grant else "role.revoke",
            user.id,
            {"roles": before},
            {"roles": after},
        )
        return UserRolesOut(user_id=user.id, roles=after)


def _policy_out(rec: PolicyRec) -> PolicyOut:
    return PolicyOut(
        id=rec.id,
        booking_limit=rec.booking_limit,
        cancel_window_minutes=int(rec.cancel_window.total_seconds() // 60),
    )


def current_policy(actor: CurrentUser) -> PolicyOut:
    """Повертає чинну політику лише адміністратору."""
    with store.lock:
        _check_admin(actor)
        if store.policy is None:
            raise ApiProblem(ErrorCode.INTERNAL_ERROR)
        return _policy_out(store.policy)


def update_policy(actor: CurrentUser, data: PolicyUpdate) -> PolicyOut:
    """Створює версію політики, не змінюючи policy_id/deadline старих бронювань."""
    with store.lock:
        before = current_policy(actor)
        if data.model_dump() == before.model_dump(exclude={"id"}):
            return before
        window = timedelta(minutes=data.cancel_window_minutes)
        try:
            _ = clock.utc_now() - window
        except OverflowError:
            raise validation_problem(
                "Вікно скасування виходить за межі підтримуваних дат.",
                field="body.cancel_window_minutes",
                kind="time_out_of_range",
                message="Зменште вікно скасування",
            ) from None
        rec = PolicyRec(uuid.uuid4(), data.booking_limit, window)
        store.policies[rec.id] = rec
        store.policy = rec
        after = _policy_out(rec)
        _audit(
            actor,
            "policy.update",
            rec.id,
            before.model_dump(mode="json"),
            after.model_dump(mode="json"),
        )
        return after
