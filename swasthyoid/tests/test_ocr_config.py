"""capture/ocr.py without a database: validators, manifest, allowlist, the isolated probe, and the
OCR attempt entry run in-process. Interface version 0 and the fakes are test-only (D17)."""
import hashlib
import json
import os
import time
from datetime import timedelta

import pytest

from swasthyoid.capture import ocr
from swasthyoid.tests.adapters import fake_adapters

FAKE = "swasthyoid.tests.adapters.fake_adapters:"
IDENTITY = {k: v for k, v in fake_adapters.IDENTITY.items()}
EMPTY_SHA = hashlib.sha256(b"").hexdigest()


@pytest.fixture
def test_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("SWASTHYOID_TEST_MODE_CONFIRM", "1")
    for name in ("OCR_ADAPTER", "OCR_ADAPTERS_APPROVED", "OCR_TEST_BLOCK_NETWORK", "FLIP_MARKER"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("FAKE_ADAPTER_LOG", str(tmp_path / "adapter.log"))
    return tmp_path


def events(tmp_path):
    path = tmp_path / "adapter.log"
    return path.read_text(encoding="utf-8").split() if path.exists() else []


def code(excinfo):
    return excinfo.value.code


# ---- identity

def test_identity_accepts_the_documented_shape():
    assert ocr.validate_identity(IDENTITY) == IDENTITY
    without = {k: v for k, v in IDENTITY.items() if k != "adapter_version"}
    assert ocr.validate_identity(without) == without


@pytest.mark.parametrize("change", [
    {"engine_id": "Upper"}, {"engine_id": ""}, {"engine_id": "x" * 65}, {"engine_id": 7},
    {"model_version": ""}, {"model_version": "x" * 129}, {"model_version": "a\nb"},
    {"interface_versions": []}, {"interface_versions": [True]}, {"interface_versions": [-1]},
    {"interface_versions": 0}, {"test_only": 1}, {"adapter_version": ""}, {"adapter_version": "x" * 65},
    {"unknown": 1},
])
def test_identity_rejects(change):
    with pytest.raises(ocr.AdapterError) as e:
        ocr.validate_identity({**IDENTITY, **change})
    assert code(e) == "malformed_output"


def test_identity_rejects_a_missing_key_and_a_non_dict():
    for bad in ({k: v for k, v in IDENTITY.items() if k != "test_only"}, ["engine_id"], None):
        with pytest.raises(ocr.AdapterError):
            ocr.validate_identity(bad)


# ---- result, interface version 0

def result(*pages):
    return {"interface_version": 0, "engine_id": IDENTITY["engine_id"], "model_version": IDENTITY["model_version"],
            "pages": [{"page_number": n, "items": items} for n, items in enumerate(pages, 1)]}


def nested(depth):
    value = None
    for _ in range(depth - 1):
        value = [value]
    return value


@pytest.mark.parametrize("items", [
    [], [{"text": "a"}], [{"text": "a\tb"}], [{"text": "a", "confidence": None}],
    [{"text": "a", "confidence": 7.5}], [{"text": "a", "confidence": -1}],  # the range is not checked
    [{"text": "a", "position": None}], [{"text": "a", "position": {"x": [1, 2.5, "s", True, None]}}],
    [{"text": "a", "position": nested(32)}],
])
def test_result_accepts(items):
    r = result(items)
    assert ocr.validate_result(r, 1, IDENTITY) is r


@pytest.mark.parametrize("items", [
    None, "text", [None], [{}], [{"text": ""}], [{"text": "   "}], [{"text": "a\x00b"}], [{"text": "a\nb"}],
    [{"text": "\ud800"}], [{"text": 5}], [{"text": "a", "confidence": True}],
    [{"text": "a", "confidence": float("nan")}], [{"text": "a", "confidence": float("inf")}],
    [{"text": "a", "confidence": "0.9"}], [{"text": "a", "position": nested(33)}],
    [{"text": "a", "position": {1: "x"}}], [{"text": "a", "position": float("nan")}],
    [{"text": "a", "extra": 1}],
])
def test_result_rejects_malformed_items(items):
    with pytest.raises(ocr.AdapterError) as e:
        ocr.validate_result(result(items), 1, IDENTITY)
    assert code(e) == "malformed_output"


@pytest.mark.parametrize("mutate", [
    lambda r: r.update(interface_version=1), lambda r: r.update(interface_version=True),
    lambda r: r.update(engine_id="other"), lambda r: r.update(model_version="other"),
    lambda r: r.update(extra=1), lambda r: r.pop("pages"), lambda r: r["pages"].append(r["pages"][0]),
    lambda r: r["pages"][0].update(page_number=2), lambda r: r["pages"][0].update(extra=1),
    lambda r: r["pages"][0].pop("items"),
])
def test_result_rejects_malformed_structure(mutate):
    r = result([{"text": "a"}])
    mutate(r)
    with pytest.raises(ocr.AdapterError):
        ocr.validate_result(r, 1, IDENTITY)


def test_raw_text_is_test_only(test_mode, monkeypatch):
    r = result([{"text": "a"}, {"text": "b"}], [], [{"text": "c"}])
    assert ocr.raw_text_v0(r) == "a\nb\n\n\n\nc"
    monkeypatch.delenv("APP_ENV")
    with pytest.raises(ocr.AdapterError):
        ocr.raw_text_v0(r)


def test_error_codes_carry_no_message():
    assert ocr.AdapterError("not a code").code == "engine_error"
    assert str(ocr.AdapterError("model_integrity_failed")) == "model_integrity_failed"


# ---- manifest

@pytest.mark.parametrize("path", ["", "/abs", "a\\b", "C:/x", "a//b", "./a", "a/../b", "a/.", 7, None])
def test_artifact_paths_are_refused(path):
    with pytest.raises(ocr.AdapterError) as e:
        ocr.normalize_path(path)
    assert code(e) == "engine_unavailable"


def test_artifact_paths_are_nfc_normalised():
    assert ocr.normalize_path("e\u0301/b") == "\u00e9/b"


def artifacts(tmp_path, files=None):
    root = tmp_path / "model"
    for rel, data in (files or {"weights/a.bin": b"aaa", "b.json": b"{}"}).items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(data)
    return root


def entry(root, paths, checksum="0" * 64, ref=FAKE + "good"):
    return {"ref": ref, "artifact_root": str(root), "artifacts": paths, "model_checksum": checksum}


def expected(root, paths):
    lines = sorted((p.encode(), f"{p}\t{hashlib.sha256((root / p).read_bytes()).hexdigest()}\n") for p in paths)
    return hashlib.sha256("".join(line for _, line in lines).encode()).hexdigest()


def test_manifest_checksum_is_deterministic_and_order_free(test_mode):
    root = artifacts(test_mode)
    one = ocr.manifest_checksum(entry(root, ["weights/a.bin", "b.json"]))
    assert one == ocr.manifest_checksum(entry(root, ["b.json", "weights/a.bin"]))
    assert one == expected(root, ["weights/a.bin", "b.json"])
    (root / "b.json").write_bytes(b"{ }")
    assert ocr.manifest_checksum(entry(root, ["weights/a.bin", "b.json"])) != one


def test_empty_artifact_list_only_in_test_mode(test_mode, monkeypatch):
    assert ocr.manifest_checksum(None) == EMPTY_SHA
    assert ocr.manifest_checksum(entry(test_mode, [])) == EMPTY_SHA
    monkeypatch.delenv("SWASTHYOID_TEST_MODE_CONFIRM")
    for e in (None, entry(test_mode, [])):
        with pytest.raises(ocr.AdapterError) as err:
            ocr.manifest_checksum(e)
        assert code(err) == "engine_unavailable"


def symlink_or_skip(link, target, directory=False):
    try:
        os.symlink(target, link, target_is_directory=directory)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks need extra privileges on this platform")


def test_manifest_refuses_symlinks_escapes_and_non_regular_files(test_mode):
    root = artifacts(test_mode)
    outside = test_mode / "outside.bin"
    outside.write_bytes(b"x")
    symlink_or_skip(root / "link.bin", outside)
    (root / "sub").mkdir()
    symlink_or_skip(root / "dirlink", root / "sub", directory=True)
    (root / "sub" / "f.bin").write_bytes(b"f")
    for paths in (["link.bin"], ["dirlink/f.bin"], ["sub"], ["missing.bin"]):
        with pytest.raises(ocr.AdapterError) as e:
            ocr.manifest_checksum(entry(root, paths))
        assert code(e) == "model_integrity_failed", paths
    linked_root = test_mode / "linked-root"
    symlink_or_skip(linked_root, root, directory=True)
    with pytest.raises(ocr.AdapterError):
        ocr.manifest_checksum(entry(linked_root, ["b.json"]))


# ---- allowlist

def write_allowlist(tmp_path, monkeypatch, entries):
    path = tmp_path / "approved.json"
    path.write_text(json.dumps({"adapters": entries}), encoding="utf-8")
    monkeypatch.setenv("OCR_ADAPTERS_APPROVED", str(path))


@pytest.mark.parametrize("bad", [
    "not json", json.dumps({"adapters": "x"}), json.dumps({"adapters": [], "extra": 1}),
    json.dumps({"adapters": [{"ref": FAKE + "good"}]}),
])
def test_malformed_allowlist_is_unavailable(test_mode, monkeypatch, bad):
    path = test_mode / "approved.json"
    path.write_text(bad, encoding="utf-8")
    monkeypatch.setenv("OCR_ADAPTERS_APPROVED", str(path))
    with pytest.raises(ocr.AdapterError) as e:
        ocr.load_allowlist()
    assert code(e) == "engine_unavailable"


def test_allowlist_refuses_duplicates_and_bad_entries(test_mode, monkeypatch):
    root = str(test_mode)
    for entries in ([entry(root, ["a", "a"])], [entry(root, ["a"]), entry(root, ["b"])],
                    [entry("relative", ["a"])], [entry(root, ["a"], checksum="A" * 64)],
                    [entry(root, ["a"], ref="no-colon")]):
        write_allowlist(test_mode, monkeypatch, entries)
        with pytest.raises(ocr.AdapterError):
            ocr.load_allowlist()


# ---- availability: the isolated probe

def test_no_adapter_configured_is_unavailable(test_mode, monkeypatch):
    for value in (None, "", "not a reference"):
        monkeypatch.delenv("OCR_ADAPTER", raising=False) if value is None else monkeypatch.setenv("OCR_ADAPTER", value)
        with pytest.raises(ocr.AdapterError) as e:
            ocr.check_available()
        assert code(e) == "engine_unavailable"


def test_probe_reads_identity_and_never_prepares(test_mode, monkeypatch):
    monkeypatch.setenv("OCR_ADAPTER", FAKE + "good")
    config = ocr.check_available(timedelta(seconds=60))
    assert config["identity"] == IDENTITY and config["interface_version"] == 0
    assert config["model_checksum"] == EMPTY_SHA and config["entry"] is None
    assert events(test_mode) == ["identity"]  # no prepare, no read


@pytest.mark.parametrize("ref", [FAKE + "hangs_identity", "swasthyoid.tests.adapters.fake_hang_import:adapter"])
def test_a_hanging_probe_is_killed_at_the_timeout(test_mode, monkeypatch, ref):
    monkeypatch.setenv("OCR_ADAPTER", ref)
    started = time.monotonic()
    with pytest.raises(ocr.AdapterError) as e:
        ocr.check_available(timedelta(seconds=4))
    assert code(e) == "availability_timeout"
    assert time.monotonic() - started < 30


def test_probe_checks_the_artifacts_against_the_owners_list(test_mode, monkeypatch):
    root = artifacts(test_mode)
    monkeypatch.setenv("OCR_ADAPTER", FAKE + "good")
    write_allowlist(test_mode, monkeypatch, [entry(root, ["weights/a.bin", "b.json"],
                                                   checksum=expected(root, ["weights/a.bin", "b.json"]))])
    assert ocr.check_available(timedelta(seconds=60))["model_checksum"] == expected(root, ["weights/a.bin", "b.json"])
    (root / "b.json").write_bytes(b"changed")
    with pytest.raises(ocr.AdapterError) as e:
        ocr.check_available(timedelta(seconds=60))
    assert code(e) == "model_integrity_failed"


def test_outside_test_mode_a_fake_is_refused_before_any_probe(test_mode, monkeypatch):
    monkeypatch.setenv("OCR_ADAPTER", FAKE + "not_test_only")
    for unset in ("APP_ENV", "SWASTHYOID_TEST_MODE_CONFIRM"):
        monkeypatch.setenv("APP_ENV", "test")
        monkeypatch.setenv("SWASTHYOID_TEST_MODE_CONFIRM", "1")
        monkeypatch.delenv(unset)
        if unset == "SWASTHYOID_TEST_MODE_CONFIRM":
            with pytest.raises(RuntimeError):  # APP_ENV=test without confirmation fails closed
                ocr.check_available()
            continue
        root = artifacts(test_mode)
        write_allowlist(test_mode, monkeypatch, [entry(root, ["b.json"], checksum=expected(root, ["b.json"]),
                                                       ref=FAKE + "not_test_only")])
        with pytest.raises(ocr.AdapterError) as e:
            ocr.check_available(timedelta(seconds=60))
        assert code(e) == "engine_unavailable"
    assert events(test_mode) == []  # refused before any adapter code ran


def test_outside_test_mode_version_0_is_never_available(test_mode, monkeypatch):
    """Even for an adapter on the owner's list outside the test package that is not test-only:
    no interface version is implemented outside test mode (D17, D18)."""
    monkeypatch.delenv("APP_ENV")
    monkeypatch.setenv("OCR_ADAPTER", "owner_models.ocr:adapter")
    monkeypatch.setattr(ocr, "load_allowlist", lambda: {"owner_models.ocr:adapter": entry(
        test_mode, ["w.bin"], checksum="1" * 64, ref="owner_models.ocr:adapter")})
    monkeypatch.setattr(ocr, "probe", lambda ref, e, t: ("1" * 64, {**IDENTITY, "test_only": False}))
    with pytest.raises(ocr.AdapterError) as e:
        ocr.check_available()
    assert code(e) == "engine_unavailable"


# ---- the probe message protocol (M2) and the probe child's own test-mode check (L5)

class Scripted:
    """Stands in for the worker's end of the probe channel: messages, then EOF."""

    def __init__(self, *items, eof=True):
        self.items, self.eof = list(items), eof

    def poll(self, timeout):
        if self.items or self.eof:
            return True
        time.sleep(min(timeout, 0.05))
        return False

    def recv_bytes(self, maxlength):
        if not self.items:
            raise EOFError
        item = self.items.pop(0)
        if isinstance(item, BaseException):
            raise item
        data = item if isinstance(item, bytes) else json.dumps(item).encode("utf-8")
        if len(data) > maxlength:
            raise OSError("message too long")
        return data


CHECKSUM, IDENT = ["checksum", "a" * 64], ["identity", dict(IDENTITY)]


def read(conn, seconds=5):
    return ocr._read_probe(conn, time.monotonic() + seconds)


def test_probe_protocol_accepts_checksum_then_identity_then_eof():
    assert read(Scripted(CHECKSUM, IDENT)) == ("a" * 64, IDENTITY)


@pytest.mark.parametrize("messages", [
    [IDENT, CHECKSUM],                      # out of order
    [CHECKSUM, CHECKSUM, IDENT],            # duplicate checksum
    [CHECKSUM, IDENT, CHECKSUM],            # late checksum, after identity
    [CHECKSUM, IDENT, IDENT],               # late identity
    [CHECKSUM, IDENT, ["note", "x"]],       # anything after identity
    [CHECKSUM, ["note", "x"], IDENT],       # unexpected kind
    [CHECKSUM], [IDENT], [],                # incomplete, or EOF with nothing
    [b"not json"], [["checksum"]], ["checksum"],
    [CHECKSUM, IDENT, OSError()],           # channel error
    [b"x" * (ocr._PROBE_MESSAGE_MAX + 1)],  # over the size limit
])
def test_probe_protocol_refuses_anything_else(messages):
    with pytest.raises(ocr.AdapterError) as e:
        read(Scripted(*messages))
    assert code(e) == "engine_unavailable"


def test_probe_protocol_passes_a_failure_code_through():
    for messages in ([["failed", "model_integrity_failed"]], [CHECKSUM, ["failed", "malformed_output"]]):
        with pytest.raises(ocr.AdapterError) as e:
            read(Scripted(*messages))
        assert code(e) == messages[-1][1]
    with pytest.raises(ocr.AdapterError) as e:
        read(Scripted(["failed", "made up"]))
    assert code(e) == "engine_unavailable"


def test_probe_protocol_waits_for_eof_within_the_deadline():
    """A complete sequence is not accepted until the channel closes: a message could follow."""
    started = time.monotonic()
    with pytest.raises(ocr.AdapterError) as e:
        read(Scripted(CHECKSUM, IDENT, eof=False), seconds=1)
    assert code(e) == "availability_timeout" and time.monotonic() - started < 10


def test_a_forged_second_checksum_from_adapter_code_is_refused(test_mode, monkeypatch):
    monkeypatch.setenv("OCR_ADAPTER", FAKE + "extra_checksum")
    with pytest.raises(ocr.AdapterError) as e:
        ocr.check_available(timedelta(seconds=60))
    assert code(e) == "engine_unavailable"


MARKER = "swasthyoid.tests.adapters.fake_import_marker:adapter"


@pytest.mark.parametrize("unset", ["APP_ENV", "SWASTHYOID_TEST_MODE_CONFIRM"])
def test_probe_child_refuses_outside_test_mode_before_importing_adapter_code(test_mode, monkeypatch, unset):
    monkeypatch.delenv(unset)  # without APP_ENV: off; with APP_ENV=test but no confirmation: fails closed
    started = time.monotonic()
    with pytest.raises(ocr.AdapterError) as e:
        ocr.probe(MARKER, None, timedelta(seconds=30))
    assert code(e) == "engine_unavailable"  # a probe failure, not a timeout and not a success
    assert time.monotonic() - started < 25
    assert "imported" not in events(test_mode)


def test_probe_child_in_test_mode_imports_and_reports(test_mode):
    checksum, identity = ocr.probe(MARKER, None, timedelta(seconds=60))
    assert (checksum, identity) == (EMPTY_SHA, IDENTITY) and "imported" in events(test_mode)


@pytest.mark.parametrize("ref, expected", [
    ("swasthyoid.tests:x", True), ("swasthyoid.tests.adapters.fake_adapters:good", True),
    ("swasthyoid.testsuite:x", False), ("swasthyoid.tests_extra.mod:x", False), ("owner_models.ocr:adapter", False),
])
def test_test_package_references(ref, expected):
    assert ocr.is_test_ref(ref) is expected


def test_the_test_package_itself_is_refused_outside_test_mode(test_mode, monkeypatch):
    """Regression: "swasthyoid.tests:x" was not caught by the old "swasthyoid.tests." prefix."""
    monkeypatch.delenv("APP_ENV")
    ref = "swasthyoid.tests:x"
    monkeypatch.setenv("OCR_ADAPTER", ref)
    monkeypatch.setattr(ocr, "load_allowlist", lambda: {ref: entry(test_mode, ["w.bin"], checksum="1" * 64, ref=ref)})
    monkeypatch.setattr(ocr, "probe", lambda *a: pytest.fail("probed a test-package adapter outside test mode"))
    with pytest.raises(ocr.AdapterError) as e:
        ocr.check_available()
    assert code(e) == "engine_unavailable"


# ---- the OCR attempt (OCR child entry, run in-process here)

def config_for(test_mode, monkeypatch, factory="good"):
    monkeypatch.setenv("OCR_ADAPTER", FAKE + factory)
    return ocr.check_available(timedelta(seconds=60))


DOC = [{"page_number": 1, "image": b"\xff\xd8\xff page", "media_type": "image/jpeg"},
       {"page_number": 2, "image": b"\x89PNG\r\n\x1a\n page", "media_type": "image/png"}]


def test_attempt_returns_a_validated_result(test_mode, monkeypatch):
    got = ocr.run_attempt(config_for(test_mode, monkeypatch), DOC, "prescription")
    assert [p["page_number"] for p in got["pages"]] == [1, 2]
    assert events(test_mode) == ["identity", "identity", "prepare", "read", "release"]


def test_attempt_refuses_version_0_outside_test_mode_before_adapter_code(test_mode, monkeypatch):
    config = config_for(test_mode, monkeypatch)
    monkeypatch.delenv("SWASTHYOID_TEST_MODE_CONFIRM")
    with pytest.raises(ocr.AdapterError) as e:
        ocr.run_attempt(config, DOC, "prescription")
    assert code(e) == "engine_unavailable" and events(test_mode) == ["identity"]  # the probe's only


def test_attempt_rechecks_the_artifacts_before_adapter_code(test_mode, monkeypatch):
    root = artifacts(test_mode)
    write_allowlist(test_mode, monkeypatch, [entry(root, ["b.json"], checksum=expected(root, ["b.json"]))])
    config = config_for(test_mode, monkeypatch)
    (root / "b.json").write_bytes(b"swapped after the probe")
    with pytest.raises(ocr.AdapterError) as e:
        ocr.run_attempt(config, DOC, "prescription")
    assert code(e) == "model_integrity_failed" and events(test_mode) == ["identity"]


@pytest.mark.parametrize("factory, expected_code", [
    ("boom", "engine_error"), ("malformed", "malformed_output"), ("wrong_identity_in_result", "malformed_output"),
])
def test_attempt_failures_are_codes(test_mode, monkeypatch, factory, expected_code):
    with pytest.raises(ocr.AdapterError) as e:
        ocr.run_attempt(config_for(test_mode, monkeypatch, factory), DOC, "prescription")
    assert code(e) == expected_code
    assert fake_adapters.SECRET not in str(e.value)


def test_attempt_refuses_an_identity_that_changed_since_the_probe(test_mode, monkeypatch):
    marker = test_mode / "flip"
    monkeypatch.setenv("FLIP_MARKER", str(marker))
    config = config_for(test_mode, monkeypatch, "flips_identity")
    marker.write_text("x")
    with pytest.raises(ocr.AdapterError) as e:
        ocr.run_attempt(config, DOC, "prescription")
    assert code(e) == "engine_unavailable"


def test_empty_items_are_a_valid_result(test_mode, monkeypatch):
    got = ocr.run_attempt(config_for(test_mode, monkeypatch, "empty"), DOC, "prescription")
    assert [p["items"] for p in got["pages"]] == [[], []]
