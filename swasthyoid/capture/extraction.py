"""M2 — extraction pipeline (FRD M2, section 8).

Reads a document's images with an OCR engine, shapes the result into the typed schema with
a confidence per field, and leaves the document in `needs_review` or `extraction_failed`.
It never writes to the timeline: only M3's confirm step creates events.

An engine is engine(pages, doc_type) -> {"engine": name, "raw_text": str, "fields": {...}},
where a field is {"value", "confidence"} and a repeated group is a list of such dicts.
The real OCR engine and image pre-processing come later; tests pass fakes.

A cloud AI provider is ai(pages, doc_type, paths) -> {path: {"value", "confidence"}}. It is
called only for a patient who opted in, and only for the low-confidence fields.
PLACEHOLDER: no provider is chosen (DECISIONS.md Q5), so callers pass none.

shortcut: no Celery yet, run_due is a plain function; wrap it in a task when Redis and
hosting exist. The document row stays locked while the engine runs.
"""
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from swasthyoid.capture import documents
from swasthyoid.core import audit

CONFIDENCE_THRESHOLD = 0.85     # manual review: FRD M3 start value, configurable
# Below this confidence a field may be sent to the cloud AI (opt-in patients only).
# DECISION-PENDING: the FRD gives no number for this and does not say it equals the review
# threshold. None means nothing is ever sent, whatever the opt-in.
CLOUD_AI_THRESHOLD = None
# Engineering defaults, not FRD values.
MAX_ATTEMPTS = 3
BACKOFF = timedelta(minutes=1)

# doc_type -> {field: kind}. kind is "text", "number" or "date"; a repeated group is
# [{sub_field: kind}]. Fields an engine returns that are not listed here are dropped.
# PENDING APPROVAL: the FRD says "typed schema" but lists no fields. Until the list in
# docs/DECISIONS.md is approved this is empty, so every document goes to review with its
# raw text only.
SCHEMAS = {}

_BANGLA_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y")  # day first, as written in Bangladesh


def normalise_numerals(text):
    return text.translate(_BANGLA_DIGITS)


def parse(kind, value):
    """The value in its stored form, or ValueError."""
    text = normalise_numerals(str(value)).strip()
    if not text:
        raise ValueError("empty")
    if kind == "text":
        return text
    if kind == "number":
        try:
            number = Decimal(text)
        except InvalidOperation:
            raise ValueError("not a number")
        if not number.is_finite():
            raise ValueError("not a number")
        return str(number)
    if kind == "date":
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(text, fmt).date().isoformat()
            except ValueError:
                pass
        raise ValueError("not a date")
    raise ValueError(f"unknown kind {kind}")


def _field(kind, got, threshold, source="ocr"):
    """One schema field. Below the threshold, missing or invalid: left empty for manual entry
    (FRD section 8). `raw` keeps what was read, for the reviewer to see."""
    out = {"value": None, "raw": None, "confidence": 0.0, "source": None, "manual_entry": True}
    if not isinstance(got, dict) or got.get("value") is None:
        return out
    try:
        confidence = min(max(float(got.get("confidence", 0)), 0.0), 1.0)
    except (TypeError, ValueError):
        confidence = 0.0
    out.update(raw=str(got["value"]), confidence=confidence, source=source)
    if confidence >= threshold:
        try:
            out.update(value=parse(kind, got["value"]), manual_entry=False)
        except ValueError:
            out["error"] = f"invalid_{kind}"
    return out


def structure(spec, got, threshold):
    """Shape engine output into the schema: every schema field present, nothing else kept."""
    got = got if isinstance(got, dict) else {}
    out = {}
    for name, kind in spec.items():
        if isinstance(kind, list):
            rows = got.get(name) if isinstance(got.get(name), list) else []
            out[name] = [{sub: _field(k, row.get(sub), threshold) for sub, k in kind[0].items()}
                         for row in rows if isinstance(row, dict)]
        else:
            out[name] = _field(kind, got.get(name), threshold)
    return out


def _slots(spec, fields):
    """(path, kind, holder, key) for every field, e.g. path "items[0].name"."""
    for name, kind in spec.items():
        if isinstance(kind, list):
            for i, row in enumerate(fields[name]):
                for sub, k in kind[0].items():
                    yield f"{name}[{i}].{sub}", k, row, sub
        else:
            yield name, kind, fields, name


