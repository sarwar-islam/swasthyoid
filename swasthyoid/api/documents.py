"""M2 endpoints: upload and view documents (FRD M2, section 7; caregiver access per DECISIONS.md).

Who may do what is decided by the gateway chain before a handler runs. Upload handlers
take no body parameter on purpose: FastAPI would read the upload before the access check,
so the handler reads it itself, after the check.

Upload (decision D5, docs/DECISIONS.md "Phase 5"): the form carries `doc_type`, the `images`, and optionally
`upload_anyway=true`. Files that cannot be used are refused with a stable code whatever the flag says (422
image_file_too_large, image_unsupported, image_undecodable, image_too_large; details.page). Files that decode but look poor
are refused with 422 image_quality_warning (details.pages: page, reasons and Bangla guidance) unless upload_anyway is
true; a retake is simply a new upload, because a refused upload stores nothing. Viewing (D6): the patient gets the stored
original; anyone else gets a copy without EXIF or other metadata, and nothing at all if that copy cannot be made.
"""
import hashlib
from dataclasses import replace
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, Request, Response
from fastapi.concurrency import run_in_threadpool

from swasthyoid.api.deps import (Actor, ApiError, actor, authorize_patient_access, client_info, get_conn, idempotent,
                                 patient_read, require)
from swasthyoid.capture import documents, extraction, extraction_crypto, imaging
from swasthyoid.capture.guidance import guidance_for
from swasthyoid.verification import review

router = APIRouter()

# Uploads: the patient, a caregiver holding upload_documents, or a verifier in an active assisted session (B4b).
may_upload = patient_read("TIMELINE", "documents", roles=("verifier",), caregiver="upload_documents")
# Views: the patient, a caregiver holding view_documents, a doctor whose consent covers documents, or a verifier in session
# (documents not yet verified or rejected only).
may_view = dict(purpose="TIMELINE", categories=("documents",), caregiver="view_documents")
STAFF_VIEW = ("doctor", "verifier")
CLOSED = ("verified", "rejected")  # never shown to a verifier: that is the record, not work to check
MAX_REQUEST_BYTES = documents.MAX_IMAGES * documents.MAX_IMAGE_BYTES + 1024 * 1024
_HARD_MESSAGES = {
    "image_file_too_large": "This image file is too large.",
    "image_unsupported": "Only JPEG and PNG images are accepted.",
    "image_undecodable": "This file is not a readable image (it may be damaged).",
    "image_too_large": "This image has too many pixels.",
}


def _view(doc):
    keys = ("id", "patient_id", "doc_type", "status", "uploaded_by", "created_at", "images")
    return {k: doc[k] for k in keys}


async def _upload(request, conn, a, patient_id):
    length = request.headers.get("content-length", "")
    if not length.isdigit():
        raise ApiError(411, "length_required", "Content-Length is required.")
    if int(length) > MAX_REQUEST_BYTES:
        raise ApiError(413, "too_large", "The upload is too large.")
    try:
        form = await request.form(max_files=documents.MAX_IMAGES, max_fields=2)
        images = [await f.read(documents.MAX_IMAGE_BYTES + 1) for f in form.getlist("images") if hasattr(f, "read")]
        doc_type = form.get("doc_type")
        flag = form.get("upload_anyway")
    except Exception:
        raise ApiError(422, "invalid_upload", "Send doc_type and 1 to 10 image files as multipart form data.")
    if flag not in (None, "true", "false"):
        raise ApiError(422, "invalid_upload", "upload_anyway must be true or false.")
    upload_anyway = flag == "true"
    fingerprint = (f"{patient_id}:{doc_type}:{upload_anyway}:"
                   + ",".join(hashlib.sha256(i).hexdigest() for i in images))

    def work():
        try:
            return _view(documents.create(conn, patient_id=patient_id, doc_type=doc_type, uploaded_by=a.id,
                                          images=images, upload_anyway=upload_anyway,
                                          # a caregiver's account role is "patient"; the chain audits them as "caregiver" (deps.py)
                                          actor=replace(a, role="caregiver") if a.role == "patient" and a.id != patient_id else a,
                                          context=client_info(request)))
        except documents.UploadRejected as e:  # never bypassed by upload_anyway
            raise ApiError(422, e.code, _HARD_MESSAGES[e.code], page=e.page)
        except documents.QualityWarning as e:
            raise ApiError(422, "image_quality_warning",
                           "Some pages look poor. Retake them, or upload anyway.",
                           pages=[{"page": page, "reasons": reasons, "guidance": guidance_for(reasons)}
                                  for page, reasons in e.pages])
        except ValueError as e:
            raise ApiError(422, "invalid_document", str(e))
        except psycopg.errors.IntegrityError:
            raise ApiError(422, "invalid_document", "Unknown or missing doc_type.")

    return await run_in_threadpool(idempotent, conn, request, a, fingerprint, work)


