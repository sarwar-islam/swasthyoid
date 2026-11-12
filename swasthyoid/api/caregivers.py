"""Caregiver-assisted access: request, approve, decline, list (DECISIONS.md, "Caregiver access").

A caregiver is an ordinary person account. They ask; only the patient can authorise, either
signed in to the app (approve) or by reading out the code sent to the patient's own phone
(confirm). Revoking is the existing POST /consents/{id}/revoke. Rules live in core/.

Health IDs must not be guessable from this API: asking and confirming answer the same way
whether or not the Health ID exists, no request id is returned, pending requests are not
listed to the caregiver, limits count attempts not hits, and responses take a minimum time.
"""
import logging
import time
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from pydantic import BaseModel, Field

from swasthyoid import pii
from swasthyoid.api.deps import Actor, ApiError, client_info, get_code_sender, get_conn, idempotent, person_labels, require
from swasthyoid.api.m1 import CONSENT_VERSION, POLICY_VERSION
from swasthyoid.core import audit, consent_authz, notification
from swasthyoid.identity import otp

router = APIRouter()
log = logging.getLogger(__name__)

# Configurable security defaults, PROVISIONAL, not FRD values (docs/DECISIONS.md).
RESPONSE_FLOOR = 0.3          # seconds; request and confirm never answer faster than this
MAX_CODES_PER_REQUEST = 3
MAX_REQUESTS = 5              # attempts per caregiver, whether or not the Health ID exists ...
REQUEST_WINDOW_MINUTES = 15   # ... within this window

Scope = Literal["upload_documents", "view_documents", "view_timeline"]


class RequestBody(BaseModel):
    patient_health_id: str
    scopes: list[Scope] = Field(min_length=1)
    duration_days: int = Field(consent_authz.CAREGIVER_DEFAULT_DAYS, ge=1, le=consent_authz.CAREGIVER_MAX_DAYS)


class ConfirmBody(BaseModel):
    patient_health_id: str
    code: str


def _floor(started):
    remaining = RESPONSE_FLOOR - (time.monotonic() - started)
    if remaining > 0:
        time.sleep(remaining)


def _deliver(send, phone, code, context):
    try:
        send(phone, code, context)
    except Exception as e:  # never let a delivery problem, or the code, reach the logs
        log.error("code delivery failed: %s", type(e).__name__)


def _patient(conn, health_id, not_id):
    row = conn.execute("SELECT id, phone_enc FROM patients WHERE health_id = %s", [health_id]).fetchone()
    return None if row is None or row[0] == not_id else row


def _view(row, **extra):
    return {
        "id": row["id"], "patient_id": row["patient_id"], "caregiver_id": row["grantee_id"],
        "scopes": row["allowed_categories"], "status": row["status"],
        "requested_days": row["requested_ttl"].days, "activated_at": row["activated_at"],
        "expires_at": row["expires_at"], **extra,
    }


def _granted(conn, row):
    notification.enqueue(conn, recipient_id=row["patient_id"], template_id="CAREGIVER_GRANTED_PLACEHOLDER",
                         payload={"consent_id": str(row["id"])})


@router.post("/caregiver-authorizations", status_code=202)
def request_authorization(body: RequestBody, request: Request, background: BackgroundTasks,
                          conn=Depends(get_conn), send=Depends(get_code_sender),
                          a: Actor = Depends(require("patient"))):
    """Ask to act for a patient. Always 202 {"status": "pending"}; grants nothing. The patient
    sees who is asking, for which scopes and for how long, in the app and in the code message."""
    started = time.monotonic()
    info = {"actor_id": a.id, "actor_role": "caregiver", "device_id": a.device_id, **client_info(request)}

    def work():
        recent = conn.execute(
            "SELECT count(*) FROM audit_logs WHERE action = 'caregiver.request' AND actor_id = %s "
            "AND at > clock_timestamp() - make_interval(mins => %s)",
            [a.id, REQUEST_WINDOW_MINUTES],
        ).fetchone()[0]
        if recent >= MAX_REQUESTS:
            raise ApiError(429, "too_many_requests", "Too many requests. Try again later.")
        patient = _patient(conn, body.patient_health_id, a.id)
        if patient is None:
            audit.append(conn, action="caregiver.request", result="deny", reason="no_such_patient", **info)
            return {"status": "pending"}
        row, created = consent_authz.request_caregiver(
            conn, patient_id=patient[0], caregiver_id=a.id, scopes=body.scopes, days=body.duration_days,
            consent_version=CONSENT_VERSION, policy_version=POLICY_VERSION,
        )
        audit.append(conn, action="caregiver.request", result="allow", patient_id=patient[0],
                     consent_id=row["id"], purpose="CAREGIVER", **info)
        if created:
            notification.enqueue(conn, recipient_id=patient[0], template_id="CAREGIVER_REQUEST_PLACEHOLDER",
                                 payload={"consent_id": str(row["id"])})
        try:
            phone, code = otp.create_code(conn, pii.decrypt(patient[1]), "caregiver", str(row["id"]),
                                          max_per_ref=MAX_CODES_PER_REQUEST)
        except otp.TooManyRequests:
            return {"status": "pending"}  # same answer; the limit is not revealed
        me = person_labels(conn, [a.id])[a.id]
        # Sent after the response, so gateway latency cannot reveal that the Health ID exists.
        background.add_task(_deliver, send, phone, code, {
            "caregiver_name": me["name"], "caregiver_phone_tail": me["phone_tail"],
            "scopes": sorted(row["allowed_categories"]), "days": row["requested_ttl"].days,
        })
        return {"status": "pending"}

    try:
        return idempotent(conn, request, a, body, work)
    finally:
        _floor(started)


