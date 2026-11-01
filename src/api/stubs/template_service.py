"""Шаблони в пам'яті: атомарне оновлення й ідемпотентне продовження горизонту."""

from __future__ import annotations

import uuid
from datetime import datetime

from api.errors import ApiProblem, ErrorCode
from api.policy import HORIZON, KYIV
from api.schemas.availability import TemplateConflict, TemplateOut, TemplatePut
from api.security import CurrentUser
from api.stubs.availability_service import check_owner
from api.stubs.store import SlotRec, TemplateRec, store
from unislot.availability.domain.templates import WeeklyPattern, generate_occurrences


def _generate(rec: TemplateRec, now: datetime) -> TemplateOut:
    candidates, calendar_conflicts = generate_occurrences(rec.pattern, now, HORIZON, KYIV)
    intervals = {(c.starts_at, c.ends_at) for c in candidates}
    withdrawn = retained = 0
    referenced = {b.slot_id for b in store.bookings.values()}
    for slot in list(store.slots.values()):
        if slot.template_id != rec.id or slot.starts_at <= now or not slot.is_active:
            continue
        if store.confirmed_booking_for_slot(slot.id) is not None:
            retained += 1
        elif (slot.starts_at, slot.ends_at) not in intervals:
            withdrawn += 1
            slot.is_active = False
            if slot.id not in referenced:
                del store.slots[slot.id]
    conflicts = [
        TemplateConflict(code=c.code, day=c.day, start_local=c.start_local)
        for c in calendar_conflicts
    ]
    created = 0
    for candidate in candidates:
        same = next(
            (
                s
                for s in store.slots.values()
                if s.template_id == rec.id
                and s.starts_at == candidate.starts_at
                and s.ends_at == candidate.ends_at
            ),
            None,
        )
        if same is not None and same.is_active:
            continue
        clashes = [
            s
            for s in store.slots.values()
            if s.is_active
            and s.resource_id == rec.resource_id
            and s.starts_at < candidate.ends_at
            and candidate.starts_at < s.ends_at
        ]
        if clashes:
            local = candidate.starts_at.astimezone(KYIV)
            conflicts.extend(
                TemplateConflict(
                    code="slot_overlap",
                    day=local.date(),
                    start_local=local.time(),
                    conflicting_slot_id=s.id,
                )
                for s in sorted(clashes, key=lambda slot: (slot.starts_at, str(slot.id)))
            )
            continue
        if same is not None:
            same.is_active = True
        else:
            slot = SlotRec(
                uuid.uuid4(),
                rec.resource_id,
                candidate.starts_at,
                candidate.ends_at,
                template_id=rec.id,
            )
            store.slots[slot.id] = slot
            created += 1
    return TemplateOut(
        id=rec.id,
        resource_id=rec.resource_id,
        weekday=rec.pattern.weekday,
        start_local=rec.pattern.start_local,
        end_local=rec.pattern.end_local,
        slot_minutes=rec.pattern.slot_minutes,
        valid_from=rec.pattern.valid_from,
        valid_to=rec.pattern.valid_to,
        created_slots=created,
        withdrawn_slots=withdrawn,
        retained_booked_slots=retained,
        conflicts=conflicts,
    )


def save_template(
    actor: CurrentUser,
    resource_id: uuid.UUID,
    template_id: uuid.UUID,
    data: TemplatePut,
    now: datetime,
) -> tuple[TemplateOut, bool]:
    """Зберігає розклад і генерує не конфліктні слоти, не змінюючи чинних бронювань."""
    pattern: WeeklyPattern = data.to_pattern()
    with store.lock:
        check_owner(actor, resource_id)
        existing = store.templates.get(template_id)
        if existing is not None and existing.resource_id != resource_id:
            raise ApiProblem(ErrorCode.TEMPLATE_NOT_FOUND)
        rec = TemplateRec(template_id, resource_id, pattern)
        report = _generate(rec, now)
        store.templates[template_id] = rec
        return report, existing is None


def get_template(
    actor: CurrentUser,
    resource_id: uuid.UUID,
    template_id: uuid.UUID,
    now: datetime,
) -> TemplateOut:
    """Повертає власний шаблон і актуальні конфлікти генерації горизонту."""
    with store.lock:
        check_owner(actor, resource_id)
        rec = store.templates.get(template_id)
        if rec is None or rec.resource_id != resource_id:
            raise ApiProblem(ErrorCode.TEMPLATE_NOT_FOUND)
        return _generate(rec, now)


def extend_horizon(now: datetime) -> None:
    """Створює нові слоти перед пошуком; придатна також для виклику майбутнім Worker."""
    with store.lock:
        for rec in store.templates.values():
            _generate(rec, now)
