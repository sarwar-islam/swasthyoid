import threading
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import psycopg
import pytest

from swasthyoid.core import audit


def count(conn):
    return conn.execute("SELECT count(*) FROM audit_logs").fetchone()[0]


def test_append_chains_and_verifies(conn):
    assert audit.verify_stored(conn) is None  # empty chain
    actor, patient = uuid4(), uuid4()
    first = audit.append(conn, action="timeline.read", result="deny", reason="consent_required",
                         actor_id=actor, actor_role="doctor", patient_id=patient, ip="127.0.0.1")
    # an upper-case UUID string must hash the same as the value the database stores
    second = audit.append(conn, action="timeline.read", result="allow", actor_id=str(actor).upper())
    conn.commit()

    assert first["prev_hash"] == audit.GENESIS
    assert second["prev_hash"] == first["entry_hash"]
    assert count(conn) == 2
    assert audit.verify_stored(conn) is None
    assert abs(first["at"] - datetime.now(timezone.utc)) < timedelta(minutes=1)  # server time


def test_caller_cannot_set_time_or_hashes(conn):
    for forbidden in ("at", "id", "prev_hash", "entry_hash", "seq", "bogus"):
        with pytest.raises(ValueError):
            audit.append(conn, action="x", result="allow", **{forbidden: "2000-01-01"})
    assert count(conn) == 0


def test_failed_write_raises_and_writes_nothing(conn):
    audit.append(conn, action="login", result="allow")
    conn.commit()
    with pytest.raises(psycopg.Error):
        audit.append(conn, action="login", result=None)  # NOT NULL violation
    with pytest.raises(ValueError):
        audit.append(conn, action="login", result="allow", patient_id="not-a-uuid")
    conn.commit()
    assert count(conn) == 1
    assert audit.verify_stored(conn) is None


def test_audit_entry_rolls_back_with_callers_transaction(conn):
    with conn.transaction():
        audit.append(conn, action="read", result="allow")
        raise psycopg.Rollback
    assert count(conn) == 0


def test_append_outside_a_transaction_commits_itself(conn):
    audit.append(conn, action="read", result="allow")
    conn.rollback()
    assert count(conn) == 1


@pytest.mark.parametrize("sql", [
    "UPDATE audit_logs SET result = 'allow'",
    "DELETE FROM audit_logs",
    "TRUNCATE audit_logs",
])
def test_append_only(conn, sql):
    audit.append(conn, action="read", result="deny")
    conn.commit()
    with pytest.raises(psycopg.Error, match="append-only"):
        conn.execute(sql)
    conn.rollback()
    assert count(conn) == 1


def test_chain_cannot_fork(conn):
    audit.append(conn, action="read", result="allow")
    conn.commit()
    with pytest.raises(psycopg.errors.UniqueViolation):
        conn.execute(
            "INSERT INTO audit_logs (id, at, action, result, prev_hash, entry_hash) "
            "VALUES (%s, now(), 'read', 'allow', %s, 'forged')",
            [uuid4(), audit.GENESIS],
        )


def test_tampering_is_detected(conn):
    for _ in range(3):
        audit.append(conn, action="read", result="deny")
    conn.commit()
    # Simulate someone with owner rights bypassing the triggers.
    conn.execute("ALTER TABLE audit_logs DISABLE TRIGGER USER")
    conn.execute("UPDATE audit_logs SET result = 'allow' WHERE seq = (SELECT min(seq) + 1 FROM audit_logs)")
    conn.commit()
    second = conn.execute("SELECT min(seq) + 1 FROM audit_logs").fetchone()[0]
    assert audit.verify_stored(conn) == second


def test_concurrent_writers_keep_one_chain(connect):
    errors = []

    def writer():
        try:
            c = connect()
            for _ in range(15):
                audit.append(c, action="read", result="allow")
                c.commit()
        except Exception as e:  # surfaced below
            errors.append(e)

    threads = [threading.Thread(target=writer) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    conn = connect()
    assert errors == []
    assert count(conn) == 60
    assert audit.verify_stored(conn) is None
