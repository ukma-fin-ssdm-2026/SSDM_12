"""Migration 0005 preserves data and fails closed on unsafe helper attributes."""

import pytest
from sqlalchemy import select

from api.infrastructure import tables as t
from api.infrastructure.postgres import PostgresStore
from api.stubs.store import Ids
from scripts.manage_db import migrate

pytestmark = pytest.mark.req("FR-007", "FR-032", "SEC-002", "REL-001", "REL-002")
FUNCTION = "public.booking_context(uuid,uuid,timestamptz,boolean,text)"


def test_context_function_is_invoker_volatile_and_not_publicly_executable(database):
    with database.owner.connect() as conn:
        row = (
            conn.exec_driver_sql(
                """
            SELECT provolatile, prosecdef, proparallel,
                EXISTS(SELECT 1 FROM aclexplode(COALESCE(proacl, acldefault('f', proowner)))
                    WHERE grantee = 0 AND privilege_type = 'EXECUTE') AS public_execute
            FROM pg_proc WHERE oid = to_regprocedure(%s)
        """,
                (FUNCTION,),
            )
            .mappings()
            .one()
        )
    assert dict(row) == {
        "provolatile": "v",
        "prosecdef": False,
        "proparallel": "u",
        "public_execute": False,
    }
    with database.backend.engine.connect() as conn:
        assert conn.exec_driver_sql(
            "SELECT has_function_privilege(current_user, %s, 'EXECUTE')", (FUNCTION,)
        ).scalar_one()


@pytest.mark.parametrize("unsafe", ["missing", "stable", "definer", "grant"])
def test_runtime_refuses_missing_or_unsafe_context_helper(database, unsafe):
    with database.owner.begin() as conn:
        if unsafe == "missing":
            conn.exec_driver_sql("DROP FUNCTION " + FUNCTION)
        elif unsafe == "stable":
            conn.exec_driver_sql("ALTER FUNCTION " + FUNCTION + " STABLE")
        elif unsafe == "definer":
            conn.exec_driver_sql("ALTER FUNCTION " + FUNCTION + " SECURITY DEFINER")
        else:
            role = conn.dialect.identifier_preparer.quote(database.role)
            conn.exec_driver_sql(f"REVOKE EXECUTE ON FUNCTION {FUNCTION} FROM {role}")
    with pytest.raises(ValueError, match="migration 0005"):
        PostgresStore(database.app_url)


def test_upgrade_from_0004_keeps_existing_bookings_and_can_be_repeated(database, client):
    with database.owner.begin() as conn:
        before = conn.execute(select(t.bookings).order_by(t.bookings.c.id)).all()
        conn.exec_driver_sql("DROP FUNCTION " + FUNCTION)
        conn.exec_driver_sql("UPDATE alembic_version SET version_num='0004'")
    migrate(database.owner_url, database.role)
    migrate(database.owner_url, database.role)
    with database.owner.connect() as conn:
        assert conn.execute(select(t.bookings).order_by(t.bookings.c.id)).all() == before
        assert (
            conn.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() == "0005"
        )
    response = client.post(
        "/api/v1/bookings",
        headers={"Authorization": "Bearer demo-student", "Idempotency-Key": "after-upgrade"},
        json={"slot_id": str(Ids.SLOT_NET_D4_0900)},
    )
    assert response.status_code == 201, response.text
