"""One-time codes by phone (FRD M1). Only a keyed hash of each code is stored.

A code is tied to a kind and a reference (login, one consent request, one caregiver
request) and works for nothing else: the code a patient reads out to a doctor or a
caregiver cannot log anyone in. Codes are never logged, audited or queued.

The limits below are configurable security defaults, not FRD values; change them here.
"""
import hmac
import secrets
from datetime import timedelta
from uuid import uuid4

from swasthyoid import pii
from swasthyoid.core import audit

CODE_TTL = timedelta(minutes=5)
MAX_ATTEMPTS = 5                      # wrong guesses before a code is dead
MAX_REQUESTS = 5                      # codes per phone and kind ...
REQUEST_WINDOW = timedelta(minutes=15)  # ... within this window


class TooManyRequests(Exception):
    pass


def _new_code():
    return f"{secrets.randbelow(10**6):06d}"


def _code_hash(phone_hash, kind, ref, code):
    return pii.secret_hash(f"otp:{phone_hash}:{kind}:{ref}:{code}")


def create_code(conn, phone, kind="login", ref="", max_per_ref=None):
    """Store a new code (hashed) and return (normalised phone, code) for the caller to deliver.
    Older codes for the same thing stop working. max_per_ref caps codes per reference."""
    phone = pii.normalize_phone(phone)
    h = pii.phone_hash(phone)
    code = _new_code()
    with conn.transaction():
        recent = conn.execute(
            "SELECT count(*) FROM otp_codes WHERE phone_hash = %s AND kind = %s AND created_at > clock_timestamp() - %s",
            [h, kind, REQUEST_WINDOW],
        ).fetchone()[0]
        if recent >= MAX_REQUESTS:
            raise TooManyRequests("too many codes requested, try again later")
        if max_per_ref is not None:
            for_ref = conn.execute(
                "SELECT count(*) FROM otp_codes WHERE phone_hash = %s AND kind = %s AND ref = %s", [h, kind, ref],
            ).fetchone()[0]
            if for_ref >= max_per_ref:
                raise TooManyRequests("too many codes for this request")
        conn.execute(
            "UPDATE otp_codes SET used_at = clock_timestamp() "
            "WHERE phone_hash = %s AND kind = %s AND ref = %s AND used_at IS NULL",
            [h, kind, ref],
        )
        conn.execute(
            "INSERT INTO otp_codes (id, phone_hash, kind, ref, code_hash, expires_at) "
            "VALUES (%s, %s, %s, %s, %s, clock_timestamp() + %s)",
            [uuid4(), h, kind, ref, _code_hash(h, kind, ref, code), CODE_TTL],
        )
    return phone, code


def request_code(conn, phone, send, kind="login", ref=""):
    """Create a code and hand it to send(phone, code)."""
    send(*create_code(conn, phone, kind, ref))


def verify_code(conn, phone, code, kind="login", ref="", **who):
    """True once for the right, unexpired code. Every failure is audited, without the phone or
    the code. `who` adds audit context such as actor_id and patient_id."""
    try:
        h = pii.phone_hash(phone)
    except ValueError:
        h = None
    with conn.transaction():
        row = h and conn.execute(
            """SELECT id, code_hash, attempts FROM otp_codes
               WHERE phone_hash = %s AND kind = %s AND ref = %s AND used_at IS NULL
                 AND expires_at > clock_timestamp()
               ORDER BY created_at DESC LIMIT 1 FOR UPDATE""",
            [h, kind, ref],
        ).fetchone()
        if not row:
            reason = "no_valid_code"
        elif row[2] >= MAX_ATTEMPTS:
            reason = "too_many_attempts"
        elif not hmac.compare_digest(row[1], _code_hash(h, kind, ref, str(code))):
            reason = "wrong_code"
            conn.execute("UPDATE otp_codes SET attempts = attempts + 1 WHERE id = %s", [row[0]])
        else:
            reason = None
            conn.execute("UPDATE otp_codes SET used_at = clock_timestamp() WHERE id = %s", [row[0]])
        if reason:
            audit.append(conn, action="auth.otp_failed", result="deny", reason=reason, **who)
    return reason is None
