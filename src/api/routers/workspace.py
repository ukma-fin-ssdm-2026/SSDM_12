"""Операції читання для кабінетів; права перевіряються також під транзакційним lock."""

from dataclasses import asdict
from datetime import date, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from api import clock
from api.config import API_PREFIX
from api.enums import Role
from api.errors import ErrorCode, problem_responses, validation_problem
from api.infrastructure.unit_of_work import transactional
from api.pagination import DEFAULT_PAGE_SIZE, Limit, Offset, OffsetPagination
from api.policy import KYIV
from api.routers.availability import ResourceId
from api.schemas.workspace import (
    AccountList,
    AccountOut,
    AuditEntry,
    AuditList,
    CalendarList,
    CalendarSlot,
    CalendarSummary,
    ManagedSlot,
    ManagedSlotList,
    TemplateList,
    TimeBlockList,
    TimeBlockRead,
)
from api.security import Admin, Provider
from api.slot_rules import kyiv_day_bounds
from api.stubs import admin_service, availability_service, slot_service, template_service
from api.stubs.store import store

TAG = {"name": "workspace", "description": "Приватні списки даних для провайдера й адміністратора."}
router = APIRouter(prefix=API_PREFIX, tags=[TAG["name"]])
_ERRORS = (
    ErrorCode.AUTH_REQUIRED,
    ErrorCode.FORBIDDEN_ROLE,
    ErrorCode.NOT_OWNER,
    ErrorCode.RESOURCE_NOT_FOUND,
    ErrorCode.VALIDATION_FAILED,
)


def _page(items, limit, offset):
    return {
        "items": items[offset : offset + limit],
        "pagination": OffsetPagination(
            limit=limit, offset=offset, total=len(items), has_more=offset + limit < len(items)
        ),
    }


@router.get(
    "/admin/users",
    response_model=AccountList,
    summary="Знайти користувачів для адміністрування",
    response_description="Сторінка користувачів без секретів автентифікації.",
    responses=problem_responses(
        ErrorCode.AUTH_REQUIRED, ErrorCode.FORBIDDEN_ROLE, ErrorCode.VALIDATION_FAILED
    ),
)
@transactional
def list_admin_users(
    admin: Admin,
    q: Annotated[
        str | None, Query(max_length=254, description="Частина імені або адреси без регістру.")
    ] = None,
    role: Annotated[Role | None, Query(description="Лише користувачі з указаною роллю.")] = None,
    limit: Limit = DEFAULT_PAGE_SIZE,
    offset: Offset = 0,
) -> AccountList:
    """Пошук для призначення провайдера та ролей. Тільки адміністратор бачить чужі
    адреси; ні хеші паролів, ні сесії, ні лічильники входу не серіалізуються.
    """
    admin_service._check_admin(admin)
    query = (q or "").strip().casefold()
    found = sorted(
        (
            u
            for u in store.users.values()
            if (not query or query in u.full_name.casefold() or query in u.email.casefold())
            and (role is None or role in u.roles)
        ),
        key=lambda u: (u.full_name.casefold(), str(u.id)),
    )
    page = _page(found, limit, offset)
    return AccountList(
        items=[
            AccountOut(
                id=u.id,
                full_name=u.full_name,
                email=u.email,
                roles=sorted(u.roles, key=lambda r: r.value),
                is_active=u.is_active,
            )
            for u in page["items"]
        ],
        pagination=page["pagination"],
    )


