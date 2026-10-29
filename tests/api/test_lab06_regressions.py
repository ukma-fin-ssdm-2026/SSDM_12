"""Регресія Лаб6: неправильна структура курсора повертає клієнтську помилку.

Підготовлено з допомогою Codex; відтворено через маршрут API та виправлено локально.
"""

import base64
import json

import pytest

pytestmark = pytest.mark.req("FR-020", "QA-06")


def test_non_string_cursor_uuid_returns_422(client):
    payload = {"s": "2026-10-20T09:00:00Z", "i": 7}
    cursor = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    result = client.get(
        "/api/v1/slots",
        params={"cursor": cursor},
        headers={"Authorization": "Bearer demo-student"},
    )
    assert result.status_code == 422
    assert result.json()["code"] == "VALIDATION_FAILED"
    assert result.json()["errors"][0]["field"] == "query.cursor"
