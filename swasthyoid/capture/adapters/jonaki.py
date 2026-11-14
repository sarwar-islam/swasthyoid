"""TEMPORARY, replaceable OCR adapter for Jonaki (islamsidratul/jonaki-bangla-ocr).

Implements the existing provider-independent adapter contract (capture/ocr.py, interface version
0, test mode only; D17/D18 are unchanged). Nothing downstream knows about Jonaki: a first-party
model replaces this module by being named in OCR_ADAPTER, with no change to the worker, the
extraction rows or M3.

What Jonaki is: a PP-OCRv6 small text-LINE recognizer for printed Bengali. A page needs a
PP-OCRv6 detector in front of it. Not handwriting, not tables, English-only pages not evaluated.
Its weights are gated (the author approves each request) and licensed CC BY-NC 4.0: see
docs/OCR_JONAKI.md. Nothing is downloaded by this code.

Isolation: this module imports only the standard library. PaddleOCR and PaddlePaddle run in a
SEPARATE Python environment, started as a child process per read() (jonaki_runner.py, JSON over
stdin and stdout), so the core installation gains no heavy dependency. The child receives an
ALLOWLISTED environment only (no database URL, no keys, no tokens), model directories are local
and offline mode is set (this asks the libraries not to use the network; it does not block the
network), its stderr is discarded, and no exception message, page text or path is ever carried
in an AdapterError.

What is preserved: per line the text, the recognition score as `confidence` (a recognition score
is NOT clinical correctness) and the box as `position`, in explicit reading order, per page. In
interface version 0 only the text reaches the database (items and positions are never stored); the
provenance that is stored is engine_id, model_version (recognizer and detector revisions),
adapter_version and, through the approved-artifact manifest, the model checksum. That checksum proves the
loaded weights only when an approved-adapter entry exists: the factory then requires every file in both
model directories to be listed (check_linkage). Without an entry (test mode only) it is the SHA-256 of
empty input, a constant, and proves nothing. Linkage is tested with synthetic files, not real weights.

Fail closed: a page that cannot be decoded, a crashed or hung runner, or malformed runner output
raises an AdapterError (the attempt fails and is retried, then goes to manual entry). A page that
decodes and holds no text is a valid empty page.
"""
import base64
import json
import math
import os
import re
import statistics
import subprocess
import sys
import unicodedata
from pathlib import Path

from swasthyoid.capture import ocr
from swasthyoid.capture.ocr import AdapterError

ENGINE_ID = "jonaki-bangla-ocr"
ADAPTER_VERSION = "jonaki-1"
RUNNER = Path(__file__).with_name("jonaki_runner.py")
PAGE_SECONDS = 120.0  # PROVISIONAL: CPU takes 13-16 s per page plus model loading (model card)
ROW_TOLERANCE = 0.5   # a line joins a row when its centre is within this share of the median line height
_REVISION = re.compile(r"[A-Za-z0-9._-]{1,40}")
# The runner child gets ONLY these variables (an allowlist, not "everything except known secrets"):
# the worker's environment holds DATABASE_URL, JWT_SECRET, DOCUMENT_KEY, PII_KEY, HMAC_KEY and any
# Hugging Face token, and a third-party OCR stack has no business seeing them.
_ENV_NAMES = frozenset({"PATH", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "TMPDIR",
                        "HOME", "USERPROFILE", "LANG", "LC_ALL", "LC_CTYPE", "LD_LIBRARY_PATH"})
_ENV_PREFIXES = ("JONAKI_", "FLAGS_", "PADDLE", "OMP_", "MKL_", "KMP_", "CUDA_")


def _fail(code):
    return AdapterError(code)


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def clean_text(text):
    """NFC text with control characters turned into spaces and the ends trimmed ('' if nothing
    is left). NFC is the form the model card scores in."""
    if not isinstance(text, str):
        raise _fail("malformed_output")
    spaced = "".join(" " if unicodedata.category(c) == "Cc" else c for c in text)
    return unicodedata.normalize("NFC", spaced).strip()


def _polygon(raw):
    if not (isinstance(raw, list) and len(raw) >= 3):
        raise _fail("malformed_output")
    points = []
    for point in raw:
        if not (isinstance(point, list) and len(point) == 2 and all(_number(v) for v in point)):
            raise _fail("malformed_output")
        points.append([point[0], point[1]])
    return points


def reading_order(lines):
    """The lines top to bottom, and left to right within a printed row. Each line is a dict with a
    "position" polygon. A line joins a row when its vertical centre is within ROW_TOLERANCE of the
    median line height from the row's mean centre. Deterministic; ties keep their input order.
    shortcut: one column. A two-column or two-page layout comes out in row order across the
    columns (the model card's gutter detection is not reproduced); upgrade when such pages matter."""
    if not lines:
        return []
    heights = [max(p[1] for p in line["position"]) - min(p[1] for p in line["position"]) for line in lines]
    limit = ROW_TOLERANCE * (statistics.median(heights) or 1.0)
    keyed = sorted(((sum(p[1] for p in line["position"]) / len(line["position"]),
                     min(p[0] for p in line["position"]), n) for n, line in enumerate(lines)))
    rows = []
    for cy, x, n in keyed:
        if rows and abs(cy - statistics.fmean(c for c, _, _ in rows[-1])) < limit:
            rows[-1].append((cy, x, n))
        else:
            rows.append([(cy, x, n)])
    return [lines[n] for row in rows for _, _, n in sorted(row, key=lambda r: (r[1], r[2]))]


