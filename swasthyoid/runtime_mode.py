"""Test mode (DECISIONS.md, 4A plan R10, owner Option C).

Test-only behaviour (OCR interface version 0, legacy engine callables, the test network guard)
needs BOTH APP_ENV=test and SWASTHYOID_TEST_MODE_CONFIRM=1, compared as exact strings. Either
alone is not test mode. This guards against accidental misconfiguration; it is not a security
boundary.

Not named test_*: pytest would collect a test_* function imported into a test module.
"""
import os

CONFIRM = "SWASTHYOID_TEST_MODE_CONFIRM"


def is_test_mode():
    return os.environ.get("APP_ENV") == "test" and os.environ.get(CONFIRM) == "1"


def check_test_mode_config():
    """Fail closed: APP_ENV=test without the exact confirmation must not start anything."""
    if os.environ.get("APP_ENV") == "test" and os.environ.get(CONFIRM) != "1":
        raise RuntimeError(f"APP_ENV=test requires {CONFIRM}=1")


def confirm_without_test_env():
    """The confirmation is set but APP_ENV is not test: test mode stays off (worth a warning)."""
    return os.environ.get(CONFIRM) is not None and os.environ.get("APP_ENV") != "test"
