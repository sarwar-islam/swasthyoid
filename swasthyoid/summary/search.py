"""M5 search (P3; FRD M5, 8.4; owner decisions D1, D9, D10). Results are events, never generated answers.

Keyword search always: every word of the query must appear in one of the event's values as written (case, spacing and
Bangla digits aside). The patient and the permitted statuses and event types are hard filters inside the SQL, so another
patient's row is never read. Only current events: verified ones and patient-reported readings (D10).
Semantic search only when an embedding adapter is configured (D9: interface and test adapter only, no vector store): the
same filtered rows are embedded and ranked, so the filters hold for it too. Any adapter problem leaves keyword results.
"""
import logging
import math

from psycopg.rows import dict_row

from swasthyoid.capture.drugmatch import normalize
from swasthyoid.summary import adapters, build

log = logging.getLogger(__name__)
LIMIT = 50           # engineering limits, not clinical values
SEMANTIC_LIMIT = 10
MAX_QUERY = 200
TIMELINE_TYPES = ["visit", "diagnosis", "medication", "lab_result", "allergy", "follow_up", "prescription", "vital_reading"]
_BN, _ASCII = "০১২৩৪৫৬৭৮৯", "0123456789"

# Values of one event as one text, Bangla digits as ASCII, lower case. Keys are never searched.
_TEXT = "lower(translate(coalesce((SELECT string_agg(v.value, ' ') FROM jsonb_each_text(e.payload) v), ''), %s, %s))"
_FILTER = """e.patient_id = %s AND e.event_type = ANY(%s)
             AND (e.verification_status = 'document_verified'
                  OR (e.verification_status = 'patient_reported' AND e.event_type = 'vital_reading'))
             AND NOT EXISTS (SELECT 1 FROM events n WHERE n.supersedes = e.id)"""


class BadQuery(Exception):
    """args[0]: query_required or query_too_long."""


def terms(q):
    if not isinstance(q, str) or not normalize(q):
        raise BadQuery("query_required")
    if len(q) > MAX_QUERY:
        raise BadQuery("query_too_long")
    return normalize(q).split()


def _like(term):
    return "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _rows(conn, patient_id, where="", params=()):
    return conn.cursor(row_factory=dict_row).execute(
        f"SELECT e.* FROM events e WHERE {_FILTER} {where} ORDER BY e.event_date DESC, e.recorded_at DESC, e.id LIMIT %s",
        [patient_id, TIMELINE_TYPES, *params, LIMIT]).fetchall()


def _snippet(e):
    """The values as written, in the summary's field order (jsonb keeps no key order), then any other field."""
    known = build.FIELDS.get(e["event_type"], ())
    keys = [k for k in known if k in e["payload"]] + sorted(k for k in e["payload"] if k not in known)
    values = (e["payload"][k] for k in keys)
    return " · ".join(str(v).strip() for v in values if isinstance(v, (str, int, float)) and str(v).strip())


def hit(e, match, with_documents):
    return {"event_id": str(e["id"]), "event_type": e["event_type"], "date": e["event_date"].isoformat(),
            # a source document link only under a consent that covers `documents` (owner correction 3)
            "source_document_id": str(e["source_document_id"]) if with_documents and e["source_document_id"] else None,
            "snippet": _snippet(e), "match": match}


def _semantic(conn, patient_id, q, exclude):
    try:
        adapter = adapters.resolve("embedding")
    except adapters.AdapterRefused:
        return []
    if adapter is None:
        return []
    candidates = [e for e in _rows(conn, patient_id) if str(e["id"]) not in exclude]
    if not candidates:
        return []
    try:
        texts = [q] + [_snippet(e) for e in candidates]
        vectors = adapters.check_embeddings(adapter.embed(texts), len(texts))
    except Exception as e:
        log.warning("search embedding adapter failed: %s", type(e).__name__)
        return []
    query, rest = vectors[0], vectors[1:]

    def cosine(v):
        den = math.sqrt(sum(x * x for x in query)) * math.sqrt(sum(x * x for x in v))
        return sum(a * b for a, b in zip(query, v)) / den if den else 0.0

    ranked = sorted(zip(candidates, rest), key=lambda p: (-cosine(p[1]), str(p[0]["id"])))
    return [e for e, _ in ranked[:SEMANTIC_LIMIT]]


def search(conn, patient_id, q, *, with_documents):
    words = terms(q)
    where = " ".join(f"AND {_TEXT} LIKE %s" for _ in words)
    params = [p for w in words for p in (_BN, _ASCII, _like(w.translate(str.maketrans(_BN, _ASCII))))]
    keyword = _rows(conn, patient_id, where, params)
    out = [hit(e, "keyword", with_documents) for e in keyword]
    out += [hit(e, "semantic", with_documents) for e in _semantic(conn, patient_id, q, {h["event_id"] for h in out})]
    return out
