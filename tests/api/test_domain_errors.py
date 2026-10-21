"""Переклад доменних помилок у problem+json (HLD §9, DD-07).

Домен не знає про HTTP: підклас `DomainError` задає лише код причини, а статус,
назву й дію для користувача бере REST API з каталогу `api.errors.CATALOG`.
Тестові маршрути — в окремому застосунку, тож перевірка не залежить від модулів.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.errors import CATALOG, ErrorCode
from api.main import create_app
from unislot.platform.errors import DomainError


class _SlotTaken(DomainError):
    code = "SLOT_ALREADY_BOOKED"


class _LimitReached(DomainError):
    code = "BOOKING_LIMIT_REACHED"


class _UnknownCode(DomainError):
    code = "NO_SUCH_CODE"


def _client_raising(exc: Exception) -> TestClient:
    app = create_app()

    @app.get("/raise")
    def raise_it() -> None:
        raise exc

    return TestClient(app, raise_server_exceptions=False)


def test_domain_error_becomes_problem_json_with_its_code() -> None:
    r = _client_raising(_SlotTaken("Слот щойно зайняли.")).get("/raise")
    assert r.status_code == 409
    assert r.headers["content-type"] == "application/problem+json"
    body = r.json()
    assert body["code"] == "SLOT_ALREADY_BOOKED"
    assert body["detail"] == "Слот щойно зайняли."
    assert body["action"] == CATALOG[ErrorCode.SLOT_ALREADY_BOOKED].action
    assert body["request_id"] == r.headers["X-Request-ID"]


def test_domain_error_without_detail_uses_catalog_text() -> None:
    r = _client_raising(_SlotTaken()).get("/raise")
    assert r.json()["detail"] == CATALOG[ErrorCode.SLOT_ALREADY_BOOKED].when


def test_domain_error_context_reaches_the_client() -> None:
    r = _client_raising(_LimitReached("Ліміт — 3.", limit=3, active_bookings=3)).get("/raise")
    assert r.status_code == 409
    assert r.json()["limit"] == 3
    assert r.json()["active_bookings"] == 3


def test_unknown_domain_code_is_internal_error_without_details() -> None:
    r = _client_raising(_UnknownCode("внутрішня деталь")).get("/raise")
    assert r.status_code == 500
    assert r.json()["code"] == "INTERNAL_ERROR"
    assert "внутрішня деталь" not in r.text
    assert "_UnknownCode" not in r.text
