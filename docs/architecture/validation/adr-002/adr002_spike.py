#!/usr/bin/env python3
"""Архітектурний спайк до ADR-002 (UniSlot, Лаб 3).

Питання спайку: чи гарантують частковий унікальний індекс і блокування рядків
PostgreSQL інваріанти бронювання за одночасних запитів, і чи справді без них
виникають гонки?

Запуск (потрібен PostgreSQL 16; спайк відкриває 100 з'єднань одночасно, тому
max_connections піднято до 200):
    docker run --rm -d --name pg-spike -p 5432:5432 -e POSTGRES_PASSWORD=spike \
        postgres:16 -c max_connections=200
    pip install "psycopg[binary]>=3.2"
    SPIKE_DSN="postgresql://postgres:spike@localhost:5432/postgres" python3 adr002_spike.py
Менше навантаження: SPIKE_CONCURRENCY=50 SPIKE_RUNS=5 (типово 100 і 20).

Код спайку та журнали зберігаються разом у docs/architecture/validation/adr-002/.
"""

import os
import json
from pathlib import Path
import threading
import time
import uuid

import psycopg
from psycopg import errors

DSN = os.environ.get("SPIKE_DSN", "host=/tmp port=55432 user=postgres dbname=postgres")
N = int(os.environ.get("SPIKE_CONCURRENCY", "100"))
RUNS = int(os.environ.get("SPIKE_RUNS", "20"))
REPORT = {"concurrency": N, "runs": RUNS, "results": {}}

SCHEMA = """
DROP SCHEMA IF EXISTS spike CASCADE;
CREATE SCHEMA spike;
SET search_path TO spike, public;
CREATE EXTENSION IF NOT EXISTS btree_gist SCHEMA public;
CREATE TABLE app_user (id uuid PRIMARY KEY, email text NOT NULL);
CREATE UNIQUE INDEX uq_app_user_email ON app_user (lower(email));
CREATE TABLE resource (id uuid PRIMARY KEY, name text NOT NULL);
CREATE TABLE slot (
  id uuid PRIMARY KEY,
  resource_id uuid NOT NULL REFERENCES resource(id),
  starts_at timestamptz NOT NULL,
  ends_at timestamptz NOT NULL CHECK (ends_at > starts_at),
  CONSTRAINT ex_slot_no_overlap EXCLUDE USING gist
    (resource_id WITH =, tstzrange(starts_at, ends_at, '[)') WITH &&)
);
CREATE TYPE booking_status AS ENUM ('confirmed', 'cancelled');
CREATE TABLE booking (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slot_id uuid NOT NULL REFERENCES slot(id),
  student_id uuid NOT NULL REFERENCES app_user(id),
  status booking_status NOT NULL DEFAULT 'confirmed'
);
CREATE UNIQUE INDEX uq_booking_slot_confirmed ON booking (slot_id) WHERE status = 'confirmed';
-- Контрольна таблиця БЕЗ часткового індексу: показує гонку check-then-act.
CREATE TABLE booking_naive (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slot_id uuid NOT NULL,
  student_id uuid NOT NULL,
  status booking_status NOT NULL DEFAULT 'confirmed'
);
CREATE TABLE time_block (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  resource_id uuid NOT NULL,
  starts_at timestamptz NOT NULL,
  ends_at timestamptz NOT NULL,
  reason text NOT NULL CHECK (length(reason) > 0)
);
CREATE TABLE audit_log (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  occurred_at timestamptz NOT NULL DEFAULT now(),
  actor_id uuid,
  action text NOT NULL
);
CREATE FUNCTION forbid_audit_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'audit_log is append-only'; END $$;
CREATE TRIGGER trg_audit_append_only BEFORE UPDATE OR DELETE ON audit_log
  FOR EACH ROW EXECUTE FUNCTION forbid_audit_change();
"""


def connect():
    conn = psycopg.connect(DSN, autocommit=False, connect_timeout=10)
    conn.execute("SET search_path TO spike, public")
    conn.execute("SET statement_timeout = '20s'")
    conn.execute("SET lock_timeout = '15s'")
    conn.commit()
    return conn


def setup():
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute(SCHEMA)
        c.execute("DROP ROLE IF EXISTS spike_app")
        c.execute("CREATE ROLE spike_app LOGIN")
        c.execute("GRANT USAGE ON SCHEMA spike TO spike_app")
        c.execute("GRANT SELECT, INSERT ON spike.audit_log TO spike_app")


