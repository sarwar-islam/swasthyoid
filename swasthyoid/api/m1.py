"""M1 endpoints: login, credentials and the Consent Center (FRD M1, section 7).

Handlers only orchestrate; the rules live in core/ and identity/.
"""
import os
from datetime import date, timedelta
from typing import Literal
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from swasthyoid import pii
from swasthyoid.api.deps import (
    Actor, ApiError, client_info, get_code_sender, get_conn, idempotent, person_labels, require,
)
from swasthyoid.core import audit, consent_authz, notification
from swasthyoid.identity import accounts, otp, sessions

router = APIRouter()

# LEGAL-PENDING (FRD open question 8): versions of the consent wording and policy the patient saw.
CONSENT_VERSION = 0
POLICY_VERSION = "PLACEHOLDER"


def _consent_hours():
    # DECISION-PENDING: how long a TIMELINE consent lasts is not in the FRD, so there is no default.
    try:
        hours = float(os.environ["TIMELINE_CONSENT_HOURS"])
        if hours <= 0:
            raise ValueError
        return timedelta(hours=hours)
    except (KeyError, ValueError):
        raise ApiError(503, "not_configured", "TIMELINE_CONSENT_HOURS is not set.")


# ---- login

class PhoneBody(BaseModel):
    phone: str


class PatientProfile(BaseModel):
    name: str = Field(min_length=1)
    dob: date
    sex: str = Field(min_length=1)
    language: str = "bn"


class StaffProfile(BaseModel):
    role: Literal["doctor", "pharmacist", "verifier", "clinical_reviewer"]
    name: str = Field(min_length=1)


class VerifyBody(BaseModel):
    phone: str
    code: str
    device_id: str = Field(min_length=1)
    # DECISION-PENDING: one phone may hold a patient and a staff account; the client says which.
    account: Literal["patient", "staff"] = "patient"
    profile: PatientProfile | None = None   # needed the first time a patient logs in
    staff: StaffProfile | None = None       # needed the first time a staff member logs in


class RefreshBody(BaseModel):
    refresh_token: str
    device_id: str = Field(min_length=1)


@router.post("/auth/otp/request", status_code=204)
def otp_request(body: PhoneBody, conn=Depends(get_conn), send=Depends(get_code_sender)):
    try:
        otp.request_code(conn, body.phone, send)
    except ValueError:
        raise ApiError(422, "invalid_phone", "Enter a Bangladesh mobile number.")
    except otp.TooManyRequests:
        raise ApiError(429, "too_many_requests", "Too many codes requested. Try again later.")
    return Response(status_code=204)


@router.post("/auth/otp/verify")
def otp_verify(body: VerifyBody, request: Request, conn=Depends(get_conn)):
    if not otp.verify_code(conn, body.phone, body.code):
        raise ApiError(401, "invalid_code", "The code is wrong or has expired.")
    h = pii.phone_hash(body.phone)
    needs_profile = ApiError(409, "registration_required", "Request a new code and send your profile with it.")
    if body.account == "patient":
        row = conn.execute("SELECT id FROM patients WHERE phone_hash = %s", [h]).fetchone()
        if row is None:
            if body.profile is None:
                raise needs_profile
            row = (accounts.register_patient(conn, phone=body.phone, **body.profile.model_dump())["id"],)
        who, role = row[0], "patient"
    else:
        row = conn.execute("SELECT id, role, status FROM users WHERE phone_hash = %s", [h]).fetchone()
        if row is None:
            if body.staff is None:
                raise needs_profile
            new = accounts.register_user(conn, phone=body.phone, **body.staff.model_dump())
            row = (new["id"], new["role"], new["status"])
        who, role, status = row
        if status == "suspended":
            audit.append(conn, action="auth.login", result="deny", reason="user_suspended", actor_id=who,
                         actor_role=role, device_id=body.device_id, **client_info(request))
            raise ApiError(403, "user_suspended", "This account is suspended.")
    return sessions.issue_tokens(conn, subject_id=who, role=role, device_id=body.device_id, **client_info(request))


@router.post("/auth/refresh")
def refresh(body: RefreshBody, conn=Depends(get_conn)):
    try:
        return sessions.refresh(conn, body.refresh_token, body.device_id)
    except sessions.InvalidSession:
        raise ApiError(401, "invalid_session", "Log in again.")


# ---- credentials

class CredentialBody(BaseModel):
    type: str = Field(min_length=1)
    number: str = Field(min_length=1)
    doc_key: str | None = None


@router.post("/credentials", status_code=201)
def submit_credential(body: CredentialBody, request: Request, conn=Depends(get_conn),
                      a: Actor = Depends(require("doctor", "pharmacist", verified=False))):
    def work():
        try:
            row = accounts.submit_credential(conn, user_id=a.id, **body.model_dump())
        except psycopg.errors.UniqueViolation:
            raise ApiError(409, "credential_exists", "This credential number is already registered.")
        return {"id": row["id"], "status": row["status"]}

    return idempotent(conn, request, a, body, work)


@router.post("/credentials/{credential_id}/approve")
def approve_credential(credential_id: UUID, request: Request, conn=Depends(get_conn),
                       a: Actor = Depends(require("admin"))):
    def work():
        try:
            user_id = accounts.approve_credential(conn, credential_id, admin_id=a.id)
        except ValueError:
            raise ApiError(404, "not_found", "No pending credential with this id.")
        return {"user_id": user_id, "status": "verified"}

    return idempotent(conn, request, a, None, work)


