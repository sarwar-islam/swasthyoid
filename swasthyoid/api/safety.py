"""M6 safety alerts and M13 threshold overrides for the treating doctor (B6; FRD section 7, invariant 6).

GET /patients/{id}/safety-alerts (approved 2026-11-16), POST /safety/alerts/{id}/ack { action, reason } (FRD),
GET (GAP, approved) and PUT /patients/{id}/vital-thresholds (FRD), and GET /patients/{id}/safety-checks (P3, D6:
proposal, not in FRD section 7 yet). A verified doctor only, and only under a TIMELINE consent
covering `safety`: RBAC -> C1 -> C2 before anything is read. Patients never see raw M6 alerts, so unlike patient_read the
patient's own access does not pass here; caregivers, verifiers and console roles are refused too.
"""
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Request

from swasthyoid.api.deps import Actor, ApiError, authorize_patient_access, get_conn, require
from swasthyoid.core import consent_authz
from swasthyoid.safety import alerts, checks, thresholds

router = APIRouter()
doctor = require("doctor")


def _consented(request, conn, a, patient_id):
    authorize_patient_access(request, conn, a, patient_id, "TIMELINE", ("safety",))


@router.get("/patients/{patient_id}/safety-alerts")
def list_alerts(patient_id: UUID, request: Request, conn=Depends(get_conn), a: Actor = Depends(doctor)):
    _consented(request, conn, a, patient_id)
    return [alerts.view(r) for r in alerts.for_patient(conn, patient_id)]


@router.get("/patients/{patient_id}/safety-checks")
def list_checks(patient_id: UUID, request: Request, conn=Depends(get_conn), a: Actor = Depends(doctor)):
    """P3 (D6): each verified prescription's M6 check: queued, retrying, completed, blocked or failed, with the
    unrecognised medications and the checks that could not run. Names as written only when the consent also covers
    `timeline`; otherwise event ids and codes."""
    _consented(request, conn, a, patient_id)
    named = consent_authz.covers(conn, user=a, patient_id=patient_id, purpose="TIMELINE", category="timeline")
    rows = checks.for_patient(conn, patient_id)
    ids = [u["event_id"] for r in rows for u in (r["unrecognised"] or [])]
    names = dict(conn.execute("SELECT id::text, payload->>'name_as_written' FROM events WHERE id::text = ANY(%s) "
                              "AND patient_id = %s", [ids, patient_id]).fetchall()) if named and ids else {}
    return [{"document_id": r["document_id"], "status": checks.status(r), "reason": r["reason"], "attempts": r["attempts"],
             "queued_at": r["created_at"], "checked_at": r["checked_at"], "alert_count": len(r["alert_ids"] or []),
             "unrecognised": [{**u, "name_as_written": names.get(u["event_id"])} for u in (r["unrecognised"] or [])],
             "not_run": r["not_run"] or []} for r in rows]


@router.post("/safety/alerts/{alert_id}/ack")
def ack_alert(alert_id: UUID, request: Request, body: dict | None = Body(None), conn=Depends(get_conn),
              a: Actor = Depends(doctor)):
    try:
        patient_id = alerts.patient_of(conn, alert_id)
    except LookupError:
        raise ApiError(404, "not_found", "No alert with this id.")
    _consented(request, conn, a, patient_id)
    body = body or {}
    try:
        return alerts.view(alerts.handle(conn, alert_id, doctor=a, action=body.get("action"), reason=body.get("reason")))
    except alerts.Invalid as e:
        raise ApiError(422, e.args[0], "Acknowledge, or override with a reason.")
    except alerts.NotOpen:
        raise ApiError(409, "not_open", "This alert was already handled.")


@router.get("/patients/{patient_id}/vital-thresholds")
def read_thresholds(patient_id: UUID, request: Request, conn=Depends(get_conn), a: Actor = Depends(doctor)):
    _consented(request, conn, a, patient_id)
    return thresholds.read(conn, patient_id)


@router.put("/patients/{patient_id}/vital-thresholds")
def update_thresholds(patient_id: UUID, request: Request, body: dict | None = Body(None), conn=Depends(get_conn),
                      a: Actor = Depends(doctor)):
    _consented(request, conn, a, patient_id)
    try:
        return thresholds.update(conn, patient_id, body, doctor=a)
    except thresholds.Invalid:
        raise ApiError(422, "invalid_threshold", "Check the fields and values.")
    except thresholds.Conflict:
        raise ApiError(409, "version_conflict", "Someone changed these thresholds. Reload them.")
