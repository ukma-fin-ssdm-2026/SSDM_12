"""US-010 та загрози THR-01/02/13: справжні паролі й cookie, demo-* вимкнено."""
# ruff: noqa: S105 -- passwords in this file are isolated test fixtures, never live credentials.

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from api import clock
from api.config import get_settings
from api.enums import Role
from api.infrastructure.passwords import hasher
from api.main import app
from api.services.auth_service import CSRF_COOKIE, SESSION_COOKIE, token_digest
from api.stubs.store import Ids, store

pytestmark = pytest.mark.req(
    "US-010", "FR-001", "FR-002", "FR-003", "FR-004", "FR-005", "FR-006", "SEC-001", "SEC-002"
)
PASSWORD = (
    "correct demo password with spaces"  # pragma: allowlist secret -- isolated example/test input
)
WRONG_PASSWORD = (
    "deliberately incorrect test phrase"  # pragma: allowlist secret -- negative test fixture
)
SHORT_PASSWORD = "short dummy"  # pragma: allowlist secret -- invalid-length test fixture
EMAIL = "auth-student@example.com"


@pytest.fixture
def web(monkeypatch):
    monkeypatch.setenv("UNISLOT_DEMO_AUTH", "0")
    get_settings.cache_clear()
    try:
        yield TestClient(app, base_url="https://testserver")
    finally:
        get_settings.cache_clear()


def register(web, **extra):
    return web.post(
        "/api/v1/auth/register",
        json={"full_name": "Тестовий студент", "email": EMAIL, "password": PASSWORD, **extra},
    )


def login(web, **extra):
    return web.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD, **extra})


@pytest.mark.parametrize(
    "extra",
    [
        {},
        {"role": "admin"},
        {"roles": ["admin", "provider"]},
        {"role": {"nested": "admin"}, "is_admin": True},
    ],
)
def test_registration_never_accepts_privileges_from_client(web, extra):
    response = register(web, **extra)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["roles"] == ["student"]
    assert set(body) == {"id", "full_name", "email", "roles"}
    uid = uuid.UUID(body["id"])
    encoded = store.credentials[uid].password_hash
    assert encoded.startswith("$argon2id$v=19$m=65536,t=3,p=4$")
    assert PASSWORD not in encoded
    assert hasher.verify(encoded, PASSWORD)
    assert login(web).status_code == 200


def test_email_uniqueness_ignores_case_and_spaces(web):
    assert register(web).status_code == 201
    before = len(store.users)
    response = register(web, email="  AUTH-STUDENT@EXAMPLE.COM  ")
    assert response.status_code == 409
    assert response.json()["code"] == "EMAIL_ALREADY_REGISTERED"
    assert len(store.users) == before
    assert login(web, email="AUTH-STUDENT@EXAMPLE.COM").status_code == 200


@pytest.mark.parametrize("password", ["a" * 14, "a" * 1025, ""])
def test_invalid_password_length_creates_no_account_or_secret_echo(web, password):
    before = len(store.users)
    response = register(web, password=password)
    assert response.status_code == 422, response.text
    assert len(store.users) == before
    assert response.json()["errors"][0]["field"] == "body.password"
    assert "input" not in response.json()["errors"][0]


@pytest.mark.parametrize(
    "password", ["a" * 15, "я" * 64 + " first ending", "a" * 1024, "  spaced password here  "]
)
def test_full_password_is_preserved_without_72_byte_truncation(web, password):
    assert register(web, password=password).status_code == 201
    assert login(web, password=password).status_code == 200
    assert login(web, password=password[:-1] + "X").status_code == 401


@pytest.mark.parametrize(
    "change", [{"full_name": "  "}, {"email": "invalid"}, {"full_name": "a" * 161}]
)
def test_invalid_registration_is_rejected_before_storage(web, change):
    before = len(store.users)
    assert register(web, **change).status_code == 422
    assert len(store.users) == before


def test_login_error_does_not_disclose_account_existence(web):
    register(web)
    wrong = login(web, password=WRONG_PASSWORD)
    absent = login(web, email="absent@example.com", password=WRONG_PASSWORD)
    assert wrong.status_code == absent.status_code == 401

    def sanitize(response):
        return {k: v for k, v in response.json().items() if k != "request_id"}

    assert sanitize(wrong) == sanitize(absent)
    assert EMAIL not in wrong.text
    assert "wrong password" not in wrong.text