@router.post("/patients/{patient_id}/documents", status_code=201)
async def upload_for(patient_id: UUID, request: Request, conn=Depends(get_conn), a: Actor = Depends(may_upload)):
    return await _upload(request, conn, a, patient_id)


@router.post("/documents", status_code=201)
async def upload_own(request: Request, conn=Depends(get_conn), a: Actor = Depends(require("patient"))):
    return await _upload(request, conn, a, a.id)


@router.get("/patients/{patient_id}/documents")
def list_documents(patient_id: UUID, conn=Depends(get_conn),
                   a: Actor = Depends(patient_read("TIMELINE", "documents", roles=STAFF_VIEW, caregiver="view_documents"))):
    docs = documents.list_for_patient(conn, patient_id)
    return [_view(d) for d in docs if a.role != "verifier" or d["status"] not in CLOSED]


def _document(request, conn, a, document_id, closed_ok=False):
    """The document, if the caller may view it. Unknown and not-allowed look the same (404);
    a refusal is still audited by the chain, against the real patient. A verifier never reaches a closed document's
    content; `closed_ok` lets them read its status line right after they closed it."""
    missing = ApiError(404, "not_found", "No document with this id.")
    doc = documents.get(conn, document_id)
    if doc is None:
        raise missing
    try:
        authorize_patient_access(request, conn, a, doc["patient_id"], may_view["purpose"], may_view["categories"],
                                 roles=STAFF_VIEW, caregiver=may_view["caregiver"])
    except ApiError as e:
        if e.status == 403:
            raise missing
        raise
    if a.role == "verifier" and doc["status"] in CLOSED and not closed_ok:
        raise missing
    return doc


def _workable(request, conn, a, document_id):
    """A document the caller may check (M3, manual entry, retry, extraction): the patient's own, or, for a verifier, one
    their active assisted session covers that is not closed. Never a caregiver or a doctor."""
    if a.role == "patient":
        return _own_document(conn, a, document_id)
    return _document(request, conn, a, document_id)


@router.get("/documents/{document_id}")
def get_document(document_id: UUID, request: Request, conn=Depends(get_conn), a: Actor = Depends(actor)):
    return _view(_document(request, conn, a, document_id, closed_ok=True))


@router.get("/documents/{document_id}/extraction")
def get_extraction(document_id: UUID, request: Request, conn=Depends(get_conn), a: Actor = Depends(require("patient", "verifier"))):
    """Unverified extracted fields, for review: the patient, or a verifier in an active assisted session (B4b). Caregivers
    do not verify, and nobody else may see data that has not been verified."""
    doc = _workable(request, conn, a, document_id)
    return {"document_id": doc["id"], "status": doc["status"], "threshold": extraction.CONFIDENCE_THRESHOLD,
            "extraction": _latest(conn, document_id)}


@router.get("/documents/{document_id}/images/{n}")
def get_image(document_id: UUID, n: int, request: Request, conn=Depends(get_conn), a: Actor = Depends(actor)):
    doc = _document(request, conn, a, document_id)
    try:
        image = documents.read_image(conn, document_id, n)  # verifies the stored hash before anything is served
    except documents.Corrupted:
        raise ApiError(500, "document_corrupted", "The stored original failed its integrity check.")
    if image is None:
        raise ApiError(404, "not_found", "No such image.")
    content_type, data = image
    if a.id != doc["patient_id"]:  # D6: nobody but the patient receives the photo's metadata (location, device, time)
        try:
            data, content_type = imaging.strip_metadata(data)
        except imaging.ImageRejected:
            raise ApiError(500, "image_unavailable", "A copy without metadata could not be made, so nothing was served.")
    return Response(data, media_type=content_type, headers={"Cache-Control": "no-store"})


# ---- manual entry and retry: the patient (D10) or a verifier in an active assisted session (B4b, FRD M3 / Q3), always
# allowed for manual entry (D12), conflicts not audited (D14)

_CONFLICTS = {
    "not_allowed_state": "The document is not in a state that allows this.",
    "extraction_in_progress": "A worker is extracting this document right now; try again shortly.",
    "retry_limit_reached": f"This document has used all {extraction.MAX_LIFETIME_ATTEMPTS} reading attempts; enter it by hand instead.",
    "not_retryable": "Reading this document failed in a way that trying again cannot fix; enter it by hand instead.",
}


