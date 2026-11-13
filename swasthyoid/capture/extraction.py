"""M2 — extraction pipeline (FRD M2, section 8).

Reads a document's images with an OCR engine, shapes the result into the typed schema with
a confidence per field, and leaves the document in `needs_review` or `extraction_failed`.
It never writes to the timeline: only M3's confirm step creates events.

The OCR engine is the adapter named by OCR_ADAPTER (capture/ocr.py, step 4A). Before anything is
claimed, an isolated probe checks that it is available; if not, nothing is claimed and documents
stay `uploaded` (Option A). Outside test mode no adapter is ever available until an OCR interface
version beyond the test-only version 0 is approved (D18) and the owner approves integration.

DEPRECATED, test mode only: an engine passed in as a callable,
engine(pages, doc_type) -> {"engine": name, "raw_text": str, "fields": {...}}, where a field is
{"value", "confidence"} and a repeated group is a list of such dicts.
shortcut: legacy engine path, test-only; remove after 6B parsers replace engine-supplied fields.

A cloud AI provider is ai(pages, doc_type, paths) -> {path: {"value", "confidence"}}. It is
called only for a patient who opted in, and only for the low-confidence fields.
PLACEHOLDER: no provider is chosen (DECISIONS.md Q5), so callers pass none.

How a job runs (worker reliability, docs/DECISIONS.md):
  1. claim   short transaction: take a due document other workers are not holding
             (FOR UPDATE SKIP LOCKED), count the attempt, write a fresh claim token and a lease.
  2. work    no transaction open: read the images, renew the lease once, and run the engine in
             a child process that is killed at the hard timeout. The lease is renewed on a
             heartbeat meanwhile.
  3. store   short transaction: keep the result only if the claim token is still ours and the
             lease has not run out. A late or superseded worker changes nothing.
A worker that dies or hangs just stops renewing; when the lease ends the document is due
again as the next attempt, and after the last attempt it becomes extraction_failed.

shortcut: no Celery yet, run_due is a plain function; a runner that calls it is a later step.
"""
import functools
import logging
import multiprocessing
import os
import time
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from swasthyoid import runtime_mode
from swasthyoid.capture import documents, imaging, ocr
from swasthyoid.core import audit

log = logging.getLogger(__name__)

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
# be sent to another process, and is refused unless in test mode (runtime_mode).
HARD_TIMEOUT = timedelta(minutes=10)
# Operations applied to a transient processing copy of each page before the engine sees it (step
# 5B; capture/imaging.py: "exif", "deskew", "denoise", "contrast"). Empty by default: a model
# trained on unprocessed photos may do worse with them, so nothing is on until the model's
# specification and the 9B measurements say so. The stored original is never changed; the copy
# lives in memory for one attempt. NOT recorded in the extraction row (that needs a column).
PREPROCESS = ()

# doc_type -> {field: entry}. An entry is a kind ("text", "number" or "date") or a dict
# {"kind": ..., "required": bool, "rules": [names from RULES]}; a repeated group is
# [{sub_field: entry}]. Fields an engine returns that are not listed here are dropped. A value
# that breaks a rule is never accepted, whatever its confidence. "required" only makes
# missing_required() report the field: M3's confirm step enforces it, M2 does not.
# PENDING APPROVAL: the FRD says "typed schema" but lists no fields. Until the list in
# docs/DECISIONS.md is approved this is empty, so every document goes to review with its
# raw text only.
SCHEMAS = {}

# Technical checks only. Clinical rules (ranges, units, thresholds) are NOT defined here: they wait
# for the approved field list and the clinical reviewer.
RULES = {
    "not_future": lambda value: date.fromisoformat(value) <= date.today(),
    "positive": lambda value: Decimal(value) > 0,
}

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


def _entry(entry):
    """(kind, required, rules) of a schema entry given as a kind or as a dict."""
    if isinstance(entry, str):
        return entry, False, ()
    return entry["kind"], bool(entry.get("required")), tuple(entry.get("rules", ()))


