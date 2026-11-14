"""M2 — documents: the uploaded originals and their status (FRD M2).

Uploading stores the images and a row with status `uploaded`, nothing more. It never
creates events and never verifies anything: that is M3's confirm step.

Before anything is stored every image is really decoded (JPEG or PNG within the pixel cap: `imaging.load`, once) and
quality-checked (`imaging.check_measures`, provisional limits). A file that cannot be used is refused whatever the caller
asks (UploadRejected). A file that decodes but looks poor is refused with its reason codes (QualityWarning) unless the
caller passed upload_anyway, in which case the warnings are stored with the image and an audit entry records the override
(decision D5, docs/DECISIONS.md "Phase 5"). The original bytes are stored exactly as received.
"""
import hashlib
import threading
from uuid import uuid4

from psycopg.rows import dict_row

from swasthyoid.capture import imaging, storage
from swasthyoid.core import audit

# Engineering limits, not FRD values.
MAX_IMAGES = 10
MAX_IMAGE_BYTES = 10 * 1024 * 1024

# Document state machine, FRD M2/M3. verified and rejected are terminal.
TRANSITIONS = {
    "uploaded": {"extracting", "needs_review"},  # needs_review: manual entry before any extraction (D12)
    "extracting": {"needs_review", "extraction_failed"},
    "extraction_failed": {"extracting", "needs_review"},
    "needs_review": {"verified", "rejected"},
    "verified": set(),
    "rejected": set(),
}

_SIGNATURES = (b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n")
# decoding and measuring a large page takes a lot of memory: only this many pages are checked at the same time
_CHECKS = threading.BoundedSemaphore(2)


class Corrupted(Exception):
    """A stored original no longer matches the hash recorded at upload."""


class UploadRejected(Exception):
    """A file that cannot be stored, and that no choice by the caller changes. `code` is a stable machine-readable word
    (image_file_too_large, image_unsupported, image_undecodable, image_too_large); `page` is its 1-based position."""

    def __init__(self, code, page):
        super().__init__(code)
        self.code, self.page = code, page


class QualityWarning(Exception):
    """Every file decodes, but some look poor. `pages` is [(page, [reason codes])] for those pages only. The caller may
    retake the photo or repeat the upload with upload_anyway."""

    def __init__(self, pages):
        super().__init__("image_quality_warning")
        self.pages = pages


def inspect_images(images, *, upload_anyway=False):
    """Validate every image and return [{content_type, ext, warnings}] in order, or raise. Touches no database and no file.
    ValueError for the number of images or an empty one; UploadRejected for a file that cannot be used; QualityWarning
    (unless upload_anyway) for decodable but poor pages. The cheap checks for every page run before any decoding."""
    if not 1 <= len(images) <= MAX_IMAGES:
        raise ValueError(f"a document needs 1 to {MAX_IMAGES} images")
    for page, data in enumerate(images, 1):
        if not data:
            raise ValueError("an image must not be empty")
        if len(data) > MAX_IMAGE_BYTES:
            raise UploadRejected("image_file_too_large", page)
        if not data.startswith(_SIGNATURES):  # by content, never by the file name or type the client claims
            raise UploadRejected("image_unsupported", page)
    checked, flagged = [], []
    for page, data in enumerate(images, 1):
        with _CHECKS:
            try:
                grey, kind = imaging.load(data, exif=True)  # the one decode of this image
            except imaging.ImageRejected as e:
                raise UploadRejected(e.args[0], page) from None
            reasons = imaging.check_measures(imaging.measure_grey(grey))
            del grey
        content_type, ext = imaging.CONTENT_TYPES[kind]
        checked.append({"content_type": content_type, "ext": ext, "warnings": reasons})
        if reasons:
            flagged.append((page, reasons))
    if flagged and not upload_anyway:
        raise QualityWarning(flagged)
    return checked


def create(conn, *, patient_id, doc_type, uploaded_by, images, upload_anyway=False, actor=None, context=None):
    """Store the original images and the document row (status `uploaded`). All or nothing.
    The caller must already have authorised uploaded_by to upload for patient_id. See the module note for what is refused;
    when warnings are overridden the audit entry `document.upload_override` is written in the same transaction (actor and
    context as extraction.start_manual_entry takes them)."""
    kinds = inspect_images(images, upload_anyway=upload_anyway)
    document_id, written = uuid4(), []
    try:
        with conn.transaction():
            row = conn.cursor(row_factory=dict_row).execute(
                "INSERT INTO documents (id, patient_id, doc_type, uploaded_by) VALUES (%s, %s, %s, %s) RETURNING *",
                [document_id, patient_id, doc_type, uploaded_by],
            ).fetchone()
            for n, (data, kind) in enumerate(zip(images, kinds), 1):
                key = f"patients/{patient_id}/documents/{document_id}/{n}.{kind['ext']}"
                storage.put(key, data)
                written.append(key)
                conn.execute(
                    "INSERT INTO document_images (document_id, n, storage_key, content_type, size_bytes, sha256, "
                    "quality_warnings) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    [document_id, n, key, kind["content_type"], len(data), hashlib.sha256(data).hexdigest(),
                     kind["warnings"]],
                )
            overridden = [(n, k["warnings"]) for n, k in enumerate(kinds, 1) if k["warnings"]]
            if overridden:  # only reachable with upload_anyway: the warnings were shown and accepted
                audit.append(conn, action="document.upload_override", result="allow", patient_id=patient_id,
                             resource_type="document", resource_id=document_id,
                             reason="; ".join(f"page {n}: {','.join(w)}" for n, w in overridden),
                             actor_id=actor.id if actor else uploaded_by, actor_role=actor.role if actor else None,
                             **(context or {}))
    except BaseException:
        for key in written:  # the rows rolled back; do not leave orphan files
            storage.discard(key)
        raise
    return get(conn, document_id)


