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

How a job runs (worker reliability, docs/DECISIONS.md):
  1. claim   short transaction: take a due document other workers are not holding
             (FOR UPDATE SKIP LOCKED), count the attempt, write a fresh claim token and a lease.
  2. work    no transaction open: read the images and run the engine in a child process that
             is killed at the hard timeout. The lease is renewed on a heartbeat meanwhile.
  3. store   short transaction: keep the result only if the claim token is still ours and the
             lease has not run out. A late or superseded worker changes nothing.
A worker that dies or hangs just stops renewing; when the lease ends the document is due
again as the next attempt, and after the last attempt it becomes extraction_failed.

shortcut: no Celery yet, run_due is a plain function; a runner that calls it is a later step.
"""
import multiprocessing
import os
import threading
import time
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
# Worker reliability settings. Configurable defaults approved by the owner, not FRD values.
MAX_ATTEMPTS = 3
BACKOFF = timedelta(minutes=1)          # wait before a retry; doubles each time
LEASE = timedelta(minutes=5)            # how long a claim holds without a heartbeat
HEARTBEAT = timedelta(seconds=60)       # how often a working attempt renews its lease
# The engine runs in a child process that is killed after this long. A database timeout cannot
# stop a hung OCR process; killing it can. None runs the engine inside the worker instead,
# with no heartbeat and no hard timeout. That mode is for unit tests with engines that cannot
# be sent to another process, and is refused unless APP_ENV=test.
HARD_TIMEOUT = timedelta(minutes=10)

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


class AttemptFailed(Exception):
    """This attempt is over; args[0] is a short reason with no document text."""


class LeaseLost(Exception):
    """The claim is no longer ours. Stop, and change nothing."""


_DUE = "(status = 'uploaded' OR (status = 'extracting' AND next_extraction_at <= clock_timestamp()))"
_MINE = "id = %s AND extraction_claim = %s AND status = 'extracting'"
_DEFAULTS = ("threshold", "ai_threshold", "max_attempts", "backoff", "lease", "heartbeat", "hard_timeout")


def _settings(given):
    """Per-call settings over the module constants, read now so they can be reconfigured."""
    unknown = set(given) - set(_DEFAULTS)
    if unknown:
        raise TypeError(f"unknown extraction options: {sorted(unknown)}")
    o = {"threshold": CONFIDENCE_THRESHOLD, "ai_threshold": CLOUD_AI_THRESHOLD, "max_attempts": MAX_ATTEMPTS,
         "backoff": BACKOFF, "lease": LEASE, "heartbeat": HEARTBEAT, "hard_timeout": HARD_TIMEOUT, **given}
    if o["hard_timeout"] is None:
        if os.environ.get("APP_ENV") != "test":
            raise RuntimeError("in-process OCR (no heartbeat, no hard timeout) is only allowed with APP_ENV=test")
    elif o["heartbeat"] >= o["lease"]:
        raise ValueError("heartbeat must be shorter than the lease, or every lease runs out before it is renewed")
    return o


def claim(conn, document_id=None, *, lease=None, max_attempts=None):
    """Take one due document for one attempt, or return None if there is none to take.

    Counts the attempt and writes a new claim token and lease in one short transaction. A
    document another worker has locked is skipped, never waited for. A document whose
    attempts are used up (its last attempt never reported back) is closed as
    extraction_failed here. Returns {id, patient_id, doc_type, attempt, version, token}.
    """
    if not conn.autocommit:
        raise ValueError("extraction needs an autocommit connection, so each step commits on its own")
    lease, max_attempts = lease or LEASE, max_attempts or MAX_ATTEMPTS
    while True:
        with conn.transaction():
            doc = conn.cursor(row_factory=dict_row).execute(
                f"SELECT * FROM documents WHERE {_DUE} {'AND id = %s' if document_id else ''} "
                "ORDER BY created_at, id LIMIT 1 FOR UPDATE SKIP LOCKED",
                [document_id] if document_id else [],
            ).fetchone()
            if doc is None:
                return None
            if doc["extraction_attempts"] < max_attempts:
                token = uuid4()
                conn.execute(
                    "UPDATE documents SET status = 'extracting', extraction_attempts = extraction_attempts + 1, "
                    "extraction_claim = %s, next_extraction_at = clock_timestamp() + %s, "
                    # a claim that was still set means the previous attempt never reported back
                    "extraction_error = CASE WHEN extraction_claim IS NULL THEN extraction_error ELSE 'LeaseExpired' END, "
                    "updated_at = clock_timestamp() WHERE id = %s",
                    [token, lease, doc["id"]],
                )
                return {"id": doc["id"], "patient_id": doc["patient_id"], "doc_type": doc["doc_type"],
                        "attempt": doc["extraction_attempts"] + 1, "version": _next_version(conn, doc["id"]),
                        "token": token}
            conn.execute(
                "UPDATE documents SET status = 'extraction_failed', extraction_claim = NULL, "
                "next_extraction_at = NULL, extraction_error = 'LeaseExpired', updated_at = clock_timestamp() "
                "WHERE id = %s", [doc["id"]])
        if document_id:
            return None


def _renew(conn, job, lease):
    """Heartbeat: push the lease forward. False if the claim is gone or the lease already ran out."""
    return conn.execute(
        f"UPDATE documents SET next_extraction_at = clock_timestamp() + %s "
        f"WHERE {_MINE} AND next_extraction_at > clock_timestamp()",
        [lease, job["id"], job["token"]],
    ).rowcount == 1


def _child(engine, pages, doc_type, out, limit):
    """Runs in the child process: the engine, and nothing that touches the database."""
    def watchdog():  # an orphan must not outlive its worker, nor the hard timeout
        deadline = time.monotonic() + limit
        while time.monotonic() < deadline and multiprocessing.parent_process().is_alive():
            time.sleep(1)
        os._exit(1)

    threading.Thread(target=watchdog, daemon=True).start()
    try:
        out.send(("ok", engine(pages, doc_type)))
    except BaseException as e:
        out.send(("failed", type(e).__name__))


def _run_engine(engine, pages, doc_type, hard_timeout, heartbeat, renew):
    """The engine's result. Raises AttemptFailed (engine error, child died, hard timeout) or
    LeaseLost. With a hard timeout the engine runs in a child process that is always killed
    before this returns."""
    if hard_timeout is None:
        try:
            return engine(pages, doc_type)
        except Exception as e:
            raise AttemptFailed(type(e).__name__)
    spawn = multiprocessing.get_context("spawn")
    results, out = spawn.Pipe(duplex=False)
    child = spawn.Process(target=_child, args=(engine, pages, doc_type, out, hard_timeout.total_seconds() + 5),
                          daemon=True)
    child.start()
    out.close()
    deadline = time.monotonic() + hard_timeout.total_seconds()
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AttemptFailed("HardTimeout")
            if results.poll(min(heartbeat.total_seconds(), remaining)):
                try:
                    outcome, value = results.recv()
                except (EOFError, OSError):
                    raise AttemptFailed("WorkerDied")
                if outcome != "ok":
                    raise AttemptFailed(value)
                return value
            if not renew():
                raise LeaseLost()
    finally:
        if child.is_alive():
            child.kill()
        child.join(10)
        results.close()


def _fail(conn, job, reason, max_attempts, backoff):
    """Record a failed attempt, if the claim is still ours and inside its lease. The last
    attempt closes the document. A stale worker writes nothing: the next claim deals with it."""
    final = job["attempt"] >= max_attempts
    conn.execute(
        f"UPDATE documents SET status = %s, extraction_claim = NULL, extraction_error = %s, "
        f"next_extraction_at = CASE WHEN %s THEN NULL ELSE clock_timestamp() + %s END, "
        f"updated_at = clock_timestamp() WHERE {_MINE} AND next_extraction_at > clock_timestamp()",
        ["extraction_failed" if final else "extracting", str(reason)[:100], final,
         backoff * 2 ** (job["attempt"] - 1), job["id"], job["token"]],
    )


def _attempt(conn, job, engine, ai, o):
    """Work and store for one claimed attempt. Never raises for a failed attempt."""
    try:
        pages = [documents.read_image(conn, job["id"], i["n"])[1]
                 for i in documents.get(conn, job["id"])["images"]]
        got = _run_engine(engine, pages, job["doc_type"], o["hard_timeout"], o["heartbeat"],
                          lambda: _renew(conn, job, o["lease"]))
        spec = SCHEMAS.get(job["doc_type"], {})
        fields = structure(spec, got.get("fields"), o["threshold"])
        _cloud_ai(conn, job, pages, spec, fields, ai, o["threshold"], o["ai_threshold"])
        with conn.transaction():
            # the fence: only the current claim, inside its lease, may store a result
            mine = conn.execute(
                f"SELECT 1 FROM documents WHERE {_MINE} AND next_extraction_at > clock_timestamp() FOR UPDATE",
                [job["id"], job["token"]]).fetchone()
            if mine is None:
                raise LeaseLost()
            _store(conn, job["id"], job["version"], str(got.get("engine") or "unknown"), fields,
                   str(got.get("raw_text") or ""))
            conn.execute(
                "UPDATE documents SET status = 'needs_review', extraction_claim = NULL, extraction_error = NULL, "
                "next_extraction_at = NULL, updated_at = clock_timestamp() WHERE id = %s", [job["id"]])
    except LeaseLost:
        pass  # another attempt owns the document now, or will: leave everything as it is
    except AttemptFailed as e:
        _fail(conn, job, e.args[0], o["max_attempts"], o["backoff"])
    except Exception as e:
        _fail(conn, job, type(e).__name__, o["max_attempts"], o["backoff"])


def extract(conn, document_id, version, engine, ai=None, **options):
    """Run one extraction job. Keyed by (document_id, version): a repeat, a job for a document
    that is not due, or one another worker holds, does nothing and returns False.
    Options: threshold, ai_threshold, max_attempts, backoff, lease, heartbeat, hard_timeout."""
    o = _settings(options)
    if version != _next_version(conn, document_id):
        return False
    job = claim(conn, document_id, lease=o["lease"], max_attempts=o["max_attempts"])
    if job is None or job["version"] != version:
        return False
    _attempt(conn, job, engine, ai, o)
    return True


def run_due(conn, engine, ai=None, *, limit=100, **options):
    """Claim and run due extraction jobs until none is left; returns how many attempts ran.
    Several workers can run this at once: each takes different documents."""
    o = _settings(options)
    done = 0
    while done < limit:
        job = claim(conn, lease=o["lease"], max_attempts=o["max_attempts"])
        if job is None:
            break
        _attempt(conn, job, engine, ai, o)
        done += 1
    return done


def requeue(conn, document_id):
    """extraction_failed -> extracting: try again from the first attempt."""
    with conn.transaction():
        documents.set_status(conn, document_id, "extracting")
        conn.execute("UPDATE documents SET extraction_attempts = 0, extraction_claim = NULL, "
                     "next_extraction_at = clock_timestamp() WHERE id = %s", [document_id])


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