def make_slot(c, resource_id, start_hour):
    sid = uuid.uuid4()
    c.execute(
        "INSERT INTO slot VALUES (%s, %s, %s::timestamptz, %s::timestamptz)",
        (sid, resource_id, f"2026-10-20 {start_hour:02d}:00+00", f"2026-10-20 {start_hour:02d}:30+00"),
    )
    return sid


def make_students(c, n):
    ids = [uuid.uuid4() for _ in range(n)]
    for i in ids:
        c.execute("INSERT INTO app_user VALUES (%s, %s)", (i, f"{i}@example.edu"))
    return ids


def run_concurrently(worker, args_list, connections=None):
    """Запускає worker(args) у потоках, стартуючи всіх одночасно через бар'єр."""
    barrier = threading.Barrier(len(args_list))
    results = [None] * len(args_list)
    conns = connections if connections is not None else [connect() for _ in args_list]
    failures = [None] * len(args_list)

    def target(i):
        try:
            barrier.wait(timeout=30)
            results[i] = worker(conns[i], *args_list[i])
        except BaseException as exc:
            failures[i] = exc

    threads = [threading.Thread(target=target, args=(i,)) for i in range(len(args_list))]
    for t in threads:
        t.start()
    deadline = time.monotonic() + 35
    for t in threads:
        t.join(max(0, deadline - time.monotonic()))
    if connections is None:
        for c in conns:
            c.close()
    assert not any(t.is_alive() for t in threads), "worker did not finish"
    for failure in failures:
        if failure is not None:
            raise RuntimeError("concurrent worker failed") from failure
    assert all(r in ("201", "409") for r in results), results
    return results


def book_with_locks(conn, slot_id, student_id):
    """Алгоритм ADR-002: рядок студента → рядок слота → перевірка → INSERT."""
    try:
        with conn.transaction():
            conn.execute("SELECT 1 FROM app_user WHERE id = %s FOR UPDATE", (student_id,))
            conn.execute("SELECT 1 FROM slot WHERE id = %s FOR UPDATE", (slot_id,))
            taken = conn.execute(
                "SELECT count(*) FROM booking WHERE slot_id = %s AND status = 'confirmed'",
                (slot_id,),
            ).fetchone()[0]
            if taken:
                raise LookupError("slot taken")
            conn.execute(
                "INSERT INTO booking (slot_id, student_id) VALUES (%s, %s)", (slot_id, student_id)
            )
        return "201"
    except (LookupError, errors.UniqueViolation):
        return "409"


def book_index_only(conn, slot_id, student_id):
    """Лише частковий унікальний індекс, без блокувань і перевірок."""
    try:
        with conn.transaction():
            conn.execute(
                "INSERT INTO booking (slot_id, student_id) VALUES (%s, %s)", (slot_id, student_id)
            )
        return "201"
    except errors.UniqueViolation:
        return "409"


def book_naive(conn, slot_id, student_id):
    """Check-then-act без індексу й без блокувань — так робити НЕ можна."""
    with conn.transaction():
        taken = conn.execute(
            "SELECT count(*) FROM booking_naive WHERE slot_id = %s AND status = 'confirmed'",
            (slot_id,),
        ).fetchone()[0]
        if taken:
            return "409"
        time.sleep(0.005)  # реалістична затримка між перевіркою й записом
        conn.execute(
            "INSERT INTO booking_naive (slot_id, student_id) VALUES (%s, %s)", (slot_id, student_id)
        )
    return "201"


def concurrency_test(name, worker, use_naive=False):
    outcomes = []
    with connect() as c:
        rid = uuid.uuid4()
        c.execute("INSERT INTO resource VALUES (%s, 'spike')", (rid,))
        students = make_students(c, N)
        c.commit()
    assert 1 <= RUNS <= 24 and N >= 2
    connections = [connect() for _ in students]
    try:
        for run in range(RUNS):
            with connect() as c:
                slot_id = make_slot(c, rid, run)
                c.commit()
            results = run_concurrently(worker, [(slot_id, s) for s in students], connections)
            with connect() as c:
                table = "booking_naive" if use_naive else "booking"
                rows = c.execute(
                    f"SELECT count(*) FROM {table} WHERE slot_id = %s AND status = 'confirmed'", (slot_id,)
                ).fetchone()[0]
            outcomes.append((results.count("201"), results.count("409"), rows))
            if (run + 1) % 5 == 0:
                print(f"[progress] {name}: {run + 1}/{RUNS}", flush=True)
    finally:
        for c in connections:
            c.close()
    ok = all(o[0] == 1 and o[1] == N - 1 and o[2] == 1 for o in outcomes)
    worst = max(o[2] for o in outcomes)
    print(f"[{'PASS' if ok else 'RACE'}] {name}: {RUNS} прогонів по {N} запитів; "
          f"успіхів за прогін: {sorted({o[0] for o in outcomes})}; "
          f"максимум чинних бронювань на слот: {worst}")
    REPORT["results"][name] = [{"success": a, "conflict": b, "confirmed_rows": c} for a, b, c in outcomes]
    if use_naive:
        assert any(o[2] > 1 for o in outcomes), "negative control did not reproduce the race"
    else:
        assert ok, outcomes
    return ok


