import os
import uuid

import pytest


@pytest.fixture
def connect():
    """Factory for connections into a fresh, throwaway schema with the core tables."""
    if "DATABASE_URL" not in os.environ:
        if os.environ.get("CI"):
            pytest.fail("DATABASE_URL must be set in CI: database tests may not be skipped")
        pytest.skip("DATABASE_URL not set")
    from swasthyoid import db

    schema = f"test_{uuid.uuid4().hex}"
    with db.connect(autocommit=True) as admin:
        admin.execute(f"CREATE SCHEMA {schema}")
    conns = []

    def _connect():
        conn = db.connect(options=f"-c search_path={schema}")
        conns.append(conn)
        return conn

    db.apply_schema(_connect())
    yield _connect
    for c in conns:
        c.close()
    with db.connect(autocommit=True) as admin:
        admin.execute(f"DROP SCHEMA {schema} CASCADE")


@pytest.fixture
def conn(connect):
    return connect()
