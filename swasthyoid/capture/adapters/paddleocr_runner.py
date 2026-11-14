"""Runner for the PaddleOCR (English) adapter. Executed as a SCRIPT by an interpreter of a SEPARATE environment that has
PaddleOCR and PaddlePaddle (swasthyoid/capture/adapters/paddleocr_requirements.txt) and started with `-I`; never imported
by the application. docs/OCR_PADDLEOCR.md describes the setup.

NOT EXECUTED in this repository's tests: it needs PaddleOCR, PaddlePaddle and the weights, none of which is installed
here. It follows the same PaddleOCR 3.x call as the Jonaki runner (which is also unexecuted here); the adapter's tests
use a fake runner with the same protocol. The first real run is the owner's, after paddleocr_prepare.py.

Protocol: JSON on stdin {"pages": [{"page_number": n, "image": base64}]}; JSON on stdout
{"pages": [{"page_number": n, "status": "ok" | "undecodable", "lines": [{"text", "score", "poly"}]}]}.
Anything else printed by the libraries is kept off stdout. No model is downloaded: both model directories are required and
are passed explicitly, the cache is a private temporary directory, and offline library settings are set. Those settings do
NOT technically block network access. Orientation classification, textline orientation and document unwarping are OFF.
On any failure the process exits non-zero with no output, so no text or message can leak.
"""
import argparse
import base64
import json
import os
import shutil
import sys
import uuid


def run(args, cache):
    for name in ("HOME", "USERPROFILE", "XDG_CACHE_HOME", "PADDLE_PDX_CACHE_HOME"):
        os.environ[name] = cache
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    request = json.loads(sys.stdin.read())
    real_stdout, sys.stdout = sys.stdout, sys.stderr  # the libraries may print: keep stdout for the protocol

    import cv2
    import numpy as np
    from paddleocr import PaddleOCR

    ocr = PaddleOCR(
        text_detection_model_name=args.detector_name, text_detection_model_dir=args.detector,
        text_recognition_model_name=args.recognizer_name, text_recognition_model_dir=args.recognizer,
        use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=False,
    )
    pages = []
    for page in request["pages"]:
        data = np.frombuffer(base64.b64decode(page["image"]), dtype=np.uint8)
        image = cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None
        if image is None:
            pages.append({"page_number": page["page_number"], "status": "undecodable", "lines": []})
            continue
        result = ocr.predict(image)[0]
        lines = [{"text": str(text), "score": float(score), "poly": np.asarray(poly).astype(float).tolist()}
                 for poly, text, score in zip(result["rec_polys"], result["rec_texts"], result["rec_scores"])]
        pages.append({"page_number": page["page_number"], "status": "ok", "lines": lines})
    real_stdout.write(json.dumps({"pages": pages}))
    real_stdout.flush()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--recognizer", required=True)
    parser.add_argument("--detector", required=True)
    parser.add_argument("--recognizer-name", required=True)
    parser.add_argument("--detector-name", required=True)
    args = parser.parse_args()
    for directory in (args.recognizer, args.detector):
        if not os.path.isdir(directory):
            raise SystemExit(2)  # the models must already be there: nothing is ever downloaded
    # A private, empty cache directory (no shared cache is read or written). Made with os.mkdir and not tempfile: the
    # privacy guard forbids tempfile under capture/, and this directory never holds page content, only library caches.
    base = os.environ.get("TMPDIR") or os.environ.get("TEMP") or os.environ.get("TMP") or "/tmp"
    cache = os.path.join(base, "paddleocr-" + uuid.uuid4().hex)
    os.mkdir(cache, 0o700)
    try:
        run(args, cache)
    finally:
        shutil.rmtree(cache, ignore_errors=True)


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        os._exit(1)  # no traceback, no message: they could carry page text or paths
