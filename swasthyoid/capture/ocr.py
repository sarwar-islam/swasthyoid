"""M2 step 4A — model-independent OCR infrastructure (docs/DECISIONS.md, D17; plan Revision 4).

No OCR model or engine is chosen, bundled or integrated here. The owner trains, owns and
supplies the model; a model-specific adapter is written only after the owner's specification
and explicit approval (D4, D18).

Interface version 0 is an INFRASTRUCTURE-TEST interface, not an OCR contract. It is accepted
only in test mode (runtime_mode) and is checked again in the probe, in the OCR child and before
anything is stored. Outside test mode no interface version is implemented, so no adapter is ever
available: documents stay `uploaded` and manual entry remains possible (Option A).

An adapter is named by a reference "package.module:factory". The worker never imports it: a
short-lived probe child checks the artifacts, then imports the adapter and reads its identity,
before anything is claimed; the OCR child of each attempt re-checks the artifacts before it
imports the adapter. Neither child touches the database.

Logs carry error codes and operational metadata only: never document text, OCR output,
adapter exception messages or artifact contents.
"""
import hashlib
import importlib
import json
import logging
import math
import multiprocessing
import os
import re
import signal
import socket
import stat
import sys
import threading
import time
import unicodedata
from datetime import timedelta
from pathlib import Path

from swasthyoid import runtime_mode

log = logging.getLogger(__name__)

INTERFACE_VERSION = 0                         # test-only; version 1 waits for D18 and owner approval
AVAILABILITY_TIMEOUT = timedelta(seconds=30)  # provisional engineering default (owner-approved)
POSITION_MAX_DEPTH = 32                       # provisional engineering limit (owner-approved)
CODES = {"engine_unavailable", "model_integrity_failed", "availability_timeout", "malformed_output",
         "engine_error"}