def test_cookie_session_works_with_demo_disabled_and_only_digests_are_stored(web):
    uid = register(web).json()["id"]
    response = login(web)
    assert response.status_code == 200
    token = web.cookies.get(SESSION_COOKIE)
    csrf = response.json()["csrf_token"]
    session = store.sessions[token_digest(token)]
    assert token not in repr(session)
    assert csrf not in repr(session)
    assert token not in response.text
    assert session.csrf_hash == token_digest(csrf)
    cookies = response.headers.get_list("set-cookie")
    assert len(cookies) == 2
    session_header = next(c.lower() for c in cookies if c.startswith(SESSION_COOKIE))
    assert all(flag in session_header for flag in ["httponly", "secure", "samesite=lax", "path=/"])
    assert "domain=" not in session_header
    assert web.get("/api/v1/auth/me").json()["id"] == uid
    assert (
        web.post(
            "/api/v1/bookings",
            json={"slot_id": str(Ids.SLOT_NET_D4_0900)},
            headers={"X-CSRF-Token": csrf},
        ).status_code
        == 201
    )


def test_csrf_is_bound_to_session_and_missing_or_wrong_header_cannot_book(web):
    register(web)
    csrf = login(web).json()["csrf_token"]
    before = len(store.bookings)
    for token in [None, "x" * 43, b"\xe9" * 43]:
        headers = {"X-CSRF-Token": token} if token else {}
        response = web.post(
            "/api/v1/bookings", json={"slot_id": str(Ids.SLOT_NET_D4_0900)}, headers=headers
        )
        assert response.status_code == 403
        assert response.json()["code"] == "CSRF_FAILED"
    assert len(store.bookings) == before
    assert web.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 204


def test_successful_logout_revokes_server_token_and_preserves_other_device(web):
    register(web)
    first = login(web)
    first_token = web.cookies.get(SESSION_COOKIE)
    other = TestClient(app, base_url="https://testserver")
    assert login(other).status_code == 200
    response = web.post("/api/v1/auth/logout", headers={"X-CSRF-Token": first.json()["csrf_token"]})
    assert response.status_code == 204
    assert token_digest(first_token) not in store.sessions
    assert SESSION_COOKIE not in web.cookies and CSRF_COOKIE not in web.cookies
    web.cookies.set(SESSION_COOKIE, first_token)
    assert web.get("/api/v1/auth/me").status_code == 401
    assert other.get("/api/v1/auth/me").status_code == 200


def test_relogin_rotates_session_and_csrf_token(web):
    register(web)
    old_csrf = login(web).json()["csrf_token"]
    old_token = web.cookies.get(SESSION_COOKIE)
    new_csrf = login(web).json()["csrf_token"]
    assert web.cookies.get(SESSION_COOKIE) != old_token
    assert old_csrf != new_csrf
    assert token_digest(old_token) not in store.sessions
    assert len(store.sessions) == 1
    assert web.post("/api/v1/auth/logout", headers={"X-CSRF-Token": old_csrf}).status_code == 403


def test_session_expiry_is_enforced_at_exact_boundary(web, monkeypatch):
    register(web)
    login(web)
    expires = next(iter(store.sessions.values())).expires_at
    monkeypatch.setattr(clock, "utc_now", lambda: expires - timedelta(microseconds=1))
    assert web.get("/api/v1/auth/me").status_code == 200
    monkeypatch.setattr(clock, "utc_now", lambda: expires)
    assert web.get("/api/v1/auth/me").status_code == 401


def test_cookie_does_not_fall_back_to_demo_admin_on_invalid_session(web, monkeypatch):
    monkeypatch.setenv("UNISLOT_DEMO_AUTH", "1")
    get_settings.cache_clear()
    web.cookies.set(SESSION_COOKIE, "x" * 43)
    assert (
        web.get("/api/v1/auth/me", headers={"Authorization": "Bearer demo-admin"}).status_code
        == 401
    )


def test_roles_are_read_again_without_relogging_in(web):
    uid = uuid.UUID(register(web).json()["id"])
    csrf = login(web).json()["csrf_token"]
    assert web.get("/api/v1/admin/policies/current").status_code == 403
    store.users[uid].roles = frozenset({Role.STUDENT, Role.ADMIN})
    assert web.get("/api/v1/admin/policies/current").status_code == 200
    store.users[uid].roles = frozenset({Role.STUDENT})
    assert (
        web.put(
            "/api/v1/admin/policies/current",
            headers={"X-CSRF-Token": csrf},
            json={"booking_limit": 3, "cancel_window_minutes": 120},
        ).status_code
        == 403
    )


@pytest.mark.parametrize(
    "origin", ["https://evil.example", "https://testserver.evil.example", "null"]
)
def test_foreign_origin_cannot_login_register_or_mutate_session(web, origin):
    assert register(web).status_code == 201
    body = {"email": EMAIL, "password": PASSWORD}
    assert web.post("/api/v1/auth/login", json=body, headers={"Origin": origin}).status_code == 403
    assert (
        web.post(
            "/api/v1/auth/register", json={"full_name": "Demo", **body}, headers={"Origin": origin}
        ).status_code
        == 403
    )
    csrf = login(web).json()["csrf_token"]
    assert (
        web.post(
            "/api/v1/auth/logout", headers={"Origin": origin, "X-CSRF-Token": csrf}
        ).status_code
        == 403
    )


