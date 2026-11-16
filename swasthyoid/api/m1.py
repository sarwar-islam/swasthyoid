"""M1 endpoints: login, credentials and the Consent Center (FRD M1, section 7).

Handlers only orchestrate; the rules live in core/ and identity/.
"""
import os
from datetime import date, timedelta
from typing import Literal
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, Request, Response
from psycopg.rows import dict_row
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
    # Console roles (clinical_reviewer, admin) never self-register: an admin creates them (owner decision 2026-11-16).
    role: Literal["doctor", "verifier"]
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
                      a: Actor = Depends(require("doctor", verified=False))):
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
    method: Literal["otp", "qr"] = "otp"  # GAP approved in B2: "qr" sends no SMS and returns the QR once


class CodeBody(BaseModel):
    code: str


def _view(row):
    keys = ("id", "grantee_id", "grantee_role", "purpose", "allowed_categories", "status",
            "activated_at", "expires_at", "created_at")
    return {k: row[k] for k in keys}


def _doctor_view(conn, row):
    """What the requesting doctor sees: the consent plus the patient it opens (APPROVED contract, 2026-11-16)."""
    health_id = conn.execute("SELECT health_id FROM patients WHERE id = %s", [row["patient_id"]]).fetchone()[0]
    return {**_view(row), "patient_id": row["patient_id"], "health_id": health_id}


def _method(row):
    return row["method"].lower() if row["purpose"] == "TIMELINE" and row["method"] in ("OTP", "QR") else None


@router.post("/consents/requests", status_code=201)
def request_consent(body: ConsentRequestBody, request: Request, conn=Depends(get_conn),
                    send=Depends(get_code_sender), a: Actor = Depends(require("doctor"))):
    """A verified doctor asks for TIMELINE access by Health ID. By default the patient gets a one-time code to read out;
    with method "qr" no code is sent and the doctor shows a QR the patient answers in their own app."""

    def work():
        _consent_hours()
        patient = conn.execute("SELECT id, phone_enc FROM patients WHERE health_id = %s", [body.health_id]).fetchone()
        if patient is None:
            raise ApiError(404, "patient_not_found", "No patient has this Health ID.")
        with conn.transaction():
            row = consent_authz.create(
                conn, patient_id=patient[0], grantee_id=a.id, grantee_role=a.role, purpose="TIMELINE",
                allowed_categories=set(body.categories), consent_version=CONSENT_VERSION,
                policy_version=POLICY_VERSION, actor_id=a.id, method=body.method.upper(),
            )
            if body.method == "qr":
                token, code, expires_at = consent_authz.create_qr(conn, row["id"], ttl=otp.CODE_TTL)
                return {**_doctor_view(conn, row), "qr": {"token": token, "short_code": code, "expires_at": expires_at}}
        try:
            otp.request_code(conn, pii.decrypt(patient[1]), send, kind="consent", ref=str(row["id"]))
        except otp.TooManyRequests:
            raise ApiError(429, "too_many_requests", "Too many codes sent to this patient. Try again later.")
        return _doctor_view(conn, row)

    if body.method == "qr":  # never replayed: a stored response would keep the QR token and code in plain form
        return work()
    return idempotent(conn, request, a, body, work)


@router.get("/consents/requests/{consent_id}")
def get_request(consent_id: UUID, conn=Depends(get_conn), a: Actor = Depends(require("doctor"))):
    """The doctor's own request, so a QR screen can see when the patient has answered."""
    row = consent_authz.get(conn, consent_id)
    if row is None or row["grantee_id"] != a.id or row["purpose"] != "TIMELINE":
        raise ApiError(404, "not_found", "No consent request with this id.")
    return _doctor_view(conn, row)


@router.post("/consents/requests/{consent_id}/confirm")
def confirm_consent(consent_id: UUID, body: CodeBody, request: Request, conn=Depends(get_conn),
                    a: Actor = Depends(require("doctor"))):
    """The doctor enters the code the patient told them; only then does the consent become active."""

    def work():
        lifetime = _consent_hours()
        row = consent_authz.get(conn, consent_id)
        if row is None or row["grantee_id"] != a.id or row["status"] != "pending":
            raise ApiError(404, "not_found", "No pending consent request with this id.")
        if row["method"] == "QR":  # no code was sent: only the patient's own app can answer a QR request
            audit.append(conn, action="auth.otp_failed", result="deny", reason="qr_request", actor_id=a.id,
                         actor_role=a.role, patient_id=row["patient_id"], consent_id=consent_id)
            raise ApiError(403, "invalid_code", "The code is wrong or has expired.")
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
        return _doctor_view(conn, row)

    return idempotent(conn, request, a, body, work)


