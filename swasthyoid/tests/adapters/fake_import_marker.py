"""Test-only: records "imported" in FAKE_ADAPTER_LOG when this module is imported, to prove the
probe child loads no adapter code outside test mode."""
from swasthyoid.tests.adapters.fake_adapters import Good, note

note("imported")


def adapter():
    return Good()
