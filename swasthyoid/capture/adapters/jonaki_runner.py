"""Runner for the Jonaki adapter. Executed as a SCRIPT by an interpreter of a SEPARATE environment
that has PaddleOCR and PaddlePaddle (swasthyoid/capture/adapters/jonaki_requirements.txt); never
imported by the application. docs/OCR_JONAKI.md describes the setup.

NOT EXECUTED in this repository's tests: it needs PaddleOCR, PaddlePaddle, the gated Jonaki
weights and a PP-OCRv6 detector, none of which is installed here. It follows the usage on the
model card (paddleocr 3.7.0); the adapter's tests use a fake runner with the same protocol.

Protocol: JSON on stdin {"pages": [{"page_number": n, "image": base64}]}; JSON on stdout
{"pages": [{"page_number": n, "status": "ok" | "undecodable", "lines": [{"text", "score", "poly"}]}]}.
Anything else printed by the libraries is kept off stdout. No model is downloaded: both model
directories are required and offline library settings are set; those settings do NOT technically block
network access. On any failure the process exits non-zero with
no output, so no text or message can leak.
"""
import argparse
import base64
import json
import os
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--recognizer", required=True)
    parser.add_argument("--detector", required=True)
    args = parser.parse_args()
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    request = json.loads(sys.stdin.read())
    real_stdout, sys.stdout = sys.stdout, sys.stderr  # the libraries may print: keep stdout for the protocol

    import cv2
    import numpy as np
    from paddleocr import PaddleOCR

    ocr = PaddleOCR(
        text_detection_model_name="PP-OCRv6_medium_det", text_detection_model_dir=args.detector,
        text_recognition_model_name="PP-OCRv6_small_rec", text_recognition_model_dir=args.recognizer,
        use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=False,
        text_det_limit_type="max", text_det_limit_side_len=1280,
        enable_mkldnn=os.environ.get("JONAKI_ENABLE_MKLDNN") == "1",  # off by default: the model card says the
        # PP-OCRv6 detector fails with oneDNN under PaddlePaddle 3.3 on CPU
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


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        os._exit(1)  # no traceback, no message: they could carry page text or paths
