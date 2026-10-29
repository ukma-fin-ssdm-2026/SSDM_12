"""Таблиця рішень «роль × операція × власник» для SEC-002 (Лаб 7, бонус 2; TP-09).

Умови: хто надсилає запит (анонім, студент, провайдер, адміністратор) і, для операцій
над конкретним бронюванням чи ресурсом, чи належить цей об'єкт користувачу. Дії:
2xx, 401 `AUTH_REQUIRED`, 403 `FORBIDDEN_ROLE`, 403 `NOT_OWNER`.

Одне правило таблиці — один випадок тесту; ID випадку дорівнює ID правила (DT-01…DT-56).
Таблиця в людському вигляді — `docs/validation/test-plan.md`, розділ «Бонуси», бонус 2.
Метрика SEC-002: 100% заборонених правил дають 401/403, і жодне з них не змінює даних.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.stubs.store import Ids, store

pytestmark = pytest.mark.req("FR-007", "SEC-002", "QA-07", "TC-065", "TP-09")

TOKENS = {
    "anon": None,
    "student": "demo-student",
    "provider": "demo-provider",
    "admin": "demo-admin",
}

# Тіла запитів однакові для дозволених і заборонених правил: якщо запит відхилено,
# то через роль чи власника, а не через некоректне тіло.
BODIES = {
    ("POST", "/api/v1/bookings"): {"slot_id": str(Ids.SLOT_DB_D1_1030)},
    ("POST", "/api/v1/bookings/{booking_id}/reschedule"): {"new_slot_id": str(Ids.SLOT_DB_D1_1100)},
    ("POST", "/api/v1/admin/resources"): {
        "name": "Аудиторія 2-110",
        "type": "room",
        "capacity": 24,
        "provider_id": str(Ids.PROVIDER_2),
    },
    ("PATCH", "/api/v1/admin/resources/{resource_id}"): {"capacity": 28},
    ("POST", "/api/v1/resources/{resource_id}/slots"): {
        "starts_at": "2027-02-15T10:00:00+02:00",
        "duration_minutes": 30,
    },
}


@dataclass(frozen=True)
class Rule:
    rule_id: str
    method: str
    template: str
    actor: str
    status: int
    code: str | None = None

    @property
    def role(self) -> str:
        return self.actor.split(":", 1)[0]

    @property
    def foreign(self) -> bool:
        return self.actor.endswith(":foreign")

    @property
    def forbidden(self) -> bool:
        return self.status in {401, 403}

    def path(self) -> str:
        booking = Ids.BOOKING_OTHER if self.foreign else Ids.BOOKING_ACTIVE
        if self.template.endswith("/slots") and "{resource_id}" in self.template:
            resource = Ids.RES_NET_CONSULT if self.foreign else Ids.RES_DB_CONSULT
        else:
            resource = Ids.RES_ROOM_1_225
        return self.template.format(
            booking_id=booking, resource_id=resource, slot_id=Ids.SLOT_DB_D1_1030
        )


def block(method: str, template: str, outcomes: list[tuple[str, int, str | None]], first: int):
    return [
        Rule(f"DT-{first + i:02d}", method, template, actor, status, code)
        for i, (actor, status, code) in enumerate(outcomes)
    ]


ANON = ("anon", 401, "AUTH_REQUIRED")
EVERYONE = [ANON, ("student", 200, None), ("provider", 200, None), ("admin", 200, None)]
ROLE = "FORBIDDEN_ROLE"
OWNER = "NOT_OWNER"


def own_booking_only(status: int) -> list[tuple[str, int, str | None]]:
    return [
        ANON,
        ("student", status, None),
        ("student:foreign", 403, OWNER),
        ("provider", 403, ROLE),
        ("admin", 403, ROLE),
    ]


def students_only(status: int) -> list[tuple[str, int, str | None]]:
    return [ANON, ("student", status, None), ("provider", 403, ROLE), ("admin", 403, ROLE)]


def admin_only(status: int) -> list[tuple[str, int, str | None]]:
    return [ANON, ("student", 403, ROLE), ("provider", 403, ROLE), ("admin", status, None)]


RULES: list[Rule] = [
    *block("GET", "/api/v1/auth/me", EVERYONE, 1),
    *block("POST", "/api/v1/bookings", students_only(201), 5),
    *block("GET", "/api/v1/bookings/{booking_id}", own_booking_only(200), 9),
    *block("POST", "/api/v1/bookings/{booking_id}/cancel", own_booking_only(200), 14),
    *block("POST", "/api/v1/bookings/{booking_id}/reschedule", own_booking_only(201), 19),
    *block("GET", "/api/v1/me/bookings", students_only(200), 24),
    *block("GET", "/api/v1/resources", EVERYONE, 28),
    *block("GET", "/api/v1/resources/{resource_id}", EVERYONE, 32),
    *block("POST", "/api/v1/admin/resources", admin_only(201), 36),
    *block("PATCH", "/api/v1/admin/resources/{resource_id}", admin_only(200), 40),
    *block("GET", "/api/v1/slots", students_only(200), 44),
    *block("GET", "/api/v1/slots/{slot_id}", EVERYONE, 48),
    *block(
        "POST",
        "/api/v1/resources/{resource_id}/slots",
        [
            ANON,
            ("student", 403, ROLE),
            ("provider", 201, None),
            ("provider:foreign", 403, OWNER),
            ("admin", 403, ROLE),
        ],
        52,
    ),
]


def snapshot() -> tuple:
    """Стан даних, який заборонене правило не має змінити (друга половина SEC-002)."""
    return (
        sorted((str(b.id), b.status.value, str(b.slot_id)) for b in store.bookings.values()),
        sorted((str(r.id), r.name, r.capacity) for r in store.resources.values()),
        sorted(str(s) for s in store.slots),
        len(store.audit),
    )


def send(client: TestClient, rule: Rule):
    token = TOKENS[rule.role]
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    body = BODIES.get((rule.method, rule.template))
    return client.request(rule.method, rule.path(), headers=headers, json=body)


@pytest.mark.parametrize("rule", RULES, ids=[r.rule_id for r in RULES])
def test_rbac_decision_table(client: TestClient, rule: Rule) -> None:
    before = snapshot()
    response = send(client, rule)
    assert response.status_code == rule.status, response.text
    if rule.forbidden:
        assert response.json()["code"] == rule.code
        assert snapshot() == before, "заборонене правило змінило дані"


def test_decision_table_ids_are_unique_and_consecutive() -> None:
    assert [r.rule_id for r in RULES] == [f"DT-{i:02d}" for i in range(1, len(RULES) + 1)]


def test_decision_table_covers_every_protected_operation_for_every_role() -> None:
    """Нова операція API без правил для всіх чотирьох ролей — червоний тест, а не дірка."""
    operations = {
        (method.upper(), path)
        for path, item in app.openapi()["paths"].items()
        for method in item
        if method in {"get", "post", "put", "patch", "delete"} and path != "/health"
    }
    roles: dict[tuple[str, str], set[str]] = {}
    for rule in RULES:
        roles.setdefault((rule.method, rule.template), set()).add(rule.role)
    assert set(roles) == operations
    assert all(found == set(TOKENS) for found in roles.values())


def test_share_of_denied_forbidden_rules_meets_sec002_threshold(
    client: TestClient, record_testsuite_property
) -> None:
    """Поріг SEC-002 як число: частка заборонених правил, що справді отримали 401/403."""
    forbidden = [r for r in RULES if r.forbidden]
    denied = 0
    for rule in forbidden:
        store.reset()
        denied += send(client, rule).status_code == rule.status
    record_testsuite_property("sec002_forbidden_rules", len(forbidden))
    record_testsuite_property("sec002_denied", denied)
    assert denied / len(forbidden) == 1.0, f"SEC-002: {denied} з {len(forbidden)}"
