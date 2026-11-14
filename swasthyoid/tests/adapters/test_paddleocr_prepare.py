"""The owner-run weights preparation script (capture/adapters/paddleocr_prepare.py), the parts that need no PaddleOCR and no
network: locating a downloaded model directory, hashing, the manifest, and the refusals. The download itself is never run
here. Synthetic files only."""
import ast
import hashlib
import json
from pathlib import Path

import pytest

from swasthyoid.capture.adapters import paddleocr_prepare as prepare

SCRIPT = Path(prepare.__file__)


def test_a_model_directory_is_found_by_name_anywhere_under_the_cache(tmp_path):
    folder = tmp_path / "official_models" / "PP-OCRv5_mobile_det"
    folder.mkdir(parents=True)
    (folder / "inference.json").write_bytes(b"synthetic")
    assert prepare.find_model_directory(tmp_path, "PP-OCRv5_mobile_det") == folder


def test_a_missing_or_ambiguous_model_directory_stops_the_script(tmp_path):
    with pytest.raises(SystemExit):
        prepare.find_model_directory(tmp_path, "PP-OCRv5_mobile_det")  # none
    for place in ("a", "b"):
        folder = tmp_path / place / "PP-OCRv5_mobile_det"
        folder.mkdir(parents=True)
        (folder / "w.bin").write_bytes(b"x")
    with pytest.raises(SystemExit):
        prepare.find_model_directory(tmp_path, "PP-OCRv5_mobile_det")  # two


def test_an_empty_directory_with_the_right_name_is_not_a_model(tmp_path):
    (tmp_path / "PP-OCRv5_mobile_det").mkdir()
    with pytest.raises(SystemExit):
        prepare.find_model_directory(tmp_path, "PP-OCRv5_mobile_det")


def test_the_manifest_lists_every_file_with_its_sha256_and_the_versions(tmp_path):
    (tmp_path / "detector" / "sub").mkdir(parents=True)
    (tmp_path / "recognizer").mkdir()
    (tmp_path / "detector" / "sub" / "w.bin").write_bytes(b"detector weights")
    (tmp_path / "recognizer" / "w.bin").write_bytes(b"recognizer weights")
    manifest = prepare.build_manifest(tmp_path, "det-name", "rec-name", {"paddleocr": "9.9", "paddlepaddle": "8.8"})
    assert manifest["files"] == [
        {"path": "detector/sub/w.bin", "sha256": hashlib.sha256(b"detector weights").hexdigest()},
        {"path": "recognizer/w.bin", "sha256": hashlib.sha256(b"recognizer weights").hexdigest()}]
    assert (manifest["detector_name"], manifest["recognizer_name"], manifest["paddleocr"]) == ("det-name", "rec-name", "9.9")
    json.dumps(manifest)  # it prints as JSON


def test_a_symbolic_link_in_a_model_directory_stops_the_manifest(tmp_path):
    (tmp_path / "detector").mkdir()
    (tmp_path / "recognizer").mkdir()
    (tmp_path / "recognizer" / "real.bin").write_bytes(b"x")
    try:
        (tmp_path / "detector" / "link.bin").symlink_to(tmp_path / "recognizer" / "real.bin")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks need extra privileges on this platform")
    with pytest.raises(SystemExit):
        prepare.build_manifest(tmp_path, "d", "r", {})


def test_a_non_empty_output_directory_is_refused_before_anything_is_downloaded(tmp_path):
    (tmp_path / "existing.txt").write_text("synthetic")
    with pytest.raises(SystemExit):
        prepare.main(["--out", str(tmp_path)])
    assert [p.name for p in tmp_path.iterdir()] == ["existing.txt"]  # nothing was added, nothing was removed


def test_the_script_imports_the_network_library_only_inside_main_and_nothing_from_the_application():
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    top = {n.module.split(".")[0] for n in tree.body if isinstance(n, ast.ImportFrom) and n.module}
    top |= {a.name.split(".")[0] for n in tree.body if isinstance(n, ast.Import) for a in n.names}
    assert "paddleocr" not in top and "swasthyoid" not in top  # importing it (as these tests do) loads no model library
    nested = [n for f in tree.body if isinstance(f, ast.FunctionDef) for n in ast.walk(f) if isinstance(n, ast.ImportFrom)]
    assert any(n.module == "paddleocr" for n in nested)


def test_nothing_in_the_application_or_its_worker_imports_the_preparation_script():
    root = SCRIPT.parents[2]
    for path in root.rglob("*.py"):
        if path.name in {"paddleocr_prepare.py", "test_paddleocr_prepare.py"}:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else                 [node.module or ""] + [a.name for a in node.names] if isinstance(node, ast.ImportFrom) else []
            assert not any("paddleocr_prepare" in n for n in names), path.name
