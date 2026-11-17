"""M10 emergency access behind a server flag, off by default (B7; FRD M10, section 7; owner decisions 2026-11-16/17).

Unless EMERGENCY_ACCESS_ENABLED=1, every route here is refused with 403 emergency_not_enabled, and the refusal audited.
- GET (GAP, approved) and PUT /me/emergency-profile: the patient.
- POST /emergency/access { health_id, reason, facility }: a verified doctor with emergency capability. C1's emergency
  policy writes the audit entry first (core.consent_authz.check_emergency); only then is the card built.
- GET /admin/emergency/reviews, POST /admin/emergency/reviews/{id}/review { decision, note }: a verified clinical reviewer.
- POST /admin/users/{id}/emergency { enabled } (GAP, owner decision 1): an admin.
"""
import math
import os
from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Request

from swasthyoid.api.deps import Actor, ApiError, client_info, get_conn, require
from swasthyoid.core import audit, consent_authz
from swasthyoid.emergency import profile, sessions
from swasthyoid.identity import accounts

router = APIRouter()
_REFUSED = {"reason_required": (422, "A reason and a facility are required."),
            "patient_not_found": (404, "No patient has this Health ID.")}


def enabled():
    return os.environ.get("EMERGENCY_ACCESS_ENABLED") == "1"


def _flag(request, conn, a):
    if not enabled():
        audit.append(conn, action="emergency.refused", result="deny", reason="emergency_not_enabled", actor_id=a.id,
                     actor_role=a.role, device_id=a.device_id, **client_info(request))
        raise ApiError(403, "emergency_not_enabled", "Emergency access is not enabled.")


def _length():
    try:  # FRD M10: "default 2 hours, configurable" (owner decision 4)
        minutes = float(os.environ.get("EMERGENCY_SESSION_MINUTES", "120"))
        if not (math.isfinite(minutes) and minutes > 0):
            raise ValueError
        return timedelta(minutes=minutes)
    except ValueError:
        raise ApiError(503, "not_configured", "EMERGENCY_SESSION_MINUTES is not a positive number.")


# ---- the patient's profile

@router.get("/me/emergency-profile")
def read_profile(request: Request, conn=Depends(get_conn), a: Actor = Depends(require("patient"))):
    _flag(request, conn, a)
    return profile.read(conn, a.id)


@router.put("/me/emergency-profile")
def save_profile(request: Request, body: dict | None = Body(None), conn=Depends(get_conn),
                 a: Actor = Depends(require("patient"))):
    _flag(request, conn, a)
    try:
        return profile.save(conn, a.id, body, actor=a)
    except profile.Invalid as e:
        raise ApiError(422, e.args[0], "Check the fields and each contact's name and Bangladesh mobile number.")


# ---- break-glass

@router.post("/emergency/access", status_code=201)
def break_glass(request: Request, body: dict | None = Body(None), conn=Depends(get_conn),
                a: Actor = Depends(require("doctor"))):
    body = body or {}
    length = _length() if enabled() else None
    health_id = body.get("health_id")
    patient = conn.execute("SELECT id FROM patients WHERE health_id = %s", [health_id]).fetchone() \
        if isinstance(health_id, str) else None
    reason, facility = body.get("reason"), body.get("facility")
    decision = consent_authz.check_emergency(
        conn, user=a, patient_id=patient and patient[0], reason=reason, facility=facility, enabled=enabled(),
        action="emergency.access", device_id=a.device_id, **client_info(request))
    if not decision.allowed:
        status, message = _REFUSED.get(decision.reason, (403, "You are not allowed to do this."))
        raise ApiError(status, decision.reason, message)
    row, card = sessions.start(conn, doctor_id=a.id, patient_id=patient[0], reason=reason, facility=facility,
                               length=length)
    return {"session_id": row["id"], "expires_at": row["ends_at"], "card": card}


# ---- post-hoc review (clinical reviewer) and the doctor's capability (admin)

@router.get("/admin/emergency/reviews")
def list_reviews(request: Request, conn=Depends(get_conn), a: Actor = Depends(require("clinical_reviewer"))):
    _flag(request, conn, a)
    audit.append(conn, action="emergency.review.read", result="allow", actor_id=a.id, actor_role=a.role,
                 device_id=a.device_id, **client_info(request))
    return [sessions.view(r) for r in sessions.closed(conn)]


@router.post("/admin/emergency/reviews/{session_id}/review")
def review_session(session_id: UUID, request: Request, body: dict | None = Body(None), conn=Depends(get_conn),
                   a: Actor = Depends(require("clinical_reviewer"))):
    _flag(request, conn, a)
    body = body or {}
    try:
        return sessions.view(sessions.review(conn, session_id, reviewer=a, decision=body.get("decision"),
                                             note=body.get("note")))
    except sessions.Invalid as e:
        raise ApiError(422, e.args[0], "Justified, or unjustified with a note.")
    except sessions.NotPending:
        raise ApiError(409, "not_pending", "This session was already reviewed.")
    except LookupError:
        raise ApiError(404, "not_found", "No closed session with this id.")


@router.post("/admin/users/{user_id}/emergency")
def set_capability(user_id: UUID, request: Request, body: dict | None = Body(None), conn=Depends(get_conn),
                   a: Actor = Depends(require("admin"))):
    _flag(request, conn, a)
    value = (body or {}).get("enabled")
    if not isinstance(value, bool):
        raise ApiError(422, "invalid_request", "Send enabled: true or false.")
    try:
        accounts.set_emergency(conn, user_id, admin_id=a.id, enabled=value)
    except ValueError:
        raise ApiError(404, "not_found", "No verified doctor with this id.")
    return {"user_id": user_id, "emergency_enabled": value}
