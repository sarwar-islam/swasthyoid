"""Test-only stand-in for capture/adapters/paddleocr_runner.py: the same JSON protocol, no OCR, no PaddleOCR, no weights.
FAKE_PADDLEOCR_MODE picks the behavior. The 'text' is synthetic."""
import base64
import json
import os
import sys
import time

MODE = os.environ.get("FAKE_PADDLEOCR_MODE", "ok")
OFFLINE = os.environ.get("HF_HUB_OFFLINE")
SECRETS = ("DATABASE_URL", "JWT_SECRET", "DOCUMENT_KEY", "PII_KEY", "HMAC_KEY", "HF_TOKEN", "HUGGING_FACE_HUB_TOKEN",
           "SYNTHETIC_SECRET", "EXTRACTION_KEY")


def box(x, y, w=200, h=40):
    return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]


# deliberately NOT in reading order: the adapter must order them
LINES = [
    {"text": "second row right", "score": 0.91, "poly": box(400, 104)},
    {"text": "Tab. Synthetic 500 mg twice daily", "score": 0.97, "poly": box(20, 50)},
    {"text": "   ", "score": 0.30, "poly": box(300, 300)},          # a box with no readable text
    {"text": "third row", "score": 0.88, "poly": box(20, 160)},
    {"text": "second row left", "score": 0.93, "poly": box(20, 100)},
    {"text": "first row right", "score": 0.95, "poly": box(400, 53)},  # a little lower than its row mates
]


def main():
    request = json.loads(sys.stdin.read())
    if MODE == "crash":
        os._exit(3)
    if MODE == "hang":
        time.sleep(3600)
    if MODE == "garbage":
        sys.stdout.write("this is not json")
        return
    if MODE == "leak":  # a misbehaving runner that prints page content on stderr and exits non-zero
        sys.stderr.write("synthetic patient text that must never be logged")
        os._exit(2)
    pages = []
    for page in request["pages"]:
        raw = base64.b64decode(page["image"])
        if MODE == "undecodable" or raw == b"UNDECODABLE":
            pages.append({"page_number": page["page_number"], "status": "undecodable", "lines": []})
        elif MODE == "wrong_page":
            pages.append({"page_number": page["page_number"] + 5, "status": "ok", "lines": []})
        elif MODE == "empty":
            pages.append({"page_number": page["page_number"], "status": "ok", "lines": []})
        elif MODE == "bad_poly":
            pages.append({"page_number": page["page_number"], "status": "ok",
                          "lines": [{"text": "x", "score": 0.9, "poly": [[0, 0]]}]})
        elif MODE == "environment":  # report what reached this process: the secrets that did, as names
            leaked = [name for name in SECRETS if name in os.environ]
            home = [name for name in ("HOME", "USERPROFILE") if name in os.environ]
            pages.append({"page_number": page["page_number"], "status": "ok", "lines": [
                {"text": f"offline={OFFLINE} leaked={leaked} home={home} marker={'PADDLEOCR_MARKER' in os.environ}",
                 "score": 1.0, "poly": box(0, 0)}]})
        elif MODE == "arguments":  # report the command line the runner was started with (names only, no paths)
            names = [sys.argv[i + 1] for i, a in enumerate(sys.argv[:-1]) if a in ("--recognizer-name", "--detector-name")]
            pages.append({"page_number": page["page_number"], "status": "ok", "lines": [
                {"text": " ".join(names), "score": 1.0, "poly": box(0, 0)}]})
        elif MODE == "nan_score":
            pages.append({"page_number": page["page_number"], "status": "ok",
                          "lines": [{"text": "t", "score": float("nan"), "poly": box(0, 0)}]})
        else:
            pages.append({"page_number": page["page_number"], "status": "ok", "lines": LINES})
    sys.stdout.write(json.dumps({"pages": pages}))


main()