def test_exclusion():
    with connect() as c:
        rid = uuid.uuid4()
        c.execute("INSERT INTO resource VALUES (%s, 'ex')", (rid,))
        c.execute("INSERT INTO slot VALUES (%s, %s, '2026-10-21 10:00+00', '2026-10-21 11:00+00')",
                  (uuid.uuid4(), rid))
        c.commit()
        try:
            c.execute("INSERT INTO slot VALUES (%s, %s, '2026-10-21 10:30+00', '2026-10-21 11:30+00')",
                      (uuid.uuid4(), rid))
            c.commit()
            overlap = "НЕ відхилено"
        except errors.ExclusionViolation as e:
            c.rollback()
            overlap = f"відхилено, SQLSTATE {e.sqlstate}"
        assert overlap == "відхилено, SQLSTATE 23P01", overlap
        c.execute("INSERT INTO slot VALUES (%s, %s, '2026-10-21 11:00+00', '2026-10-21 12:00+00')",
                  (uuid.uuid4(), rid))
        c.commit()
    print(f"[PASS] EXCLUDE: перетин 10:30–11:30 з 10:00–11:00 — {overlap}; суміжний 11:00–12:00 — дозволено")
    REPORT["results"]["exclusion"] = {"overlap_sqlstate": "23P01", "adjacent_allowed": True}


def test_partial_unique():
    with connect() as c:
        rid = uuid.uuid4()
        c.execute("INSERT INTO resource VALUES (%s, 'pu')", (rid,))
        sid = make_slot(c, rid, 5)
        s1, s2, s3 = make_students(c, 3)
        c.execute("INSERT INTO booking (slot_id, student_id) VALUES (%s, %s)", (sid, s1))
        c.commit()
        try:
            c.execute("INSERT INTO booking (slot_id, student_id) VALUES (%s, %s)", (sid, s2))
            c.commit()
            second = "НЕ відхилено"
        except errors.UniqueViolation as e:
            c.rollback()
            second = f"відхилено, SQLSTATE {e.sqlstate}"
        assert second == "відхилено, SQLSTATE 23505", second
        c.execute("UPDATE booking SET status = 'cancelled' WHERE slot_id = %s", (sid,))
        c.execute("INSERT INTO booking (slot_id, student_id) VALUES (%s, %s)", (sid, s3))
        c.commit()
        assert c.execute("SELECT count(*) FROM booking WHERE slot_id=%s AND status='confirmed'", (sid,)).fetchone()[0] == 1
    print(f"[PASS] Частковий індекс: друге чинне бронювання — {second}; після скасування першого — дозволено")
    REPORT["results"]["partial_unique"] = {"duplicate_sqlstate": "23505", "rebooking_after_cancel": True}