@router.post("/caregiver-authorizations/confirm")
def confirm_authorization(body: ConfirmBody, request: Request, conn=Depends(get_conn),
                          a: Actor = Depends(require("patient"))):
    """The caregiver enters the code the patient read out from the patient's own phone.
    Every failure is the same 403 invalid_code."""
    started = time.monotonic()
    invalid = ApiError(403, "invalid_code", "The code is wrong or has expired.")

    def work():
        patient = _patient(conn, body.patient_health_id, a.id)
        row = patient and consent_authz.pending_caregiver_request(conn, patient_id=patient[0], caregiver_id=a.id)
        if not row:
            audit.append(conn, action="auth.otp_failed", result="deny", reason="no_pending_request",
                         actor_id=a.id, **client_info(request))
            raise invalid
        if not otp.verify_code(conn, pii.decrypt(patient[1]), body.code, kind="caregiver", ref=str(row["id"]),
                               actor_id=a.id, patient_id=patient[0]):
            raise invalid
        try:
            with conn.transaction():
                row = consent_authz.approve_caregiver(conn, row["id"], patient_id=patient[0], method="OTP")
                _granted(conn, row)
        except (LookupError, ValueError):
            raise invalid
        return _view(row)

    try:
        return idempotent(conn, request, a, body, work)
    finally:
        _floor(started)


@router.post("/caregiver-authorizations/{consent_id}/approve")
def approve_authorization(consent_id: UUID, request: Request, conn=Depends(get_conn),
                          a: Actor = Depends(require("patient"))):
    """The patient, signed in, approves a request shown in GET /consents."""

    def work():
        consent_authz.expire_stale_requests(conn, a.id)  # the 24-hour window is enforced here, not by a job
        try:
            with conn.transaction():
                row = consent_authz.approve_caregiver(conn, consent_id, patient_id=a.id, method="in-app")
                _granted(conn, row)
        except LookupError:
            raise ApiError(404, "not_found", "No caregiver request with this id.")
        except ValueError:
            raise ApiError(409, "not_pending", "This request is no longer open.")
        return _view(row)

    return idempotent(conn, request, a, None, work)


@router.post("/caregiver-authorizations/{consent_id}/decline")
def decline_authorization(consent_id: UUID, request: Request, conn=Depends(get_conn),
                          a: Actor = Depends(require("patient"))):
    def work():
        row = consent_authz.get(conn, consent_id)
        if row is None or row["purpose"] != "CAREGIVER" or row["patient_id"] != a.id:
            raise ApiError(404, "not_found", "No caregiver request with this id.")
        try:
            return _view(consent_authz.decline(conn, consent_id, actor_id=a.id))
        except ValueError:
            raise ApiError(409, "not_pending", "This request is no longer open.")

    return idempotent(conn, request, a, None, work)


@router.get("/caregiver-authorizations")
def my_patients(conn=Depends(get_conn), a: Actor = Depends(require("patient"))):
    """Patients the caller may act for right now, with scopes and expiry."""
    rows = consent_authz.list_for_caregiver(conn, a.id)
    people = person_labels(conn, {r["patient_id"] for r in rows})
    return [_view(r, patient_name=people[r["patient_id"]]["name"]) for r in rows]