# ---- Consent Center

class ConsentRequestBody(BaseModel):
    health_id: str
    categories: list[Literal["timeline", "documents", "safety"]] = Field(min_length=1)


class CodeBody(BaseModel):
    code: str


def _view(row):
    keys = ("id", "grantee_id", "grantee_role", "purpose", "allowed_categories", "status",
            "activated_at", "expires_at", "created_at")
    return {k: row[k] for k in keys}


@router.post("/consents/requests", status_code=201)
def request_consent(body: ConsentRequestBody, request: Request, conn=Depends(get_conn),
                    send=Depends(get_code_sender), a: Actor = Depends(require("doctor"))):
    """A verified doctor asks for TIMELINE access by Health ID. The patient gets a one-time code."""

    def work():
        _consent_hours()
        patient = conn.execute("SELECT id, phone_enc FROM patients WHERE health_id = %s", [body.health_id]).fetchone()
        if patient is None:
            raise ApiError(404, "patient_not_found", "No patient has this Health ID.")
        row = consent_authz.create(
            conn, patient_id=patient[0], grantee_id=a.id, grantee_role=a.role, purpose="TIMELINE",
            allowed_categories=set(body.categories), consent_version=CONSENT_VERSION,
            policy_version=POLICY_VERSION, actor_id=a.id,
        )
        try:
            otp.request_code(conn, pii.decrypt(patient[1]), send, kind="consent", ref=str(row["id"]))
        except otp.TooManyRequests:
            raise ApiError(429, "too_many_requests", "Too many codes sent to this patient. Try again later.")
        return _view(row)

    return idempotent(conn, request, a, body, work)


@router.post("/consents/requests/{consent_id}/confirm")
def confirm_consent(consent_id: UUID, body: CodeBody, request: Request, conn=Depends(get_conn),
                    a: Actor = Depends(require("doctor"))):
    """The doctor enters the code the patient told them; only then does the consent become active."""

    def work():
        lifetime = _consent_hours()
        row = consent_authz.get(conn, consent_id)
        if row is None or row["grantee_id"] != a.id or row["status"] != "pending":
            raise ApiError(404, "not_found", "No pending consent request with this id.")
        phone = pii.decrypt(
            conn.execute("SELECT phone_enc FROM patients WHERE id = %s", [row["patient_id"]]).fetchone()[0])
        if not otp.verify_code(conn, phone, body.code, kind="consent", ref=str(consent_id)):
            raise ApiError(403, "invalid_code", "The code is wrong or has expired.")
        with conn.transaction():
            now = conn.execute("SELECT clock_timestamp()").fetchone()[0]
            row = consent_authz.activate(conn, consent_id, method="OTP", expires_at=now + lifetime,
                                         actor_id=row["patient_id"])
            notification.enqueue(conn, recipient_id=row["patient_id"], template_id="CONSENT_GRANTED_PLACEHOLDER",
                                 payload={"consent_id": str(consent_id)})
        return _view(row)

    return idempotent(conn, request, a, body, work)


def _names(conn, ids):
    return dict(conn.execute("SELECT id, name FROM users WHERE id = ANY(%s)", [list(ids)]).fetchall())


@router.get("/consents")
def list_consents(conn=Depends(get_conn), a: Actor = Depends(require("patient"))):
    consent_authz.expire_stale_requests(conn, a.id)
    rows = consent_authz.list_for_patient(conn, a.id)
    names = _names(conn, {r["grantee_id"] for r in rows})
    people = person_labels(conn, {r["grantee_id"] for r in rows if r["purpose"] == "CAREGIVER"})
    return [{
        **_view(r),
        "grantee_name": names.get(r["grantee_id"]) or people.get(r["grantee_id"], {}).get("name"),
        "grantee_phone_tail": people.get(r["grantee_id"], {}).get("phone_tail"),
        "requested_days": r["requested_ttl"] and r["requested_ttl"].days,
    } for r in rows]


@router.post("/consents/{consent_id}/revoke")
def revoke_consent(consent_id: UUID, request: Request, conn=Depends(get_conn),
                   a: Actor = Depends(require("patient"))):
    def work():
        try:
            return _view(consent_authz.revoke(conn, consent_id, actor_id=a.id))
        except (LookupError, PermissionError):
            raise ApiError(404, "not_found", "No consent with this id.")  # never reveal another patient's consent
        except ValueError:
            raise ApiError(409, "not_revocable", "This consent is not active.")

    return idempotent(conn, request, a, None, work)


@router.get("/me/access-history")
def access_history(conn=Depends(get_conn), a: Actor = Depends(require("patient"))):
    rows = audit.history_for_patient(conn, a.id)
    names = _names(conn, {r["actor_id"] for r in rows if r["actor_id"]})
    # People are named only if this patient has (or had) a caregiver request from them.
    known = [r[0] for r in conn.execute(
        "SELECT DISTINCT grantee_id FROM consents WHERE patient_id = %s AND purpose = 'CAREGIVER'", [a.id])]
    names.update({k: v["name"] for k, v in person_labels(conn, known).items()})
    return [{**r, "actor_name": names.get(r["actor_id"])} for r in rows]