# ---- consent by QR, the patient's side (GAP approved in B2)

def _qr_view(conn, row):
    names = _names(conn, [row["grantee_id"]])
    status = "expired" if row["status"] == "pending" and (row["qr_expired"] or row["qr_used_at"]) else row["status"]
    return {"consent_id": row["id"], "doctor_name": names.get(row["grantee_id"]), "categories": row["allowed_categories"],
            "status": status, "expires_at": row["qr_expires_at"],
            "access_hours": _consent_hours().total_seconds() / 3600}


def _qr_lookup(conn, a, ref):
    """The request a QR or short code names, for this patient only; every lookup is audited, found or not."""
    row = consent_authz.find_qr(conn, ref, patient_id=a.id)
    audit.append(conn, action="consent.qr.read", result="allow" if row else "deny", reason=None if row else "not_found",
                 actor_id=a.id, actor_role=a.role, patient_id=a.id, consent_id=row and row["id"],
                 purpose=row and row["purpose"])
    if row is None:
        raise ApiError(404, "not_found", "This request is not open.")
    return row


@router.get("/consents/qr/{ref}")
def qr_request(ref: str, conn=Depends(get_conn), a: Actor = Depends(require("patient"))):
    return _qr_view(conn, _qr_lookup(conn, a, ref))


def _qr_answer(request, conn, a, ref, approve):
    """A successful answer is audited by C1 (consent.activate or consent.decline); a refused one here."""
    def work():
        lifetime = _consent_hours()
        row = _qr_lookup(conn, a, ref)
        try:
            with conn.transaction():
                consent_authz.answer_qr(conn, row["id"], patient_id=a.id, approve=approve, lifetime=lifetime)
                if approve:
                    notification.enqueue(conn, recipient_id=a.id, template_id="CONSENT_GRANTED_PLACEHOLDER",
                                         payload={"consent_id": str(row["id"])})
        except (LookupError, ValueError):  # used, expired or no longer pending: the same answer as unknown
            audit.append(conn, action=f"consent.qr.{'approve' if approve else 'decline'}", result="deny",
                         reason="not_open", actor_id=a.id, actor_role=a.role, patient_id=a.id, consent_id=row["id"],
                         purpose=row["purpose"])
            raise ApiError(404, "not_found", "This request is not open.")
        return _qr_view(conn, consent_authz.find_qr(conn, ref, patient_id=a.id))

    return idempotent(conn, request, a, None, work)


@router.post("/consents/qr/{ref}/approve")
def qr_approve(ref: str, request: Request, conn=Depends(get_conn), a: Actor = Depends(require("patient"))):
    return _qr_answer(request, conn, a, ref, approve=True)


@router.post("/consents/qr/{ref}/decline")
def qr_decline(ref: str, request: Request, conn=Depends(get_conn), a: Actor = Depends(require("patient"))):
    return _qr_answer(request, conn, a, ref, approve=False)


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
        "method": _method(r),
    } for r in rows]


# ---- who am I (APPROVED contract: patient 2026-11-15, every staff role 2026-11-16)

@router.get("/me")
def me(conn=Depends(get_conn),
       a: Actor = Depends(require("patient", "doctor", "verifier", "clinical_reviewer", "admin", verified=False))):
    if a.role == "patient":
        p = conn.cursor(row_factory=dict_row).execute(
            "SELECT id, health_id, name_enc, language, cloud_ai_opt_in FROM patients WHERE id = %s", [a.id]).fetchone()
        return {"id": p["id"], "health_id": p["health_id"], "name": pii.decrypt(p["name_enc"]), "language": p["language"],
                "cloud_ai_opt_in": p["cloud_ai_opt_in"]}
    u = conn.cursor(row_factory=dict_row).execute(
        "SELECT id, role, name, status, emergency_enabled FROM users WHERE id = %s", [a.id]).fetchone()
    cred = accounts.current_credential(conn, a.id)
    return {**u, "credential": cred and {"type": cred["type"], "number": cred["number"], "status": cred["status"]}}


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
