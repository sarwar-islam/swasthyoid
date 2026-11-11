"""Health ID: SID- + 10 digits, the last one a check digit (FRD section 2).

Random, never derived from a phone number or national ID. Uniqueness is enforced
by the store (slice 6), not here.
DECISION-PENDING: the FRD does not name the check-digit algorithm; Luhn is assumed.
"""
import re
import secrets

_FORMAT = re.compile(r"SID-\d{10}")


def _luhn_check_digit(payload):
    total = 0
    for i, ch in enumerate(reversed(payload)):
        d = int(ch)
        if i % 2 == 0:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return str(-total % 10)


def generate():
    payload = "".join(secrets.choice("0123456789") for _ in range(9))
    return f"SID-{payload}{_luhn_check_digit(payload)}"


def is_valid(health_id):
    if not isinstance(health_id, str) or not _FORMAT.fullmatch(health_id):
        return False
    digits = health_id[4:]
    return _luhn_check_digit(digits[:-1]) == digits[-1]