_REF = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*:[A-Za-z_][A-Za-z0-9_]*")
_ENGINE_ID = re.compile(r"[a-z0-9_-]{1,64}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_IDENTITY_KEYS, _IDENTITY_OPTIONAL = {"engine_id", "model_version", "interface_versions", "test_only"}, {"adapter_version"}
_RESULT_KEYS = {"interface_version", "engine_id", "model_version", "pages"}
_ENTRY_KEYS = {"ref", "artifact_root", "artifacts", "model_checksum"}


class AdapterError(Exception):
    """args[0] is one of CODES; anything else becomes engine_error. Carries no message."""

    def __init__(self, code):
        super().__init__(code if code in CODES else "engine_error")

    @property
    def code(self):
        return self.args[0]


# ---- validation (interface version 0)

def _malformed():
    return AdapterError("malformed_output")


def _no_controls(text, allow_tab=False):
    return not any(unicodedata.category(c) == "Cc" and not (allow_tab and c == "\t") for c in text)


def _short_text(value, longest):
    if not (isinstance(value, str) and 1 <= len(value) <= longest and _no_controls(value)):
        raise _malformed()
    return value


def _int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def validate_identity(identity):
    """A plain copy of a valid identity, or malformed_output."""
    if not isinstance(identity, dict):
        raise _malformed()
    keys = set(identity)
    if not _IDENTITY_KEYS <= keys or keys - _IDENTITY_KEYS - _IDENTITY_OPTIONAL:
        raise _malformed()
    if not (isinstance(identity["engine_id"], str) and _ENGINE_ID.fullmatch(identity["engine_id"])):
        raise _malformed()
    versions = identity["interface_versions"]
    if not (isinstance(versions, list) and versions and all(_int(v) and v >= 0 for v in versions)):
        raise _malformed()
    if not isinstance(identity["test_only"], bool):
        raise _malformed()
    out = {"engine_id": identity["engine_id"], "model_version": _short_text(identity["model_version"], 128),
           "interface_versions": list(versions), "test_only": identity["test_only"]}
    if "adapter_version" in identity:
        out["adapter_version"] = _short_text(identity["adapter_version"], 64)
    return out


def _item_text(text):
    if not (isinstance(text, str) and text.strip() and _no_controls(text, allow_tab=True)):
        raise _malformed()
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:  # lone surrogates
        raise _malformed()


def _json_value(value, depth=1):
    if depth > POSITION_MAX_DEPTH:
        raise _malformed()
    if value is None or isinstance(value, (bool, str)) or _int(value):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise _malformed()
        return
    if isinstance(value, list):
        for v in value:
            _json_value(v, depth + 1)
        return
    if isinstance(value, dict):
        for k, v in value.items():
            if not isinstance(k, str):
                raise _malformed()
            _json_value(v, depth + 1)
        return
    raise _malformed()


def validate_result(result, page_count, identity):
    """Interface version 0 output. Raises malformed_output; returns the result unchanged."""
    if not (isinstance(result, dict) and set(result) == _RESULT_KEYS):
        raise _malformed()
    if not (_int(result["interface_version"]) and result["interface_version"] == INTERFACE_VERSION):
        raise _malformed()
    if result["engine_id"] != identity["engine_id"] or result["model_version"] != identity["model_version"]:
        raise _malformed()
    pages = result["pages"]
    if not (isinstance(pages, list) and len(pages) == page_count):
        raise _malformed()
    for n, page in enumerate(pages, 1):
        if not (isinstance(page, dict) and set(page) == {"page_number", "items"}):
            raise _malformed()
        if not (_int(page["page_number"]) and page["page_number"] == n and isinstance(page["items"], list)):
            raise _malformed()  # an empty list is valid: the page was read and nothing was found
        for item in page["items"]:
            if not (isinstance(item, dict) and "text" in item and set(item) <= {"text", "confidence", "position"}):
                raise _malformed()
            _item_text(item["text"])
            confidence = item.get("confidence")
            # the range is not checked: what confidence means is open until D18
            if confidence is not None and not ((_int(confidence) or isinstance(confidence, float))
                                               and math.isfinite(confidence)):
                raise _malformed()
            if "position" in item:
                _json_value(item["position"])  # never interpreted, never stored
    return result


def raw_text_v0(result):
    """shortcut: interface version 0 only, synthetic infrastructure tests only (D17 revision 3);
    how production raw text is formed is open until D18."""
    if not runtime_mode.is_test_mode():
        raise AdapterError("engine_unavailable")
    return "\n\n".join("\n".join(i["text"] for i in p["items"]) for p in result["pages"])


# ---- configuration and the owner's approved-adapter list

def normalize_path(path):
    """One artifact path relative to artifact_root, or engine_unavailable (configuration error)."""
    if not (isinstance(path, str) and path):
        raise AdapterError("engine_unavailable")
    path = unicodedata.normalize("NFC", path)
    if "\\" in path or path.startswith("/") or re.match(r"[A-Za-z]:", path):
        raise AdapterError("engine_unavailable")
    if any(part in ("", ".", "..") for part in path.split("/")):
        raise AdapterError("engine_unavailable")
    return path


def _entry(raw):
    if not (isinstance(raw, dict) and set(raw) == _ENTRY_KEYS):
        raise AdapterError("engine_unavailable")
    ref, root, artifacts, checksum = raw["ref"], raw["artifact_root"], raw["artifacts"], raw["model_checksum"]
    if not (isinstance(ref, str) and _REF.fullmatch(ref) and isinstance(root, str) and os.path.isabs(root)
            and isinstance(artifacts, list) and isinstance(checksum, str) and _SHA256.fullmatch(checksum)):
        raise AdapterError("engine_unavailable")
    paths = [normalize_path(p) for p in artifacts]
    if len(set(paths)) != len(paths):
        raise AdapterError("engine_unavailable")  # duplicates after normalisation
    return {"ref": ref, "artifact_root": root, "artifacts": paths, "model_checksum": checksum}


def load_allowlist():
    """{ref: entry} from the owner's OCR_ADAPTERS_APPROVED file; {} if the variable is unset."""
    path = os.environ.get("OCR_ADAPTERS_APPROVED")
    if not path:
        return {}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise AdapterError("engine_unavailable")
    if not (isinstance(data, dict) and set(data) == {"adapters"} and isinstance(data["adapters"], list)):
        raise AdapterError("engine_unavailable")
    entries = [_entry(e) for e in data["adapters"]]
    if len({e["ref"] for e in entries}) != len(entries):
        raise AdapterError("engine_unavailable")
    return {e["ref"]: e for e in entries}


# ---- artifact manifest (version 0 rule; the final format is open until D18)

def manifest_checksum(entry):
    """SHA-256 over sorted "path<TAB>sha256<LF>" lines of the approved artifacts.
    Documented limitation recorded by the owner (docs/DECISIONS.md, "Owner decisions applied",
    2026-11-12): hard links are not detected.
    UNRESOLVED RESIDUAL RISK, NOT approved by the owner: a file can still change between this
    check and the adapter reading it (see docs/M2_OWNER_DECISIONS.md, R1)."""
    if entry is None or not entry["artifacts"]:
        if not runtime_mode.is_test_mode():
            raise AdapterError("engine_unavailable")  # an empty artifact list is test-only
        return hashlib.sha256(b"").hexdigest()
    root = Path(entry["artifact_root"])
    try:
        if not root.is_absolute() or root.is_symlink() or not root.is_dir():
            raise AdapterError("model_integrity_failed")
        real_root = root.resolve(strict=True)
        lines = []
        for rel in entry["artifacts"]:
            current = root
            for part in rel.split("/"):
                current = current / part
                if current.is_symlink():
                    raise AdapterError("model_integrity_failed")
            if not stat.S_ISREG(os.stat(current, follow_symlinks=False).st_mode):
                raise AdapterError("model_integrity_failed")
            if real_root not in current.resolve(strict=True).parents:
                raise AdapterError("model_integrity_failed")
            digest = hashlib.sha256()
            with open(current, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    digest.update(chunk)
            lines.append((rel.encode("utf-8"), f"{rel}\t{digest.hexdigest()}\n"))
    except OSError:
        raise AdapterError("model_integrity_failed")
    return hashlib.sha256("".join(line for _, line in sorted(lines)).encode("utf-8")).hexdigest()


# ---- child processes (probe and OCR attempt)

def _block_network():
    def blocked(*args, **kwargs):
        raise OSError("blocked by the test network guard")
    socket.socket.connect = blocked
    socket.socket.connect_ex = blocked
    socket.create_connection = blocked


_STOP, _KILL = getattr(signal, "SIGSTOP", 19), getattr(signal, "SIGKILL", 9)  # numbers: Linux, for tests on any system


def _children_by_parent(proc_root="/proc"):
    """{parent pid: [child pids]} read from /proc (Linux). A process that exits while the table is
    read is skipped; no /proc gives an empty table."""
    tree = {}
    try:
        names = os.listdir(proc_root)
    except OSError:
        return tree
    for name in names:
        if not name.isdigit():
            continue
        try:
            with open(os.path.join(proc_root, name, "stat"), "rb") as f:
                # "pid (name) state ppid ...": the name may hold spaces and brackets, so split after the last ")"
                parent = int(f.read().decode("ascii", "replace").rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            continue
        tree.setdefault(parent, []).append(int(name))
    return tree


def descendants(pid, proc_root="/proc"):
    """Every live descendant of `pid` (children, their children, ...), whatever its session or process
    group: the walk follows parent ids, which a new session does not change."""
    tree, found, seen, stack = _children_by_parent(proc_root), [], {pid}, [pid]
    while stack:
        for child in tree.get(stack.pop(), ()):
            if child not in seen:
                seen.add(child)
                found.append(child)
                stack.append(child)
    return found


def _send(send, pid, sig):
    """Send one signal. False if the process is already gone (it exited first: not an error) or the
    system refused (logged by code only)."""
    try:
        send(pid, sig)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        log.warning("ocr process kill refused: code=kill_permission")
        return False


def kill_descendants(pid, *, freeze_root=False, proc_root="/proc", send=os.kill, rounds=10):
    """Linux: kill every descendant of `pid`, including those in another session or group.
    Everything found is stopped first (a stopped process cannot fork), the walk repeats until it finds
    nothing new, then all of it is killed, then one last pass catches any straggler. With freeze_root the
    root is stopped first too, so it cannot start new children meanwhile (the caller kills it afterwards).
    Races are expected and harmless: a process that exits first is skipped, a refused signal is logged.
    Without /proc (Windows, macOS) it does nothing; Windows trees are ended by stop_child instead."""
    if not isinstance(pid, int) or pid <= 1 or not os.path.isdir(proc_root):
        return
    if freeze_root:
        _send(send, pid, _STOP)
    known = []
    for _ in range(rounds):
        fresh = [p for p in descendants(pid, proc_root) if p not in known]
        if not fresh:
            break
        for p in fresh:
            _send(send, p, _STOP)
        known.extend(fresh)
    for p in known:
        _send(send, p, _KILL)
    for p in descendants(pid, proc_root):
        _send(send, p, _KILL)


def _become_subreaper():
    """Linux: make this process the adopter of its orphaned descendants (PR_SET_CHILD_SUBREAPER), so a
    grandchild whose parent exits is re-parented here instead of to init, and the walk still finds it."""
    if not sys.platform.startswith("linux"):
        return
    try:
        import ctypes
        ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0)
    except (OSError, AttributeError):
        pass  # best effort: without it only descendants whose parents are still alive are found


def _watchdog(limit):
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline and multiprocessing.parent_process().is_alive():
        time.sleep(1)
    kill_descendants(os.getpid())  # also the ones in their own session
    if hasattr(os, "killpg"):
        try:
            os.killpg(0, signal.SIGKILL)  # this child leads its own group: take the group with it
        except OSError:
            pass
    os._exit(1)


def enter_child(limit):
    """First thing in every probe and OCR child: own process group (Linux), quiet output outside
    test mode, the network guard in test mode on request, and a watchdog that ends the group when
    the worker is gone or the limit has passed."""
    if hasattr(os, "setsid"):
        try:
            os.setsid()
        except OSError:
            pass
    _become_subreaper()
    if not runtime_mode.is_test_mode():
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, 1)
        os.dup2(devnull, 2)
    elif os.environ.get("OCR_TEST_BLOCK_NETWORK") == "1":
        _block_network()
    threading.Thread(target=_watchdog, args=(limit,), daemon=True).start()


def _taskkill_tree(pid):
    """Windows: end the process and everything it started (fixed command, no shell, a number as argument)."""
    import subprocess
    try:
        subprocess.run(["taskkill", "/PID", str(int(pid)), "/T", "/F"], stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        log.warning("ocr child tree kill failed: code=taskkill")


def stop_child(proc):
    """End the child and everything it started, then reap it. Linux: the child is frozen, every
    descendant is found by walking parent ids (so one in its own session or group is found too) and
    killed, then the child's group and the child are killed. All of this happens before the child is
    reaped, so its id cannot have been reused. Windows: the whole tree is ended with taskkill /T.
    Remaining limit: a descendant whose parent died earlier and that left the group (a daemon started by
    an engine that was itself killed from outside) is not found; the child is its subreaper while it
    lives, which covers every normal exit, timeout and worker death."""
    if proc.pid is None:
        return
    if sys.platform == "win32":
        _taskkill_tree(proc.pid)
    else:
        kill_descendants(proc.pid, freeze_root=True)
    if hasattr(os, "killpg"):
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass  # the group is already gone
        except PermissionError:
            log.warning("ocr child group kill refused: code=killpg_permission")
    if proc.is_alive():
        proc.kill()
    proc.join(10)


def _load(ref):
    module, _, name = ref.partition(":")
    adapter = getattr(importlib.import_module(module), name)()
    if not all(callable(getattr(adapter, m, None)) for m in ("identity", "prepare", "read", "release")):
        raise AdapterError("engine_unavailable")
    return adapter


def is_test_ref(ref):
    """An adapter reference inside the swasthyoid.tests package (test-only fakes)."""
    module = ref.partition(":")[0]
    return module == "swasthyoid.tests" or module.startswith("swasthyoid.tests.")


_PROBE_MESSAGE_MAX = 1 << 16  # bytes; a probe message is a checksum or an identity


def _probe_main(ref, entry, out, limit):
    """Probe child. Re-checks test mode before anything else: interface version 0 is the only
    version and it is test-only, so outside test mode no adapter code is imported. Then the
    artifacts (no adapter code loaded yet), then the identity. Never calls prepare(): whether a
    probe may load the model is open until D18. Messages are JSON bytes, never pickles, and the
    channel is closed at the end so the worker sees EOF."""
    def send(kind, value):
        out.send_bytes(json.dumps([kind, value]).encode("utf-8"))

    enter_child(limit)
    try:
        try:
            runtime_mode.check_test_mode_config()
            test_mode = runtime_mode.is_test_mode()
        except Exception:  # APP_ENV=test without its confirmation: fail closed
            test_mode = False
        if not test_mode:
            send("failed", "engine_unavailable")
            return
        send("checksum", manifest_checksum(entry))
        send("identity", validate_identity(_load(ref).identity()))
    except AdapterError as e:
        send("failed", e.code)
    except BaseException:
        send("failed", "engine_unavailable")
    finally:
        out.close()
        kill_descendants(os.getpid())  # an adapter's identity() must not leave processes behind


def _read_probe(results, deadline):
    """Every message the probe child sends, read until the channel reaches EOF, or AdapterError.
    The only accepted sequences are [checksum, identity], [failed] and [checksum, failed];
    anything duplicate, late, out of order or unexpected is refused. The deadline still applies
    to the whole exchange, including waiting for EOF."""
    messages = []
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise AdapterError("availability_timeout")
        try:
            if not results.poll(remaining):
                continue
            raw = results.recv_bytes(_PROBE_MESSAGE_MAX)
        except (EOFError, BrokenPipeError):
            break  # the child closed its end: the sequence is complete
        except OSError:  # includes a message over the size limit
            raise AdapterError("engine_unavailable")
        try:
            message = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise AdapterError("engine_unavailable")
        if not (isinstance(message, list) and len(message) == 2 and isinstance(message[0], str)):
            raise AdapterError("engine_unavailable")
        messages.append(message)
        if len(messages) > 2:
            raise AdapterError("engine_unavailable")  # nothing valid is longer than two
    kinds = [kind for kind, _ in messages]
    if kinds in (["failed"], ["checksum", "failed"]):
        failure = messages[-1][1]  # child-supplied: only a string can be a code (a list is unhashable)
        raise AdapterError(failure if isinstance(failure, str) and failure in CODES else "engine_unavailable")
    if kinds != ["checksum", "identity"]:
        raise AdapterError("engine_unavailable")
    return messages[0][1], messages[1][1]


def probe(ref, entry, timeout):
    """(model_checksum, identity) from an isolated, time-bounded child, or AdapterError."""
    spawn = multiprocessing.get_context("spawn")
    results, out = spawn.Pipe(duplex=False)
    child = spawn.Process(target=_probe_main, args=(ref, entry, out, timeout.total_seconds() + 5), daemon=True)
    try:
        child.start()
        out.close()  # so that EOF arrives once the child closes its end
        checksum, identity = _read_probe(results, time.monotonic() + timeout.total_seconds())
    finally:
        stop_child(child)
        out.close()  # also when start() failed
        results.close()
    if not (isinstance(checksum, str) and _SHA256.fullmatch(checksum)):
        raise AdapterError("engine_unavailable")
    return checksum, validate_identity(identity)  # never trust the child's copy


def check_available(timeout=None):
    """Before any claim: the configured adapter as a plain dict, or AdapterError (unavailable)."""
    runtime_mode.check_test_mode_config()
    test_mode = runtime_mode.is_test_mode()
    ref = os.environ.get("OCR_ADAPTER")
    if not (ref and _REF.fullmatch(ref)):
        raise AdapterError("engine_unavailable")
    entry = load_allowlist().get(ref)
    if not test_mode and (entry is None or is_test_ref(ref) or not entry["artifacts"]):
        raise AdapterError("engine_unavailable")
    checksum, identity = probe(ref, entry, timeout or AVAILABILITY_TIMEOUT)
    if identity["test_only"] and not test_mode:
        raise AdapterError("engine_unavailable")
    # version 0 is the only version implemented, and only in test mode
    if not (test_mode and INTERFACE_VERSION in identity["interface_versions"]):
        raise AdapterError("engine_unavailable")
    if entry is not None and checksum != entry["model_checksum"]:
        raise AdapterError("model_integrity_failed")
    return {"ref": ref, "entry": entry, "identity": identity, "model_checksum": checksum,
            "interface_version": INTERFACE_VERSION}


def run_attempt(config, document, doc_type):
    """OCR child, one attempt: re-check, then the adapter. Returns a validated v0 result."""
    if config["interface_version"] == 0 and not runtime_mode.is_test_mode():
        raise AdapterError("engine_unavailable")
    if manifest_checksum(config["entry"]) != config["model_checksum"]:  # before any adapter code
        raise AdapterError("model_integrity_failed")
    try:
        adapter = _load(config["ref"])
        identity = validate_identity(adapter.identity())
    except AdapterError:
        raise
    except Exception:
        raise AdapterError("engine_unavailable")
    if identity != config["identity"]:
        raise AdapterError("engine_unavailable")
    try:
        adapter.prepare()
        try:
            result = adapter.read(document)
        finally:
            adapter.release()
    except AdapterError:
        raise
    except Exception:
        raise AdapterError("engine_error")
    return validate_result(result, len(document), identity)
