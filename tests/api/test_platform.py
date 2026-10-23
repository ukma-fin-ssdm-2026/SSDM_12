"""Наскрізна поведінка API: автентифікація, заголовки, формат помилок (Лаб 4)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict

from api.config import API_VERSION, get_settings
from api.main import create_app

STUDENT = {"Authorization": "Bearer demo-student"}


def test_health_is_public(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "version": API_VERSION}


def test_me_returns_current_user_and_roles(client: TestClient) -> None:
    r = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer demo-admin"})
    assert r.status_code == 200
    assert r.json()["roles"] == ["admin"]
    assert r.json()["full_name"] == "Марія Ткаченко"


def test_missing_token_gives_401_problem(client: TestClient) -> None:
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401
    assert r.headers["content-type"] == "application/problem+json"
    assert r.headers["WWW-Authenticate"].startswith("Bearer")
    body = r.json()
    assert body["code"] == "AUTH_REQUIRED" and body["status"] == 401
    assert body["type"].endswith("errors.html#auth-required")
    assert body["request_id"] == r.headers["X-Request-ID"]


def test_unknown_token_gives_401(client: TestClient) -> None:
    r = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not-a-demo-token"})
    assert r.status_code == 401


def test_demo_auth_can_be_switched_off(monkeypatch, client: TestClient) -> None:
    monkeypatch.setenv("UNISLOT_DEMO_AUTH", "0")
    get_settings.cache_clear()
    try:
        assert client.get("/api/v1/auth/me", headers=STUDENT).status_code == 401
    finally:
        get_settings.cache_clear()


def test_demo_auth_is_off_unless_enabled(monkeypatch, client: TestClient) -> None:
    """V-01 (docs/code-quality/static-analysis.md): безпечне значення за замовчуванням.

    Без змінної UNISLOT_DEMO_AUTH сервер не приймає демо-токени, зокрема `demo-admin`,
    який відкрито описаний у README й OpenAPI. До виправлення цей запит давав 200.
    """
    monkeypatch.delenv("UNISLOT_DEMO_AUTH", raising=False)
    get_settings.cache_clear()
    try:
        r = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer demo-admin"})
        assert r.status_code == 401
        assert r.json()["code"] == "AUTH_REQUIRED"
    finally:
        get_settings.cache_clear()


def test_request_id_is_echoed_or_replaced(client: TestClient) -> None:
    assert (
        client.get("/health", headers={"X-Request-ID": "trace-12345678"}).headers["X-Request-ID"]
        == "trace-12345678"
    )
    replaced = client.get("/health", headers={"X-Request-ID": "bad id\nwith newline"})
    assert replaced.headers["X-Request-ID"] != "bad id\nwith newline"


def test_version_and_cache_headers(client: TestClient) -> None:
    r = client.get("/api/v1/auth/me", headers=STUDENT)
    assert r.headers["API-Version"] == API_VERSION
    assert r.headers["Cache-Control"] == "no-store"


def test_unknown_route_and_method_use_problem_json(client: TestClient) -> None:
    missing = client.get("/api/v1/nothing-here", headers=STUDENT)
    assert missing.status_code == 404 and missing.json()["code"] == "NOT_FOUND"
    wrong_method = client.delete("/api/v1/auth/me", headers=STUDENT)
    assert wrong_method.status_code == 405
    assert wrong_method.json()["code"] == "METHOD_NOT_ALLOWED"
    assert "GET" in wrong_method.headers["Allow"]


class _Login(BaseModel):
    """Тіло тестового маршруту: обов'язкове поле й заборона зайвих полів, як у схемах API."""

    model_config = ConfigDict(extra="forbid")
    email: str


def test_validation_error_does_not_echo_input() -> None:
    """CWE-209: значення з тіла запиту не повертаються у відповіді (див. review-report.md).

    Окремий маршрут у тестовому застосунку: обробник помилок спільний для всіх роутерів,
    тож тест не залежить від того, які модулі вже злито.
    """
    app = create_app()

    @app.post("/echo-check")
    def echo_check(body: _Login) -> None:
        return None

    sent_value = "my-very-secret-password-123"
    r = TestClient(app).post("/echo-check", json={"password": sent_value})
    assert r.status_code == 422
    assert sent_value not in r.text
    fields = {e["field"] for e in r.json()["errors"]}
    assert fields == {"body.email", "body.password"}


def test_unhandled_error_hides_details() -> None:
    app = create_app()

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("database password is hunter2")

    r = TestClient(app, raise_server_exceptions=False).get("/boom")
    assert r.status_code == 500
    assert r.json()["code"] == "INTERNAL_ERROR"
    assert "hunter2" not in r.text and "RuntimeError" not in r.text