def check_spec(spec):
    """ValueError for an unknown kind or rule anywhere in a doc_type's spec."""
    for name, entry in spec.items():
        for sub in (entry[0].values() if isinstance(entry, list) else [entry]):
            kind, _, rules = _entry(sub)
            if kind not in ("text", "number", "date"):
                raise ValueError(f"{name}: unknown kind {kind}")
            for rule in rules:
                if rule not in RULES:
                    raise ValueError(f"{name}: unknown rule {rule}")


def missing_required(spec, fields):
    """Paths of required fields that have no accepted value (left for manual entry)."""
    return [path for path, entry, holder, key in _slots(spec, fields)
            if _entry(entry)[1] and holder[key]["value"] is None]


def _field(entry, got, threshold, source="ocr"):
    """One schema field. Below the threshold, missing or invalid: left empty for manual entry
    (FRD section 8). `raw` keeps what was read, for the reviewer to see."""
    kind, _, rules = _entry(entry)
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
            value = parse(kind, got["value"])
        except ValueError:
            out["error"] = f"invalid_{kind}"
            return out
        broken = next((rule for rule in rules if not RULES[rule](value)), None)
        if broken:
            out["error"] = f"invalid_{broken}"
        else:
            out.update(value=value, manual_entry=False)
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


def _store(conn, document_id, version, engine, fields, raw_text, config=None):
    """config is the checked adapter (ocr.check_available) for an OCR result; None for manual
    entry and the legacy test path, whose identity columns stay NULL."""
    identity = config["identity"] if config else {}
    conn.execute(
        "INSERT INTO extractions (id, document_id, version, engine, fields, raw_text, engine_id, model_version, "
        "model_checksum, adapter_interface_version, adapter_version) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        [uuid4(), document_id, version, engine, Jsonb(fields), raw_text, identity.get("engine_id"),
         identity.get("model_version"), config and config["model_checksum"], config and config["interface_version"],
         identity.get("adapter_version")],
    )


def _next_version(conn, document_id):
    return conn.execute(
        "SELECT coalesce(max(version), 0) + 1 FROM extractions WHERE document_id = %s", [document_id]).fetchone()[0]


class AttemptFailed(Exception):
    """This attempt is over; args[0] is a short reason with no document text."""


class LeaseLost(Exception):
    """The claim is no longer ours. Stop, and change nothing."""


class WorkerConnectionLost(Exception):
    """The worker's database connection is gone. Nothing more was written for the attempt: it
    stays counted and claimed until its lease ends, then the document is due again. The caller
    must open a new connection; __cause__ is the original error."""


_DUE = "(status = 'uploaded' OR (status = 'extracting' AND next_extraction_at <= clock_timestamp()))"
_MINE = "id = %s AND extraction_claim = %s AND status = 'extracting'"
_DEFAULTS = ("threshold", "ai_threshold", "max_attempts", "backoff", "lease", "heartbeat", "hard_timeout",
             "availability_timeout", "preprocess")
_TEST_MODE = f"APP_ENV=test and {runtime_mode.CONFIRM}=1"


def _duration(o, name, *, zero_ok=False):
    """o[name] must be a timedelta above zero (or from zero, with zero_ok). The message names the
    option and never the value."""
    value = o[name]
    if not isinstance(value, timedelta):
        raise TypeError(f"extraction option {name} must be a datetime.timedelta")
    if value < timedelta(0) or (value == timedelta(0) and not zero_ok):
        raise ValueError(f"extraction option {name} must be {'zero or ' if zero_ok else ''}positive")


def _fraction(o, name):
    """o[name] must be a number from 0 to 1 inclusive; not a bool, NaN or infinite."""
    value = o[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"extraction option {name} must be a number")
    if not 0 <= value <= 1:  # false for NaN and infinity too
        raise ValueError(f"extraction option {name} must be between 0 and 1")


def _attempts(value):
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("extraction option max_attempts must be an integer")
    if value < 1:
        raise ValueError("extraction option max_attempts must be at least 1")


PREPROCESS_OPERATIONS = ("exif", "deskew", "denoise", "contrast")


def _preprocess(value):
    if isinstance(value, (str, bytes)) or not isinstance(value, (tuple, list)):
        raise TypeError("extraction option preprocess must be a tuple of operation names")
    if len(set(value)) != len(value) or any(op not in PREPROCESS_OPERATIONS for op in value):
        raise ValueError(f"extraction option preprocess must hold distinct names from {PREPROCESS_OPERATIONS}")