def test_throttle_applies_equally_to_known_and_unknown_and_does_not_extend(web, monkeypatch):
    register(web)
    now = clock.utc_now()
    for address in [EMAIL, "unknown@example.com"]:
        statuses = [
            login(web, email=address, password=WRONG_PASSWORD).status_code
            for _ in range(5)  # pragma: allowlist secret -- negative test input
        ]  # pragma: allowlist secret -- isolated example/test input
        assert statuses == [401] * 4 + [429]
    untils = {a.blocked_until for a in store.login_attempts.values()}
    assert untils == {now + timedelta(seconds=300)}
    monkeypatch.setattr(clock, "utc_now", lambda: now + timedelta(seconds=100))
    response = login(web)
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "200"
    assert {a.blocked_until for a in store.login_attempts.values()} == untils
    monkeypatch.setattr(clock, "utc_now", lambda: now + timedelta(seconds=300))
    assert login(web).status_code == 200
    assert token_digest(EMAIL) not in store.login_attempts


def test_inactive_user_cannot_login_or_use_existing_session(web):
    uid = uuid.UUID(register(web).json()["id"])
    login(web)
    store.users[uid].is_active = False
    assert web.get("/api/v1/auth/me").status_code == 401
    assert login(web).status_code == 401


def test_login_and_validation_never_echo_password_in_access_log(web, caplog):
    register(web)
    login(web, password=WRONG_PASSWORD)  # pragma: allowlist secret -- isolated example/test input
    register(
        web, password=SHORT_PASSWORD
    )  # pragma: allowlist secret -- isolated example/test input
    assert PASSWORD not in caplog.text
    assert WRONG_PASSWORD not in caplog.text
    assert EMAIL not in caplog.text


def test_old_argon2_parameters_are_upgraded_after_successful_login(web):
    from argon2 import PasswordHasher

    uid = uuid.UUID(register(web).json()["id"])
    old = PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1).hash(PASSWORD)
    store.credentials[uid].password_hash = old
    assert login(web).status_code == 200
    updated = store.credentials[uid].password_hash
    assert updated != old
    assert hasher.check_needs_rehash(updated) is False
    assert hasher.verify(updated, PASSWORD)


def test_malformed_cookie_and_corrupt_password_hash_fail_closed(web):
    uid = uuid.UUID(register(web).json()["id"])
    store.credentials[uid].password_hash = "$argon2id$broken"
    assert login(web).status_code == 401
    web.cookies.set(SESSION_COOKIE, "malformed")
    assert web.get("/api/v1/auth/me").status_code == 401


def test_csrf_token_from_another_session_is_rejected(web):
    register(web)
    token = login(web).json()["csrf_token"]
    other = TestClient(app, base_url="https://testserver")
    assert login(other).status_code == 200
    assert other.post("/api/v1/auth/logout", headers={"X-CSRF-Token": token}).status_code == 403


def test_public_login_rejects_cross_site_fetch_even_without_origin(web):
    response = web.post(
        "/api/v1/auth/login",
        json={"email": EMAIL, "password": PASSWORD},
        headers={"Sec-Fetch-Site": "cross-site"},
    )
    assert response.status_code == 403


def test_json_only_login_guard_and_allowed_cors_origin(web, monkeypatch):
    from fastapi import Request

    from api.errors import ApiProblem
    from api.security import check_public_auth_request

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "scheme": "https",
            "server": ("testserver", 443),
            "path": "/api/v1/auth/login",
            "headers": [(b"host", b"testserver"), (b"content-type", b"text/plain")],
        }
    )
    with pytest.raises(ApiProblem) as error:
        check_public_auth_request(request)
    assert error.value.code.value == "CSRF_FAILED"
    monkeypatch.setenv("UNISLOT_CORS_ORIGINS", "https://trusted-ui.example")
    get_settings.cache_clear()
    response = web.post(
        "/api/v1/auth/register",
        json={"email": EMAIL, "password": PASSWORD, "full_name": "Student"},
        headers={"Origin": "https://trusted-ui.example"},
    )
    assert response.status_code == 201, response.text


def test_local_http_requires_explicit_insecure_cookie_setting(web, monkeypatch):
    monkeypatch.setenv("UNISLOT_SESSION_COOKIE_SECURE", "0")
    get_settings.cache_clear()
    connection = TestClient(app, base_url="http://testserver")
    assert register(connection).status_code == 201
    response = login(connection)
    assert response.status_code == 200
    assert "secure" not in response.headers.get_list("set-cookie")[0].lower()
    assert connection.get("/api/v1/auth/me").status_code == 200
