"""M2 document upload and viewing, including caregiver access. Synthetic bytes only."""
import hashlib
from pathlib import Path
from types import SimpleNamespace

import psycopg
import pytest
from starlette.requests import Request

from swasthyoid.capture import documents, storage
from swasthyoid.tests.authz_matrix.test_caregiver import SCOPES, grant, w  # noqa: F401
from swasthyoid.tests.test_api_m1 import V1, api, login  # noqa: F401

JPEG = b"\xff\xd8\xff\xe0 synthetic prescription page"
PNG = b"\x89PNG\r\n\x1a\n synthetic lab report page"
OTHER = "+8801700000003"


@pytest.fixture
def d(w, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setenv("DOCUMENT_STORE", str(tmp_path))
    w.store = tmp_path
    return w


def files_in(d):
    return sorted(p for p in Path(d.store).rglob("*") if p.is_file())


def upload(d, who=None, patient=None, images=(JPEG,), doc_type="prescription", own=False, headers=None):
    who = who or d.patient
    url = f"{V1}/documents" if own else f"{V1}/patients/{(patient or d.patient).id}/documents"
    parts = [("images", (f"page{i}.bin", data, "application/octet-stream")) for i, data in enumerate(images)]
    data = {"doc_type": doc_type} if doc_type else {}
    return d.http.post(url, headers={**who.h, **(headers or {})}, data=data, files=parts or None)


def counts(d):
    return tuple(d.conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in ("documents", "document_images"))


def audit_rows(d, like):
    return d.conn.execute(
        "SELECT actor_id, actor_role, patient_id, purpose, result, reason FROM audit_logs "
        "WHERE action LIKE %s ORDER BY seq", [like]).fetchall()


# ---- upload

def test_patient_uploads_own_document_and_nothing_is_verified(d):
    r = upload(d, images=[JPEG, PNG], own=True)
    assert r.status_code == 201, r.text
    doc = r.json()
    assert (doc["status"], doc["doc_type"]) == ("uploaded", "prescription")
    assert doc["patient_id"] == doc["uploaded_by"] == str(d.patient.id)
    assert [(i["n"], i["content_type"], i["size_bytes"], i["sha256"]) for i in doc["images"]] == [
        (1, "image/jpeg", len(JPEG), hashlib.sha256(JPEG).hexdigest()),
        (2, "image/png", len(PNG), hashlib.sha256(PNG).hexdigest())]
    assert "storage_key" not in str(doc)

    assert d.http.get(f"{V1}/documents/{doc['id']}", headers=d.patient.h).json() == doc
    first = d.http.get(f"{V1}/documents/{doc['id']}/images/1", headers=d.patient.h)
    assert (first.content, first.headers["content-type"], first.headers["cache-control"]) == (
        JPEG, "image/jpeg", "no-store")
    assert d.http.get(f"{V1}/documents/{doc['id']}/images/2", headers=d.patient.h).content == PNG
    assert d.http.get(f"{V1}/documents/{doc['id']}/images/3", headers=d.patient.h).status_code == 404

    # uploading never verifies and never writes to the timeline
    assert d.conn.execute("SELECT count(*) FROM events").fetchone()[0] == 0
    assert d.conn.execute("SELECT verified_by FROM documents").fetchone()[0] is None
    # stored encrypted, in the FRD key layout
    stored = files_in(d)
    assert [p.relative_to(d.store).as_posix() for p in stored] == [
        f"patients/{d.patient.id}/documents/{doc['id']}/1.jpg", f"patients/{d.patient.id}/documents/{doc['id']}/2.png"]
    assert all(b"synthetic" not in p.read_bytes() for p in stored)


def test_caregiver_upload_records_patient_and_actor_separately(d):
    grant(d, ["upload_documents"])
    r = upload(d, who=d.caregiver)
    assert r.status_code == 201, r.text
    assert (r.json()["patient_id"], r.json()["uploaded_by"]) == (str(d.patient.id), str(d.caregiver.id))
    assert r.json()["status"] == "uploaded"
    assert d.conn.execute("SELECT count(*) FROM events").fetchone()[0] == 0
    assert audit_rows(d, "POST %/documents") == [
        (d.caregiver.id, "caregiver", d.patient.id, "CAREGIVER", "allow", None)]
    # upload_documents alone does not let the caregiver look at what they uploaded
    doc_id = r.json()["id"]
    assert d.http.get(f"{V1}/documents/{doc_id}", headers=d.caregiver.h).status_code == 404
    assert d.http.get(f"{V1}/documents/{doc_id}/images/1", headers=d.caregiver.h).status_code == 404
    assert d.http.get(f"{V1}/patients/{d.patient.id}/documents", headers=d.caregiver.h).status_code == 403
    assert d.http.get(f"{V1}/documents/{doc_id}", headers=d.patient.h).status_code == 200  # the patient sees it


@pytest.mark.parametrize("scope", ["view_documents", "view_timeline", None])
def test_only_the_upload_scope_allows_upload(d, scope):
    if scope:
        grant(d, [scope])
    r = upload(d, who=d.caregiver)
    assert r.status_code == 403
    assert r.json()["code"] == ("category_not_allowed" if scope else "consent_required")
    assert counts(d) == (0, 0) and files_in(d) == []


def test_access_is_checked_before_the_upload_is_read(d, monkeypatch):
    read = []
    real = Request.form
    monkeypatch.setattr(Request, "form", lambda self, **kw: read.append(1) or real(self, **kw))
    stranger = d.person(OTHER, "Synthetic Stranger")
    # an upload that is also invalid: a 403 (not 422) shows the check came first
    r = upload(d, who=stranger, images=[b"not an image"] * 3, doc_type="nonsense")
    assert (r.status_code, r.json()["code"]) == (403, "consent_required")
    assert read == [] and counts(d) == (0, 0) and files_in(d) == []
    assert audit_rows(d, "POST %/documents") == [
        (stranger.id, "caregiver", d.patient.id, "CAREGIVER", "deny", "consent_required")]
    assert upload(d).status_code == 201 and read == [1]


def test_revoked_caregiver_cannot_upload_or_view(d):
    consent_id = grant(d, SCOPES)
    doc_id = upload(d, who=d.caregiver).json()["id"]
    assert d.http.get(f"{V1}/documents/{doc_id}", headers=d.caregiver.h).status_code == 200
    d.http.post(f"{V1}/consents/{consent_id}/revoke", headers=d.patient.h)
    assert upload(d, who=d.caregiver).status_code == 403
    assert d.http.get(f"{V1}/documents/{doc_id}", headers=d.caregiver.h).status_code == 404
    assert d.http.get(f"{V1}/documents/{doc_id}/images/1", headers=d.caregiver.h).status_code == 404
    assert d.http.get(f"{V1}/patients/{d.patient.id}/documents", headers=d.caregiver.h).status_code == 403
    assert counts(d) == (1, 1)
    # the document they uploaded stays, still attributed to them
    assert d.conn.execute("SELECT uploaded_by FROM documents").fetchone()[0] == d.caregiver.id


def test_staff_and_unauthenticated_cannot_upload(d):
    doctor = SimpleNamespace(h=login(d.api, "+8801900000002", account="staff",
                                     staff={"role": "doctor", "name": "Synthetic Doctor"}))
    d.conn.execute("UPDATE users SET status = 'verified'")
    assert upload(d, who=doctor).json()["code"] == "role_not_allowed"
    assert upload(d, who=doctor, own=True).json()["code"] == "role_not_allowed"
    assert upload(d, who=SimpleNamespace(h={})).status_code == 401
    assert counts(d) == (0, 0) and files_in(d) == []


# ---- viewing and ownership

def test_view_scope_and_document_ownership(d):
    mine = upload(d).json()["id"]
    other = d.person(OTHER, "Synthetic Neighbour")
    theirs = upload(d, who=other, own=True).json()["id"]
    grant(d, ["view_documents"])  # the caregiver may view the first patient's documents only

    assert d.http.get(f"{V1}/documents/{mine}", headers=d.caregiver.h).status_code == 200
    assert d.http.get(f"{V1}/documents/{mine}/images/1", headers=d.caregiver.h).content == JPEG
    listed = d.http.get(f"{V1}/patients/{d.patient.id}/documents", headers=d.caregiver.h).json()
    assert [x["id"] for x in listed] == [mine]

    for headers in (d.caregiver.h, d.patient.h):  # neither can reach another patient's document
        assert d.http.get(f"{V1}/documents/{theirs}", headers=headers).status_code == 404
        assert d.http.get(f"{V1}/documents/{theirs}/images/1", headers=headers).status_code == 404
        assert d.http.get(f"{V1}/patients/{other.id}/documents", headers=headers).status_code == 403
    assert d.http.get(f"{V1}/documents/{mine}", headers=other.h).status_code == 404
    unknown = d.http.get(f"{V1}/documents/00000000-0000-0000-0000-000000000000", headers=other.h)
    refused = d.http.get(f"{V1}/documents/{mine}", headers=other.h)
    assert (unknown.status_code, unknown.text) == (refused.status_code, refused.text)  # indistinguishable

    # every refusal is audited against the real patient and the real actor
    denied = [r for r in audit_rows(d, "GET %documents%") if r[4] == "deny"]
    assert (other.id, "caregiver", d.patient.id, "CAREGIVER", "deny", "consent_required") in denied
    assert (d.caregiver.id, "caregiver", other.id, "CAREGIVER", "deny", "consent_required") in denied
    allowed = [r for r in audit_rows(d, "GET %documents%") if r[4] == "allow"]
    assert set(allowed) == {(d.caregiver.id, "caregiver", d.patient.id, "CAREGIVER", "allow", None)}
    assert d.http.get(f"{V1}/patients/{d.patient.id}/documents", headers=d.patient.h).status_code == 200


def test_doctor_needs_a_consent_that_covers_documents(d):
    doc_id = upload(d).json()["id"]
    doctor = login(d.api, "+8801900000002", account="staff", staff={"role": "doctor", "name": "Synthetic Doctor"})
    d.conn.execute("UPDATE users SET status = 'verified'")
    assert d.http.get(f"{V1}/documents/{doc_id}", headers=doctor).status_code == 404

    def consent(categories):
        d.conn.execute("UPDATE consents SET status = 'revoked' WHERE purpose = 'TIMELINE'")
        cid = d.http.post(f"{V1}/consents/requests", headers=doctor,
                          json={"health_id": d.patient.health_id, "categories": categories}).json()["id"]
        d.http.post(f"{V1}/consents/requests/{cid}/confirm", headers=doctor, json={"code": d.api.codes[d.patient.phone]})

    consent(["timeline"])
    assert d.http.get(f"{V1}/documents/{doc_id}", headers=doctor).status_code == 404
    consent(["timeline", "documents"])
    assert d.http.get(f"{V1}/documents/{doc_id}", headers=doctor).status_code == 200
    assert d.http.get(f"{V1}/documents/{doc_id}/images/1", headers=doctor).content == JPEG
    reasons = [r[5] for r in audit_rows(d, "GET /documents/{document_id}") if r[1] == "doctor"]
    assert reasons == ["consent_required", "category_not_allowed", None]


# ---- validation

@pytest.mark.parametrize("kwargs, status", [
    ({"doc_type": "horoscope"}, 422),
    ({"doc_type": None}, 422),
    ({"images": []}, 422),
    ({"images": [JPEG] * 11}, 422),
    ({"images": [b"GIF89a not allowed"]}, 422),
    ({"images": [JPEG, b"<html>not an image</html>"]}, 422),
    ({"images": [b""]}, 422),
])
def test_invalid_uploads_store_nothing(d, kwargs, status):
    r = upload(d, **kwargs)
    assert r.status_code == status and set(r.json()) == {"code", "message", "details"}
    assert counts(d) == (0, 0) and files_in(d) == []


def test_size_limits(d, monkeypatch):
    monkeypatch.setattr(documents, "MAX_IMAGE_BYTES", 40)
    assert upload(d, images=[JPEG + b"x" * 40]).status_code == 422
    assert upload(d, images=[JPEG]).status_code == 201
    from swasthyoid.api import documents as api_documents
    monkeypatch.setattr(api_documents, "MAX_REQUEST_BYTES", 10)
    r = upload(d, images=[JPEG])
    assert (r.status_code, r.json()["code"]) == (413, "too_large")
    assert counts(d) == (1, 1)


def test_the_claimed_file_type_is_ignored(d):
    r = d.http.post(f"{V1}/documents", headers=d.patient.h, data={"doc_type": "other"},
                    files=[("images", ("page.jpg", b"MZ this is a program", "image/jpeg"))])
    assert r.status_code == 422 and counts(d) == (0, 0)
    ok = d.http.post(f"{V1}/documents", headers=d.patient.h, data={"doc_type": "other"},
                     files=[("images", ("virus.exe", PNG, "application/x-msdownload"))])
    assert ok.status_code == 201 and ok.json()["images"][0]["content_type"] == "image/png"


# ---- immutability and integrity

def test_originals_are_immutable(d):
    doc_id = upload(d).json()["id"]
    for sql in ("UPDATE document_images SET sha256 = 'x'", "DELETE FROM document_images",
                "TRUNCATE document_images", "DELETE FROM documents", "TRUNCATE documents CASCADE",
                f"UPDATE documents SET patient_id = '{d.caregiver.id}'", "UPDATE documents SET doc_type = 'other'",
                f"UPDATE documents SET uploaded_by = '{d.caregiver.id}'"):
        with pytest.raises(psycopg.Error, match="append-only|immutable|cannot be deleted"):
            d.conn.execute(sql)
    documents.set_status(d.conn, doc_id, "extracting")  # only the status moves
    key = d.conn.execute("SELECT storage_key FROM document_images").fetchone()[0]
    with pytest.raises(FileExistsError):
        storage.put(key, b"replacement")
    with pytest.raises(ValueError):
        storage.put("../outside.jpg", JPEG)
    assert d.http.get(f"{V1}/documents/{doc_id}/images/1", headers=d.patient.h).content == JPEG


def test_a_tampered_or_missing_original_is_detected(d):
    doc_id = upload(d, images=[JPEG, PNG]).json()["id"]
    first, second = files_in(d)
    first.write_bytes(storage.Fernet(storage.os.environ["DOCUMENT_KEY"]).encrypt(JPEG + b" altered"))
    second.unlink()
    for n in (1, 2):
        r = d.http.get(f"{V1}/documents/{doc_id}/images/{n}", headers=d.patient.h)
        assert (r.status_code, r.json()["code"]) == (500, "document_corrupted")
        with pytest.raises(documents.Corrupted):
            documents.read_image(d.conn, doc_id, n)


def test_failed_upload_leaves_no_rows_and_no_files(d, monkeypatch):
    real, calls = storage.put, []

    def fail_on_second(key, data):
        calls.append(key)
        if len(calls) == 2:
            raise OSError("disk full")
        real(key, data)

    monkeypatch.setattr(storage, "put", fail_on_second)
    with pytest.raises(OSError):
        upload(d, images=[JPEG, PNG])
    assert len(calls) == 2 and counts(d) == (0, 0) and files_in(d) == []


# ---- idempotency and state machine

def test_same_key_uploads_once(d):
    key = {"Idempotency-Key": "upload-1"}
    first = upload(d, images=[JPEG, PNG], headers=key)
    second = upload(d, images=[JPEG, PNG], headers=key)
    assert (first.status_code, second.status_code) == (201, 201) and first.json() == second.json()
    assert counts(d) == (1, 2) and len(files_in(d)) == 2
    different = upload(d, images=[PNG], headers=key)
    assert (different.status_code, different.json()["code"]) == (422, "idempotency_key_reused")
    assert upload(d, images=[JPEG, PNG]).status_code == 201  # no key: a second document
    assert counts(d) == (2, 4)


def test_document_state_machine(d):
    allowed = {(s, t) for s, targets in documents.TRANSITIONS.items() for t in targets}
    assert allowed == {
        ("uploaded", "extracting"), ("uploaded", "needs_review"),  # needs_review: the patient's manual entry (D12)
        ("extracting", "needs_review"), ("extracting", "extraction_failed"),
        ("extraction_failed", "extracting"), ("extraction_failed", "needs_review"),
        ("needs_review", "verified"), ("needs_review", "rejected"),
    }
    doc_id = upload(d).json()["id"]
    for bad in ("verified", "rejected", "uploaded"):  # nothing skips review; only manual entry skips extraction
        with pytest.raises(ValueError):
            documents.set_status(d.conn, doc_id, bad)
    for step in ("extracting", "extraction_failed", "extracting", "needs_review", "rejected"):
        documents.set_status(d.conn, doc_id, step)
    skipped = upload(d).json()["id"]
    documents.set_status(d.conn, skipped, "needs_review")  # uploaded -> needs_review is the manual-entry move
    for final in documents.TRANSITIONS:
        with pytest.raises(ValueError):
            documents.set_status(d.conn, doc_id, final)
    with pytest.raises(LookupError):
        documents.set_status(d.conn, "00000000-0000-0000-0000-000000000000", "extracting")