def _latest(conn, document_id):
    """The decrypted extraction, or a controlled 500 that says nothing about its content (wrong or lost key, or a
    missing or unsupported schema version)."""
    try:
        return extraction.latest(conn, document_id)
    except (extraction_crypto.Undecryptable, extraction.SchemaVersionError):
        raise ApiError(500, "extraction_unreadable", "The stored extraction could not be read.")


def _own_document(conn, a, document_id):
    """The patient's own document. Unknown and someone else's look the same (404)."""
    doc = documents.get(conn, document_id)
    if doc is None or doc["patient_id"] != a.id:
        raise ApiError(404, "not_found", "No document with this id.")
    return doc


@router.post("/documents/{document_id}/manual-entry")
def start_manual_entry(document_id: UUID, request: Request, conn=Depends(get_conn),
                       a: Actor = Depends(require("patient", "verifier"))):
    """Move a document to review with every field empty, to be typed in by hand. 409
    extraction_in_progress while a worker holds it; 409 not_allowed_state once it is in review or closed."""
    _workable(request, conn, a, document_id)

    def work():
        try:
            extraction.start_manual_entry(conn, document_id, actor=a, context=client_info(request))
        except extraction.Conflict as e:
            raise ApiError(409, e.args[0], _CONFLICTS[e.args[0]])
        return {"document_id": document_id, "status": "needs_review", "extraction": _latest(conn, document_id)}

    return idempotent(conn, request, a, f"manual-entry:{document_id}", work)


# ---- M3 check, confirm, reject (B4a): the patient for their own documents, or a verifier in an active assisted session (B4b)
VERIFIERS = require("patient", "verifier")

def _m3(work_fn, conn, document_id):
    try:
        return work_fn()
    except review.Conflict as e:
        raise ApiError(409, e.args[0], _CONFLICTS[e.args[0]])
    except review.Invalid as e:
        raise ApiError(422, e.args[0], "Check this field.", field=e.args[1])
    except LookupError:
        raise ApiError(404, "not_found", "No document with this id.")
    except (extraction_crypto.Undecryptable, extraction.SchemaVersionError):
        raise ApiError(500, "extraction_unreadable", "The stored extraction could not be read.")


@router.put("/documents/{document_id}/review")
async def save_review(document_id: UUID, request: Request, conn=Depends(get_conn), a: Actor = Depends(VERIFIERS)):
    try:
        body = await request.json()
    except ValueError:
        body = None
    fields = body.get("fields") if isinstance(body, dict) else None

    def work():  # database calls off the event loop, as for uploads
        _workable(request, conn, a, document_id)
        saved = _m3(lambda: review.save(conn, document_id, fields, actor=a), conn, document_id)
        return {"document_id": document_id, "status": "needs_review", "fields": saved}

    return await run_in_threadpool(work)


@router.post("/documents/{document_id}/confirm")
def confirm_document(document_id: UUID, request: Request, conn=Depends(get_conn), a: Actor = Depends(VERIFIERS)):
    """One transaction: the document_verified events, the correction record, status verified. A repeat is 409."""
    _workable(request, conn, a, document_id)

    def work():
        _m3(lambda: review.confirm(conn, document_id, actor=a, context=client_info(request)), conn, document_id)
        return _view(documents.get(conn, document_id))

    return idempotent(conn, request, a, f"confirm:{document_id}", work)


@router.post("/documents/{document_id}/reject")
def reject_document(document_id: UUID, request: Request, conn=Depends(get_conn), a: Actor = Depends(VERIFIERS)):
    _workable(request, conn, a, document_id)

    def work():
        _m3(lambda: review.reject(conn, document_id, actor=a, context=client_info(request)), conn, document_id)
        return _view(documents.get(conn, document_id))

    return idempotent(conn, request, a, f"reject:{document_id}", work)


@router.post("/documents/{document_id}/retry-extraction")
def retry_extraction(document_id: UUID, request: Request, conn=Depends(get_conn),
                     a: Actor = Depends(require("patient", "verifier"))):
    """Try a failed extraction again while the document's lifetime budget of MAX_LIFETIME_ATTEMPTS OCR executions
    has attempts left. 409 not_allowed_state unless the extraction failed; 409 retry_limit_reached when the budget
    is used up; 409 not_retryable after a permanent failure."""
    _workable(request, conn, a, document_id)

    def work():
        try:
            used = extraction.retry_extraction(conn, document_id, actor=a, context=client_info(request))
        except extraction.Conflict as e:
            raise ApiError(409, e.args[0], _CONFLICTS[e.args[0]])
        return {"document_id": document_id, "status": "extracting", "retries_used": used,
                "attempts_used": extraction.attempts_used(conn, document_id),
                "attempts_allowed": extraction.MAX_LIFETIME_ATTEMPTS}

    return idempotent(conn, request, a, f"retry:{document_id}", work)
