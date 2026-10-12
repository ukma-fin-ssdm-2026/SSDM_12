"""Executable PostgreSQL checks for rescheduling constraints and transaction rollback."""

import json
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
from psycopg import errors

import adr002_spike as base

REPORT = {"results": {}}
DDL = """
DROP SCHEMA IF EXISTS spike_extra CASCADE;
CREATE SCHEMA spike_extra;
SET search_path TO spike_extra, public;
CREATE TABLE app_user (id uuid PRIMARY KEY);
CREATE TABLE resource (id uuid PRIMARY KEY);
CREATE TABLE slot (
 id uuid PRIMARY KEY, resource_id uuid NOT NULL REFERENCES resource(id),
 starts_at timestamptz NOT NULL, ends_at timestamptz NOT NULL CHECK (ends_at > starts_at),
 EXCLUDE USING gist (resource_id WITH =, tstzrange(starts_at,ends_at,'[)') WITH &&)
);
CREATE TABLE booking (
 id uuid PRIMARY KEY, slot_id uuid NOT NULL REFERENCES slot(id),
 student_id uuid NOT NULL REFERENCES app_user(id),
 status text NOT NULL CHECK (status IN ('confirmed','cancelled')),
 cancelled_at timestamptz, cancelled_by uuid REFERENCES app_user(id),
 cancellation_kind text CHECK (cancellation_kind IN ('student','provider_block','rescheduled')),
 cancellation_reason text,
 rescheduled_to_id uuid UNIQUE,
 CONSTRAINT fk_booking_successor FOREIGN KEY (rescheduled_to_id)
   REFERENCES booking(id) DEFERRABLE INITIALLY DEFERRED,
 CHECK ((rescheduled_to_id IS NOT NULL) = (cancellation_kind IS NOT DISTINCT FROM 'rescheduled')),
 CHECK ((status='confirmed' AND cancelled_at IS NULL AND cancelled_by IS NULL AND cancellation_kind IS NULL)
     OR (status='cancelled' AND cancelled_at IS NOT NULL AND cancelled_by IS NOT NULL AND cancellation_kind IS NOT NULL)),
 CHECK (cancellation_kind IS DISTINCT FROM 'provider_block' OR
        (cancellation_reason IS NOT NULL AND length(trim(cancellation_reason)) > 0))
);
CREATE UNIQUE INDEX uq_booking_slot_confirmed ON booking(slot_id) WHERE status='confirmed';
CREATE TABLE retry_marker (worker text PRIMARY KEY);
CREATE TABLE audit_uuid (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), action text NOT NULL);
CREATE FUNCTION forbid_audit_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'audit_log is append-only'; END $$;
CREATE TRIGGER trg_audit_append_only BEFORE UPDATE OR DELETE ON audit_uuid
 FOR EACH ROW EXECUTE FUNCTION forbid_audit_change();
"""


def connect():
    c = base.connect()
    c.execute("SET search_path TO spike_extra, public")
    c.commit()
    return c


def expect_state(action, expected):
    try:
        with connect() as c:
            action(c)
    except psycopg.Error as exc:
        assert exc.sqlstate == expected, (exc.sqlstate, expected)
        return exc.sqlstate
    raise AssertionError(f"expected SQLSTATE {expected}")


def fixture(n=1):
    students = [uuid.uuid4() for _ in range(n)]
    olds = [(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), student) for student in students]
    target_resource, target_slot = uuid.uuid4(), uuid.uuid4()
    start = datetime(2026, 10, 22, 10, tzinfo=timezone.utc)
    with connect() as c:
        for booking, resource, slot, student in olds:
            c.execute("INSERT INTO app_user VALUES (%s)", (student,))
            c.execute("INSERT INTO resource VALUES (%s)", (resource,))
            c.execute("INSERT INTO slot VALUES (%s,%s,%s,%s)", (slot,resource,start,start+timedelta(minutes=30)))
            c.execute("INSERT INTO booking(id,slot_id,student_id,status) VALUES (%s,%s,%s,'confirmed')", (booking,slot,student))
        c.execute("INSERT INTO resource VALUES (%s)", (target_resource,))
        c.execute("INSERT INTO slot VALUES (%s,%s,%s,%s)", (target_slot,target_resource,start+timedelta(hours=1),start+timedelta(hours=1,minutes=30)))
    return olds, target_slot


