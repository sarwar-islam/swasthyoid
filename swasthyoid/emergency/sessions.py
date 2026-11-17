"""M10 break-glass sessions and their post-hoc review (B7; FRD M10, owner decisions 2026-11-17).

A session is opened only after core.consent_authz.check_emergency allowed it and wrote the audit entry. It is
time-boxed, notifies the patient in the same transaction (the emergency contact's notice is unbuilt until an SMS
gateway exists, owner decision 3), and once closed waits for a clinical reviewer. "Unjustified" turns the doctor's
emergency capability off. emergency/schema.sql guards the rows.
"""
from uuid import uuid4

from psycopg.rows import dict_row

from swasthyoid.core import audit, notification
from swasthyoid.emergency import profile

DECISIONS = ("justified", "unjustified")


class Invalid(Exception):
    """args[0]: invalid_decision or reason_required."""


class NotPending(Exception):
    """The session was already reviewed."""


def start(conn, *, doctor_id, patient_id, reason, facility, length):
    """Open a session for `length` (a timedelta) and return (row, card)."""
    with conn.transaction():
        card = profile.card(conn, patient_id)
        row = conn.cursor(row_factory=dict_row).execute(
            "INSERT INTO emergency_sessions (id, doctor_id, patient_id, reason, facility, fields_shown, ends_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, clock_timestamp() + %s) RETURNING *",
            [uuid4(), doctor_id, patient_id, reason.strip(), facility.strip(), list(card or {}), length]).fetchone()
        notification.enqueue(conn, recipient_id=patient_id, template_id="EMERGENCY_ACCESS_PLACEHOLDER",
                             payload={"session_id": str(row["id"]), "facility": row["facility"]})
    return row, card


_CLOSED = ("SELECT s.*, u.name AS doctor_name FROM emergency_sessions s JOIN users u ON u.id = s.doctor_id "
           "WHERE s.ends_at <= clock_timestamp() ")


def closed(conn):
    """Every closed session, newest first: those waiting for review and those already reviewed."""
    return conn.cursor(row_factory=dict_row).execute(_CLOSED + "ORDER BY s.ends_at DESC, s.id").fetchall()


def review(conn, session_id, *, reviewer, decision, note):
    if decision not in DECISIONS:
        raise Invalid("invalid_decision")
    note = note.strip() if isinstance(note, str) else ""
    if decision == "unjustified" and not note:
        raise Invalid("reason_required")
    with conn.transaction():
        row = conn.cursor(row_factory=dict_row).execute(_CLOSED + "AND s.id = %s FOR UPDATE OF s", [session_id]).fetchone()
        if row is None:  # unknown, or still open
            raise LookupError("no closed session with this id")
        if row["review_status"] != "review_pending":
            raise NotPending()
        conn.execute("UPDATE emergency_sessions SET review_status = %s, reviewed_by = %s, reviewed_at = clock_timestamp(), "
                     "note = %s WHERE id = %s", [decision, reviewer.id, note or None, session_id])
        if decision == "unjustified":  # FRD M10: an unjustified access suspends the doctor's emergency capability
            conn.execute("UPDATE users SET emergency_enabled = false, updated_at = clock_timestamp() WHERE id = %s",
                         [row["doctor_id"]])
        audit.append(conn, action=f"emergency.review.{decision}", result="allow", actor_id=reviewer.id,
                     actor_role=reviewer.role, device_id=reviewer.device_id, resource_type="emergency_session",
                     resource_id=session_id, reason="reason_given" if note else None)
        return conn.cursor(row_factory=dict_row).execute(_CLOSED + "AND s.id = %s", [session_id]).fetchone()


def view(row):
    return {"id": row["id"], "doctor_id": row["doctor_id"], "doctor_name": row["doctor_name"], "reason": row["reason"],
            "facility": row["facility"], "opened_at": row["started_at"], "closed_at": row["ends_at"],
            "fields_shown": row["fields_shown"], "status": row["review_status"], "note": row["note"],
            "reviewed_at": row["reviewed_at"], "capability_suspended": row["review_status"] == "unjustified"}
