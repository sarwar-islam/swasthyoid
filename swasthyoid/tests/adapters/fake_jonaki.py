"""Test-only factory: the real Jonaki adapter class wired to the fake runner, so the worker can run
it by reference ("swasthyoid.tests.adapters.fake_jonaki:jonaki") without PaddleOCR or weights."""
import os
import sys
from pathlib import Path

from swasthyoid.capture.adapters.jonaki import Jonaki

RUNNER = Path(__file__).with_name("fake_jonaki_runner.py")


def jonaki():
    return Jonaki([sys.executable, str(RUNNER)], revision="fake-rev-1", detector_revision="fake-det-1", page_seconds=20,
                  extra_env={"FAKE_JONAKI_MODE": os.environ.get("FAKE_JONAKI_MODE", "ok")})
