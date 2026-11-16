"""M3 — human verification: save a check, confirm it into events, or reject (FRD M3; owner decisions 2026-11-16, B4a).

A check is the reviewer's values for the document type's approved fields (capture/extraction.py SCHEMAS), saved as a new
append-only, sealed version each time. Confirm needs the document's own date, then in ONE transaction writes the
`document_verified` events (mapping below), records the corrections and sets the document `verified`. A document has at
most one verifications row, so a repeated confirm can never write events twice. The caller must already have checked that
the actor may verify this document (the patient; a verifier in an assisted session arrives in B4b).
"""
from uuid import uuid4

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from swasthyoid.capture import documents, extraction, extraction_crypto
from swasthyoid.core import audit, events_provenance

# The date every event of a document takes. Required at confirm (owner decision: never invent a date from the upload).
DATE_FIELD = {"prescription": "prescription_date", "lab_report": "report_date", "discharge_summary": "discharge_date"}


class Invalid(Exception):
    """A check that cannot be saved or confirmed: args[0] is a stable code, args[1] the field path or None."""


class Conflict(Exception):
    """The document is not in review: args[0] is a stable code."""


def _spec(doc_type):
    return extraction.SCHEMAS.get(doc_type, {})


def _value(kind, value, path):
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if not isinstance(value, str):
        raise Invalid("invalid_field", path)
    try:
        return extraction.parse(kind, value.strip())
    except ValueError:
        raise Invalid(f"invalid_{kind}", path) from None


def clean(doc_type, fields):
    """The check in its stored form: every schema field present (None when empty), values parsed like extracted ones
    (dates to ISO, Bangla digits accepted). Raises Invalid for an unknown field or a value that does not parse."""
    if not isinstance(fields, dict):
        raise Invalid("invalid_fields", None)
    spec = _spec(doc_type)
    unknown = set(fields) - set(spec)
    if unknown:
        raise Invalid("unknown_field", sorted(unknown)[0])
    out = {}
    for name, kind in spec.items():
        got = fields.get(name)
        if isinstance(kind, list):
            if got is None:
                got = []
            if not isinstance(got, list) or not all(isinstance(r, dict) for r in got):
                raise Invalid("invalid_field", name)
            rows = []
            for i, row in enumerate(got):
                extra = set(row) - set(kind[0])
                if extra:
                    raise Invalid("unknown_field", f"{name}[{i}].{sorted(extra)[0]}")
                parsed = {sub: _value(k, row.get(sub), f"{name}[{i}].{sub}") for sub, k in kind[0].items()}
                if any(v is not None for v in parsed.values()):  # a row left wholly empty is dropped
                    rows.append(parsed)
            out[name] = rows
        else:
            out[name] = _value(kind, got, name)
    return out


def _in_review(conn, document_id):
    doc = conn.cursor(row_factory=dict_row).execute(
        "SELECT * FROM documents WHERE id = %s FOR UPDATE", [document_id]).fetchone()
    if doc is None:
        raise LookupError("document not found")
    if doc["status"] != "needs_review":
        raise Conflict("not_allowed_state")
    return doc


