"""Права окремого runtime-користувача й захист audit_log на рівні PostgreSQL."""

import re

from sqlalchemy import inspect
from sqlalchemy.engine import Connection

from api.infrastructure import tables


def install_audit_protection(conn: Connection) -> None:
    """Тригер забороняє UPDATE/DELETE/TRUNCATE навіть власнику без вимкнення тригера."""
    conn.exec_driver_sql("""
        CREATE OR REPLACE FUNCTION reject_audit_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
            RAISE EXCEPTION 'audit_log is append-only';
        END $$;
        CREATE TRIGGER audit_no_update_delete BEFORE UPDATE OR DELETE ON audit_log
            FOR EACH ROW EXECUTE FUNCTION reject_audit_mutation();
        CREATE TRIGGER audit_no_truncate BEFORE TRUNCATE ON audit_log
            FOR EACH STATEMENT EXECUTE FUNCTION reject_audit_mutation();
    """)


def grant_runtime(conn: Connection, role: str) -> None:
    """Runtime не володіє схемою, не виконує DDL і має лише INSERT/SELECT для аудиту."""
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", role):
        raise ValueError("runtime role must be a simple PostgreSQL identifier")
    name = conn.dialect.identifier_preparer.quote(role)
    conn.exec_driver_sql(f"GRANT USAGE ON SCHEMA public TO {name}")
    existing = set(inspect(conn).get_table_names())
    for table in tables.MUTABLE:
        if table.name not in existing:
            continue
        table_name = conn.dialect.identifier_preparer.quote(table.name)
        conn.exec_driver_sql(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table_name} TO {name}")
    conn.exec_driver_sql(f"GRANT SELECT, INSERT ON audit_log, notification_delivery TO {name}")
    conn.exec_driver_sql(f"GRANT USAGE, SELECT ON SEQUENCE audit_log_seq_seq TO {name}")
    conn.exec_driver_sql("REVOKE ALL ON audit_log FROM PUBLIC")


def check_runtime(conn: Connection) -> None:
    """Відмовляється запускати API з власником БД або роллю, здатною переписати аудит."""
    unsafe = conn.exec_driver_sql("""
        SELECT rolsuper OR rolcreaterole OR rolcreatedb OR
               has_table_privilege(current_user,'audit_log','UPDATE,DELETE,TRUNCATE,TRIGGER') OR
               pg_has_role(current_user, pg_get_userbyid(c.relowner), 'USAGE')
        FROM pg_roles r CROSS JOIN pg_class c
        WHERE r.rolname=current_user AND c.oid='audit_log'::regclass
    """).scalar_one()
    if unsafe:
        raise ValueError("API requires a restricted runtime role, not a database owner")
