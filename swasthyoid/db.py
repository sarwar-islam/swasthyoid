import os
from pathlib import Path

import psycopg

_ROOT = Path(__file__).parent
SCHEMA_FILES = [_ROOT / d / "schema.sql" for d in ("core", "identity", "capture")]  # in dependency order


def connect(**kwargs):
    return psycopg.connect(os.environ["DATABASE_URL"], **kwargs)


def connect_worker():
    """Connection for background workers: autocommit, and the database ends any statement,
    lock wait or idle transaction that runs too long. A backstop only: it cannot stop a hung
    OCR process, which is what the hard timeout in capture/extraction.py is for."""
    return connect(autocommit=True, options="-c statement_timeout=60000 -c lock_timeout=10000 "
                                            "-c idle_in_transaction_session_timeout=60000")


def apply_schema(conn):
    for f in SCHEMA_FILES:
        conn.execute(f.read_text(encoding="utf-8"))
    conn.commit()
