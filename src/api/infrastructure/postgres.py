"""Реляційний адаптер із транзакційною межею для існуючих сценаріїв.

Поки сервіси використовують словники, одна advisory-транзакція серіалізує їх між
процесами. У БД записуються лише зміни, не весь знімок. Це консервативна межа
коректності; масштабування потребує репозиторіїв з адресними SQL-запитами.
"""

from __future__ import annotations

import copy
import threading
import uuid

from sqlalchemy import and_, create_engine, delete, update
from sqlalchemy.dialects.postgresql import insert

from api.infrastructure import codec, tables
from api.infrastructure.security import check_runtime
from api.stubs.store import StubStore

LOCK_KEY = 7120001
POOL_SIZE = 32


class DatabaseLock:
    """Зовнішній with — одна транзакція, вкладені with повторно використовують її."""

    def __init__(self, state: PostgresStore) -> None:
        """Тримання Python RLock обмежене одним потоком виконання маршруту."""
        self.state = state
        self.mutex = threading.RLock()
        self.depth = 0
        self.connection = None
        self.before = None
        self.rollback_only = False

    def __enter__(self) -> DatabaseLock:
        """Завантажує стан у зовнішній транзакції."""
        self.mutex.acquire()
        try:
            if self.depth == 0:
                self.connection = self.state.engine.connect()
                self.connection.begin()
                self.connection.exec_driver_sql("SET LOCAL lock_timeout = '5s'")
                self.connection.exec_driver_sql("SET LOCAL statement_timeout = '15s'")
                self.connection.exec_driver_sql("SELECT pg_advisory_xact_lock(%s)", (LOCK_KEY,))
                codec.load(self.connection, self.state)
                self.before = {
                    name: copy.deepcopy(getattr(self.state, name)) for name in codec.COLLECTIONS
                }
                self.rollback_only = False
            self.depth += 1
            return self
        except BaseException:
            if self.connection is not None and self.depth == 0:
                self.connection.close()
                self.connection = None
            self.mutex.release()
            raise

    def __exit__(self, exc_type, exc, traceback) -> bool:
        """Комітить дельту або відкочує весь запит."""
        self.depth -= 1
        self.rollback_only |= exc_type is not None
        try:
            if self.depth == 0:
                try:
                    if self.rollback_only:
                        if exc_type is None:
                            raise RuntimeError("transaction is marked rollback-only")
                        self.connection.rollback()
                        self._restore()
                    else:
                        self.state.flush(self.connection, self.before)
                        self.connection.commit()
                except BaseException:
                    self.connection.rollback()
                    self._restore()
                    raise
                finally:
                    self.connection.close()
                    self.connection = self.before = None
        finally:
            self.mutex.release()
        return False

    def _restore(self) -> None:
        for name, value in self.before.items():
            setattr(self.state, name, value)


class PostgresStore(StubStore):
    """Постійний адаптер; міграція й первинне наповнення не виконуються в API."""

    def __init__(self, url: str) -> None:
        """Перевіряє схему й відхиляє owner/superuser URL для робочого процесу."""
        super().__init__()
        self.engine = create_engine(
            url,
            hide_parameters=True,
            pool_pre_ping=True,
            isolation_level="READ COMMITTED",
            skip_autocommit_rollback=True,
            pool_size=POOL_SIZE,
            max_overflow=0,
            pool_timeout=5,
            connect_args={
                "connect_timeout": 5,
                "options": "-c timezone=UTC -c lock_timeout=5000 -c statement_timeout=15000",
            },
        )
        try:
            with self.engine.connect() as conn:
                check_runtime(conn)
        except BaseException:
            self.engine.dispose()
            raise
        self.lock = DatabaseLock(self)
        self.persistent = True

    def reset(self, now=None) -> None:
        """Демо-reset не може стерти постійні дані."""
        raise RuntimeError("persistent data cannot be reset through the application store")

    def close(self) -> None:
        """Звільняє пул після завершення роботи процесу."""
        self.engine.dispose()

    def resolve_session(self, token, now):
        """Адресне читання сесії й актуальних ролей без знімка всього сховища."""
        from api.infrastructure.queries import session_identity

        return session_identity(self.engine, token, now)

    def flush(self, conn, before: dict) -> None:
        """Зберігає дельту; outbox і аудит комітяться разом із дією."""
        previous = type("Snapshot", (), before)
        old, new = codec.rows(previous), codec.rows(self)
        names = (
            "users",
            "roles",
            "resources",
            "templates",
            "policies",
            "current_policy",
            "slots",
            "blocks",
            "bookings",
            "idempotency",
            "notifications",
            "sessions",
            "login_attempts",
        )
        for name in reversed(names):
            table = getattr(tables, name)
            for key in old[name].keys() - new[name].keys():
                if name == "notifications":
                    raise ValueError("outbox records cannot be erased")
                values = key if isinstance(key, tuple) else (key,)
                predicate = and_(
                    *(
                        column == value
                        for column, value in zip(table.primary_key, values, strict=True)
                    )
                )
                conn.execute(delete(table).where(predicate))
        for name in names:
            table = getattr(tables, name)
            for key, row in new[name].items():
                if row == old[name].get(key):
                    continue
                if name == "notifications" and key in old[name]:
                    if row["status"] == "cancelled":
                        conn.execute(
                            update(table)
                            .where(table.c.id == key, table.c.status.in_(["pending", "sending"]))
                            .values(status="cancelled", claim_token=None, locked_until=None)
                        )
                    continue
                statement = insert(table).values(**row)
                changed = {
                    c.name: statement.excluded[c.name]
                    for c in table.c
                    if not c.primary_key and c.name in row
                }
                if changed:
                    conn.execute(
                        statement.on_conflict_do_update(
                            index_elements=list(table.primary_key), set_=changed
                        )
                    )
                else:
                    conn.execute(
                        statement.on_conflict_do_nothing(index_elements=list(table.primary_key))
                    )
        old_audit = before["audit"]
        if self.audit[: len(old_audit)] != old_audit:
            raise ValueError("audit history cannot be rewritten")
        for entry in self.audit[len(old_audit) :]:
            entry.setdefault("id", uuid.uuid4())
            conn.execute(insert(tables.audit).values(**entry))