def _working_copy(pages, operations):
    """Processing copies of the page bytes, or the same objects when no operation is switched on.
    Raises imaging.ImageRejected for a page that cannot be decoded; the originals are only read."""
    if not operations:
        return pages
    return [imaging.process(page, **{op: True for op in operations})[0] for page in pages]


def _settings(given):
    """Per-call settings over the module constants, read now so they can be reconfigured."""
    runtime_mode.check_test_mode_config()  # fail closed before anything else
    unknown = set(given) - set(_DEFAULTS)
    if unknown:
        raise TypeError(f"unknown extraction options: {sorted(unknown)}")
    o = {"threshold": CONFIDENCE_THRESHOLD, "ai_threshold": CLOUD_AI_THRESHOLD, "max_attempts": MAX_ATTEMPTS,
         "backoff": BACKOFF, "lease": LEASE, "heartbeat": HEARTBEAT, "hard_timeout": HARD_TIMEOUT,
         "availability_timeout": ocr.AVAILABILITY_TIMEOUT, "preprocess": PREPROCESS, **given}
    if o["availability_timeout"] is None:
        o["availability_timeout"] = ocr.AVAILABILITY_TIMEOUT  # None means "the default"
    if o["hard_timeout"] is None:
        if not runtime_mode.is_test_mode():
            raise RuntimeError(f"in-process OCR (no heartbeat, no hard timeout) is only allowed with {_TEST_MODE}")
    else:
        _duration(o, "hard_timeout")
    for name in ("lease", "heartbeat", "availability_timeout"):
        _duration(o, name)
    _duration(o, "backoff", zero_ok=True)
    _fraction(o, "threshold")
    if o["ai_threshold"] is not None:  # None: nothing is ever sent to the cloud AI
        _fraction(o, "ai_threshold")
    _attempts(o["max_attempts"])
    _preprocess(o["preprocess"])
    if o["hard_timeout"] is not None and o["heartbeat"] >= o["lease"]:
        raise ValueError("heartbeat must be shorter than the lease, or every lease runs out before it is renewed")
    return o


def _engine(engine, o):
    """(engine for the attempt, adapter config or None), or (None, None) if no adapter is
    available. Runs before anything is claimed. A probe failure writes nothing: no claim, no
    attempt, no row; the document stays `uploaded`. It is logged with codes only."""
    if engine is not None:
        if not runtime_mode.is_test_mode():
            raise RuntimeError(f"legacy engine callables are deprecated and only allowed with {_TEST_MODE}")
        return engine, None
    started = time.monotonic()
    try:
        config = ocr.check_available(o["availability_timeout"])
    except ocr.AdapterError as e:
        log.warning("ocr adapter unavailable: code=%s stage=probe ref=%s duration_ms=%d", e.code,
                    os.environ.get("OCR_ADAPTER") or "-", (time.monotonic() - started) * 1000)
        return None, None
    return functools.partial(ocr.run_attempt, config), config


def _code(e):
    return e.code if isinstance(e, ocr.AdapterError) else type(e).__name__


def claim(conn, document_id=None, *, lease=None, max_attempts=None):
    """Take one due document for one attempt, or return None if there is none to take.

    Counts the attempt and writes a new claim token and lease in one short transaction. A
    document another worker has locked is skipped, never waited for. A document whose
    attempts are used up (its last attempt never reported back) is closed as
    extraction_failed here. Returns {id, patient_id, doc_type, attempt, version, token}.
    """
    if not conn.autocommit:
        raise ValueError("extraction needs an autocommit connection, so each step commits on its own")
    # only an omitted value or None selects the default; an explicit zero is refused, not replaced
    lease = LEASE if lease is None else lease
    max_attempts = MAX_ATTEMPTS if max_attempts is None else max_attempts
    _duration({"lease": lease}, "lease")
    _attempts(max_attempts)
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
    """Runs in the child process: the engine, and nothing that touches the database. Its own
    process group on Linux; a watchdog ends the group if the worker dies or the limit passes."""
    ocr.enter_child(limit)
    try:
        out.send(("ok", engine(pages, doc_type)))
    except BaseException as e:
        out.send(("failed", _code(e)))  # a code or type name, never the message


