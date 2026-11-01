"""Справжня PostgreSQL: паролі, сесії, транзакції та стійкий throttle."""
# ruff: noqa: S105 -- these are isolated test credentials, never real passwords.

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from api import clock
from api.config import get_settings
from api.enums import Role
from api.infrastructure import tables as t
from api.infrastructure.postgres import PostgresStore
from api.main import app
from api.services.auth_service import SESSION_COOKIE, bootstrap_admin, token_digest
from api.stubs.store import Ids, store

pytestmark = pytest.mark.req(
    "FR-001", "FR-003", "FR-004", "FR-005", "FR-006", "FR-007", "SEC-001", "SEC-002"
)
PASSWORD = "isolated integration password phrase"  # pragma: allowlist secret -- isolated example/test input
WRONG_PASSWORD = (
    "deliberately incorrect test phrase"  # pragma: allowlist secret -- negative test fixture
)
EMAIL = "integration@example.com"


@pytest.fixture
def web(database, monkeypatch):
    monkeypatch.setenv("UNISLOT_DEMO_AUTH", "0")
    get_settings.cache_clear()
    try:
        yield TestClient(app, base_url="https://testserver")
    finally:
        get_settings.cache_clear()


def register(web, email=EMAIL):
    return web.post(
        "/api/v1/auth/register",
        json={"full_name": "Demo Student", "email": email, "password": PASSWORD},
    )


def login(web, password=PASSWORD, email=EMAIL):
    return web.post("/api/v1/auth/login", json={"email": email, "password": password})


def test_password_and_session_survive_reopening_database(database, web):
    response = register(web)
    assert response.status_code == 201, response.text
    uid = uuid.UUID(response.json()["id"])
    signed = login(web)
    assert signed.status_code == 200, signed.text
    token = web.cookies.get(SESSION_COOKIE)
    with database.owner.connect() as conn:
        row = conn.execute(select(t.users).where(t.users.c.id == uid)).mappings().one()
        assert row["password_hash"].startswith("$argon2id$")
        assert PASSWORD not in row["password_hash"]
        session = conn.execute(select(t.sessions)).mappings().one()
        assert session["id"].version == 4
        assert len(session["token_hash"]) == 32
        assert bytes(session["token_hash"]).hex() == token_digest(token)
    previous = store.set_backend(PostgresStore(database.app_url))
    try:
        assert web.get("/api/v1/auth/me").json()["id"] == str(uid)
        assert (
            web.post(
                "/api/v1/auth/logout", headers={"X-CSRF-Token": signed.json()["csrf_token"]}
            ).status_code
            == 204
        )
        assert login(web).status_code == 200
    finally:
        store.set_backend(previous).close()


def test_failed_login_commits_user_counter_and_unknown_account_counter(database, web):
    assert register(web).status_code == 201
    for email in [EMAIL, "unknown@example.com"]:
        for _ in range(5):
            response = login(
                web, password=WRONG_PASSWORD, email=email
            )  # pragma: allowlist secret -- isolated example/test input
        assert response.status_code == 429, response.text
    with database.owner.connect() as conn:
        row = conn.execute(select(t.users).where(t.users.c.email == EMAIL)).mappings().one()
        assert row["failed_login_count"] == 5 and row["locked_until"] is not None
        assert row["last_failed_login_at"] == clock.utc_now()
        unknown = conn.execute(select(t.login_attempts)).mappings().one()
        assert unknown["key"] == token_digest("unknown@example.com")
        assert unknown["failures"] == 5
    previous = store.set_backend(PostgresStore(database.app_url))
    try:
        assert login(web).status_code == 429
    finally:
        store.set_backend(previous).close()


def test_registration_is_atomic_when_database_rejects_credentials(database, web):
    with database.owner.begin() as conn:
        conn.exec_driver_sql("""CREATE FUNCTION fail_signup() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'test credentials failure'; END $$;
            CREATE TRIGGER fail_signup BEFORE INSERT ON app_user
            FOR EACH ROW EXECUTE FUNCTION fail_signup();""")
    response = register(web)
    assert response.status_code == 503, response.text
    with store.lock:
        assert not any(u.email == EMAIL for u in store.users.values())
    assert "test credentials failure" not in response.text


def test_failed_session_insert_does_not_revoke_old_session_or_set_new_cookie(database, web):
    assert register(web).status_code == 201
    assert login(web).status_code == 200
    old = web.cookies.get(SESSION_COOKIE)
    with database.owner.begin() as conn:
        conn.exec_driver_sql("""CREATE FUNCTION fail_session() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'test session failure'; END $$;
            CREATE TRIGGER fail_session BEFORE INSERT ON session
            FOR EACH ROW EXECUTE FUNCTION fail_session();""")
    response = login(web)
    assert response.status_code == 503, response.text
    assert "set-cookie" not in response.headers
    assert web.cookies.get(SESSION_COOKIE) == old
    assert web.get("/api/v1/auth/me").status_code == 200
    with store.lock:
        assert len(store.sessions) == 1


def test_parallel_case_variant_registration_creates_one_account(database, web):
    def attempt(number):
        connection = TestClient(app, base_url="https://testserver")
        return register(connection, EMAIL.upper() if number % 2 else EMAIL).status_code

    with ThreadPoolExecutor(max_workers=4) as pool:
        codes = list(pool.map(attempt, range(8)))
    assert sorted(codes) == [201] + [409] * 7


def test_role_revocation_and_account_disable_affect_existing_session(database, web):
    uid = uuid.UUID(register(web).json()["id"])
    assert login(web).status_code == 200
    with store.lock:
        store.users[uid].roles = frozenset({Role.STUDENT, Role.ADMIN})
    assert web.get("/api/v1/admin/policies/current").status_code == 200
    with store.lock:
        store.users[uid].roles = frozenset({Role.STUDENT})
    assert web.get("/api/v1/admin/policies/current").status_code == 403
    with store.lock:
        store.users[uid].is_active = False
    assert web.get("/api/v1/auth/me").status_code == 401


def test_bootstrap_admin_is_one_time_and_keeps_last_admin_guard(database, web):
    user = bootstrap_admin("Initial Administrator", "admin@example.com", PASSWORD, clock.utc_now())
    assert user.id == Ids.ADMIN
    assert login(web, email="admin@example.com").status_code == 200
    with pytest.raises(ValueError, match="already initialized"):
        bootstrap_admin("Replacement", "replacement@example.com", PASSWORD, clock.utc_now())
    assert web.get("/api/v1/admin/policies/current").status_code == 200
