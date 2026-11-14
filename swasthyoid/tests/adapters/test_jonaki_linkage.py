"""Jonaki artifact linkage: the approved-list entry must cover exactly the files in the model
directories the runner loads. Temporary directories with synthetic files; no weights, no PaddleOCR."""
import json
import os
import subprocess
import sys

import pytest

from swasthyoid.capture import ocr
from swasthyoid.capture.adapters import jonaki as module

REF = "swasthyoid.capture.adapters.jonaki:jonaki"


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "models"
    (root / "rec").mkdir(parents=True)
    (root / "det" / "sub").mkdir(parents=True)
    (root / "rec" / "weights.bin").write_bytes(b"synthetic recognizer weights")
    (root / "rec" / "config.json").write_text("{}")
    (root / "det" / "sub" / "weights.bin").write_bytes(b"synthetic detector weights")
    return root


def entry_for(root):
    return module.build_allowlist_entry(REF, root, root / "rec", root / "det")


def test_the_entry_lists_exactly_the_files_of_both_directories(tree):
    entry = entry_for(tree)
    assert entry["artifacts"] == ["det/sub/weights.bin", "rec/config.json", "rec/weights.bin"]
    assert entry["ref"] == REF and os.path.isabs(entry["artifact_root"])


def test_the_checksum_is_the_real_manifest_checksum_and_changes_with_a_file(tree):
    entry = entry_for(tree)
    assert entry["model_checksum"] == ocr.manifest_checksum(entry) != ocr.hashlib.sha256(b"").hexdigest()
    (tree / "rec" / "weights.bin").write_bytes(b"one byte different")
    assert ocr.manifest_checksum(entry) != entry["model_checksum"]


def test_an_entry_built_from_the_directories_passes_the_linkage_check(tree):
    module.check_linkage(entry_for(tree), tree / "rec", tree / "det")


def test_a_file_in_a_model_directory_that_is_not_approved_fails_the_linkage_check(tree):
    entry = entry_for(tree)
    (tree / "rec" / "extra.bin").write_bytes(b"added after approval")
    with pytest.raises(ocr.AdapterError) as failure:
        module.check_linkage(entry, tree / "rec", tree / "det")
    assert failure.value.code == "model_integrity_failed"


def test_a_directory_outside_the_artifact_root_fails_the_linkage_check(tree, tmp_path):
    other = tmp_path / "elsewhere"
    other.mkdir()
    (other / "w.bin").write_bytes(b"x")
    with pytest.raises(ocr.AdapterError) as failure:
        module.check_linkage(entry_for(tree), tree / "rec", other)
    assert failure.value.code == "model_integrity_failed"


def test_a_symlink_inside_a_model_directory_is_refused(tree):
    link = tree / "rec" / "link.bin"
    try:
        link.symlink_to(tree / "rec" / "weights.bin")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks need extra privileges on this platform")
    with pytest.raises(ocr.AdapterError) as failure:
        module.artifact_files(tree / "rec")
    assert failure.value.code == "model_integrity_failed"


# ---- the factory enforces it when an approved entry exists

@pytest.fixture
def configured(tree, tmp_path, monkeypatch):
    for name, value in {"JONAKI_PYTHON": sys.executable, "JONAKI_MODEL_DIR": str(tree / "rec"),
                        "JONAKI_DETECTOR_DIR": str(tree / "det"), "JONAKI_MODEL_REVISION": "abc123",
                        "JONAKI_DETECTOR_REVISION": "def456", "OCR_ADAPTER": REF}.items():
        monkeypatch.setenv(name, value)

    def approve(entry):
        path = tmp_path / "approved.json"
        path.write_text(json.dumps({"adapters": [entry]}), encoding="utf-8")
        monkeypatch.setenv("OCR_ADAPTERS_APPROVED", str(path))
    return approve


def test_the_factory_accepts_directories_covered_by_the_approved_entry(tree, configured):
    configured(entry_for(tree))
    assert module.jonaki().identity()["engine_id"] == "jonaki-bangla-ocr"


def test_the_factory_refuses_directories_not_covered_by_the_approved_entry(tree, configured):
    configured(entry_for(tree))
    (tree / "det" / "unapproved.bin").write_bytes(b"x")
    with pytest.raises(ocr.AdapterError) as failure:
        module.jonaki()
    assert failure.value.code == "model_integrity_failed"


def test_with_no_approved_entry_the_factory_does_not_check_linkage(tree, configured):
    assert module.jonaki().identity()["engine_id"] == "jonaki-bangla-ocr"  # test mode only: nothing ties files to a checksum


def test_the_command_line_prints_the_entry_and_only_reads(tree, tmp_path):
    before = sorted(p.name for p in tree.rglob("*"))
    done = subprocess.run([sys.executable, "-m", "swasthyoid.capture.adapters.jonaki", "--root", str(tree),
                           "--recognizer", str(tree / "rec"), "--detector", str(tree / "det")],
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    printed = json.loads(done.stdout)["adapters"][0]
    assert printed["model_checksum"] == entry_for(tree)["model_checksum"]
    assert sorted(p.name for p in tree.rglob("*")) == before


def test_the_runner_is_given_the_resolved_verified_directories(tree, configured):
    configured(entry_for(tree))
    command = module.jonaki().command
    assert command[command.index("--recognizer") + 1] == str((tree / "rec").resolve())
    assert command[command.index("--detector") + 1] == str((tree / "det").resolve())


def test_a_model_directory_that_is_itself_a_symlink_is_refused(tree, configured, monkeypatch, tmp_path):
    link = tmp_path / "linked-rec"
    try:
        link.symlink_to(tree / "rec", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks need extra privileges on this platform")
    configured(entry_for(tree))
    monkeypatch.setenv("JONAKI_MODEL_DIR", str(link))
    with pytest.raises(ocr.AdapterError) as failure:
        module.jonaki()
    assert failure.value.code == "model_integrity_failed"


def test_an_unlisted_file_added_after_approval_is_caught_even_in_a_nested_directory(tree, configured):
    configured(entry_for(tree))
    (tree / "det" / "sub" / "deeper").mkdir()
    (tree / "det" / "sub" / "deeper" / "late.bin").write_bytes(b"added later")
    with pytest.raises(ocr.AdapterError):
        module.jonaki()


def test_dot_dot_in_a_directory_path_cannot_escape_the_root(tree, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "w.bin").write_bytes(b"x")
    sneaky = tree / "rec" / ".." / ".." / "outside"
    with pytest.raises(ocr.AdapterError) as failure:
        module.check_linkage(entry_for(tree), tree / "rec", sneaky)
    assert failure.value.code == "model_integrity_failed"