def move(c, old_id, target_slot, student):
    try:
        with c.transaction():
            c.execute("SELECT id FROM app_user WHERE id=%s FOR UPDATE", (student,))
            old_slot = c.execute("SELECT slot_id FROM booking WHERE id=%s", (old_id,)).fetchone()[0]
            c.execute("SELECT id FROM slot WHERE id IN (%s,%s) ORDER BY starts_at,id FOR UPDATE", (old_slot,target_slot)).fetchall()
            row = c.execute("SELECT status,student_id FROM booking WHERE id=%s FOR UPDATE", (old_id,)).fetchone()
            assert row == ('confirmed',student), row
            new_id = uuid.uuid4()
            c.execute("UPDATE booking SET status='cancelled',cancelled_at=now(),cancelled_by=%s,"
                      "cancellation_kind='rescheduled',rescheduled_to_id=%s WHERE id=%s", (student,new_id,old_id))
            c.execute("INSERT INTO booking(id,slot_id,student_id,status) VALUES (%s,%s,%s,'confirmed')", (new_id,target_slot,student))
        return '201'
    except errors.UniqueViolation as exc:
        assert exc.diag.constraint_name == 'uq_booking_slot_confirmed', exc.diag.constraint_name
        return '409'


def test_constraints():
    olds, target = fixture(2)
    first, second = olds
    # A regular immediate FK would reject the required old-before-new order.
    def immediate(c):
        c.execute("SET CONSTRAINTS fk_booking_successor IMMEDIATE")
        c.execute("UPDATE booking SET status='cancelled',cancelled_at=now(),cancelled_by=%s,"
                  "cancellation_kind='rescheduled',rescheduled_to_id=%s WHERE id=%s", (first[3],uuid.uuid4(),first[0]))
    expect_state(immediate, '23503')
    with connect() as c:
        assert move(c,first[0],target,first[3]) == '201'
    with connect() as c:
        successor = c.execute("SELECT rescheduled_to_id FROM booking WHERE id=%s", (first[0],)).fetchone()[0]
        assert c.execute("SELECT status FROM booking WHERE id=%s", (successor,)).fetchone()[0] == 'confirmed'
    expect_state(lambda c: c.execute("UPDATE booking SET status='cancelled',cancelled_at=now(),cancelled_by=%s,"
                 "cancellation_kind='rescheduled',rescheduled_to_id=%s WHERE id=%s", (second[3],successor,second[0])), '23505')
    expect_state(lambda c: c.execute("UPDATE booking SET status='cancelled',cancelled_at=now(),cancelled_by=%s,"
                 "cancellation_kind='rescheduled' WHERE id=%s", (second[3],second[0])), '23514')
    expect_state(lambda c: c.execute("UPDATE booking SET rescheduled_to_id=%s WHERE id=%s", (uuid.uuid4(),second[0])), '23514')
    expect_state(lambda c: c.execute("UPDATE booking SET status='cancelled',cancelled_at=now(),cancelled_by=%s,"
                 "cancellation_kind='rescheduled',rescheduled_to_id=%s WHERE id=%s", (second[3],uuid.uuid4(),second[0])), '23503')
    with connect() as c:
        assert move(c,second[0],target,second[3]) == '409'
    with connect() as c:
        assert c.execute("SELECT status,rescheduled_to_id,cancelled_at FROM booking WHERE id=%s", (second[0],)).fetchone() == ('confirmed',None,None)
    # Both NULL foreign keys coexist; a complete transfer rolls back if a later action fails.
    originals, another_target = fixture(2)
    with connect() as c:
        assert c.execute("SELECT count(*) FROM booking WHERE id IN (%s,%s) AND rescheduled_to_id IS NULL", (originals[0][0],originals[1][0])).fetchone()[0] == 2
    def late_failure(c):
        with c.transaction():
            assert move(c,originals[0][0],another_target,originals[0][3]) == '201'
            c.execute("SELECT 1/0")
    expect_state(late_failure, '22012')
    with connect() as c:
        assert c.execute("SELECT status FROM booking WHERE id=%s", (originals[0][0],)).fetchone()[0] == 'confirmed'
        assert c.execute("SELECT count(*) FROM booking WHERE slot_id=%s", (another_target,)).fetchone()[0] == 0
    REPORT['results']['reschedule_constraints'] = {
        'immediate_fk_control':'23503','deferred_fk_transfer':True,'unique_successor':'23505',
        'missing_or_invalid_kind':'23514','missing_successor_at_commit':'23503',
        'multiple_nulls':True,'occupied_target_rollback':True,'later_error_rollback':True,
    }
    print('[PASS] FK, UNIQUE, CHECK; successful transfer and complete rollback',flush=True)


