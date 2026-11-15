"""Synthetic printed-English baseline of the configured OCR adapter (step 9A tooling). NOT the 9B evaluation and NOT a pass
or fail: no pass mark exists (D11), and every number is reported raw with its counts.

    python -m swasthyoid.tests.evaluation.ocr_baseline --out REPORT.json [--seed 0] [--patients 8] [--with-copies]

Needs test mode (APP_ENV=test and SWASTHYOID_TEST_MODE_CONFIRM=1: interface version 0 is test-only) and the adapter's own
settings, for PaddleOCR English: OCR_ADAPTER=swasthyoid.capture.adapters.paddleocr_adapter:paddleocr_en, PADDLEOCR_PYTHON,
PADDLEOCR_MODEL_DIR, PADDLEOCR_DETECTOR_DIR, the two revisions (docs/OCR_PADDLEOCR.md). oneDNN stays OFF unless
PADDLEOCR_ENABLE_MKLDNN=1 (the runner's default; the report records the setting). The adapter is used exactly as the worker
uses it: ocr.check_available() (allowlist, probe, checksum) then ocr.run_attempt() per page, one page per document.

What it reports: field-level and whole-row precision and recall, the manual-entry and accepted-but-wrong rates at the
pipeline's configured review threshold (extraction.CONFIDENCE_THRESHOLD; a review setting, not a pass mark), CER and WER
against the rendered text, per-page latency (p50, p95, max, mean; each read starts the runner, so model loading is inside
every page's time), peak memory and CPU (tests/evaluation/resources.py; what is measured depends on the platform and is
named in the report), OCR failures by code, and the Phase 5 quality gate's refusals on the same pages.

Fields come from a reader for the SYNTHETIC generator's own layout ("Drug:", "Dose:", "Frequency:" lines): test tooling for
this layout only, not the production parser (capture/parsers.py) and no clinical rule.

Not evaluated, by design (generate.PENDING): handwritten documents (D3) and Bangla (no licensed font; Jonaki access). They
are refused, never approximated. The report holds metrics, counts, synthetic document counts and the engine's identity:
no OCR text, no image, no path. It must be written OUTSIDE the repository (refused otherwise), so it is never committed.
Heavy: it runs the real model once per page. pytest never runs it with a real model (the tests use the fake runner).
"""
import argparse
import json
import os
import platform
import sys
import time
from collections import Counter
from pathlib import Path

from swasthyoid.capture import extraction, ocr
from swasthyoid.tests.evaluation import generate, harness, resources

REPOSITORY = Path(__file__).resolve().parents[3]
EXIT_OK, EXIT_UNAVAILABLE, EXIT_USAGE = 0, 1, 2


def read_layout(lines):
    """Items from (text, confidence) lines laid out like generate.render(): "Label: value", one item per "Drug:" line.
    A field's confidence is its line's recognition score; a line with no usable score gives no confidence."""
    items = []
    for text, confidence in lines:
        label, separator, value = text.partition(":")
        field, value = label.strip().casefold(), value.strip()
        if not separator or field not in harness.FIELDS or not value:
            continue
        if field == "drug" or not items or field in items[-1]:
            items.append({"confidence": {}})
        items[-1][field] = value
        if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
            items[-1]["confidence"][field] = confidence
    return items


def reference_text(truth):
    heading, item_lines = generate.page_lines(truth["document_id"], truth["items"])
    return "\n".join([heading] + [line for lines in item_lines for line in lines])


def _lines(result):
    return [(item["text"], item.get("confidence")) for page in result["pages"] for item in page["items"]]


def _out_path(raw):
    path = Path(raw).resolve()
    if path == REPOSITORY or REPOSITORY in path.parents:
        raise ValueError("out_inside_repository")
    if path.exists():
        raise ValueError("out_exists")
    if not path.parent.is_dir():
        raise ValueError("out_directory_missing")
    return path


