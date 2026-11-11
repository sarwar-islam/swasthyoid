"""Phone normalisation, lookup hashes and field-level encryption (FRD 6.6).

Keys come from the environment and there is no default: a missing key raises.
  PII_KEY   Fernet key, encrypts phone and name
  HMAC_KEY  keys the phone lookup hash and the hashes of one-time codes and refresh tokens
"""
import hashlib
import hmac
import os
import re

from cryptography.fernet import Fernet

_BD_MOBILE = re.compile(r"\+8801[3-9]\d{8}")


def normalize_phone(phone):
    """Bangladesh mobile number in +8801XXXXXXXXX form, or ValueError."""
    p = re.sub(r"[\s-]", "", str(phone))
    if p.startswith("01"):
        p = "+88" + p
    elif p.startswith("8801"):
        p = "+" + p
    if not _BD_MOBILE.fullmatch(p):
        raise ValueError("not a valid Bangladesh mobile number")
    return p


def secret_hash(value):
    return hmac.new(os.environ["HMAC_KEY"].encode(), value.encode(), hashlib.sha256).hexdigest()


def phone_hash(phone):
    return secret_hash("phone:" + normalize_phone(phone))


def encrypt(text):
    return Fernet(os.environ["PII_KEY"]).encrypt(text.encode()).decode()


def decrypt(token):
    return Fernet(os.environ["PII_KEY"]).decrypt(token.encode()).decode()
