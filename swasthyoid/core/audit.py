"""C2 — audit: hash chain and the append-only PostgreSQL store (FRD section 4.2)."""
import hashlib
import json
from datetime import timezone
from uuid import UUID, uuid4

GENESIS = "0" * 64

# Caller-supplied columns of audit_logs. id, at and the hashes are set by append().
FIELDS = (
    "actor_id", "actor_role", "device_id", "ip", "user_agent", "action", "patient_id",
    "resource_type", "resource_id", "consent_id", "purpose", "result", "reason",
)
_UUID_FIELDS = ("actor_id", "patient_id", "resource_id", "consent_id")
_COLUMNS = ("id", "at", *FIELDS, "prev_hash", "entry_hash")


def entry_hash(prev_hash, fields):
    """Hash of one entry: its fields (without prev_hash/entry_hash) chained to prev_hash."""
    body = json.dumps({"prev": prev_hash, "entry": fields}, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def chain(prev_hash, fields):
    """Return the entry to append: fields plus prev_hash and entry_hash."""
    return {**fields, "prev_hash": prev_hash, "entry_hash": entry_hash(prev_hash, fields)}


def verify_chain(entries, head=GENESIS):
    """Index of the first broken entry, or None if the whole chain verifies."""
    prev = head
    for i, e in enumerate(entries):
        try:
            fields = {k: v for k, v in e.items() if k not in ("prev_hash", "entry_hash")}
            ok = e["prev_hash"] == prev and e["entry_hash"] == entry_hash(prev, fields)
        except Exception:
            ok = False  # a malformed entry is a broken chain
        if not ok:
            return i
        prev = e["entry_hash"]
    return None


def _hashable(row):
    """Row fields in the exact form that is hashed, identical before insert and after read."""
    fields = {k: row[k] for k in ("id", "at", *FIELDS)}
    fields["at"] = fields["at"].astimezone(timezone.utc).isoformat()
    return fields


def append(conn, **fields):
    """Append one audit entry and return it. Raises on any failure: the caller must
    let that fail the request (fail closed) and must not catch it to carry on.

    Runs inside the caller's transaction if one is open, so a read and its audit
    entry can commit or roll back together.
    """
    unknown = set(fields) - set(FIELDS)
    if unknown:
        raise ValueError(f"unknown audit fields: {sorted(unknown)}")
    row = {f: fields.get(f) for f in FIELDS}
    for f in _UUID_FIELDS:
        if row[f] is not None:
            row[f] = UUID(str(row[f]))  # normalise so the stored value hashes the same
    with conn.transaction():
        # One writer at a time, so every entry chains to the true head.
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('audit_logs'))")
        head = conn.execute("SELECT entry_hash FROM audit_logs ORDER BY seq DESC LIMIT 1").fetchone()
        row["id"] = uuid4()
        row["at"] = conn.execute("SELECT clock_timestamp()").fetchone()[0]  # server time only
        entry = chain(head[0] if head else GENESIS, _hashable(row))
        row.update(prev_hash=entry["prev_hash"], entry_hash=entry["entry_hash"])
        conn.execute(
            f"INSERT INTO audit_logs ({', '.join(_COLUMNS)}) VALUES ({', '.join(['%s'] * len(_COLUMNS))})",
            [row[c] for c in _COLUMNS],
        )
    return row


def verify_stored(conn, head=GENESIS):
    """seq of the first broken stored entry, or None if the stored chain verifies."""
    cur = conn.execute(f"SELECT seq, {', '.join(_COLUMNS)} FROM audit_logs ORDER BY seq")
    rows = [dict(zip(("seq", *_COLUMNS), r)) for r in cur]
    entries = [{**_hashable(r), "prev_hash": r["prev_hash"], "entry_hash": r["entry_hash"]} for r in rows]
    bad = verify_chain(entries, head)
    return None if bad is None else rows[bad]["seq"]
