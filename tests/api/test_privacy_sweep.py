"""SEC-004: перебір усіх операцій читання від імені студента (Лаб 7, бонус 4; TP-10).

Поріг SEC-004 (`requirements.md` §5.4): **0** ендпоінтів, через які студент отримує
персональні дані іншого студента. Умова вимоги — «перебір усіх операцій читання», тому
перелік операцій береться зі специфікації OpenAPI: новий `GET` без рядка в `READS`
валить тест, а не лишається неперевіреним.

Витоком вважаємо дві речі:
- ім'я, e-mail або ідентифікатор облікового запису іншого студента — будь-де в тілі чи
  заголовках відповіді;
- бронювання іншого студента як об'єкт відповіді: JSON-об'єкт з `"id"` його бронювання.
  Той самий ID у полі `instance` відповіді 403 — лише повтор шляху, який студент сам
  надіслав, і витоком не є.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.stubs.store import Ids, store

pytestmark = pytest.mark.req("SEC-004", "QA-07", "TC-067", "TP-10")

STUDENT = {"Authorization": "Bearer demo-student"}
OTHER = {"Authorization": "Bearer demo-student-2"}

# Кожна операція читання → запит із ID об'єктів, пов'язаних з іншим студентом
# (demo-student-2 має бронювання BOOKING_OTHER на слот SLOT_DB_D1_1000).
READS = {
    "/health": "/health",
    "/api/v1/auth/me": "/api/v1/auth/me",
    "/api/v1/resources": f"/api/v1/resources?provider_id={Ids.PROVIDER}",
    "/api/v1/resources/{resource_id}": f"/api/v1/resources/{Ids.RES_DB_CONSULT}",
    "/api/v1/slots": f"/api/v1/slots?provider_id={Ids.PROVIDER}",
    "/api/v1/slots/{slot_id}": f"/api/v1/slots/{Ids.SLOT_DB_D1_1000}",
    "/api/v1/bookings/{booking_id}": f"/api/v1/bookings/{Ids.BOOKING_OTHER}",
    "/api/v1/me/bookings": "/api/v1/me/bookings?limit=100",
}


def person_markers() -> list[str]:
    """Ім'я, e-mail і ID demo-student-2 у тому вигляді, в якому їх зберігає сховище."""
    other = store.users[Ids.STUDENT_2]
    return [other.full_name, other.email, str(other.id)]


def foreign_booking_ids(owner: str = str(Ids.STUDENT)) -> set[str]:
    """ID бронювань, що належать будь-кому, крім `owner`."""
    return {str(b.id) for b in store.bookings.values() if str(b.student_id) != owner}


def objects(node: Any) -> Iterator[dict[str, Any]]:
    """Усі JSON-об'єкти відповіді, зокрема вкладені в списки й інші об'єкти."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from objects(value)
    elif isinstance(node, list):
        for item in node:
            yield from objects(item)


def found_in(response, owner: str = str(Ids.STUDENT)) -> list[str]:
    """Що з персональних даних інших людей видно у відповіді."""
    visible = (response.text + " " + " ".join(response.headers.values())).lower()
    hits = [m for m in person_markers() if m.lower() in visible]
    try:
        body = response.json()
    except ValueError:
        body = None
    foreign = foreign_booking_ids(owner)
    hits += [f"бронювання {o['id']}" for o in objects(body) if o.get("id") in foreign]
    return hits


def leaks(client: TestClient) -> dict[str, list[str]]:
    """Операції читання, відповідь яких студенту містить ПД іншого студента."""
    found = {}
    for template, url in READS.items():
        response = client.get(url, headers=STUDENT)
        assert response.status_code < 500, f"{template}: {response.status_code}"
        hits = found_in(response)
        if hits:
            found[template] = hits
    return found


def test_every_read_operation_is_in_the_sweep() -> None:
    """Повнота перебору — умова SEC-004: перелік збігається з усіма GET у специфікації."""
    reads = {path for path, item in app.openapi()["paths"].items() if "get" in item}
    assert set(READS) == reads


def test_detector_finds_data_where_its_owner_legitimately_sees_it(client: TestClient) -> None:
    """Контроль методу: детектор спрацьовує там, де дані показують самому власнику.

    Без цього контролю помилка в детекторі (одруківка в e-mail, не той ключ JSON) зробила б
    основний тест завжди зеленим — перевірка, яка не вміє падати, нічого не доводить.
    """
    me = client.get("/api/v1/auth/me", headers=OTHER)
    assert [m for m in person_markers() if m in me.text] == person_markers()
    mine = client.get("/api/v1/me/bookings?limit=100", headers=OTHER)
    assert f"бронювання {Ids.BOOKING_OTHER}" in found_in(mine)


def test_no_read_operation_reveals_another_students_personal_data(
    client: TestClient, record_testsuite_property
) -> None:
    found = leaks(client)
    record_testsuite_property("sec004_read_operations", len(READS))
    record_testsuite_property("sec004_leaking_operations", len(found))
    assert found == {}, f"SEC-004: витік у {len(found)} з {len(READS)} операцій: {found}"
