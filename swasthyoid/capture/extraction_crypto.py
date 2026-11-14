"""Encryption of extracted text at rest (M2 step 2; owner decision D2 option (b), 2026-11-14).

- `extractions.fields` is stored as ONE sealed object {"v": 1, "enc": <Fernet token>}: field-level
  encryption of everything the extraction holds (values, raw readings, confidences). It is still a JSON
  object, so the table needs no change for it.
- `raw_text` is NOT kept in the append-only `extractions` row (that column stays ''). Its Fernet token
  lives in `extraction_raw_texts`, a table whose rows can be deleted, and only its SHA-256 stays in the
  append-only row (`raw_text_sha256`). Verification or rejection of the document deletes the row (the database
  trigger `extraction_raw_texts_retention` on `documents`); the hash remains as proof of what was read.
- The key is the environment variable EXTRACTION_KEY, a Fernet key held outside the database, like
  DOCUMENT_KEY and PII_KEY. No default. A wrong or missing key fails closed (an error, never garbage).

Rows written before this change keep their plain `fields` and `raw_text`: the table is append-only, so
they cannot be rewritten. They are read as they are. They hold synthetic data only.
"""
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken

VERSION = 1


class KeyError_(Exception):
    """EXTRACTION_KEY is missing or unusable; args[0] is a fixed reason word. Never carries the key."""


class Undecryptable(Exception):
    """Stored text did not decrypt with the current key (wrong key or damaged data). No details."""


def check_key():
    """The Fernet for EXTRACTION_KEY, or KeyError_("missing" | "empty" | "invalid")."""
    raw = os.environ.get("EXTRACTION_KEY")
    if raw is None:
        raise KeyError_("missing")
    if not raw.strip():
        raise KeyError_("empty")
    try:
        return Fernet(raw)
    except (ValueError, TypeError):
        raise KeyError_("invalid") from None


def sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def seal_fields(fields):
    import json
    token = check_key().encrypt(json.dumps(fields, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    return {"v": VERSION, "enc": token.decode("ascii")}


def is_sealed(stored):
    return isinstance(stored, dict) and set(stored) == {"v", "enc"} and isinstance(stored["enc"], str)


def open_fields(stored):
    """The fields of a stored `fields` value: decrypted if sealed, as they are if written before D2."""
    import json
    if not is_sealed(stored):
        return stored
    try:
        return json.loads(check_key().decrypt(stored["enc"].encode("ascii")).decode("utf-8"))
    except (InvalidToken, ValueError):
        raise Undecryptable() from None


def seal_text(text):
    return check_key().encrypt(text.encode("utf-8")).decode("ascii")


def open_text(token):
    try:
        return check_key().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        raise Undecryptable() from None
