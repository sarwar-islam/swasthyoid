"""The patient's C3 in-app inbox (B3; FRD 4.3, owner decisions 2026-11-16).

Notices only: nothing here grants access. Rows hold a template and the consent id; names and categories are resolved
when read, so a notice never stores a name, a code or a token. Consent, caregiver and emergency-access notices cannot be
switched off; the patient can only mark them read. A notice about a request that later closed stays as history.
"""
from uuid import UUID

from fastapi import APIRouter, Depends

from swasthyoid.api.deps import Actor, ApiError, get_conn, person_labels, require
from swasthyoid.core import notification

router = APIRouter()
patient_only = require("patient")


def _views(conn, rows):
    rows = [r for r in rows if r["template_id"] in notification.INBOX_KINDS]
    ids = {r["payload"].get("consent_id") for r in rows} - {None}
    consents = {str(c[0]): c for c in conn.execute(
        "SELECT id, grantee_id, allowed_categories FROM consents WHERE id = ANY(%s::uuid[])", [list(ids)]).fetchall()}
    sessions = {r["payload"].get("session_id") for r in rows} - {None}  # emergency_access (M10, B7): the doctor's name
    doctors = {str(s[0]): s[1] for s in conn.execute(
        "SELECT id, doctor_id FROM emergency_sessions WHERE id = ANY(%s::uuid[])", [list(sessions)]).fetchall()}
    grantees = {c[1] for c in consents.values()} | set(doctors.values())
    names = dict(conn.execute("SELECT id, name FROM users WHERE id = ANY(%s)", [list(grantees)]).fetchall())
    names.update({k: v["name"] for k, v in person_labels(conn, grantees - set(names)).items()})
    out = []
    for r in rows:
        c = consents.get(r["payload"].get("consent_id"))
        actor = c[1] if c else doctors.get(r["payload"].get("session_id"))
        out.append({"id": r["id"], "kind": notification.INBOX_KINDS[r["template_id"]], "created_at": r["created_at"],
                    "read_at": r["read_at"], "actor_name": names.get(actor),
                    "categories": c[2] if c else [], "facility": r["payload"].get("facility")})
    return out


@router.get("/notifications")
def list_notifications(conn=Depends(get_conn), a: Actor = Depends(patient_only)):
    return _views(conn, notification.inbox(conn, a.id))


@router.post("/notifications/{notification_id}/read")
def read_notification(notification_id: UUID, conn=Depends(get_conn), a: Actor = Depends(patient_only)):
    row = notification.mark_read(conn, notification_id, a.id)
    views = _views(conn, [row]) if row else []
    if not views:  # someone else's, unknown, or not an inbox notice: one answer
        raise ApiError(404, "not_found", "No notification with this id.")
    return views[0]