def test_block_race(with_locks):
    """Бронювання й блокування того самого слота перетинаються в часі."""
    setup_c = connect()
    rid = uuid.uuid4()
    setup_c.execute("INSERT INTO resource VALUES (%s, 'block')", (rid,))
    sid = make_slot(setup_c, rid, 9 if with_locks else 8)
    (student,) = make_students(setup_c, 1)
    setup_c.commit()
    a, b = connect(), connect()  # a — бронювання, b — блокування

    # A: починає бронювання і перевіряє, що блокувань немає.
    if with_locks:
        a.execute("SELECT 1 FROM slot WHERE id = %s FOR UPDATE", (sid,))
    blocks = a.execute(
        "SELECT count(*) FROM time_block t JOIN slot s ON s.resource_id = t.resource_id "
        "WHERE s.id = %s AND tstzrange(t.starts_at, t.ends_at, '[)') && tstzrange(s.starts_at, s.ends_at, '[)')",
        (sid,),
    ).fetchone()[0]
    assert blocks == 0

    # B: блокує проміжок у паралельному потоці (з блокуваннями — чекає на A).
    finished = threading.Event()
    block_failures = []

    def block_tx():
        try:
            if with_locks:
                b.execute("SELECT 1 FROM slot WHERE resource_id = %s ORDER BY starts_at, id FOR UPDATE", (rid,))
            b.execute("INSERT INTO time_block (resource_id, starts_at, ends_at, reason) "
                      "VALUES (%s, '2026-10-20 00:00+00', '2026-10-21 00:00+00', 'spike')", (rid,))
            b.execute("UPDATE booking SET status = 'cancelled' WHERE slot_id IN "
                      "(SELECT id FROM slot WHERE resource_id = %s) AND status = 'confirmed'", (rid,))
            b.commit()
        except BaseException as exc:
            block_failures.append(exc)
            b.rollback()
        finally:
            finished.set()

    t = threading.Thread(target=block_tx)
    t.start()
    if with_locks:
        waiting = False
        deadline = time.monotonic() + 10
        with connect() as monitor:
            while time.monotonic() < deadline and not finished.is_set():
                waiting = bool(monitor.execute("SELECT pg_blocking_pids(%s)", (b.info.backend_pid,)).fetchone()[0])
                if waiting:
                    break
                time.sleep(0.01)
        assert waiting, "blocking transaction never waited on the slot lock"
    else:
        assert finished.wait(10), "control blocking transaction did not finish"
    assert not block_failures, block_failures
    a.execute("INSERT INTO booking (slot_id, student_id) VALUES (%s, %s)", (sid, student))
    a.commit()
    t.join(20)
    assert not t.is_alive() and not block_failures, block_failures

    with connect() as c:
        survivors = c.execute(
            "SELECT count(*) FROM booking WHERE slot_id = %s AND status = 'confirmed'", (sid,)
        ).fetchone()[0]
    a.close(); b.close(); setup_c.close()
    label = "з блокуванням рядків" if with_locks else "без блокування рядків"
    verdict = "PASS" if survivors == 0 else "RACE"
    print(f"[{verdict}] Блокування часу vs бронювання ({label}): чинних бронювань у заблокованому проміжку — {survivors}")
    assert survivors == (0 if with_locks else 1), survivors
    REPORT["results"][f"block_race_{with_locks}"] = {"surviving_confirmed": survivors}
    return survivors == 0


def test_audit_append_only():
    with psycopg.connect(DSN, autocommit=True) as app:
        app.execute("SET search_path TO spike")
        # Права ролі застосунку без окремого входу й пароля: працює з будь-яким DSN.
        app.execute("SET ROLE spike_app")
        app.execute("INSERT INTO audit_log (action) VALUES ('resource.create')")
        try:
            app.execute("UPDATE audit_log SET action = 'x'")
            app_update = "дозволено"
        except errors.InsufficientPrivilege as e:
            app_update = f"заборонено правами, SQLSTATE {e.sqlstate}"
    with psycopg.connect(DSN, autocommit=True) as owner:
        owner.execute("SET search_path TO spike")
        try:
            owner.execute("DELETE FROM audit_log")
            owner_delete = "дозволено"
        except errors.RaiseException as e:
            owner_delete = f"заборонено тригером, SQLSTATE {e.sqlstate}"
    ok = app_update.startswith("заборонено") and owner_delete.startswith("заборонено")
    print(f"[{'PASS' if ok else 'FAIL'}] audit_log: UPDATE роллю застосунку — {app_update}; "
          f"DELETE власником — {owner_delete}")
    assert ok, (app_update, owner_delete)
    REPORT["results"]["audit_append_only"] = {"app_update_sqlstate": "42501", "owner_delete_sqlstate": "P0001"}


if __name__ == "__main__":
    setup()
    with psycopg.connect(DSN) as c:
        REPORT["server_version"] = c.execute('show server_version').fetchone()[0]
    print(f"PostgreSQL: {REPORT['server_version']}")
    test_exclusion()
    test_partial_unique()
    concurrency_test("ADR-002: блокування рядків + перевірка + частковий індекс", book_with_locks)
    concurrency_test("Лише частковий унікальний індекс", book_index_only)
    concurrency_test("Контроль: check-then-act без індексу й блокувань", book_naive, use_naive=True)
    test_block_race(with_locks=False)
    test_block_race(with_locks=True)
    test_audit_append_only()
    REPORT["passed"] = True
    if os.environ.get("SPIKE_REPORT"):
        Path(os.environ["SPIKE_REPORT"]).write_text(json.dumps(REPORT, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("[PASS] Усі твердження спайку перевірено; помилок потоків немає.")
