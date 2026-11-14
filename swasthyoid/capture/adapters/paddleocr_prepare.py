"""ONE-TIME weights preparation for the PaddleOCR (English) adapter. Run BY THE OWNER, in the SEPARATE environment that has
PaddleOCR and PaddlePaddle (paddleocr_requirements.txt), with network access, never in the application's environment and
never by CI or by the worker:

    python -I paddleocr_prepare.py --out /srv/ocr/paddleocr-en [--detector-name NAME] [--recognizer-name NAME]

What it does, and nothing else:
1. Refuses to run if --out already holds files (it never overwrites or mixes).
2. Lets PaddleOCR download the two named official models into a private cache directory inside --out (this is the only
   step that uses the network, and the only one in this project that downloads anything); the cache is deleted at the end.
3. Copies exactly those two model directories to <out>/detector and <out>/recognizer (real files, no symlinks).
4. PRINTS the manifest as JSON on stdout (the model names, the PaddleOCR and PaddlePaddle versions, and the SHA-256 of every
   copied file); redirect it to a file of your choosing OUTSIDE both model directories. This script writes no file of its own.
5. Prints the next steps. It never writes an approved-adapter list: putting an entry in OCR_ADAPTERS_APPROVED is the
   owner's act, after reviewing the entry that `python -m swasthyoid.capture.adapters.paddleocr_adapter --root <out>
   --recognizer <out>/recognizer --detector <out>/detector` prints.

After this, run strictly offline from <out>. Review the licence of what was downloaded (PaddleOCR is Apache-2.0; the
models' own terms were not read here). Imports nothing from swasthyoid. The model names default to the first slice's
choice and are PROVISIONAL: confirm they exist in the PaddleOCR version you installed. NOT EXECUTED in this repository;
the layout PaddleX uses inside its cache is assumed from its documentation and is checked: if a model directory is not
found exactly once the script stops without copying.
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
from importlib import metadata
from pathlib import Path

DEFAULT_DETECTOR_NAME = "PP-OCRv5_mobile_det"
DEFAULT_RECOGNIZER_NAME = "en_PP-OCRv5_mobile_rec"


def find_model_directory(cache, name):
    """The one directory named `name` that holds files, anywhere under `cache`; SystemExit if there is none or several."""
    hits = [Path(root) for root, dirs, files in os.walk(cache) if Path(root).name == name and files]
    if len(hits) != 1:
        raise SystemExit(f"expected exactly one downloaded model directory named {name}, found {len(hits)}")
    return hits[0]


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(out, detector_name, recognizer_name, versions):
    files = []
    for sub in ("detector", "recognizer"):
        for path in sorted((out / sub).rglob("*")):
            if path.is_symlink():
                raise SystemExit("a symbolic link was found in a model directory")
            if path.is_file():
                files.append({"path": f"{sub}/{path.relative_to(out / sub).as_posix()}", "sha256": sha256_of(path)})
    return {"detector_name": detector_name, "recognizer_name": recognizer_name, **versions, "files": files}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="paddleocr_prepare.py")
    parser.add_argument("--out", required=True)
    parser.add_argument("--detector-name", default=DEFAULT_DETECTOR_NAME)
    parser.add_argument("--recognizer-name", default=DEFAULT_RECOGNIZER_NAME)
    args = parser.parse_args(argv)
    out = Path(args.out).resolve()
    if out.exists() and any(out.iterdir()):
        raise SystemExit("the output directory is not empty; refusing to overwrite or mix")
    out.mkdir(parents=True, exist_ok=True)
    cache = out / ".download-cache"
    cache.mkdir()
    for name in ("HOME", "USERPROFILE", "XDG_CACHE_HOME", "PADDLE_PDX_CACHE_HOME"):
        os.environ[name] = str(cache)  # the download goes to a private place we can inspect and then discard
    from paddleocr import PaddleOCR  # imported late: after the cache location is set

    PaddleOCR(text_detection_model_name=args.detector_name, text_recognition_model_name=args.recognizer_name,
              use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=False)
    detector = find_model_directory(cache, args.detector_name)
    recognizer = find_model_directory(cache, args.recognizer_name)
    shutil.copytree(detector, out / "detector", symlinks=False)
    shutil.copytree(recognizer, out / "recognizer", symlinks=False)
    versions = {"paddleocr": metadata.version("paddleocr"), "paddlepaddle": metadata.version("paddlepaddle")}
    shutil.rmtree(cache)
    manifest = build_manifest(out, args.detector_name, args.recognizer_name, versions)
    print(json.dumps(manifest, indent=2))  # stdout holds only the manifest, so it can be redirected to a file
    say = lambda text: print(text, file=sys.stderr)  # noqa: E731
    say(f"prepared {len(manifest['files'])} files under {out}. Save the manifest, review it and the models' licences, then print")
    say("the approved-list entry with:")
    say(f"  python -m swasthyoid.capture.adapters.paddleocr_adapter --root {out} "
        f"--recognizer {out / 'recognizer'} --detector {out / 'detector'}")
    say("and run offline with PADDLEOCR_PYTHON, PADDLEOCR_MODEL_DIR, PADDLEOCR_DETECTOR_DIR, PADDLEOCR_MODEL_REVISION and")
    say("PADDLEOCR_DETECTOR_REVISION set (docs/OCR_PADDLEOCR.md).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
