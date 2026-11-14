"""Step 5B wiring and 6A through the worker, with no database: the real _attempt() runs against the
fake connection of test_extraction_lease, with page reading and the engine patched.

Shows: with no operation switched on the engine gets the stored bytes unchanged; with operations on
it gets a processing copy while the stored original is untouched and nothing is written for the
copy; a page that cannot be decoded fails the attempt with a code only; the schema mechanism's
rules and required marks reach the stored fields. Synthetic data only.
"""
import hashlib
from datetime import date, timedelta

import pytest

from swasthyoid.capture import documents, extraction, imaging
from swasthyoid.tests.evaluation import generate
from swasthyoid.tests.test_extraction_lease import (READS, Conn, logged, messages,  # noqa: F401
                                                    world)

PAGE = generate.build(seed=5, patients=2)["copies"][0]["png"]  # a real, slightly rotated synthetic page


@pytest.fixture
def seen(world, monkeypatch):  # noqa: F811
    """Records the pages the engine is given and the bytes the 'storage' served."""
    record = {"engine_pages": None, "served": []}

    def read_image(conn, document_id, n):
        world.events.append(f"read {n}")
        record["served"].append(PAGE)
        return "image/png", PAGE

    def run_engine(engine, pages, doc_type, hard_timeout, heartbeat, renew):
        world.events.append("engine")
        record["engine_pages"] = pages
        return {"engine": "fake", "raw_text": "", "fields": {}}

    monkeypatch.setattr(documents, "read_image", read_image)
    monkeypatch.setattr(extraction, "_run_engine", run_engine)
    return record


def attempt(world, **options):
    world.options = extraction._settings(options)
    world.run(Conn(world.events))


def test_with_no_operation_the_engine_gets_the_stored_bytes_unchanged(world, seen):
    attempt(world)
    assert seen["engine_pages"] == [PAGE, PAGE] and all(a is b or a == b for a, b in zip(seen["engine_pages"], seen["served"]))


def test_with_operations_on_the_engine_gets_processing_copies_and_the_original_is_untouched(world, seen):
    before = hashlib.sha256(PAGE).hexdigest()
    attempt(world, preprocess=("deskew", "contrast"))
    copies = seen["engine_pages"]
    assert len(copies) == 2 and all(c != PAGE for c in copies)
    assert all(abs(imaging.measure(c)["skew"]) <= imaging.LIMITS["max_skew"] for c in copies)
    assert hashlib.sha256(PAGE).hexdigest() == before and seen["served"] == [PAGE, PAGE]
    # the copy is transient: the only statements are the ones of a normal attempt, none stores an image
    assert world.events == READS + ["renew", "begin", "engine", "fence", "store", "done"]


def test_the_default_option_is_the_module_constant_and_is_empty():
    assert extraction.PREPROCESS == () and extraction._settings({})["preprocess"] == ()


@pytest.mark.parametrize("bad", ["deskew", ("rotate",), ("deskew", "deskew"), 3, None])
def test_invalid_preprocess_options_are_refused_before_anything_is_claimed(bad):
    with pytest.raises((TypeError, ValueError)):
        extraction._settings({"preprocess": bad})


def test_a_page_that_cannot_be_decoded_fails_the_attempt_with_a_code_only(world, seen, monkeypatch, caplog):
    monkeypatch.setattr(documents, "read_image", lambda conn, d, n: ("image/png", b"SYNTHETIC-NOT-AN-IMAGE"))
    with caplog.at_level("WARNING", logger=extraction.log.name):
        attempt(world, preprocess=("deskew",))
    assert "engine" not in world.events and "store" not in world.events and "fail" in world.events
    assert "begin" not in world.events  # OCR never started: no attempt was used (lifetime budget)
    assert "SYNTHETIC-NOT-AN-IMAGE" not in caplog.text and seen["engine_pages"] is None


def test_the_originals_are_what_the_cloud_ai_path_would_receive(world, seen, monkeypatch):
    """_cloud_ai is given `pages` (the stored originals), never the processing copies."""
    given = []
    monkeypatch.setattr(extraction, "_cloud_ai", lambda conn, job, pages, *rest: given.append(pages))
    attempt(world, preprocess=("denoise",))
    assert given == [[PAGE, PAGE]]


# ---- the schema mechanism reaches the stored fields

def test_rules_and_required_marks_apply_to_what_is_stored(world, seen, monkeypatch):
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    spec = {"issued": {"kind": "date", "required": True, "rules": ["not_future"]}, "note": "text"}
    monkeypatch.setattr(extraction, "SCHEMAS", {"other": spec})
    monkeypatch.setattr(extraction, "_run_engine", lambda *a: {
        "engine": "fake", "raw_text": "", "fields": {"issued": {"value": tomorrow, "confidence": 1.0}}})
    stored = []
    monkeypatch.setattr(extraction, "_store", lambda conn, doc, version, name, fields, raw, config=None: stored.append(fields))
    attempt(world)
    (fields,) = stored
    assert fields["issued"]["value"] is None and fields["issued"]["error"] == "invalid_not_future"
    assert extraction.missing_required(spec, fields) == ["issued"]
    assert fields["note"]["manual_entry"] is True  # the optional field is left for manual entry, not required
