"""B8a: the synthetic development seed, on a throwaway database. It refuses outside APP_ENV=development, seeds an empty
database through the real routes, and changes nothing the second time."""
import os
import uuid

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from swasthyoid.devtools import seed
from swasthyoid.tests.conftest import require_database


@pytest.fixture
def dev_db(monkeypatch, tmp_path):
    require_database()
    admin_url = os.environ["DATABASE_URL"]
    name = f"seed_{uuid.uuid4().hex}"
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(f"CREATE DATABASE {name}")
    url = make_conninfo(admin_url, dbname=name)
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("DOCUMENT_STORE", str(tmp_path))
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("SWASTHYOID_TEST_MODE_CONFIRM", raising=False)
    monkeypatch.delenv("DEV_LOG_CODES", raising=False)
    yield url
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")


def test_the_seed_refuses_outside_development(dev_db, monkeypatch):
    for value in ("test", "production", None):
        if value is None:
            monkeypatch.delenv("APP_ENV")
        else:
            monkeypatch.setenv("APP_ENV", value)
        with pytest.raises(seed.Refused):
            seed.run(out=lambda *_: None)
    with psycopg.connect(dev_db) as conn:
        assert conn.execute("SELECT to_regclass('users')").fetchone()[0] is None  # nothing touched


def test_the_seed_fills_an_empty_database_once_through_the_real_workflow(dev_db):
    lines = []
    summary = seed.run(out=lines.append)
    assert summary["health_id"].startswith("SID-")
    with psycopg.connect(dev_db) as conn:
        roles = dict(conn.execute("SELECT role || ':' || status, count(*) FROM users GROUP BY 1").fetchall())
        assert roles == {"admin:verified": 1, "clinical_reviewer:verified": 2, "verifier:verified": 1, "doctor:verified": 1}
        assert conn.execute("SELECT bool_or(emergency_enabled) FROM users").fetchone()[0] is False  # M10 stays off
        assert conn.execute("SELECT count(*) FROM patients").fetchone()[0] == 2
        assert sorted(r[0] for r in conn.execute("SELECT status FROM documents")) == ["needs_review", "verified", "verified"]
        assert conn.execute("SELECT count(*) FROM verifications").fetchone()[0] == 2
        types = {r[0] for r in conn.execute("SELECT event_type FROM events WHERE verification_status = 'document_verified'")}
        assert {"prescription", "medication", "allergy", "follow_up", "lab_result"} <= types
        assert conn.execute("SELECT count(*) FROM rules").fetchone()[0] == 0  # no clinical rule (FRD Q7)
        assert conn.execute("SELECT count(*) FROM consents").fetchone()[0] == 0
        logged = {r[0] for r in conn.execute("SELECT action FROM audit_logs")}
        assert {"auth.login", "document.confirm"} <= logged
        audit_count = conn.execute("SELECT count(*) FROM audit_logs").fetchone()[0]
    assert not any(c.isdigit() and len(c) == 6 for line in lines for c in line.split())  # no code is ever printed

    assert seed.run(out=lines.append) is None  # a second run changes nothing
    with psycopg.connect(dev_db) as conn:
        assert conn.execute("SELECT count(*) FROM audit_logs").fetchone()[0] == audit_count