def _release(child, out, results):
    """Stop the child and close both pipe ends; every step runs even if one fails, an interrupt
    included. Returns the most serious failure (an interrupt such as KeyboardInterrupt outranks an
    ordinary error, otherwise the first), or None. The caller decides what to raise."""
    worst = None
    for step in (lambda: ocr.stop_child(child), out.close, results.close):
        try:
            step()
        except BaseException as e:  # deferred, never dropped: re-raised by the caller
            if worst is None or (isinstance(worst, Exception) and not isinstance(e, Exception)):
                worst = e
    return worst


def _run_engine(engine, pages, doc_type, hard_timeout, heartbeat, renew):
    """The engine's result. Raises AttemptFailed (engine error, child died, hard timeout) or
    LeaseLost. With a hard timeout the engine runs in a child process whose process group is
    always killed before this returns."""
    if hard_timeout is None:
        try:
            return engine(pages, doc_type)
        except Exception as e:
            raise AttemptFailed(_code(e))
    spawn = multiprocessing.get_context("spawn")
    results, out = spawn.Pipe(duplex=False)
    child = spawn.Process(target=_child, args=(engine, pages, doc_type, out, hard_timeout.total_seconds() + 5),
                          daemon=True)
    try:
        child.start()
        out.close()  # so that EOF arrives once the child exits
        deadline = time.monotonic() + hard_timeout.total_seconds()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AttemptFailed("HardTimeout")
            try:
                ready = results.poll(min(heartbeat.total_seconds(), remaining))
                if ready:
                    outcome, value = results.recv()
            except (EOFError, OSError):  # includes BrokenPipeError from poll() on Windows
                raise AttemptFailed("WorkerDied")
            if ready:
                if outcome != "ok":
                    raise AttemptFailed(value)
                break
            if not renew():
                raise LeaseLost()
    except BaseException:
        failure = _release(child, out, results)  # a primary exception is in flight: it wins
        if failure is not None:
            if not isinstance(failure, Exception):
                raise failure  # an interrupt during cleanup is never suppressed; the primary stays as its context
            log.warning("ocr child cleanup failed: code=%s stage=cleanup", type(failure).__name__)
        raise
    failure = _release(child, out, results)
    if failure is not None:
        raise failure  # an otherwise successful result is not returned over a failed cleanup
    return value


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


def _fail_unless_disconnected(conn, job, reason, cause, o):
    # codes and ids only: never a message, document text, OCR output or artifact content
    log.warning("ocr attempt failed: code=%s stage=attempt document=%s attempt=%d",
                str(reason)[:100], job["id"], job["attempt"])
    # a lost connection cannot record the failure; do not try another write on it
    if conn.closed:
        raise WorkerConnectionLost() from cause
    _fail(conn, job, reason, o["max_attempts"], o["backoff"])


