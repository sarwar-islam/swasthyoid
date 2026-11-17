"""M10 emergency profile and card (B7; FRD M10, owner decisions 2026-11-17).

The patient turns the profile on and picks the fields. The card is built from verified events when a session opens and
shows only those fields. REVIEWER-PENDING (owner decision 2): only allergies come from events, as written. There is no
blood-group event, diagnoses never become events (D7 Q4), and which medications are "active" and which conditions are
"long-term" needs the clinical reviewer's rules, so those stay empty; nothing clinical is decided here.
"""
import json

from swasthyoid import pii
from swasthyoid.core import audit, events_provenance

FIELDS = ("blood_group", "allergies", "active_medications", "conditions", "emergency_contacts")


class Invalid(Exception):
    """args[0]: invalid_profile or invalid_contact."""


def available(conn, patient_id):
    allergies = [e["payload"]["allergy_text"] for e in events_provenance.current_events(conn, patient_id)
                 if e["event_type"] == "allergy" and e["verification_status"] == "document_verified"
                 and e["payload"].get("allergy_text")]
    return {"blood_group": None, "allergies": allergies, "active_medications": [], "conditions": []}


def read(conn, patient_id):
    row = conn.execute("SELECT enabled, fields, contacts_enc FROM emergency_profiles WHERE patient_id = %s",
                       [patient_id]).fetchone()
    enabled, fields, sealed = row or (False, [], None)
    return {"enabled": enabled, "fields": list(fields), "contacts": json.loads(pii.decrypt(sealed)) if sealed else [],
            "available": available(conn, patient_id)}


def _contacts(value):
    if not isinstance(value, list):
        raise Invalid("invalid_profile")
    out = []
    for c in value:
        name = c.get("name") if isinstance(c, dict) else None
        if not isinstance(name, str) or not name.strip() or not isinstance(c.get("phone"), str):
            raise Invalid("invalid_contact")
        try:
            out.append({"name": name.strip(), "phone": pii.normalize_phone(c["phone"])})
        except ValueError:
            raise Invalid("invalid_contact") from None
    return out


def save(conn, patient_id, body, *, actor):
    """{ enabled, fields, contacts }, replacing the profile. Audited; the audit entry holds no field value or contact."""
    if not isinstance(body, dict) or not isinstance(body.get("enabled"), bool):
        raise Invalid("invalid_profile")
    fields = body.get("fields", [])
    if not isinstance(fields, list) or not all(f in FIELDS for f in fields) or len(set(fields)) != len(fields):
        raise Invalid("invalid_profile")
    contacts = _contacts(body.get("contacts", []))
    with conn.transaction():
        conn.execute(
            "INSERT INTO emergency_profiles (patient_id, enabled, fields, contacts_enc) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (patient_id) DO UPDATE SET enabled = EXCLUDED.enabled, fields = EXCLUDED.fields, "
            "contacts_enc = EXCLUDED.contacts_enc, updated_at = clock_timestamp()",
            [patient_id, body["enabled"], fields, pii.encrypt(json.dumps(contacts)) if contacts else None])
        audit.append(conn, action="emergency.profile.update", result="allow", actor_id=actor.id, actor_role=actor.role,
                     device_id=actor.device_id, patient_id=patient_id)
    return read(conn, patient_id)


def card(conn, patient_id):
    """The card for a break-glass session: only the fields the patient chose, or None when the profile is off."""
    p = read(conn, patient_id)
    if not p["enabled"]:
        return None
    values = {**p["available"], "emergency_contacts": p["contacts"]}
    return {f: values[f] for f in p["fields"] if values[f] is not None}
