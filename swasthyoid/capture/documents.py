"""M2 — documents: the uploaded originals and their status (FRD M2).

Uploading stores the images and a row with status `uploaded`, nothing more. It never
creates events and never verifies anything: that is M3's confirm step.
"""
import hashlib
from uuid import uuid4

from psycopg.rows import dict_row

from swasthyoid.capture import storage

# Engineering limits, not FRD values.
MAX_IMAGES = 10
MAX_IMAGE_BYTES = 10 * 1024 * 1024

# Document state machine, FRD M2/M3. verified and rejected are terminal.
TRANSITIONS = {
    "uploaded": {"extracting"},
    "extracting": {"needs_review", "extraction_failed"},
    "extraction_failed": {"extracting", "needs_review"},
    "needs_review": {"verified", "rejected"},
    "verified": set(),
    "rejected": set(),
}

_SIGNATURES = {b"\xff\xd8\xff": ("image/jpeg", "jpg"), b"\x89PNG\r\n\x1a\n": ("image/png", "png")}


class Corrupted(Exception):
    """A stored original no longer matches the hash recorded at upload."""


def _sniff(data):
    # by content, never by the file name or type the client claims
    for magic, kind in _SIGNATURES.items():
        if data.startswith(magic):
            return kind
    raise ValueError("images must be JPEG or PNG")


def create(conn, *, patient_id, doc_type, uploaded_by, images):
    """Store the original images and the document row (status `uploaded`). All or nothing.
    The caller must already have authorised uploaded_by to upload for patient_id."""
    if not 1 <= len(images) <= MAX_IMAGES:
        raise ValueError(f"a document needs 1 to {MAX_IMAGES} images")
    kinds = []
    for data in images:
        if not 0 < len(data) <= MAX_IMAGE_BYTES:
            raise ValueError(f"each image must be 1 byte to {MAX_IMAGE_BYTES} bytes")
        kinds.append(_sniff(data))
    document_id, written = uuid4(), []
    try:
        with conn.transaction():
            row = conn.cursor(row_factory=dict_row).execute(
                "INSERT INTO documents (id, patient_id, doc_type, uploaded_by) VALUES (%s, %s, %s, %s) RETURNING *",
                [document_id, patient_id, doc_type, uploaded_by],
            ).fetchone()
            for n, (data, (content_type, ext)) in enumerate(zip(images, kinds), 1):
                key = f"patients/{patient_id}/documents/{document_id}/{n}.{ext}"
                storage.put(key, data)
                written.append(key)
                conn.execute(
                    "INSERT INTO document_images (document_id, n, storage_key, content_type, size_bytes, sha256) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    [document_id, n, key, content_type, len(data), hashlib.sha256(data).hexdigest()],
                )
    except BaseException:
        for key in written:  # the rows rolled back; do not leave orphan files
            storage.discard(key)
        raise
    return get(conn, document_id)


def _images(conn, document_id):
    return conn.cursor(row_factory=dict_row).execute(
        "SELECT n, content_type, size_bytes, sha256 FROM document_images WHERE document_id = %s ORDER BY n",
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
        conn.execute("UPDATE documents SET status = %s, updated_at = clock_timestamp() WHERE id = %s",
                     [target, document_id])