def _attempt(conn, job, engine, ai, o, config=None):
    """Work and store for one claimed attempt. Never raises for a failed attempt, except
    WorkerConnectionLost when the database connection is lost: then nothing more is written and
    the lease expiry makes the document due again. config is the checked adapter, or None for
    the deprecated test-only engine callable."""
    try:
        images = documents.get(conn, job["id"])["images"]
        pages = [documents.read_image(conn, job["id"], i["n"])[1] for i in images]
        # reading ran without a heartbeat: confirm, and extend, the lease before the engine starts
        if not _renew(conn, job, o["lease"]):
            raise LeaseLost()
        used = _working_copy(pages, o["preprocess"])  # transient; `pages` stays the stored originals
        media = ["image/png"] * len(images) if o["preprocess"] else [image["content_type"] for image in images]
        work = used if config is None else [
            {"page_number": n, "image": data, "media_type": kind}
            for n, (kind, data) in enumerate(zip(media, used), 1)]
        got = _run_engine(engine, work, job["doc_type"], o["hard_timeout"], o["heartbeat"],
                          lambda: _renew(conn, job, o["lease"]))
        spec = SCHEMAS.get(job["doc_type"], {})
        if config is None:
            fields, raw_text, name = structure(spec, got.get("fields"), o["threshold"]), \
                str(got.get("raw_text") or ""), str(got.get("engine") or "unknown")
        else:
            if config["interface_version"] == 0 and not runtime_mode.is_test_mode():
                raise ocr.AdapterError("engine_unavailable")  # never store a version 0 result outside test mode
            # validated again here: the child's own check ran next to adapter code that could change it
            got = ocr.validate_result(got, len(work), config["identity"])
            # fields come from parsers (step 6B), not from OCR; items and positions are never stored
            fields, raw_text, name = structure(spec, {}, o["threshold"]), ocr.raw_text_v0(got), \
                config["identity"]["engine_id"]
        _cloud_ai(conn, job, pages, spec, fields, ai, o["threshold"], o["ai_threshold"])
        with conn.transaction():
            # the fence: only the current claim, inside its lease, may store a result
            mine = conn.execute(
                f"SELECT 1 FROM documents WHERE {_MINE} AND next_extraction_at > clock_timestamp() FOR UPDATE",
                [job["id"], job["token"]]).fetchone()
            if mine is None:
                raise LeaseLost()
            _store(conn, job["id"], job["version"], name, fields, raw_text, config)
            conn.execute(
                "UPDATE documents SET status = 'needs_review', extraction_claim = NULL, extraction_error = NULL, "
                "next_extraction_at = NULL, updated_at = clock_timestamp() WHERE id = %s", [job["id"]])
    except LeaseLost:
        # another attempt owns the document now, or will: leave everything as it is
        log.warning("ocr attempt lease lost: code=LeaseLost stage=attempt document=%s attempt=%d",
                    job["id"], job["attempt"])
    except AttemptFailed as e:
        _fail_unless_disconnected(conn, job, e.args[0], e, o)
    except Exception as e:
        _fail_unless_disconnected(conn, job, _code(e), e, o)


def extract(conn, document_id, version, engine=None, ai=None, **options):
    """Run one extraction job. Keyed by (document_id, version): a repeat, a job for a document
    that is not due, one another worker holds, or no available OCR adapter, does nothing and
    returns False. engine=None uses the configured adapter; a callable is the deprecated
    test-only path. Options: threshold, ai_threshold, max_attempts, backoff, lease, heartbeat,
    hard_timeout, availability_timeout (None: the default). Invalid values raise TypeError or
    ValueError before anything is claimed or probed.
    Raises WorkerConnectionLost if the connection is lost during the attempt: open a new one.
    Raises RuntimeError, before anything is claimed, if APP_ENV=test lacks its confirmation."""
    o = _settings(options)
    engine, config = _engine(engine, o)
    if engine is None or version != _next_version(conn, document_id):
        return False
    job = claim(conn, document_id, lease=o["lease"], max_attempts=o["max_attempts"])
    if job is None or job["version"] != version:
        return False
    _attempt(conn, job, engine, ai, o, config)
    return True


def run_due(conn, engine=None, ai=None, *, limit=100, **options):
    """Claim and run due extraction jobs until none is left; returns how many attempts ran.
    Several workers can run this at once: each takes different documents. With no available OCR
    adapter it claims nothing and returns 0. engine=None uses the configured adapter; a callable
    is the deprecated test-only path. Options as for extract(); invalid values raise TypeError or
    ValueError before anything is claimed or probed.
    Raises WorkerConnectionLost if the connection is lost during an attempt: open a new one and
    call again. The interrupted attempt stays counted and is recovered when its lease ends.
    Raises RuntimeError, before anything is claimed, if APP_ENV=test lacks its confirmation.
    Step 8 MUST call runtime_mode.check_test_mode_config() at independent worker process startup,
    before entering its worker loop (owner decision B1, 2026-11-12)."""
    o = _settings(options)
    engine, config = _engine(engine, o)
    if engine is None:
        return 0
    done = 0
    while done < limit:
        job = claim(conn, lease=o["lease"], max_attempts=o["max_attempts"])
        if job is None:
            break
        _attempt(conn, job, engine, ai, o, config)
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
