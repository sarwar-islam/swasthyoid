"""Admin routes for staff and credentials (B2; owner decisions 2026-11-16, DECISIONS.md "Backend sync plan B0-B8").

Every route needs a verified admin (RBAC, with denials audited by deps). Free-text reasons are kept on the record they
explain; the audit log says only "reason_given". Phones are shown by their last four digits only.
"""
from typing import Literal
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, Request, Response

from swasthyoid import pii
from swasthyoid.api.deps import Actor, ApiError, client_info, get_conn, idempotent, require
from swasthyoid.capture import storage
from swasthyoid.core import audit
from swasthyoid.identity import accounts

router = APIRouter()
admin = require("admin")
Status = Literal["pending", "verified", "suspended", "rejected"]


def _reason(body):
    reason = str((body or {}).get("reason") or "").strip()
    if not reason:
        raise ApiError(422, "reason_required", "Give a reason.")
    return reason


def _staff_view(row):
    return {"id": row["id"], "role": row["role"], "name": row["name"], "status": row["status"],
            "phone_tail": pii.decrypt(row["phone_enc"])[-4:]}


def _credential_view(row):
    return {"id": row["id"], "user_id": row["user_id"], "name": row["name"], "role": row["role"], "type": row["type"],
            "number": row["number"], "status": row["status"], "user_status": row["user_status"]}


# ---- credentials (M1: doctors' BMDC numbers)

@router.get("/credentials")
def list_credentials(status: Status | None = None, conn=Depends(get_conn), a: Actor = Depends(admin)):
    return [_credential_view(r) for r in accounts.list_credentials(conn, status)]


@router.post("/credentials/{credential_id}/reject")
async def reject_credential(credential_id: UUID, request: Request, conn=Depends(get_conn), a: Actor = Depends(admin)):
    reason = _reason(await _json(request))

    def work():
        try:
            user_id = accounts.reject_credential(conn, credential_id, admin_id=a.id, reason=reason)
        except LookupError:
            raise ApiError(404, "not_found", "No pending credential with this id.")
        return {"user_id": user_id, "status": "rejected"}

    return idempotent(conn, request, a, f"reject:{credential_id}:{reason}", work)


_SIGNATURES = ((b"\x89PNG\r\n\x1a\n", "image/png"), (b"\xff\xd8\xff", "image/jpeg"), (b"%PDF-", "application/pdf"))


@router.get("/credentials/{credential_id}/document")
def credential_document(credential_id: UUID, request: Request, conn=Depends(get_conn), a: Actor = Depends(admin)):
    """The document submitted with a credential, if one is stored. The type comes from the file's first bytes."""
    row = conn.execute("SELECT user_id, doc_key FROM credentials WHERE id = %s", [credential_id]).fetchone()
    missing = ApiError(404, "not_found", "No document for this credential.")
    if row is None or not row[1]:
        raise missing
    try:
        data = storage.get(row[1])
    except (FileNotFoundError, KeyError, ValueError):  # no file, no store configured, or a key outside the store
        raise missing
    audit.append(conn, action="credential.document.read", result="allow", actor_id=a.id, actor_role=a.role,
                 resource_type="user", resource_id=row[0], device_id=a.device_id, **client_info(request))
    media = next((m for sig, m in _SIGNATURES if data.startswith(sig)), "application/octet-stream")
    return Response(data, media_type=media, headers={"Cache-Control": "no-store"})


# ---- staff accounts (verifiers and clinical reviewers; console roles never self-register)

@router.get("/admin/staff")
def list_staff(status: Literal["pending", "verified", "suspended"] | None = None, conn=Depends(get_conn),
               a: Actor = Depends(admin)):
    return [_staff_view(r) for r in accounts.list_staff(conn, status)]


@router.post("/admin/staff", status_code=201)
async def create_staff(request: Request, conn=Depends(get_conn), a: Actor = Depends(admin)):
    body = await _json(request) or {}
    role, name, phone = body.get("role"), str(body.get("name") or "").strip(), str(body.get("phone") or "").strip()
    if role not in accounts.ADMIN_CREATED_ROLES:
        raise ApiError(422, "invalid_role", "Choose verifier or clinical reviewer.")
    if not name:
        raise ApiError(422, "invalid_name", "Enter the person's name.")
    try:
        phone = pii.normalize_phone(phone)
    except ValueError:
        raise ApiError(422, "invalid_phone", "Enter a Bangladesh mobile number.")

    def work():
        try:
            return _staff_view(accounts.create_staff(conn, admin_id=a.id, role=role, name=name, phone=phone))
        except psycopg.errors.UniqueViolation:
            raise ApiError(409, "phone_exists", "This phone number already has a staff account.")

    return idempotent(conn, request, a, f"staff:{role}:{name}:{pii.phone_hash(phone)}", work)


@router.post("/admin/staff/{user_id}/approve")
def approve_staff(user_id: UUID, request: Request, conn=Depends(get_conn), a: Actor = Depends(admin)):
    def work():
        try:
            return _staff_view(accounts.approve_staff(conn, user_id, admin_id=a.id))
        except ValueError:
            raise ApiError(404, "not_found", "No pending registration with this id.")

    return idempotent(conn, request, a, None, work)


@router.post("/admin/users/{user_id}/suspend")
async def suspend_user(user_id: UUID, request: Request, conn=Depends(get_conn), a: Actor = Depends(admin)):
    """Any staff role but admin. Their consents are suspended and every session ends (FRD section 2)."""
    reason = _reason(await _json(request))

    def work():
        try:
            accounts.suspend_user(conn, user_id, admin_id=a.id, reason=reason)
        except ValueError:  # unknown, an admin, or not verified: one answer
            raise ApiError(404, "not_found", "No active staff member with this id.")
        return {"user_id": user_id, "status": "suspended"}

    return idempotent(conn, request, a, f"suspend:{user_id}:{reason}", work)


async def _json(request):
    try:
        body = await request.json()
    except ValueError:
        return None
    return body if isinstance(body, dict) else None
