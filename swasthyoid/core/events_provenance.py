"""C4 — event store with provenance (FRD section 4.4).

Every module writes to the timeline through append(). Events are never changed:
a correction is a new event that supersedes the old one. Field rules (allowed
types and statuses, verified-needs-a-verifier) are enforced by the table itself,
see core/schema.sql.
"""
from uuid import UUID, uuid4

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


def append(conn, *, patient_id, event_type, event_date, date_precision, actor_id, actor_role,
           source_type, verification_status, payload, source_document_id=None, verified_by=None,
           verified_at=None, related_record_id=None, supersedes=None):
    """Append one event and return the stored row. Raises if any rule is broken.

    id, recorded_at (server time) and version are set here, never by the caller.
    """
    patient_id = UUID(str(patient_id))
    with conn.transaction():
        version = 1
        if supersedes is not None:
            old = conn.execute("SELECT patient_id, version FROM events WHERE id = %s", [supersedes]).fetchone()
            if old is None:
                raise ValueError("superseded event not found")
            if old[0] != patient_id:
                raise ValueError("an event can only supersede an event of the same patient")
            version = old[1] + 1
        return conn.cursor(row_factory=dict_row).execute(
            """INSERT INTO events (id, patient_id, event_type, event_date, date_precision, actor_id,
                   actor_role, source_type, source_document_id, verified_by, verified_at,
                   verification_status, related_record_id, version, supersedes, payload)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               RETURNING *""",
            [uuid4(), patient_id, event_type, event_date, date_precision, actor_id, actor_role,
             source_type, source_document_id, verified_by, verified_at, verification_status,
             related_record_id, version, supersedes, Jsonb(payload)],
        ).fetchone()


def current_events(conn, patient_id):
    """One patient's events that have not been superseded, oldest first.

    Raw store read: callers serving a non-patient must pass RBAC -> C1 -> C2 first.
    Includes `pending` and `patient_reported` rows; the timeline (M4) decides what to show.
    """
    return conn.cursor(row_factory=dict_row).execute(
        """SELECT * FROM events e
           WHERE patient_id = %s AND NOT EXISTS (SELECT 1 FROM events n WHERE n.supersedes = e.id)
           ORDER BY event_date, recorded_at""",
        [patient_id],
    ).fetchall()
