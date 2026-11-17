"""M13 home vitals: save, check, correct and list a patient's own readings (P6; FRD M13; owner decisions V1-V6 and
safeguards 1-7, 2026-11-17). SYNTHETIC rules only in tests; no clinical number, range or message lives here.

- A reading is a `vital_reading` event, always `patient_reported` (never device-verified), with the value exactly as
  entered and no unit conversion (V2). The patient's app makes the reading id: a retry with the same id and the same data
  returns the saved result; the same id with other data is a conflict (safeguard 4).
- Format checks only: the vital, its unit and context from the existing vocabulary, positive ASCII numbers, a measurement
  time that is not in the future (V1). Plausibility comes only from approved `vital_plausibility` rules (none yet).
- Evaluation (V3): approved `vital_threshold` rules for this vital, unit and context, each with the treating doctor's
  per-patient value (B6). No applicable value, a rule that does not fit its shape, or any failure gives `not_evaluated`,
  never "within range" (safeguard 6). A fired rule's message is that approved rule version's own text (V4).
- A flagged or critical reading queues one patient notice in the same transaction (C3 retries it and records failures;
  safeguard 1); `not_evaluated` never queues one (safeguard 2). No quiet-hours bypass: there is no approved policy.
- A correction is a new reading that supersedes the original, with a reason, actor and time; the original stays (V6, 5).
"""
import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from swasthyoid.core import audit, events_provenance, notification
from swasthyoid.safety import definitions, thresholds

log = logging.getLogger(__name__)

BD = timezone(timedelta(hours=6))  # Bangladesh keeps one offset all year; the event date is the local day
CLOCK_SKEW = timedelta(minutes=5)  # engineering allowance for a phone clock, not a clinical value
MAX_REASON, LIST_LIMIT = 500, 500
_BP = re.compile(r"^([0-9]{1,4})/([0-9]{1,4})$")
_DECIMAL = re.compile(r"^[0-9]{1,5}(\.[0-9]{1,2})?$")
_KEYS = {"id", "vital_type", "value", "unit", "context", "measured_at", "confirmed"}
NOTICE = {"critical": "VITAL_CRITICAL_PLACEHOLDER", "flagged": "VITAL_FLAGGED_PLACEHOLDER"}
_RANK = {"critical": 2, "flagged": 1}


class Invalid(Exception):
    """422: invalid_reading, reason_required."""


class Conflict(Exception):
    """409: reading_id_conflict, already_corrected."""


class NeedsConfirmation(Exception):
    """422 confirmation_required: an approved plausibility rule finds the value unusual and the patient has not confirmed."""


def _entry(body, correction):
    keys = _KEYS | ({"reason"} if correction else set())
    if not isinstance(body, dict) or not set(body) <= keys:
        raise Invalid("invalid_reading")
    try:
        rid = UUID(str(body.get("id")))
    except ValueError:
        raise Invalid("invalid_reading") from None
    vital = definitions.VITALS.get(body.get("vital_type"))
    value, unit, context, confirmed = body.get("value"), body.get("unit"), body.get("context"), body.get("confirmed", False)
    if vital is None or unit not in vital["units"] or context not in vital["contexts"] or not isinstance(value, str) \
            or not isinstance(confirmed, bool):
        raise Invalid("invalid_reading")
    if body["vital_type"] == "bp":
        m = _BP.match(value)
        parts = {"systolic": Decimal(m[1]), "diastolic": Decimal(m[2])} if m else None
    else:
        parts = {None: Decimal(value)} if _DECIMAL.match(value) else None
    if not parts or any(v <= 0 for v in parts.values()):
        raise Invalid("invalid_reading")
    try:
        when = datetime.fromisoformat(body.get("measured_at"))
    except (TypeError, ValueError):
        raise Invalid("invalid_reading") from None
    if when.tzinfo is None or when > datetime.now(timezone.utc) + CLOCK_SKEW:
        raise Invalid("invalid_reading")
    reason = None
    if correction:
        reason = body.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise Invalid("reason_required")
        reason = reason.strip()
        if len(reason) > MAX_REASON:
            raise Invalid("invalid_reading")
    return {"id": rid, "vital_type": body["vital_type"], "value": value, "unit": unit, "context": context,
            "measured_at": when.astimezone(timezone.utc), "confirmed": confirmed, "reason": reason, "parts": parts}