def test_concurrent_moves():
    n,runs=base.N,base.RUNS
    connections=[connect() for _ in range(n)]
    outcomes=[]
    try:
        for run in range(runs):
            olds,target=fixture(n)
            result=base.run_concurrently(move,[(old[0],target,old[3]) for old in olds],connections)
            with connect() as c:
                active_target=c.execute("SELECT count(*) FROM booking WHERE slot_id=%s AND status='confirmed'", (target,)).fetchone()[0]
                active_old=c.execute("SELECT count(*) FROM booking WHERE id=ANY(%s) AND status='confirmed'", ([old[0] for old in olds],)).fetchone()[0]
            assert (result.count('201'),result.count('409'),active_target,active_old)==(1,n-1,1,n-1)
            outcomes.append({'success':1,'conflict':n-1,'target_confirmed':active_target,'old_preserved':active_old})
            if (run+1)%5==0: print(f'[progress] concurrent rescheduling: {run+1}/{runs}',flush=True)
    finally:
        for c in connections:c.close()
    REPORT['results']['concurrent_reschedule']={'concurrency':n,'runs':runs,'outcomes':outcomes}
    print(f'[PASS] {runs} x {n} concurrent transfers: one success; failed transfers preserve originals',flush=True)


def test_deadlock_retry():
    students=sorted([uuid.uuid4(),uuid.uuid4()])
    with connect() as c:
        for student in students:c.execute('INSERT INTO app_user VALUES (%s)',(student,))
    barrier=threading.Barrier(2)
    failures=[];retried=[]
    def worker(label,reverse):
        try:
            with connect() as c:
                for attempt in range(2):
                    try:
                        with c.transaction():
                            order=students[::-1] if reverse and attempt==0 else students
                            c.execute('SELECT id FROM app_user WHERE id=%s FOR UPDATE',(order[0],))
                            c.execute('INSERT INTO retry_marker VALUES (%s)',(label,))
                            if attempt==0:barrier.wait(timeout=10)
                            c.execute('SELECT id FROM app_user WHERE id=%s FOR UPDATE',(order[1],))
                        return
                    except errors.DeadlockDetected as exc:
                        assert exc.sqlstate=='40P01' and attempt==0
                        retried.append(label)
                raise AssertionError('retry exhausted')
        except BaseException as exc:failures.append(exc)
    threads=[threading.Thread(target=worker,args=('A',False)),threading.Thread(target=worker,args=('B',True))]
    for t in threads:t.start()
    for t in threads:t.join(25)
    assert not failures and not any(t.is_alive() for t in threads),failures
    assert len(retried)==1,retried
    with connect() as c:assert c.execute('SELECT count(*) FROM retry_marker').fetchone()[0]==2
    REPORT['results']['deadlock_retry']={'sqlstate':'40P01','retried_transactions':1,'committed_markers':2}
    print('[PASS] Real 40P01: rollback and one full transaction retry; no duplicated writes',flush=True)


def test_uuid_audit():
    with connect() as c:
        value=c.execute("INSERT INTO audit_uuid(action) VALUES ('test') RETURNING id").fetchone()[0]
        assert isinstance(value,uuid.UUID) and value.version==4
    expect_state(lambda c:c.execute("UPDATE audit_uuid SET action='changed'"),'P0001')
    expect_state(lambda c:c.execute('DELETE FROM audit_uuid'),'P0001')
    REPORT['results']['uuid_audit']={'uuid_version':4,'update_sqlstate':'P0001','delete_sqlstate':'P0001'}
    print('[PASS] UUIDv4 audit identifier and append-only trigger',flush=True)


if __name__=='__main__':
    with psycopg.connect(base.DSN,autocommit=True) as c:
        c.execute(DDL)
        REPORT['server_version']=c.execute('SHOW server_version').fetchone()[0]
    test_constraints()
    test_concurrent_moves()
    test_deadlock_retry()
    test_uuid_audit()
    REPORT['passed']=True
    Path(os.environ['SPIKE_EXTRA_REPORT']).write_text(json.dumps(REPORT,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('[PASS] All additional assertions passed',flush=True)
