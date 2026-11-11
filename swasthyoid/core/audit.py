"""C2 — audit hash chain, pure logic (FRD section 4.2). Storage comes in slice 2."""
import hashlib
import json

GENESIS = "0" * 64


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