@router.get(
    "/resources/{resource_id}/slots",
    response_model=ManagedSlotList,
    summary="Переглянути власні опубліковані слоти",
    response_description="Слоти та причини доступності без даних студентів.",
    responses=problem_responses(*_ERRORS),
)
@transactional
def list_managed_slots(
    resource_id: ResourceId,
    provider: Provider,
    limit: Limit = DEFAULT_PAGE_SIZE,
    offset: Offset = 0,
) -> ManagedSlotList:
    """Лише власний ресурс; показує активні слоти, які ще не закінчилися, зокрема
    заброньовані та заблоковані. Історичні відкликані слоти не пропонуються повторно.
    """
    availability_service.check_owner(provider, resource_id)
    now = clock.utc_now()
    template_service.extend_horizon(now)
    found = sorted(
        (
            s
            for s in store.slots.values()
            if s.resource_id == resource_id and s.is_active and s.ends_at > now
        ),
        key=lambda s: (s.starts_at, str(s.id)),
    )
    page = _page(found, limit, offset)
    items = []
    for slot in page["items"]:
        if slot.starts_at <= now:
            status = "started"
        elif store.is_blocked(slot):
            status = "blocked"
        elif store.confirmed_booking_for_slot(slot.id):
            status = "booked"
        elif not slot_service.is_free(slot, now):
            status = "outside_horizon"
        else:
            status = "available"
        items.append(
            ManagedSlot(
                **slot_service.to_out(slot).model_dump(),
                available=slot_service.is_free(slot, now),
                availability=status,
            )
        )
    return ManagedSlotList(items=items, pagination=page["pagination"])


@router.get(
    "/resources/{resource_id}/templates",
    response_model=TemplateList,
    summary="Переглянути шаблони власного ресурсу",
    response_description="Шаблони з поточними конфліктами генерації.",
    responses=problem_responses(*_ERRORS),
)
@transactional
def list_resource_templates(
    resource_id: ResourceId,
    provider: Provider,
    limit: Limit = DEFAULT_PAGE_SIZE,
    offset: Offset = 0,
) -> TemplateList:
    """Дає змогу повторно відкрити й змінити шаблон після перезапуску браузера.
    Матеріалізує горизонт як чинний GET одного шаблону; чужі шаблони недоступні.
    """
    availability_service.check_owner(provider, resource_id)
    found = sorted(
        (t for t in store.templates.values() if t.resource_id == resource_id),
        key=lambda t: (t.pattern.weekday, t.pattern.start_local, str(t.id)),
    )
    page = _page(found, limit, offset)
    return TemplateList(
        items=[
            template_service.get_template(provider, resource_id, t.id, clock.utc_now())
            for t in page["items"]
        ],
        pagination=page["pagination"],
    )


@router.get(
    "/resources/{resource_id}/blocks",
    response_model=TimeBlockList,
    summary="Переглянути блокування власного ресурсу",
    response_description="Збережені блокування для перегляду та зняття.",
    responses=problem_responses(*_ERRORS),
)
@transactional
def list_resource_blocks(
    resource_id: ResourceId,
    provider: Provider,
    limit: Limit = DEFAULT_PAGE_SIZE,
    offset: Offset = 0,
) -> TimeBlockList:
    """Повертає причини та межі власних блокувань без ID скасованих бронювань.
    Кількість скасувань повторно не вгадується: вона відома лише під час створення.
    """
    availability_service.check_owner(provider, resource_id)
    found = sorted(
        (b for b in store.blocks.values() if b.resource_id == resource_id),
        key=lambda b: (b.starts_at, str(b.id)),
        reverse=True,
    )
    page = _page(found, limit, offset)
    return TimeBlockList(
        items=[TimeBlockRead(**asdict(b)) for b in page["items"]], pagination=page["pagination"]
    )


def _date_range(first, last):
    first = first or clock.utc_now().astimezone(KYIV).date()
    last = last or first + timedelta(days=6)
    if last < first or (last - first).days > 30:
        raise validation_problem(
            "Оберіть послідовний період до 31 дня.",
            field="query.date_to",
            kind="date_range",
            message="Range must contain 1 to 31 days",
        )
    return kyiv_day_bounds(first)[0], kyiv_day_bounds(last)[1]


