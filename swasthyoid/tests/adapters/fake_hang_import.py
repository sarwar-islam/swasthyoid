"""Test-only: an adapter module whose import never finishes (probe timeout test)."""
import time

time.sleep(3600)


def adapter():  # never reached
    raise AssertionError
