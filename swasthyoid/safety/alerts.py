"""M6 safety alerts (B6; FRD M6, section 7, invariant 6; owner decisions 2026-11-17).

Listing and handling only: alerts are created by the M6 check runner (safety/checks.py, P3). An alert shows the explanation of the
rule version that fired, even after that version is superseded. Only the treating doctor, under a consent covering
`safety`, sees or handles alerts (the route checks that); patients never see them. safety/schema.sql guards the table.
"""
from psycopg.rows import dict_row

from swasthyoid.core import audit

ACTIONS = {"acknowledge": "acknowledged", "override": "overridden"}
_SELECT = ("SELECT a.*, r.rule_id, r.explanation_en, r.explanation_bn FROM safety_alerts a "
           "JOIN rules r ON r.id = a.rule_version_id ")


class Invalid(Exception):
    """args[0]: invalid_action or reason_required."""


class NotOpen(Exception):
    """The alert was already acknowledged or overridden."""


def for_patient(conn, patient_id):
    return conn.cursor(row_factory=dict_row).execute(
        _SELECT + "WHERE a.patient_id = %s ORDER BY a.created_at DESC, a.id", [patient_id]).fetchall()


def patient_of(conn, alert_id):
    row = conn.execute("SELECT patient_id FROM safety_alerts WHERE id = %s", [alert_id]).fetchone()
    if row is None:
        raise LookupError("alert not found")
    return row[0]


def handle(conn, alert_id, *, doctor, action, reason):
    """open -> acknowledged | overridden. An override needs a reason; the audit log only says one was given."""
    status = ACTIONS.get(action)
    if status is None:
        raise Invalid("invalid_action")
    reason = reason.strip() if isinstance(reason, str) else ""
    if status == "overridden" and not reason:
        raise Invalid("reason_required")
    with conn.transaction():
        row = conn.execute(
            "UPDATE safety_alerts SET status = %s, handled_by = %s, handled_at = clock_timestamp(), reason = %s "
            "WHERE id = %s AND status = 'open' RETURNING patient_id",
            [status, doctor.id, reason or None, alert_id]).fetchone()
        if row is None:
            raise NotOpen()
        audit.append(conn, action=f"safety.alert.{action}", result="allow", actor_id=doctor.id, actor_role=doctor.role,
                     device_id=doctor.device_id, patient_id=row[0], resource_type="safety_alert", resource_id=alert_id,
                     reason="reason_given" if reason else None)
    return conn.cursor(row_factory=dict_row).execute(_SELECT + "WHERE a.id = %s", [alert_id]).fetchone()


def view(row):
    return {"id": row["id"], "rule_id": row["rule_id"], "severity": row["severity"],
            # the approved text of the version that fired (owner decision 2, 2026-11-17)
            "explanation": {"en": row["explanation_en"], "bn": row["explanation_bn"], "status": "approved"},
            "evidence_event_ids": row["evidence_event_ids"], "source_document_id": row["source_document_id"],
            "created_at": row["created_at"], "status": row["status"], "reason": row["reason"]}