@router.get(
    "/resources/{resource_id}/calendar",
    response_model=CalendarList,
    summary="Переглянути календар і завантаження власного ресурсу",
    response_description="Слоти й підсумок за київським діапазоном дат без даних студентів.",
    responses=problem_responses(*_ERRORS),
)
@transactional
def resource_calendar(
    resource_id: ResourceId,
    provider: Provider,
    date_from: Annotated[
        date | None, Query(description="Перша дата за Києвом; стандартно сьогодні.")
    ] = None,
    date_to: Annotated[
        date | None, Query(description="Остання дата включно; максимум 31 день.")
    ] = None,
    limit: Limit = DEFAULT_PAGE_SIZE,
    offset: Offset = 0,
) -> CalendarList:
    """Власник бачить минулі й майбутні слоти та навантаження; чужі ресурси — 403."""
    availability_service.check_owner(provider, resource_id)
    start, end = _date_range(date_from, date_to)
    now = clock.utc_now()
    template_service.extend_horizon(now)
    found = sorted(
        (
            s
            for s in store.slots.values()
            if s.resource_id == resource_id
            and s.is_active
            and s.starts_at < end
            and s.ends_at > start
        ),
        key=lambda s: (s.starts_at, str(s.id)),
    )
    rows, booked, blocked, available = [], 0, 0, 0
    for slot in found:
        busy, block = store.confirmed_booking_for_slot(slot.id) is not None, store.is_blocked(slot)
        free = slot_service.is_free(slot, now)
        booked += busy
        blocked += block
        available += free
        status = (
            "completed"
            if slot.ends_at <= now
            else "started"
            if slot.starts_at <= now
            else "blocked"
            if block
            else "booked"
            if busy
            else "available"
            if free
            else "outside_horizon"
        )
        rows.append(
            CalendarSlot(
                id=slot.id, starts_at=slot.starts_at, ends_at=slot.ends_at, availability=status
            )
        )
    page = _page(rows, limit, offset)
    return CalendarList(
        **page,
        summary=CalendarSummary(
            total_slots=len(rows),
            booked_slots=booked,
            blocked_slots=blocked,
            available_slots=available,
        ),
    )


def _public_audit_value(value):
    if isinstance(value, dict):
        return {
            k: _public_audit_value(v)
            for k, v in value.items()
            if not any(word in k.casefold() for word in ("password", "token", "csrf", "secret"))
        }
    if isinstance(value, list):
        return [_public_audit_value(v) for v in value]
    return value


@router.get(
    "/admin/audit",
    response_model=AuditList,
    summary="Переглянути журнал адміністративних змін із фільтрами",
    response_description="Незмінні події, від нових до старих; доступні лише адміністратору.",
    responses=problem_responses(
        ErrorCode.AUTH_REQUIRED, ErrorCode.FORBIDDEN_ROLE, ErrorCode.VALIDATION_FAILED
    ),
)
@transactional
def audit_log(
    admin: Admin,
    actor_id: Annotated[UUID | None, Query(description="Лише дії вказаного автора.")] = None,
    action: Annotated[
        str | None, Query(max_length=80, description="Точна назва, наприклад resource.update.")
    ] = None,
    date_from: Annotated[
        date | None, Query(description="Початкова київська дата; стандартно сьогодні.")
    ] = None,
    date_to: Annotated[
        date | None, Query(description="Кінцева дата включно, максимум 31 день.")
    ] = None,
    limit: Limit = DEFAULT_PAGE_SIZE,
    offset: Offset = 0,
) -> AuditList:
    """FR-068: лише читання; паролі й токени не повертаються навіть із помилкового payload."""
    admin_service._check_admin(admin)
    start, end = _date_range(date_from, date_to)
    found = [
        entry
        for entry in reversed(store.audit)
        if start <= entry["at"] < end
        and (actor_id is None or entry["actor_id"] == actor_id)
        and (not action or entry["action"] == action)
    ]
    found.sort(key=lambda row: row["at"], reverse=True)
    page = _page(found, limit, offset)
    return AuditList(
        items=[
            AuditEntry(
                id=e.get("id"),
                actor_id=e["actor_id"],
                actor_name=store.users[e["actor_id"]].full_name,
                action=e["action"],
                object_id=e.get("object_id"),
                before=_public_audit_value(e.get("before")),
                after=_public_audit_value(e.get("after")),
                at=e["at"],
            )
            for e in page["items"]
        ],
        pagination=page["pagination"],
    )
