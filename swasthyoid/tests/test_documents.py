"""M2 document upload and viewing, including caregiver access. Synthetic bytes only."""
import hashlib
from pathlib import Path
from types import SimpleNamespace

import psycopg
import pytest
from starlette.requests import Request

from swasthyoid.capture import documents, imaging, storage
from swasthyoid.capture.guidance import GUIDANCE
from swasthyoid.tests import images as img
from swasthyoid.tests.authz_matrix.test_caregiver import SCOPES, grant, w  # noqa: F401
from swasthyoid.tests.test_api_m1 import V1, api, login  # noqa: F401

JPEG, PNG = img.JPEG, img.PNG  # real, decodable synthetic pages: an upload is decoded and quality-checked (D5)
OTHER = "+8801700000003"


@pytest.fixture
def d(w, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setenv("DOCUMENT_STORE", str(tmp_path))
    w.store = tmp_path
    return w


def files_in(d):
    return sorted(p for p in Path(d.store).rglob("*") if p.is_file())


def upload(d, who=None, patient=None, images=(JPEG,), doc_type="prescription", own=False, headers=None, extra=None):
    who = who or d.patient
    url = f"{V1}/documents" if own else f"{V1}/patients/{(patient or d.patient).id}/documents"
    parts = [("images", (f"page{i}.bin", data, "application/octet-stream")) for i, data in enumerate(images)]
    data = {"doc_type": doc_type} if doc_type else {}
    data.update(extra or {})
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
    assert all(JPEG[:64] not in p.read_bytes() and PNG[:64] not in p.read_bytes() for p in stored)


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
    served = d.http.get(f"{V1}/documents/{mine}/images/1", headers=d.caregiver.h)
    assert served.content == imaging.strip_metadata(JPEG)[0] and served.content != JPEG  # D6: not the patient, so a stripped copy
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
    assert d.http.get(f"{V1}/documents/{doc_id}/images/1", headers=doctor).content == imaging.strip_metadata(JPEG)[0]
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
    monkeypatch.setattr(documents, "MAX_IMAGE_BYTES", len(JPEG))
    too_big = upload(d, images=[JPEG + b"x"])
    assert (too_big.status_code, too_big.json()["code"]) == (422, "image_file_too_large")
    assert upload(d, images=[JPEG]).status_code == 201  # exactly at the limit
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


# ---- Phase 5 (decision D5/D6): hard validation, quality warnings with Bangla guidance, upload anyway, EXIF at serve time

def override_rows(d):
    return d.conn.execute("SELECT actor_id, actor_role, patient_id, result, reason FROM audit_logs "
                          "WHERE action = 'document.upload_override' ORDER BY seq").fetchall()


def test_a_clean_upload_records_that_it_was_checked_and_had_no_warnings(d):
    r = upload(d, images=[JPEG, PNG])
    assert r.status_code == 201 and [i["quality_warnings"] for i in r.json()["images"]] == [[], []]
    assert override_rows(d) == []  # nothing was overridden, so nothing is recorded as an override


def test_a_poor_page_is_refused_with_its_reason_and_the_bangla_guidance_and_nothing_is_stored(d):
    r = upload(d, images=[JPEG, img.poor_page("rotate")])
    assert r.status_code == 422 and set(r.json()) == {"code", "message", "details"}
    assert r.json()["code"] == "image_quality_warning"
    assert r.json()["details"] == {"pages": [{"page": 2, "reasons": ["image_skewed"], "guidance": [
        {"code": "image_skewed", "bn": GUIDANCE["image_skewed"]["bn"]}]}]}
    assert counts(d) == (0, 0) and files_in(d) == [] and override_rows(d) == []


def test_upload_anyway_stores_the_original_unchanged_with_its_warnings_and_one_audit_entry(d):
    poor = img.poor_page("rotate")
    r = upload(d, images=[JPEG, poor], extra={"upload_anyway": "true"})
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc["status"] == "uploaded" and [i["quality_warnings"] for i in doc["images"]] == [[], ["image_skewed"]]
    assert d.http.get(f"{V1}/documents/{doc['id']}/images/2", headers=d.patient.h).content == poor  # the original, as sent
    assert d.conn.execute("SELECT quality_warnings FROM document_images ORDER BY n").fetchall() == [([],), (["image_skewed"],)]
    assert override_rows(d) == [(d.patient.id, "patient", d.patient.id, "allow", "page 2: image_skewed")]
    assert counts(d) == (1, 2) and d.conn.execute("SELECT count(*) FROM events").fetchone()[0] == 0


def test_a_caregiver_override_is_audited_against_the_caregiver_and_the_patient(d):
    grant(d, ["upload_documents"])
    r = upload(d, who=d.caregiver, images=[img.poor_page("blur")], extra={"upload_anyway": "true"})
    assert r.status_code == 201, r.text
    ((actor, role, patient, result, reason),) = override_rows(d)
    assert (actor, role, patient, result) == (d.caregiver.id, "caregiver", d.patient.id, "allow")
    assert reason.startswith("page 1: image_blurry")


@pytest.mark.parametrize("what, code", [(b"GIF89a not allowed", "image_unsupported"),
                                        (b"\x89PNG\r\n\x1a\n" + b"not really a png", "image_undecodable"),
                                        (img.truncated(img.PNG), "image_undecodable")])
def test_hard_failures_are_never_bypassed_by_upload_anyway(d, what, code):
    r = upload(d, images=[JPEG, what], extra={"upload_anyway": "true"})
    assert (r.status_code, r.json()["code"], r.json()["details"]) == (422, code, {"page": 2})
    assert counts(d) == (0, 0) and files_in(d) == [] and override_rows(d) == []


def test_the_pixel_cap_and_the_file_size_cap_are_never_bypassed_by_upload_anyway(d, monkeypatch):
    monkeypatch.setattr(imaging, "MAX_PIXELS", 10)
    r = upload(d, images=[JPEG], extra={"upload_anyway": "true"})
    assert (r.status_code, r.json()["code"], r.json()["details"]) == (422, "image_too_large", {"page": 1})
    monkeypatch.setattr(imaging, "MAX_PIXELS", 40_000_000)
    monkeypatch.setattr(documents, "MAX_IMAGE_BYTES", len(JPEG) - 1)
    r = upload(d, images=[JPEG], extra={"upload_anyway": "true"})
    assert (r.status_code, r.json()["code"]) == (422, "image_file_too_large")
    assert counts(d) == (0, 0) and files_in(d) == []


@pytest.mark.parametrize("value", ["yes", "1", "TRUE", ""])
def test_upload_anyway_must_be_true_or_false(d, value):
    r = upload(d, images=[img.poor_page("rotate")], extra={"upload_anyway": value})
    assert (r.status_code, r.json()["code"]) == (422, "invalid_upload") and counts(d) == (0, 0)


def test_upload_anyway_false_behaves_like_no_flag(d):
    r = upload(d, images=[img.poor_page("rotate")], extra={"upload_anyway": "false"})
    assert (r.status_code, r.json()["code"]) == (422, "image_quality_warning") and counts(d) == (0, 0)


def test_a_retake_is_a_new_upload_and_the_refused_attempt_left_nothing_behind(d):
    assert upload(d, images=[img.poor_page("glare")]).status_code == 422
    assert counts(d) == (0, 0)
    assert upload(d, images=[JPEG]).status_code == 201 and counts(d) == (1, 1)


def test_the_flag_is_part_of_the_idempotent_request_and_a_refused_upload_does_not_burn_its_key(d):
    key = {"Idempotency-Key": "photo-1"}
    poor = img.poor_page("rotate")
    assert upload(d, images=[poor], headers=key).status_code == 422  # refused: the key is free again
    first = upload(d, images=[poor], headers=key, extra={"upload_anyway": "true"})
    second = upload(d, images=[poor], headers=key, extra={"upload_anyway": "true"})
    assert (first.status_code, second.status_code) == (201, 201) and first.json() == second.json()
    assert counts(d) == (1, 1) and len(override_rows(d)) == 1  # replayed, not stored or audited twice
    again = upload(d, images=[poor], headers=key, extra={"upload_anyway": "false"})
    assert (again.status_code, again.json()["code"]) == (422, "idempotency_key_reused")


def test_the_database_refuses_an_unknown_quality_code(d):
    doc_id = upload(d).json()["id"]
    with pytest.raises(psycopg.errors.CheckViolation):
        d.conn.execute("INSERT INTO document_images (document_id, n, storage_key, content_type, size_bytes, sha256, "
                       "quality_warnings) VALUES (%s, 2, 'k', 'image/png', 1, 'x', ARRAY['not_a_code'])", [doc_id])
    with pytest.raises(psycopg.Error, match="append-only"):
        d.conn.execute("UPDATE document_images SET quality_warnings = '{}'")  # the record cannot be edited afterwards


def test_the_patient_gets_the_original_with_its_metadata_and_others_get_a_copy_without_it(d):
    import io

    from PIL import Image
    data = img.jpeg_with_metadata(orientation=6)
    doc_id = upload(d, images=[data]).json()["id"]
    grant(d, ["view_documents"])
    mine = d.http.get(f"{V1}/documents/{doc_id}/images/1", headers=d.patient.h)
    assert mine.content == data and b"SYNTHETIC-CAMERA-MAKER" in mine.content  # the stored original, untouched
    theirs = d.http.get(f"{V1}/documents/{doc_id}/images/1", headers=d.caregiver.h)
    assert theirs.status_code == 200 and theirs.headers["content-type"] == "image/jpeg"
    copy = Image.open(io.BytesIO(theirs.content))
    assert copy.size == (1000, 1400) and len(copy.getexif()) == 0  # the orientation was applied, then the metadata dropped
    assert b"SYNTHETIC-CAMERA-MAKER" not in theirs.content and b"SYNTHETIC-COMMENT" not in theirs.content
    assert d.http.get(f"{V1}/documents/{doc_id}/images/1", headers=d.patient.h).content == data  # still unchanged


def test_when_the_copy_cannot_be_made_nothing_is_served_to_others_and_the_patient_is_unaffected(d, monkeypatch):
    doc_id = upload(d).json()["id"]
    grant(d, ["view_documents"])

    def broken(data):
        raise imaging.ImageRejected("image_undecodable")

    monkeypatch.setattr(imaging, "strip_metadata", broken)
    r = d.http.get(f"{V1}/documents/{doc_id}/images/1", headers=d.caregiver.h)
    assert (r.status_code, r.json()["code"]) == (500, "image_unavailable") and JPEG[:32] not in r.content
    assert d.http.get(f"{V1}/documents/{doc_id}/images/1", headers=d.patient.h).content == JPEG