def _cloud_ai(conn, doc, pages, spec, fields, ai, threshold, ai_threshold):
    """Send fields below ai_threshold to the cloud AI, only if the patient opted in. An answer
    is judged against the review threshold like any other reading, and never replaces an
    accepted value with a rejected one."""
    if ai is None or ai_threshold is None:
        return
    low = [s for s in _slots(spec, fields)
           if s[2][s[3]]["confidence"] < ai_threshold and "error" not in s[2][s[3]]]
    opted_in = conn.execute("SELECT cloud_ai_opt_in FROM patients WHERE id = %s", [doc["patient_id"]]).fetchone()[0]
    if opted_in is not True or not low:
        return
    audit.append(conn, action="cloud_ai.send", result="allow", patient_id=doc["patient_id"], purpose="CLOUD_AI",
                 resource_type="document", resource_id=doc["id"])
    try:
        answers = ai(pages, doc["doc_type"], [s[0] for s in low])
    except Exception:
        return  # provider error: those fields simply stay for manual entry
    for path, kind, holder, key in low:
        if isinstance(answers, dict) and path in answers:
            answer = _field(kind, answers[path], threshold, source="cloud_ai")
            if holder[key]["manual_entry"] or not answer["manual_entry"]:
                holder[key] = answer


def _store(conn, document_id, version, engine, fields, raw_text):
    conn.execute(
        "INSERT INTO extractions (id, document_id, version, engine, fields, raw_text) VALUES (%s, %s, %s, %s, %s, %s)",
        [uuid4(), document_id, version, engine, Jsonb(fields), raw_text],
    )


def _next_version(conn, document_id):
    return conn.execute(
        "SELECT coalesce(max(version), 0) + 1 FROM extractions WHERE document_id = %s", [document_id]).fetchone()[0]


def extract(conn, document_id, version, engine, ai=None, *, threshold=CONFIDENCE_THRESHOLD,
            ai_threshold=CLOUD_AI_THRESHOLD, max_attempts=MAX_ATTEMPTS, backoff=BACKOFF):
    """Run one extraction job. Keyed by (document_id, version): a repeat, or a job for a
    document that is not waiting for this version, does nothing and returns False."""
    with conn.transaction():
        doc = conn.cursor(row_factory=dict_row).execute(
            "SELECT * FROM documents WHERE id = %s FOR UPDATE", [document_id]).fetchone()
        if doc is None or doc["status"] not in ("uploaded", "extracting") or version != _next_version(conn, document_id):
            return False
        if doc["status"] == "uploaded":
            documents.set_status(conn, document_id, "extracting")
        try:
            with conn.transaction():
                pages = [documents.read_image(conn, document_id, i["n"])[1]
                         for i in documents.get(conn, document_id)["images"]]
                got = engine(pages, doc["doc_type"])
                spec = SCHEMAS.get(doc["doc_type"], {})
                fields = structure(spec, got.get("fields"), threshold)
                _cloud_ai(conn, doc, pages, spec, fields, ai, threshold, ai_threshold)
                _store(conn, document_id, version, str(got.get("engine") or "unknown"), fields,
                       str(got.get("raw_text") or ""))
                documents.set_status(conn, document_id, "needs_review")
        except Exception as e:
            attempts = doc["extraction_attempts"] + 1
            if attempts >= max_attempts:
                documents.set_status(conn, document_id, "extraction_failed")
            conn.execute(
                "UPDATE documents SET extraction_attempts = %s, extraction_error = %s, "
                "next_extraction_at = clock_timestamp() + %s WHERE id = %s",
                [attempts, type(e).__name__, backoff * 2 ** (attempts - 1), document_id],
            )
        return True


def run_due(conn, engine, ai=None, *, limit=100, **options):
    """Run every due extraction job once; returns how many ran. Safe with several workers."""
    done = 0
    while done < limit:
        row = conn.execute(
            """SELECT id FROM documents
               WHERE status = 'uploaded' OR (status = 'extracting' AND next_extraction_at <= clock_timestamp())
               ORDER BY created_at, id LIMIT 1""").fetchone()
        if row is None or not extract(conn, row[0], _next_version(conn, row[0]), engine, ai, **options):
            break
        done += 1
    return done


def requeue(conn, document_id):
    """extraction_failed -> extracting: try again from the first attempt."""
    with conn.transaction():
        documents.set_status(conn, document_id, "extracting")
        conn.execute("UPDATE documents SET extraction_attempts = 0, next_extraction_at = clock_timestamp() "
                     "WHERE id = %s", [document_id])


def manual_entry(conn, document_id, *, threshold=CONFIDENCE_THRESHOLD):
    """extraction_failed -> needs_review with every field empty, to be typed in by hand."""
    with conn.transaction():
        doc_type = conn.execute("SELECT doc_type FROM documents WHERE id = %s FOR UPDATE", [document_id]).fetchone()
        if doc_type is None:
            raise LookupError("document not found")
        documents.set_status(conn, document_id, "needs_review")
        _store(conn, document_id, _next_version(conn, document_id), "manual",
               structure(SCHEMAS.get(doc_type[0], {}), {}, threshold), "")


def latest(conn, document_id):
    """The newest extraction of a document, or None."""
    return conn.cursor(row_factory=dict_row).execute(
        "SELECT version, engine, fields, raw_text, created_at FROM extractions "
        "WHERE document_id = %s ORDER BY version DESC LIMIT 1", [document_id]).fetchone()