def _images(conn, document_id):
    return conn.cursor(row_factory=dict_row).execute(
        "SELECT n, content_type, size_bytes, sha256, quality_warnings FROM document_images WHERE document_id = %s ORDER BY n",
        [document_id],
    ).fetchall()


def get(conn, document_id):
    """The document row with its image records, or None."""
    row = conn.cursor(row_factory=dict_row).execute(
        "SELECT * FROM documents WHERE id = %s", [document_id]).fetchone()
    return row and {**row, "images": _images(conn, document_id)}


def list_for_patient(conn, patient_id):
    rows = conn.cursor(row_factory=dict_row).execute(
        "SELECT * FROM documents WHERE patient_id = %s ORDER BY created_at DESC, id", [patient_id]).fetchall()
    return [{**r, "images": _images(conn, r["id"])} for r in rows]


def read_image(conn, document_id, n):
    """(content_type, original bytes), or None. Raises Corrupted if the file was altered."""
    row = conn.execute(
        "SELECT storage_key, content_type, sha256 FROM document_images WHERE document_id = %s AND n = %s",
        [document_id, n],
    ).fetchone()
    if row is None:
        return None
    try:
        data = storage.get(row[0])
    except Exception as e:  # missing file, or it does not decrypt
        raise Corrupted(str(document_id)) from e
    if hashlib.sha256(data).hexdigest() != row[2]:
        raise Corrupted(str(document_id))
    return row[1], data


def set_status(conn, document_id, target):
    """Move a document along the state machine; raises on an illegal move."""
    with conn.transaction():
        row = conn.execute("SELECT status FROM documents WHERE id = %s FOR UPDATE", [document_id]).fetchone()
        if row is None:
            raise LookupError("document not found")
        if target not in TRANSITIONS[row[0]]:
            raise ValueError(f"illegal document transition: {row[0]} -> {target}")
        # a document entering `extracting` is due at once; without a time it would never be picked up
        conn.execute(
            "UPDATE documents SET status = %s, updated_at = clock_timestamp(), next_extraction_at = "
            "CASE WHEN %s = 'extracting' THEN clock_timestamp() ELSE next_extraction_at END WHERE id = %s",
            [target, target, document_id])
