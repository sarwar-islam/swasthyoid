"""Encrypted, write-once storage for original document images (FRD 6.6).

shortcut: files on local disk under DOCUMENT_STORE, upgrade to encrypted object storage
when hosting is decided (DECISIONS.md Q4). Keys keep the FRD layout either way.
DOCUMENT_STORE and DOCUMENT_KEY (a Fernet key) come from the environment; no defaults.
"""
import os
from pathlib import Path

from cryptography.fernet import Fernet


def _path(key):
    root = Path(os.environ["DOCUMENT_STORE"]).resolve()
    path = (root / key).resolve()
    if root not in path.parents:
        raise ValueError("storage key escapes the store")
    return path


def put(key, data):
    """Store once. Raises FileExistsError if the key is taken: originals are never overwritten."""
    path = _path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "xb") as f:
        f.write(Fernet(os.environ["DOCUMENT_KEY"]).encrypt(data))


def get(key):
    return Fernet(os.environ["DOCUMENT_KEY"]).decrypt(_path(key).read_bytes())


def discard(key):
    """Only for undoing an upload whose database transaction failed."""
    _path(key).unlink(missing_ok=True)
