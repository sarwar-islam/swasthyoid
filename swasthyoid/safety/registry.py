"""M6 rule registry (B5; FRD M6, owner decisions 2026-11-16): versions, approval with four-eyes, rejection.

The registry stores what the clinical reviewer writes; it holds no clinical rule of its own and seeds none. Only an
`approved` version ever runs (the M6 engine, P3). Engine rule types must fit the strict shapes in definitions.py (D5). The database guard in safety/schema.sql keeps every version's
content unchanged and allows only draft -> approved | rejected and approved -> superseded.
"""
import secrets
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from swasthyoid.core import audit
from swasthyoid.safety import definitions

RULE_TYPES = ("ddi", "allergy", "duplicate", "drug_disease", "class_lookback", "vital_threshold", "vital_plausibility",
              "red_flag", "emergency_message")
SEVERITIES = ("contraindicated", "major", "moderate", "minor")


class Invalid(Exception):
    """args[0]: a stable code."""


class Conflict(Exception):
    """args[0]: draft_exists, not_draft or four_eyes."""


def _check(body):
    rule_type, severity = body.get("rule_type"), body.get("severity")
    definition, explanation = body.get("definition"), body.get("explanation")
    if rule_type not in RULE_TYPES or (severity is not None and severity not in SEVERITIES):
        raise Invalid("invalid_rule")
    if not isinstance(definition, dict) or not definition:
        raise Invalid("invalid_rule")
    if not isinstance(explanation, dict) or not all(isinstance(explanation.get(k), str) and explanation[k].strip()
                                                    for k in ("en", "bn")):
        raise Invalid("invalid_rule")
    if rule_type in definitions.VITAL_RULE_TYPES:  # P6 (V1, V3): strict shapes; a unit that does not fit keeps its B5 code
        try:
            definitions.parse_vital(rule_type, definition)
        except definitions.Invalid as e:
            raise Invalid("invalid_vital_threshold" if e.args == ("unit",) else "invalid_rule_definition") from None
    if rule_type in definitions.ENGINE_TYPES:  # P3 (D5): the strict shapes the M6 engine reads
        try:
            definitions.parse(rule_type, severity, definition)
        except definitions.Invalid:
            raise Invalid("invalid_rule_definition") from None
    return rule_type, severity, definition, explanation["en"].strip(), explanation["bn"].strip()


def _new_rule_id():
    return f"RULE-{secrets.token_hex(4).upper()}"


def draft(conn, body, *, author):
    """A new rule (no rule_id) or a new version of one, as a draft. One open draft per rule (Conflict draft_exists)."""
    if not isinstance(body, dict):
        raise Invalid("invalid_rule")
    rule_type, severity, definition, en, bn = _check(body)
    with conn.transaction():
        rule_id = body.get("rule_id")
        if rule_id is None:
            rule_id, version = _new_rule_id(), 1
        else:
            latest = conn.cursor(row_factory=dict_row).execute(
                "SELECT rule_type, version FROM rules WHERE rule_id = %s ORDER BY version DESC LIMIT 1 FOR UPDATE",
                [rule_id]).fetchone()
            if latest is None:
                raise LookupError("rule not found")
            if latest["rule_type"] != rule_type:
                raise Invalid("invalid_rule")  # a new version keeps the rule's type
            version = latest["version"] + 1
        try:
            with conn.transaction():
                row = conn.cursor(row_factory=dict_row).execute(
                    "INSERT INTO rules (id, rule_id, version, rule_type, severity, definition, explanation_en, explanation_bn, "
                    "created_by) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING *",
                    [uuid4(), rule_id, version, rule_type, severity, Jsonb(definition), en, bn, author.id]).fetchone()
        except psycopg.errors.UniqueViolation:
            raise Conflict("draft_exists") from None
        audit.append(conn, action="rule.draft", result="allow", actor_id=author.id, actor_role=author.role,
                     resource_type="rule", resource_id=row["id"])
        return row


def _draft_for_update(conn, version_id):
    row = conn.cursor(row_factory=dict_row).execute("SELECT * FROM rules WHERE id = %s FOR UPDATE", [version_id]).fetchone()
    if row is None:
        raise LookupError("rule version not found")
    if row["status"] != "draft":
        raise Conflict("not_draft")
    return row


def approve(conn, version_id, *, reviewer):
    """draft -> approved, superseding the rule's approved version. Never by the draft's author (Conflict four_eyes)."""
    with conn.transaction():
        row = _draft_for_update(conn, version_id)
        if row["created_by"] == reviewer.id:
            raise Conflict("four_eyes")
        conn.execute("UPDATE rules SET status = 'superseded' WHERE rule_id = %s AND status = 'approved'", [row["rule_id"]])
        row = conn.cursor(row_factory=dict_row).execute(
            "UPDATE rules SET status = 'approved', reviewed_by = %s, reviewed_at = clock_timestamp() WHERE id = %s RETURNING *",
            [reviewer.id, version_id]).fetchone()
        audit.append(conn, action="rule.approve", result="allow", actor_id=reviewer.id, actor_role=reviewer.role,
                     resource_type="rule", resource_id=version_id)
        return row


def reject(conn, version_id, *, reviewer, reason):
    """draft -> rejected with a reason. The author may withdraw their own draft this way (four-eyes is for approval)."""
    if not isinstance(reason, str) or not reason.strip():
        raise Invalid("reason_required")
    with conn.transaction():
        _draft_for_update(conn, version_id)
        row = conn.cursor(row_factory=dict_row).execute(
            "UPDATE rules SET status = 'rejected', reviewed_by = %s, reviewed_at = clock_timestamp(), reason = %s "
            "WHERE id = %s RETURNING *", [reviewer.id, reason.strip(), version_id]).fetchone()
        audit.append(conn, action="rule.reject", result="allow", actor_id=reviewer.id, actor_role=reviewer.role,
                     resource_type="rule", resource_id=version_id, reason="reason_given")
        return row


def listing(conn, rule_type=None):
    """Every version, newest rule first, with the author's and reviewer's names."""
    return conn.cursor(row_factory=dict_row).execute(
        "SELECT r.*, a.name AS created_by_name, v.name AS reviewed_by_name FROM rules r "
        "JOIN users a ON a.id = r.created_by LEFT JOIN users v ON v.id = r.reviewed_by "
        "WHERE (%s::text IS NULL OR r.rule_type = %s) ORDER BY r.created_at DESC, r.rule_id, r.version DESC",
        [rule_type, rule_type]).fetchall()


def view(row, names=None):
    names = names or {}
    return {"id": row["id"], "rule_id": row["rule_id"], "version": row["version"], "rule_type": row["rule_type"],
            "severity": row["severity"], "status": row["status"], "definition": row["definition"],
            "explanation": {"en": row["explanation_en"], "bn": row["explanation_bn"]},
            "created_by_name": row.get("created_by_name") or names.get(row["created_by"]), "created_at": row["created_at"],
            "reviewed_by_name": row.get("reviewed_by_name") or names.get(row["reviewed_by"]),
            "reviewed_at": row["reviewed_at"], "reason": row["reason"]}
