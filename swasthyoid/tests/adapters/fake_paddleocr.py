"""Test-only factory: the real PaddleOCR adapter class wired to the fake runner, so the worker can run it by reference
("swasthyoid.tests.adapters.fake_paddleocr:paddleocr_en") without PaddleOCR or weights."""
import os
import sys
from pathlib import Path

from swasthyoid.capture.adapters.paddleocr_adapter import PaddleOcr

RUNNER = Path(__file__).with_name("fake_paddleocr_runner.py")


def paddleocr_en():
    mode = os.environ.get("FAKE_PADDLEOCR_MODE", "ok")
    return PaddleOcr([sys.executable, str(RUNNER), "--recognizer-name", "en_PP-OCRv5_mobile_rec",
                      "--detector-name", "PP-OCRv5_mobile_det"],
                     revision="fake-rev-1", detector_revision="fake-det-1", page_seconds=20,
                     extra_env={"FAKE_PADDLEOCR_MODE": mode})
