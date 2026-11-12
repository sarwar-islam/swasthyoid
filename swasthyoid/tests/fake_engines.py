"""Fake OCR engines that can be sent to a child process (module-level, light imports)."""
import os
import time

RESULT = {"engine": "fake-ocr", "raw_text": "synthetic raw text", "fields": {}}


def good(pages, doc_type):
    return RESULT


def slow(pages, doc_type):
    time.sleep(float(os.environ["FAKE_ENGINE_SECONDS"]))
    return RESULT


def hang(pages, doc_type):
    time.sleep(3600)


def die(pages, doc_type):
    os._exit(3)  # the OCR process dies without a word


def boom(pages, doc_type):
    raise RuntimeError("synthetic patient text that must not be stored")


def beating(pages, doc_type):
    """Hangs, but shows it is alive by growing a file."""
    while True:
        with open(os.environ["FAKE_ENGINE_BEAT_FILE"], "a") as f:
            f.write(".")
        time.sleep(0.2)