def save(conn, document_id, fields, *, actor):
    """Store a new version of the check; returns the cleaned fields."""
    with conn.transaction():
        doc = _in_review(conn, document_id)
        cleaned = clean(doc["doc_type"], fields)
        version = conn.execute("SELECT coalesce(max(version), 0) + 1 FROM document_reviews WHERE document_id = %s",
                               [document_id]).fetchone()[0]
        conn.execute(
            "INSERT INTO document_reviews (id, document_id, version, fields, reviewed_by, reviewer_role) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            [uuid4(), document_id, version, Jsonb(extraction_crypto.seal_fields(cleaned)), actor.id, actor.role])
        return cleaned


def _latest_review(conn, document_id):
    return conn.cursor(row_factory=dict_row).execute(
        "SELECT * FROM document_reviews WHERE document_id = %s ORDER BY version DESC LIMIT 1", [document_id]).fetchone()


def _flat(spec, fields):
    """{path: value} of a fields object: a reviewed one (plain values) or an extracted one ({"value": ...} cells)."""
    out = {}
    for name, kind in spec.items():
        got = (fields or {}).get(name)
        if isinstance(kind, list):
            for i, row in enumerate(got or []):
                for sub in kind[0]:
                    cell = row.get(sub) if isinstance(row, dict) else None
                    out[f"{name}[{i}].{sub}"] = cell.get("value") if isinstance(cell, dict) else cell
        else:
            out[name] = got.get("value") if isinstance(got, dict) else got
    return out


def corrections(spec, extracted, reviewed):
    """(fields_total, [{path, before, after}]) between the extracted reading and the confirmed check."""
    before, after = _flat(spec, extracted), _flat(spec, reviewed)
    paths = sorted(set(before) | set(after))
    changed = [{"path": p, "before": before.get(p), "after": after.get(p)} for p in paths if before.get(p) != after.get(p)]
    return len(paths), changed


def _present(row):
    return {k: v for k, v in row.items() if v is not None}


def events_for(doc_type, fields):
    """The events a confirmed check becomes: [(event_type, event_date, payload)].

    REVIEWER-PENDING (owner-approved 2026-11-16, clinical reviewer not named, FRD Q7): everything stays exactly as written,
    nothing is coded, interpreted or merged. Only the fields named below are read: the written diagnosis stays with the
    document (D7 Q4) and the printed patient name is only a flag, so neither ever becomes an event.
    """
    date = fields.get(DATE_FIELD.get(doc_type, ""))
    out = []
    if doc_type == "prescription":
        out.append(("prescription", date, _present({k: fields.get(k) for k in (
            "prescriber_name", "prescriber_registration", "facility_name", "advice_text")})))
    elif doc_type == "discharge_summary":
        out.append(("visit", date, _present({k: fields.get(k) for k in ("admission_date", "discharge_date", "facility_name")})))
    elif doc_type == "lab_report":
        out += [("lab_result", date, _present(row)) for row in fields.get("tests") or []]
    if doc_type in ("prescription", "discharge_summary"):
        out += [("medication", date, _present(row)) for row in fields.get("medications") or []]
        if fields.get("follow_up_date"):
            out.append(("follow_up", fields["follow_up_date"], {"follow_up_date": fields["follow_up_date"]}))
        if fields.get("allergy_text"):  # as written, so M6 allergy rules have structured input
            out.append(("allergy", date, {"allergy_text": fields["allergy_text"]}))
    return out


def confirm(conn, document_id, *, actor, context=None):
    """needs_review -> verified, with its events and correction record, in one transaction. Returns the event ids."""
    with conn.transaction():
        doc = _in_review(conn, document_id)
        review = _latest_review(conn, document_id)
        if review is None:
            raise Invalid("review_required", None)
        fields = extraction_crypto.open_fields(review["fields"])
        spec = _spec(doc["doc_type"])
        date_field = DATE_FIELD.get(doc["doc_type"])
        if date_field and not fields.get(date_field):
            raise Invalid("date_required", date_field)
        extracted = extraction.latest(conn, document_id)
        total, changed = corrections(spec, extracted and extracted["fields"], fields)
        now = conn.execute("SELECT clock_timestamp()").fetchone()[0]
        ids = []
        for event_type, event_date, payload in events_for(doc["doc_type"], fields):
            ids.append(events_provenance.append(
                conn, patient_id=doc["patient_id"], event_type=event_type, event_date=event_date, date_precision="day",
                actor_id=actor.id, actor_role=actor.role, source_type="document", source_document_id=document_id,
                verified_by=actor.id, verified_at=now, verification_status="document_verified", payload=payload)["id"])
        conn.execute(
            "INSERT INTO verifications (document_id, review_id, extraction_version, verified_by, verifier_role, fields_total, "
            "fields_corrected, corrections, event_ids) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            [document_id, review["id"], extracted and extracted["version"], actor.id, actor.role, total, len(changed),
             Jsonb(extraction_crypto.seal_fields(changed)), ids])
        documents.set_status(conn, document_id, "verified")
        conn.execute("UPDATE documents SET verified_by = %s WHERE id = %s", [actor.id, document_id])
        audit.append(conn, action="document.confirm", result="allow", actor_id=actor.id, actor_role=actor.role,
                     patient_id=doc["patient_id"], resource_type="document", resource_id=document_id,
                     reason=f"{len(ids)} events; {len(changed)} of {total} fields corrected", **(context or {}))
        return ids


def reject(conn, document_id, *, actor, context=None):
    """needs_review -> rejected. No event is written."""
    with conn.transaction():
        doc = _in_review(conn, document_id)
        documents.set_status(conn, document_id, "rejected")
        audit.append(conn, action="document.reject", result="allow", actor_id=actor.id, actor_role=actor.role,
                     patient_id=doc["patient_id"], resource_type="document", resource_id=document_id, **(context or {}))
