"""M2 endpoints: upload and view documents (FRD M2, section 7; caregiver access per DECISIONS.md).

Who may do what is decided by the gateway chain before a handler runs. Upload handlers
take no body parameter on purpose: FastAPI would read the upload before the access check,
so the handler reads it itself, after the check.
"""
import hashlib
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, Request, Response
from fastapi.concurrency import run_in_threadpool

from swasthyoid.api.deps import Actor, ApiError, actor, authorize_patient_access, get_conn, idempotent, patient_read, require
from swasthyoid.capture import documents, extraction

router = APIRouter()

# Uploads: the patient, or a caregiver holding upload_documents. No staff role.
# PENDING (FRD question 3): the FRD also lets a verifier upload for a present patient.
may_upload = patient_read("TIMELINE", "documents", roles=(), caregiver="upload_documents")
# Views: the patient, a caregiver holding view_documents, or a doctor whose consent covers documents.
may_view = dict(purpose="TIMELINE", categories=("documents",), caregiver="view_documents")
MAX_REQUEST_BYTES = documents.MAX_IMAGES * documents.MAX_IMAGE_BYTES + 1024 * 1024


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
        form = await request.form(max_files=documents.MAX_IMAGES, max_fields=1)
        images = [await f.read(documents.MAX_IMAGE_BYTES + 1) for f in form.getlist("images") if hasattr(f, "read")]
        doc_type = form.get("doc_type")
    except Exception:
        raise ApiError(422, "invalid_upload", "Send doc_type and 1 to 10 image files as multipart form data.")
    fingerprint = f"{patient_id}:{doc_type}:" + ",".join(hashlib.sha256(i).hexdigest() for i in images)

    def work():
        try:
            return _view(documents.create(conn, patient_id=patient_id, doc_type=doc_type, uploaded_by=a.id,
                                          images=images))
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
                   a: Actor = Depends(patient_read("TIMELINE", "documents", caregiver="view_documents"))):
    return [_view(d) for d in documents.list_for_patient(conn, patient_id)]


def _document(request, conn, a, document_id):
    """The document, if the caller may view it. Unknown and not-allowed look the same (404);
    a refusal is still audited by the chain, against the real patient."""
    missing = ApiError(404, "not_found", "No document with this id.")
    doc = documents.get(conn, document_id)
    if doc is None:
        raise missing
    try:
        authorize_patient_access(request, conn, a, doc["patient_id"], may_view["purpose"], may_view["categories"],
                                 caregiver=may_view["caregiver"])
    except ApiError as e:
        if e.status == 403:
            raise missing
        raise
    return doc


@router.get("/documents/{document_id}")
def get_document(document_id: UUID, request: Request, conn=Depends(get_conn), a: Actor = Depends(actor)):
    return _view(_document(request, conn, a, document_id))


@router.get("/documents/{document_id}/extraction")
def get_extraction(document_id: UUID, conn=Depends(get_conn), a: Actor = Depends(require("patient"))):
    """Unverified extracted fields, for review. The patient only: caregivers do not verify, and
    nobody else may see data that has not been verified. PENDING (FRD question 3): verifiers."""
    doc = documents.get(conn, document_id)
    if doc is None or doc["patient_id"] != a.id:
        raise ApiError(404, "not_found", "No document with this id.")
    return {"document_id": doc["id"], "status": doc["status"], "threshold": extraction.CONFIDENCE_THRESHOLD,
            "extraction": extraction.latest(conn, document_id)}


@router.get("/documents/{document_id}/images/{n}")
def get_image(document_id: UUID, n: int, request: Request, conn=Depends(get_conn), a: Actor = Depends(actor)):
    _document(request, conn, a, document_id)
    try:
        image = documents.read_image(conn, document_id, n)
    except documents.Corrupted:
        raise ApiError(500, "document_corrupted", "The stored original failed its integrity check.")
    if image is None:
        raise ApiError(404, "not_found", "No such image.")
    return Response(image[1], media_type=image[0], headers={"Cache-Control": "no-store"})
