"""Admin routes: staff and credentials (B2), the audit log and the drug catalog upload (B5); owner decisions 2026-11-16,
DECISIONS.md "Backend sync plan B0-B8".

Every route needs a verified admin (RBAC, with denials audited by deps). Free-text reasons are kept on the record they
explain; the audit log says only "reason_given". Phones are shown by their last four digits only.
"""
from typing import Literal
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, Request, Response
from fastapi.concurrency import run_in_threadpool

from psycopg.types.json import Jsonb

from swasthyoid import pii
from swasthyoid.api.deps import Actor, ApiError, client_info, get_conn, idempotent, require
from swasthyoid.capture import drugcatalog, storage
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

    return await run_in_threadpool(idempotent, conn, request, a, f"reject:{credential_id}:{reason}", work)


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

    return await run_in_threadpool(idempotent, conn, request, a, f"staff:{role}:{name}:{pii.phone_hash(phone)}", work)


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

    return await run_in_threadpool(idempotent, conn, request, a, f"suspend:{user_id}:{reason}", work)


# ---- C2 audit log, read only (B5): the server verifies the whole chain on every read; entries are metadata only

@router.get("/audit")
def audit_log(request: Request, action: str | None = None, result: Literal["allow", "deny", "failed"] | None = None,
              role: str | None = None, conn=Depends(get_conn), a: Actor = Depends(admin)):
    page = audit.admin_page(conn, action=action or None, result=result, role=role or None)
    audit.append(conn, action="audit.read", result="allow", actor_id=a.id, actor_role=a.role, device_id=a.device_id,
                 **client_info(request))  # reading the log is itself logged
    return page


# ---- drug catalog upload (B5; owner decision: validate and report only while FRD question 1, the licence, is open)

def _counts(report):
    return {"rows": report.rows, "matchable": report.matchable, "unmatchable": len(report.unmatchable),
            "duplicate_groups": len(report.duplicate_groups), "near_duplicate_groups": len(report.near_duplicate_groups),
            "brands_with_several_generics": len(report.brands_with_several_generics),
            "products_with_several_manufacturers": len(report.products_with_several_manufacturers)}


@router.post("/catalog/import", status_code=201)
async def catalog_import(request: Request, conn=Depends(get_conn), a: Actor = Depends(admin)):
    """The admin's CSV is read in memory by the existing loader and dropped: no catalog data is stored anywhere. Only its
    SHA-256, size, the loader's counts and the admin's own statement of where it came from are recorded. The extraction
    worker still uses only DRUG_CATALOG_PATH."""
    length = request.headers.get("content-length", "")
    if not length.isdigit() or int(length) > drugcatalog.MAX_FILE_BYTES + 64 * 1024:
        raise ApiError(413, "too_large", "The file is too large.")
    try:
        form = await request.form(max_files=1, max_fields=2)
        upload, source = form.get("file"), str(form.get("source") or "").strip()
        data = await upload.read(drugcatalog.MAX_FILE_BYTES + 1) if hasattr(upload, "read") else None
    except Exception:
        raise ApiError(422, "invalid_file", "Send one CSV file and the source statement as multipart form data.")
    if not data or not str(upload.filename or "").lower().endswith(".csv"):
        raise ApiError(422, "invalid_file", "Choose a non-empty CSV file.")
    if not source:
        raise ApiError(422, "source_required", "Say where the file came from and on what terms.")
    name = str(upload.filename)

    def work():
        try:
            loaded = drugcatalog.load_medicine_bytes(data, name=name, source=source)
        except drugcatalog.CatalogError as e:
            audit.append(conn, action="catalog.validate", result="deny", reason=e.args[0], actor_id=a.id, actor_role=a.role)
            raise ApiError(422, "invalid_catalog", "The file cannot be used as a catalog.", reason=e.args[0])
        counts = _counts(loaded.report)
        with conn.transaction():
            row_id = conn.execute(
                "INSERT INTO catalog_imports (id, imported_by, file_name, size_bytes, sha256, source_statement, report) "
                "VALUES (gen_random_uuid(), %s, %s, %s, %s, %s, %s) RETURNING id",
                [a.id, name, len(data), loaded.file_sha256, source, Jsonb(counts)]).fetchone()[0]
            audit.append(conn, action="catalog.validate", result="allow", actor_id=a.id, actor_role=a.role,
                         resource_type="catalog_import", resource_id=row_id)
        return {"id": row_id, "status": "validated", "file_name": name, "size_bytes": len(data),
                "sha256": loaded.file_sha256, "report": counts}

    return await run_in_threadpool(work)


async def _json(request):
    try:
        body = await request.json()
    except ValueError:
        return None
    return body if isinstance(body, dict) else None