def _fingerprint(e, of):
    data = {"of": str(of) if of else None, "vital_type": e["vital_type"], "value": e["value"], "unit": e["unit"],
            "context": e["context"], "measured_at": e["measured_at"].isoformat(), "reason": e["reason"]}
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()  # `confirmed` is not part of the data


def _approved(conn, rule_type):
    return conn.cursor(row_factory=dict_row).execute(
        "SELECT id, rule_id, definition FROM rules WHERE rule_type = %s AND status = 'approved' ORDER BY rule_id",
        [rule_type]).fetchall()


def _applies(d, e):
    return d["vital_type"] == e["vital_type"] and d["unit"] == e["unit"] and d["component"] in e["parts"]


def _check_plausible(conn, e):
    """Approved vital_plausibility rules only (V1). A rule that does not fit its shape asks for confirmation (fail closed)."""
    if e["confirmed"]:
        return
    for rule in _approved(conn, "vital_plausibility"):
        try:
            d = definitions.parse_vital("vital_plausibility", rule["definition"])
        except definitions.Invalid:
            raise NeedsConfirmation() from None
        if _applies(d, e):
            v = e["parts"][d["component"]]
            if not Decimal(str(d["at_least"])) <= v <= Decimal(str(d["at_most"])):
                raise NeedsConfirmation()


def evaluate(conn, patient_id, e):
    """{level, rule_id, rule_version_id, reason} for a reading. Never `within_range` without an applicable threshold."""
    overrides = thresholds.current_overrides(conn, patient_id)
    fired, applicable = [], 0
    for rule in _approved(conn, "vital_threshold"):
        try:
            d = definitions.parse_vital("vital_threshold", rule["definition"])
        except definitions.Invalid:
            return {"level": "not_evaluated", "rule_id": None, "rule_version_id": None, "reason": "rule_load_error"}
        value = overrides.get(rule["rule_id"])
        if value is None or not _applies(d, e) or e["context"] not in d["contexts"]:
            continue
        applicable += 1
        v, limit = e["parts"][d["component"]], Decimal(str(value))
        if (v >= limit) if d["comparison"] == "at_or_above" else (v <= limit):
            fired.append((-_RANK[d["level"]], rule["rule_id"], d["level"], rule["id"]))
    if not applicable:
        return {"level": "not_evaluated", "rule_id": None, "rule_version_id": None, "reason": "no_applicable_threshold"}
    if not fired:
        return {"level": "within_range", "rule_id": None, "rule_version_id": None, "reason": None}
    _, rule_id, level, version_id = min(fired)  # the most serious level; ties by rule id, so the answer is stable
    return {"level": level, "rule_id": rule_id, "rule_version_id": str(version_id), "reason": None}


def _evaluate_or_not(conn, patient_id, e):
    try:
        with conn.transaction():
            return evaluate(conn, patient_id, e)
    except Exception:  # safeguard 6: a failed check is reported as not evaluated, never as within range
        log.exception("vital evaluation failed")
        return {"level": "not_evaluated", "rule_id": None, "rule_version_id": None, "reason": "evaluation_unavailable"}


def _row(conn, patient_id, reading_id):
    return conn.cursor(row_factory=dict_row).execute(
        "SELECT r.*, e.payload, e.version, e.supersedes, e.recorded_at, e.verification_status FROM vital_readings r "
        "JOIN events e ON e.id = r.event_id WHERE r.patient_id = %s AND r.id = %s", [patient_id, reading_id]).fetchone()


def _messages(conn, version_ids):
    ids = [v for v in version_ids if v]
    rows = conn.execute("SELECT id, explanation_en, explanation_bn FROM rules WHERE id = ANY(%s::uuid[])", [ids]).fetchall() \
        if ids else []
    return {str(i): {"en": en, "bn": bn, "status": "approved"} for i, en, bn in rows}