def _items(page):
    """Items of one runner page in reading order, or an AdapterError."""
    if not isinstance(page, dict) or page.get("status") not in ("ok", "undecodable"):
        raise _fail("malformed_output")
    if page["status"] == "undecodable":
        raise _fail("engine_error")  # fail closed: never report an unreadable page as "no text found"
    if not isinstance(page.get("lines"), list):
        raise _fail("malformed_output")
    lines = []
    for raw in page["lines"]:
        if not isinstance(raw, dict):
            raise _fail("malformed_output")
        text = clean_text(raw.get("text"))
        position = _polygon(raw.get("poly"))  # validated even for a line that is dropped
        if not text:
            continue  # a detected box with no readable text is not an item
        item = {"text": text, "position": position}
        score = raw.get("score")
        if _number(score):
            item["confidence"] = float(score)
        lines.append(item)
    return reading_order(lines)


class Jonaki:
    """Adapter contract version 0. `command` starts the runner (an interpreter of the separate
    environment plus the runner path and its model directories)."""

    def __init__(self, command, revision, detector_revision, page_seconds=PAGE_SECONDS, extra_env=None):
        if not (isinstance(command, (list, tuple)) and command and all(isinstance(c, str) for c in command)):
            raise _fail("engine_unavailable")
        if not all(isinstance(r, str) and _REVISION.fullmatch(r) for r in (revision, detector_revision)):
            raise _fail("engine_unavailable")
        if not (_number(page_seconds) and page_seconds > 0):
            raise _fail("engine_unavailable")
        self.command, self.revision, self.detector_revision = list(command), revision, detector_revision
        self.page_seconds = float(page_seconds)
        if not (extra_env is None or (isinstance(extra_env, dict) and all(
                isinstance(k, str) and isinstance(v, str) for k, v in extra_env.items()))):
            raise _fail("engine_unavailable")
        self.extra_env = dict(extra_env or {})  # explicit additions (tests); never copied from the worker

    def identity(self):
        return {"engine_id": ENGINE_ID, "interface_versions": [0], "test_only": True,
                "model_version": f"jonaki-small-rec@{self.revision}; PP-OCRv6_medium_det@{self.detector_revision}",
                "adapter_version": ADAPTER_VERSION}

    def prepare(self):
        """Nothing is loaded in this process; the runner loads the model for each read()."""

    def release(self):
        """Nothing to release: the runner exits after each read()."""

    def _environment(self):
        env = {k: v for k, v in os.environ.items() if k in _ENV_NAMES or k.startswith(_ENV_PREFIXES)}
        env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK="True")
        env.update(self.extra_env)
        return env

    def read(self, document):
        pages = []
        for page in document:
            image = page.get("image") if isinstance(page, dict) else None
            if not isinstance(image, (bytes, bytearray)):
                raise _fail("engine_error")
            pages.append({"page_number": page["page_number"], "image": base64.b64encode(image).decode("ascii")})
        payload = json.dumps({"pages": pages}).encode("utf-8")
        try:
            proc = subprocess.Popen(self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, env=self._environment(),
                                    start_new_session=(sys.platform != "win32"))
        except (OSError, ValueError):
            raise _fail("engine_unavailable")
        try:
            out, _ = proc.communicate(payload, timeout=self.page_seconds * max(1, len(pages)))
        except subprocess.TimeoutExpired:
            self._kill(proc)
            raise _fail("engine_error")
        except BaseException:
            self._kill(proc)
            raise
        if proc.returncode != 0:
            raise _fail("engine_error")
        try:
            data = json.loads(out.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise _fail("malformed_output")
        if not (isinstance(data, dict) and isinstance(data.get("pages"), list) and len(data["pages"]) == len(pages)):
            raise _fail("malformed_output")
        result_pages = []
        for n, (asked, page) in enumerate(zip(pages, data["pages"]), 1):
            if not isinstance(page, dict) or page.get("page_number") != asked["page_number"]:
                raise _fail("malformed_output")  # the runner must answer the pages asked, in order
            result_pages.append({"page_number": n, "items": _items(page)})
        identity = self.identity()
        return {"interface_version": 0, "engine_id": identity["engine_id"],
                "model_version": identity["model_version"], "pages": result_pages}

    @staticmethod
    def _kill(proc):
        try:
            if sys.platform != "win32":
                import signal
                os.killpg(proc.pid, signal.SIGKILL)
            else:
                proc.kill()
        except (OSError, ProcessLookupError):
            pass
        try:
            proc.communicate(timeout=10)
        except Exception:
            proc.kill()


def _env_path(name, directory):
    value = os.environ.get(name)
    if not (value and os.path.isabs(value) and (os.path.isdir(value) if directory else os.path.isfile(value))):
        raise _fail("engine_unavailable")
    return value


def artifact_files(directory):
    """Every regular file under `directory` as a sorted list of paths relative to it, '/'-separated.
    A symlink anywhere below it, or anything that is neither a file nor a directory, raises
    AdapterError(model_integrity_failed): the runner must load exactly what was approved."""
    root = Path(directory)
    found = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise _fail("model_integrity_failed")
        if path.is_file():
            found.append(path.relative_to(root).as_posix())
        elif not path.is_dir():
            raise _fail("model_integrity_failed")
    return found


def _listed(root, directory):
    """The files of `directory` as paths relative to the artifact root; the directory must be below it."""
    base = Path(directory).resolve()
    try:
        prefix = base.relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        raise _fail("model_integrity_failed")
    return {f"{prefix}/{name}" if prefix != "." else name for name in artifact_files(base)}


def check_linkage(entry, recognizer, detector):
    """Tie the approved-artifact entry to the directories the runner will load: both must lie under
    the entry's artifact_root and EVERY file in them must be listed (the manifest checksum then
    covers exactly the loaded files). Raises AdapterError(model_integrity_failed) otherwise.
    UNRESOLVED RESIDUAL RISK (not an approved limitation): a file can still change between this
    check and the runner reading it, and hard links are not detected. For the 4A artifact check
    the owner recorded hard links as a documented limitation (docs/DECISIONS.md, "Owner decisions
    applied"); that record does not mention this check. See docs/M2_OWNER_DECISIONS.md, R1 and R2."""
    listed = set(entry["artifacts"])
    for directory in (recognizer, detector):
        if not _listed(entry["artifact_root"], directory) <= listed:
            raise _fail("model_integrity_failed")


def build_allowlist_entry(ref, root, recognizer, detector):
    """The OCR_ADAPTERS_APPROVED entry for exactly the files in the two model directories, with the
    real manifest checksum of those files. A convenience for the operator: putting an entry in the
    approved list is the OWNER's act, and the entry should be reviewed before it is."""
    artifacts = sorted(_listed(root, recognizer) | _listed(root, detector))
    entry = {"ref": ref, "artifact_root": str(Path(root).resolve()), "artifacts": artifacts, "model_checksum": ""}
    entry["model_checksum"] = ocr.manifest_checksum(entry)
    return entry


def jonaki():
    """The factory named in OCR_ADAPTER. Every setting is checked here, without loading anything:
    JONAKI_PYTHON (an interpreter of the separate environment), JONAKI_MODEL_DIR and
    JONAKI_DETECTOR_DIR (local directories), JONAKI_MODEL_REVISION and JONAKI_DETECTOR_REVISION
    (what the operator says the weights are, e.g. the Hugging Face commit hash; the approved-artifact
    checksum is what proves it), optional JONAKI_PAGE_SECONDS. When OCR_ADAPTERS_APPROVED has an
    entry for this adapter, the two directories must be covered by it (check_linkage). With no
    entry (test mode only) nothing ties the loaded files to any checksum."""
    python = _env_path("JONAKI_PYTHON", directory=False)
    recognizer = _env_path("JONAKI_MODEL_DIR", directory=True)
    detector = _env_path("JONAKI_DETECTOR_DIR", directory=True)
    try:
        seconds = float(os.environ.get("JONAKI_PAGE_SECONDS", PAGE_SECONDS))
    except ValueError:
        raise _fail("engine_unavailable")
    for directory in (recognizer, detector):
        if Path(directory).is_symlink():  # the path the runner receives must be the one that was checked
            raise _fail("model_integrity_failed")
    recognizer, detector = str(Path(recognizer).resolve()), str(Path(detector).resolve())
    entry = ocr.load_allowlist().get(os.environ.get("OCR_ADAPTER"))
    if entry is not None:  # with an approved entry the loaded files must be the approved ones
        check_linkage(entry, recognizer, detector)
    command = [python, str(RUNNER), "--recognizer", recognizer, "--detector", detector]
    return Jonaki(command, os.environ.get("JONAKI_MODEL_REVISION", ""),
                  os.environ.get("JONAKI_DETECTOR_REVISION", ""), seconds)


def main(argv=None):
    """Print the approved-list entry for the model directories: python -m swasthyoid.capture.adapters.jonaki
    --root ROOT --recognizer DIR --detector DIR [--ref REF]. Read-only."""
    import argparse
    parser = argparse.ArgumentParser(prog="python -m swasthyoid.capture.adapters.jonaki")
    parser.add_argument("--root", required=True)
    parser.add_argument("--recognizer", required=True)
    parser.add_argument("--detector", required=True)
    parser.add_argument("--ref", default="swasthyoid.capture.adapters.jonaki:jonaki")
    args = parser.parse_args(argv)
    try:
        print(json.dumps({"adapters": [build_allowlist_entry(args.ref, args.root, args.recognizer, args.detector)]},
                         indent=2))
    except AdapterError as failure:
        print(f"code={failure.code}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
