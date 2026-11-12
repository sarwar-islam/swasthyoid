import os
from pathlib import Path

import psycopg

_ROOT = Path(__file__).parent
SCHEMA_FILES = [_ROOT / d / "schema.sql" for d in ("core", "identity", "capture")]  # in dependency order


def connect(**kwargs):
    return psycopg.connect(os.environ["DATABASE_URL"], **kwargs)


def apply_schema(conn):
    for f in SCHEMA_FILES:
        conn.execute(f.read_text(encoding="utf-8"))
    conn.commit()