def evaluate(config, dataset, meter, *, with_copies, threshold):
    """OCR every page once, then score. Returns the report dict (no OCR text in it)."""
    pages = [(d["id"], "printed", d["png"]) for d in dataset["documents"]]
    if with_copies:
        pages += [(c["document_id"], c["degradation"], c["png"]) for c in dataset["copies"]]
    results, seconds, cpu, failures = {}, {}, [], Counter()
    for doc_id, kind, png in pages:
        before = meter.read()["cpu_seconds"]
        started = time.perf_counter()
        try:
            result = ocr.run_attempt(config, [{"page_number": 1, "image": png, "media_type": "image/png"}], "prescription")
        except ocr.AdapterError as failure:
            result = None
            failures[failure.code] += 1
        seconds.setdefault(kind, []).append(time.perf_counter() - started)
        after = meter.read()["cpu_seconds"]
        if before is not None and after is not None:
            cpu.append(after - before)
        results[generate.sha256(png)] = (doc_id, result)

    def predictor(document):
        result = results.get(generate.sha256(document["image"]), (None, None))[1]
        return {"items": read_layout(_lines(result)) if result else []}

    truth = {d["id"]: d["truth"] for d in dataset["documents"]}
    samples = [{"reference": reference_text(truth[doc_id]),
                "hypothesis": "\n".join(text for text, _ in _lines(result)) if result else None}
               for doc_id, result in (results[d["sha256"]] for d in dataset["documents"])]
    reading = meter.read()
    return {
        "fields": harness.run(dataset, predictor, include_copies=with_copies, threshold=threshold),
        "text": harness.text_report(samples),
        "latency": {kind: harness.latency_report(values) for kind, values in sorted(seconds.items())},
        "resources": {"kind": reading["kind"], "peak_memory_bytes": reading["peak_memory_bytes"],
                      "cpu_seconds_ocr_total": sum(cpu) if cpu else None,
                      "cpu_seconds_per_page": harness.latency_report(cpu) if cpu else None},
        "failures": {"pages": len(pages), "failed": sum(failures.values()), "codes": dict(sorted(failures.items()))},
        "quality_gate": harness.quality_gate_report(dataset),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m swasthyoid.tests.evaluation.ocr_baseline")
    parser.add_argument("--out", required=True, help="report file to create, outside the repository")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--patients", type=int, default=8)
    parser.add_argument("--with-copies", action="store_true", help="also read every degraded copy (10 per document)")
    parser.add_argument("--language", default="en")
    parser.add_argument("--handwritten", action="store_true")
    args = parser.parse_args(argv)
    try:
        generate.require(args.language, args.handwritten)
    except generate.NotAvailable as pending:
        print(f"baseline: code=not_available reason={pending.args[0]!r}", file=sys.stderr)
        return EXIT_USAGE
    if args.patients < 1:
        parser.error("--patients must be at least 1")
    try:
        out = _out_path(args.out)
    except ValueError as problem:
        print(f"baseline: code={problem.args[0]}", file=sys.stderr)
        return EXIT_USAGE
    try:
        config = ocr.check_available()
    except ocr.AdapterError as failure:
        print(f"baseline: code={failure.code} stage=availability", file=sys.stderr)
        return EXIT_UNAVAILABLE
    except RuntimeError:  # APP_ENV=test without its confirmation
        print("baseline: code=test_mode_config_refused", file=sys.stderr)
        return EXIT_USAGE
    meter = resources.Meter()  # before the first OCR runner starts (the availability probe above is not measured)
    dataset = generate.build(args.seed, args.patients)
    threshold = extraction.CONFIDENCE_THRESHOLD
    report = {
        "report": "synthetic_printed_english_ocr_baseline",
        "not_a_pass_mark": "D11: no pass mark exists; every number is raw",
        "engine": {"engine_id": config["identity"]["engine_id"], "model_version": config["identity"]["model_version"],
                   "adapter_version": config["identity"].get("adapter_version"),
                   "model_checksum": config["model_checksum"], "interface_version": config["interface_version"],
                   "approved_entry": config["entry"] is not None},
        "dataset": {"generator_version": dataset["version"], "seed": dataset["seed"],
                    "documents": len(dataset["documents"]), "copies_read": len(dataset["copies"]) if args.with_copies else 0,
                    "language": "en", "printed": True, "layout_reader": "synthetic generator layout (test tooling)"},
        "settings": {"review_threshold": threshold, "paddleocr_enable_mkldnn": os.environ.get("PADDLEOCR_ENABLE_MKLDNN") == "1",
                     "platform": platform.platform(), "python": platform.python_version()},
        "not_evaluated": dict(generate.PENDING),
        **evaluate(config, dataset, meter, with_copies=args.with_copies, threshold=threshold),
    }
    with open(out, "x", encoding="utf-8") as handle:
        handle.write(harness.to_json(report) + "\n")
    held = report["fields"]["printed"]["held_out"]
    print(f"baseline: code=written pages={report['failures']['pages']} failed={report['failures']['failed']} "
          f"held_out_field_f1={held['overall']['f1']} held_out_row_recall={held['rows']['recall']}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
