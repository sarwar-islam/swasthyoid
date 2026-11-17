"""M5 doctor summary (P3; FRD M5, section 8.4; owner decisions D1-D3, D8 and correction 2, 2026-11-17).

Built only from the events the caller may see: current (not superseded) `document_verified` events, plus
`patient_reported` vital readings in their own section. Every sentence carries `facts`: each value it states, the event
it comes from and the field. The text is those values as written, nothing added, so the template summary can never state
what its cited events do not hold. The provenance validator (validate.py) checks this for the template and for any LLM
text alike. Nothing is coded, interpreted, merged or ranked as clinically important:
- "Medications recorded" (D3): every recorded medication with its date and the duration as written; never "active".
- Diagnoses are not recorded (D2, D7 Q4): the section says so and lists nothing.
- Labs: one line per result, grouped by the test name as written and in date order; no trend is computed.
- Follow-ups: dates on or after today (server date): a date comparison, not a clinical judgement.
REVIEWER-PENDING: what counts as "recent" (no window: everything is listed, newest first, up to SECTION_LIMIT).
shortcut: no cache (D8: template summaries are cheap and always fresh); add one keyed by (patient, events version,
consent scope) only when an integrated LLM makes a summary slow.
"""
from datetime import date

from swasthyoid.core import events_provenance

SECTION_IDS = ("medications_recorded", "allergies", "diagnoses", "labs", "visits", "follow_ups")
SECTION_LIMIT = 50  # engineering limit per section, not a clinical value; `truncated` says how many were left out

# The payload fields each section states, in this order, exactly as the M3 mapping wrote them (verification/review.py).
FIELDS = {
    "medication": ("name_as_written", "strength", "form", "dose_instruction", "duration"),
    "allergy": ("allergy_text",),
    "lab_result": ("test_name", "result", "unit", "reference_range"),
    "visit": ("facility_name", "admission_date", "discharge_date"),
    "follow_up": ("follow_up_date",),
}
SECTION_OF = {"medication": "medications_recorded", "allergy": "allergies", "lab_result": "labs", "visit": "visits",
              "follow_up": "follow_ups"}


def permitted_events(conn, patient_id):
    """The events a summary or search may use: current verified events and current patient-reported readings (D10).
    Raw store read: the route has passed RBAC -> C1 -> C2."""
    return [e for e in events_provenance.current_events(conn, patient_id)
            if e["verification_status"] == "document_verified"
            or (e["verification_status"] == "patient_reported" and e["event_type"] == "vital_reading")]


def _value(v):
    return v.strip() if isinstance(v, str) and v.strip() else str(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def sentence(event, fields):
    """One cited line: the event's values as written, then its date. Fields with no value are left out."""
    eid = str(event["id"])
    facts = [{"event_id": eid, "field": f, "value": _value(event["payload"].get(f))} for f in fields]
    facts = [f for f in facts if f["value"] is not None]
    facts.append({"event_id": eid, "field": "date", "value": event["event_date"].isoformat()})
    return {"text": " · ".join(f["value"] for f in facts), "citations": [eid], "facts": facts}


def _newest_first(events):
    return sorted(events, key=lambda e: (e["event_date"], e["recorded_at"], str(e["id"])), reverse=True)


def template(events, today: date):
    """The deterministic template summary (mode `template`) from already-permitted events."""
    verified = [e for e in events if e["verification_status"] == "document_verified"]
    by_section = {s: [] for s in SECTION_IDS}
    for e in _newest_first(verified):
        section = SECTION_OF.get(e["event_type"])
        if section == "follow_ups" and e["event_date"] < today:
            continue
        if section:
            by_section[section].append(e)
    # labs: grouped by test name as written (case and spacing aside), each group in date order: values side by side
    by_section["labs"].sort(key=lambda e: (" ".join(str(e["payload"].get("test_name") or "").casefold().split()),
                                           e["event_date"], e["recorded_at"], str(e["id"])))
    sections = []
    for sid in SECTION_IDS:
        rows = by_section[sid]
        sections.append({"id": sid, "note": "not_recorded" if sid == "diagnoses" else None,
                         "sentences": [sentence(e, FIELDS[e["event_type"]]) for e in rows[:SECTION_LIMIT]],
                         "truncated": max(0, len(rows) - SECTION_LIMIT)})
    return {"mode": "template", "sections": sections, "patient_reported": patient_reported(events)}


def patient_reported(events):
    """Home readings, separate and never interpreted: values and dates only (FRD M5), in every mode."""
    readings = [e for e in _newest_first(events) if e["verification_status"] == "patient_reported"]
    return [sentence(e, tuple(sorted(e["payload"]))) for e in readings[:SECTION_LIMIT]]
