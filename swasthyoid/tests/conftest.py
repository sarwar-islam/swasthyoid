import os
import uuid

import pytest
from cryptography.fernet import Fernet

# Throwaway keys for the test run only.
os.environ.setdefault("PII_KEY", Fernet.generate_key().decode())
os.environ.setdefault("DOCUMENT_KEY", Fernet.generate_key().decode())
os.environ.setdefault("HMAC_KEY", uuid.uuid4().hex * 2)
os.environ.setdefault("JWT_SECRET", uuid.uuid4().hex * 2)


def require_database():
    if "DATABASE_URL" not in os.environ:
        if os.environ.get("CI"):
            pytest.fail("DATABASE_URL must be set in CI: database tests may not be skipped")
        pytest.skip("DATABASE_URL not set")


@pytest.fixture
def connect():
    """Factory for connections into a fresh, throwaway schema with the core tables."""
    require_database()
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
