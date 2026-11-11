import os
from pathlib import Path

import psycopg

SCHEMA_FILES = [Path(__file__).parent / "core" / "schema.sql"]


def connect(**kwargs):
    return psycopg.connect(os.environ["DATABASE_URL"], **kwargs)


def apply_schema(conn):
    for f in SCHEMA_FILES:
        conn.execute(f.read_text(encoding="utf-8"))
    conn.commit()
