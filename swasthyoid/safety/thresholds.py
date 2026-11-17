"""M13 per-patient vital threshold overrides (B6; FRD M13, section 7; owner decisions 2026-11-17).

The editable fields are the approved `vital_threshold` rules: key = rule_id, with the rule's vital_type, unit and
explanation. Each change is a new append-only version holding the whole set of overrides. Values are checked only as
positive numbers: the allowed range is REVIEWER-PENDING, as is every default (always null until the reviewer names it in
the rule definition). Nothing evaluates readings against these yet.
"""
import math

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from swasthyoid.core import audit


class Invalid(Exception):
    """invalid_threshold: an unknown key, a value that is not a positive number or null, or a malformed body."""


class Conflict(Exception):
    """version_conflict: the thresholds changed since the caller read them."""


def _fields(conn):
    return conn.cursor(row_factory=dict_row).execute(
        "SELECT rule_id, definition, explanation_en, explanation_bn FROM rules "
        "WHERE rule_type = 'vital_threshold' AND status = 'approved' ORDER BY rule_id").fetchall()


def _latest(conn, patient_id):
    return conn.cursor(row_factory=dict_row).execute(
        "SELECT t.version, t.overrides, t.updated_at, u.name AS updated_by_name FROM patient_thresholds t "
        "JOIN users u ON u.id = t.updated_by WHERE t.patient_id = %s ORDER BY t.version DESC LIMIT 1",
        [patient_id]).fetchone() or {"version": 0, "overrides": {}, "updated_at": None, "updated_by_name": None}


def read(conn, patient_id):
    t = _latest(conn, patient_id)
    return {"patient_id": patient_id, "version": t["version"], "updated_at": t["updated_at"],
            "updated_by_name": t["updated_by_name"],
            "fields": [{"key": f["rule_id"], "vital_type": f["definition"]["vital_type"], "unit": f["definition"]["unit"],
                        "label": {"en": f["explanation_en"], "bn": f["explanation_bn"], "status": "approved"},
                        "default_value": None,  # REVIEWER-PENDING (owner decision 1): no rule names a default yet
                        "override_value": t["overrides"].get(f["rule_id"])} for f in _fields(conn)]}


def _value_ok(v):
    return v is None or (isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v > 0)


def update(conn, patient_id, body, *, doctor):
    """{ version, overrides }: a new version with these overrides merged in (null clears one)."""
    if not isinstance(body, dict) or type(body.get("version")) is not int or not isinstance(body.get("overrides"), dict):
        raise Invalid("invalid_threshold")
    overrides = body["overrides"]
    with conn.transaction():
        keys = {f["rule_id"] for f in _fields(conn)}
        if any(k not in keys or not _value_ok(v) for k, v in overrides.items()):
            raise Invalid("invalid_threshold")
        latest = _latest(conn, patient_id)
        if body["version"] != latest["version"]:
            raise Conflict("version_conflict")
        merged = {k: v for k, v in {**latest["overrides"], **overrides}.items() if v is not None}
        try:
            with conn.transaction():
                conn.execute("INSERT INTO patient_thresholds (patient_id, version, overrides, updated_by) VALUES (%s, %s, %s, %s)",
                             [patient_id, latest["version"] + 1, Jsonb(merged), doctor.id])
        except psycopg.errors.UniqueViolation:  # someone saved the same version first
            raise Conflict("version_conflict") from None
        audit.append(conn, action="vital_thresholds.update", result="allow", actor_id=doctor.id, actor_role=doctor.role,
                     device_id=doctor.device_id, patient_id=patient_id, resource_type="patient_thresholds")
    return read(conn, patient_id)
