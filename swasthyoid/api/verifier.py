"""Verifier (CHW) assisted sessions (B4b; FRD M3, question 3; owner decisions 2026-11-16).

The verifier enters the patient's Health ID; a one-time code goes to the patient's own phone; the present patient reads it
out; only then does a short session open, for this verifier and this patient. The code is single use, lives as long as any
one-time code and dies after its wrong tries; no response or audit entry carries it. The session length is the
REVIEWER-PENDING setting ASSIST_SESSION_MINUTES, with no default: sessions refuse to open (503) until it is set.
In the session the verifier may upload, list the documents not yet verified and check them (api/documents.py); never the
timeline, verified content, consent or access history. Every step is audited to the patient's access history by C1.
"""
import os
from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from swasthyoid import pii
from swasthyoid.api.deps import Actor, ApiError, get_code_sender, get_conn, idempotent, require
from swasthyoid.api.m1 import CONSENT_VERSION, POLICY_VERSION
from swasthyoid.core import consent_authz
from swasthyoid.identity import otp

router = APIRouter()
verifier = require("verifier")


def _minutes():
    # REVIEWER-PENDING: how long a verifier may work after the patient's code. No default (owner decision 2026-11-16).
    try:
        minutes = float(os.environ["ASSIST_SESSION_MINUTES"])
        if minutes <= 0:
            raise ValueError
        return timedelta(minutes=minutes)
    except (KeyError, ValueError):
        raise ApiError(503, "not_configured", "ASSIST_SESSION_MINUTES is not set.")


class StartBody(BaseModel):
    health_id: str


class CodeBody(BaseModel):
    code: str


def _view(conn, row):
    health_id = conn.execute("SELECT health_id FROM patients WHERE id = %s", [row["patient_id"]]).fetchone()[0]
    return {"id": row["id"], "purpose": row["purpose"], "status": row["status"], "health_id": health_id,
            "patient_id": row["patient_id"] if row["status"] == "active" else None,  # known to the verifier only once open
            "activated_at": row["activated_at"], "expires_at": row["expires_at"]}


def _own(conn, a, session_id):
    row = consent_authz.get(conn, session_id)
    if row is None or row["purpose"] != "ASSISTED_CAPTURE" or row["grantee_id"] != a.id:
        raise ApiError(404, "not_found", "No session with this id.")
    return row


@router.post("/verifier/sessions", status_code=201)
def start(body: StartBody, request: Request, conn=Depends(get_conn), send=Depends(get_code_sender),
          a: Actor = Depends(verifier)):
    def work():
        _minutes()
        patient = conn.execute("SELECT id, phone_enc FROM patients WHERE health_id = %s",
                               [body.health_id.strip().upper()]).fetchone()
        if patient is None:  # staff are vetted, so an unknown Health ID is said plainly, as for a doctor
            raise ApiError(404, "patient_not_found", "No patient has this Health ID.")
        with conn.transaction():
            consent_authz.expire_pending_sessions(conn, grantee_id=a.id, patient_id=patient[0])
            row = consent_authz.create(
                conn, patient_id=patient[0], grantee_id=a.id, grantee_role="verifier", purpose="ASSISTED_CAPTURE",
                allowed_categories=consent_authz.ASSIST_CATEGORIES, consent_version=CONSENT_VERSION,
                policy_version=POLICY_VERSION, actor_id=a.id, method="OTP")
        try:
            otp.request_code(conn, pii.decrypt(patient[1]), send, kind="assist", ref=str(row["id"]))
        except otp.TooManyRequests:
            raise ApiError(429, "too_many_requests", "Too many codes sent to this patient. Try again later.")
        return _view(conn, row)

    return idempotent(conn, request, a, body, work)


@router.post("/verifier/sessions/{session_id}/confirm")
def confirm(session_id: UUID, body: CodeBody, request: Request, conn=Depends(get_conn), a: Actor = Depends(verifier)):
    def work():
        lifetime = _minutes()
        row = _own(conn, a, session_id)
        invalid = ApiError(403, "invalid_code", "The code is wrong or has expired.")
        if row["status"] != "pending":
            raise invalid
        phone = pii.decrypt(conn.execute("SELECT phone_enc FROM patients WHERE id = %s", [row["patient_id"]]).fetchone()[0])
        if not otp.verify_code(conn, phone, body.code, kind="assist", ref=str(session_id), actor_id=a.id,
                               actor_role=a.role, patient_id=row["patient_id"], consent_id=session_id):
            raise invalid  # every failure looks the same, and is audited by verify_code
        now = conn.execute("SELECT clock_timestamp()").fetchone()[0]
        return _view(conn, consent_authz.activate(conn, session_id, method="OTP", expires_at=now + lifetime,
                                                  actor_id=row["patient_id"]))

    return idempotent(conn, request, a, body, work)


@router.post("/verifier/sessions/{session_id}/end")
def end(session_id: UUID, conn=Depends(get_conn), a: Actor = Depends(verifier)):
    _own(conn, a, session_id)
    return _view(conn, consent_authz.end_session(conn, session_id, grantee_id=a.id))