def reading_view(row):
    p = row["payload"]
    return {"id": row["id"], "event_id": row["event_id"], "vital_type": p["vital_type"], "value": p["value"],
            "unit": p["unit"], "context": p["context"], "measured_at": p["measured_at"],
            "verification_status": row["verification_status"], "version": row["version"], "supersedes": row["supersedes"],
            "supersedes_reading_id": row["supersedes_reading_id"], "correction_reason": row["correction_reason"],
            "recorded_at": row["recorded_at"]}


def saved_view(conn, row):
    ev = row["evaluation"]
    return {"reading": reading_view(row),
            "evaluation": {"level": ev["level"], "rule_id": ev["rule_id"], "reason": ev["reason"],
                           "message": _messages(conn, [ev["rule_version_id"]]).get(ev["rule_version_id"] or "")}}


def save(conn, patient_id, body, *, actor, of=None):
    """Save a new reading, or a correction of reading `of`. Returns (view, created)."""
    e = _entry(body, correction=of is not None)
    fingerprint = _fingerprint(e, of)
    try:
        with conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [f"vital:{patient_id}:{e['id']}"])
            if of is not None:  # one correction at a time per original
                conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [f"vital-of:{patient_id}:{of}"])
            existing = _row(conn, patient_id, e["id"])
            if existing is not None:
                if existing["request_hash"] != fingerprint:
                    raise Conflict("reading_id_conflict")
                return saved_view(conn, existing), False
            original = None
            if of is not None:
                original = _row(conn, patient_id, of)
                if original is None:
                    raise LookupError("reading not found")
                if conn.execute("SELECT 1 FROM vital_readings WHERE patient_id = %s AND supersedes_reading_id = %s",
                                [patient_id, of]).fetchone():
                    raise Conflict("already_corrected")
                if original["payload"]["vital_type"] != e["vital_type"]:
                    raise Invalid("invalid_reading")
            _check_plausible(conn, e)
            evaluation = _evaluate_or_not(conn, patient_id, e)
            payload = {"reading_id": str(e["id"]), "vital_type": e["vital_type"], "value": e["value"], "unit": e["unit"],
                       "context": e["context"], "measured_at": e["measured_at"].isoformat(), "source": "manual_entry"}
            if e["reason"]:
                payload["correction_reason"] = e["reason"]
            event = events_provenance.append(
                conn, patient_id=patient_id, event_type="vital_reading", event_date=e["measured_at"].astimezone(BD).date(),
                date_precision="day", actor_id=actor.id, actor_role=actor.role, source_type="patient_entry",
                verification_status="patient_reported", payload=payload,
                supersedes=original["event_id"] if original else None)
            notice = None
            if evaluation["level"] in NOTICE:
                notice = notification.enqueue(conn, recipient_id=patient_id, template_id=NOTICE[evaluation["level"]],
                                              payload={"reading_id": str(e["id"]),
                                                       "rule_version_id": evaluation["rule_version_id"]})["id"]
            conn.execute(
                "INSERT INTO vital_readings (patient_id, id, event_id, request_hash, supersedes_reading_id, correction_reason, "
                "actor_id, confirmed, evaluation, notification_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                [patient_id, e["id"], event["id"], fingerprint, of, e["reason"], actor.id, e["confirmed"],
                 Jsonb(evaluation), notice])
            audit.append(conn, action="vitals.correct" if of else "vitals.create", result="allow", actor_id=actor.id,
                         actor_role=actor.role, device_id=actor.device_id, patient_id=patient_id,
                         resource_type="vital_reading", resource_id=event["id"],
                         reason="reason_given" if of else evaluation["level"])
            return saved_view(conn, _row(conn, patient_id, e["id"])), True
    except psycopg.errors.UniqueViolation:  # a concurrent correction of the same original won
        raise Conflict("already_corrected") from None


def listing(conn, patient_id, limit=LIST_LIMIT):
    """The patient's own readings, corrected ones included (each says what it supersedes), newest first. limit=None: all
    of them (the W2 export)."""
    rows = conn.cursor(row_factory=dict_row).execute(
        "SELECT r.*, e.payload, e.version, e.supersedes, e.recorded_at, e.verification_status FROM vital_readings r "
        "JOIN events e ON e.id = r.event_id WHERE r.patient_id = %s ORDER BY e.recorded_at DESC, r.id LIMIT %s",
        [patient_id, limit]).fetchall()
    return [reading_view(r) for r in rows]
