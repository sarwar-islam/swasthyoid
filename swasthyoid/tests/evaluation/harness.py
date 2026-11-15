"""Evaluation harness and field-level scoring (steps 3A-harness and 9A mechanism).

Technical scoring only: it compares what a predictor returned with the synthetic ground truth and
measures nothing about clinical correctness. It runs fakes in tests; a real model's input and
output contract is not decided (D18), so a predictor here is any callable
`predictor(document) -> {"items": [{"drug": ..., "dose": ..., "frequency": ...}]}` that is given
the document's image bytes and id, never its ground truth.

Scoring unit: one (document, item position, field, value) tuple. A predicted tuple is a true
positive when the same tuple is in the ground truth. precision = TP / predicted, recall = TP /
truth, f1 = their harmonic mean (0 when either is 0, None when nothing is predicted or expected).
A predicted item may carry "confidence": {field: number}. Given a threshold, run() also reports
the confidence analysis: how many predicted values are accepted (confidence at or above it), how
many of those are wrong (the accepted-but-wrong rate), and how many are left for manual entry.
The threshold is an argument, never a default: no value is endorsed here (see D11). With a threshold it also
reports the manual-entry rate: the share of expected field slots with no accepted value (a person types them).
Whole rows: each split's score also has "rows", precision and recall of complete items (every field equal), matched
per document regardless of position.
Nothing here is a pass mark: every number is reported raw, with its counts (D11).
Results are reported per split, per field and per degradation, never as one number, and printed
and degraded results stay separate. The report is deterministic: same inputs, same bytes.
"""
import hashlib
import json
import math
from collections import Counter

FIELDS = ("drug", "dose", "frequency")


def manifest(dataset):
    """The dataset's identity: version, seed, and a hash of every document, truth and copy."""
    def digest(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True).encode("utf-8")).hexdigest()

    return {"version": dataset["version"], "seed": dataset["seed"],
            "documents": {d["id"]: {"split": d["split"], "image": d["sha256"], "truth": digest(d["truth"])}
                          for d in dataset["documents"]},
            "copies": {f"{c['document_id']}|{c['degradation']}|{c['amount']}": c["sha256"] for c in dataset["copies"]}}


def verify(dataset, expected):
    """Problems found when the dataset no longer matches a stored manifest, or breaks the split
    rules. An empty list means the ground truth and images are intact and nothing leaks."""
    problems = []
    now = manifest(dataset)
    for key in ("version", "seed"):
        if now[key] != expected[key]:
            problems.append(f"{key} changed")
    for section in ("documents", "copies"):
        for name in sorted(set(now[section]) | set(expected[section])):
            if now[section].get(name) != expected[section].get(name):
                problems.append(f"{section[:-1]} {name} changed, added or removed")
    splits = {d["id"]: d["split"] for d in dataset["documents"]}
    for copy in dataset["copies"]:
        if copy["document_id"] not in splits:
            problems.append(f"copy of unknown document {copy['document_id']}")
    if not {"development", "held_out"} <= set(splits.values()):
        problems.append("a split is empty")
    return problems


def _tuples(items, document_id):
    return {(document_id, i, field, str(item.get(field))) for i, item in enumerate(items or []) for field in FIELDS
            if field in item}


def _rates(true_positive, predicted, expected):
    precision = true_positive / predicted if predicted else None
    recall = true_positive / expected if expected else None
    if precision is None or recall is None:
        f1 = None
    else:
        f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
    return {"true_positive": true_positive, "predicted": predicted, "expected": expected,
            "precision": precision, "recall": recall, "f1": f1}


def _confidence(items, document_id, truth, threshold):
    """(accepted, accepted_wrong, manual) over one document's predicted values."""
    accepted = wrong = manual = 0
    for i, item in enumerate(items or []):
        for field in FIELDS:
            if field not in item:
                continue
            level = (item.get("confidence") or {}).get(field)
            if isinstance(level, bool) or not isinstance(level, (int, float)) or level < threshold:
                manual += 1  # no usable confidence counts as not accepted: it goes to a person
                continue
            accepted += 1
            wrong += (document_id, i, field, str(item[field])) not in truth
    return accepted, wrong, manual


def _rows(tuples):
    """Whole rows: Counter of (document, every (field, value) of one item). Position is ignored, so one missed row does
    not make every later row wrong; a row with any field missing or different is not the same row."""
    grouped = {}
    for document_id, i, field, value in tuples:
        grouped.setdefault((document_id, i), set()).add((field, value))
    return Counter((key[0], frozenset(row)) for key, row in grouped.items())


def _score(pairs):
    """pairs: [(predicted tuples, truth tuples)] -> overall, per-field and whole-row rates, plus the errors."""
    out = {"overall": None, "fields": {}, "errors": {"missed": 0, "wrong_or_extra": 0}}
    totals = {"all": [0, 0, 0], **{f: [0, 0, 0] for f in FIELDS}}
    rows = [0, 0, 0]
    for predicted, truth in pairs:
        p, e = _rows(predicted), _rows(truth)
        rows = [rows[0] + sum((p & e).values()), rows[1] + sum(p.values()), rows[2] + sum(e.values())]
        for key in totals:
            p = {t for t in predicted if key == "all" or t[2] == key}
            e = {t for t in truth if key == "all" or t[2] == key}
            totals[key][0] += len(p & e)
            totals[key][1] += len(p)
            totals[key][2] += len(e)
        out["errors"]["missed"] += len(truth - predicted)
        out["errors"]["wrong_or_extra"] += len(predicted - truth)
    out["overall"] = _rates(*totals["all"])
    out["fields"] = {f: _rates(*totals[f]) for f in FIELDS}
    out["rows"] = _rates(*rows)
    return out


def _left_for_manual_entry(items, document_id, truth, threshold):
    """How many expected field slots (document, item position, field) have no ACCEPTED predicted value: a person types
    those. An accepted wrong value is not counted here (it is pre-filled: see accepted_but_wrong)."""
    accepted = set()
    for i, item in enumerate(items or []):
        for field in FIELDS:
            level = (item.get("confidence") or {}).get(field) if field in item else None
            if not isinstance(level, bool) and isinstance(level, (int, float)) and level >= threshold:
                accepted.add((i, field))
    return sum((i, field) not in accepted for _, i, field, _ in truth)


def run(dataset, predictor, *, include_copies=True, threshold=None):
    """Run the predictor over every document (and degraded copy) and score it. The predictor sees
    the image bytes and the document id only, and is called once per image. Returns the deterministic report as a dict."""
    truth = {d["id"]: _tuples(d["truth"]["items"], d["id"]) for d in dataset["documents"]}
    split = {d["id"]: d["split"] for d in dataset["documents"]}
    items = {d["id"]: predictor({"id": d["id"], "image": d["png"]})["items"] for d in dataset["documents"]}

    def predict(png, doc_id):
        return _tuples(predictor({"id": doc_id, "image": png})["items"], doc_id)

    printed = [(d["id"], split[d["id"]], _tuples(items[d["id"]], d["id"])) for d in dataset["documents"]]
    report = {"manifest_version": dataset["version"], "seed": dataset["seed"], "printed": {}, "degraded": {}}
    for name in ("development", "held_out"):
        report["printed"][name] = _score([(p, truth[i]) for i, s, p in printed if s == name])
    if threshold is not None:
        report["confidence"] = {"threshold": threshold}
        for name in ("development", "held_out"):
            totals, expected, left = [0, 0, 0], 0, 0
            for d in dataset["documents"]:
                if split[d["id"]] == name:
                    for k, n in enumerate(_confidence(items[d["id"]], d["id"], truth[d["id"]], threshold)):
                        totals[k] += n
                    expected += len(truth[d["id"]])
                    left += _left_for_manual_entry(items[d["id"]], d["id"], truth[d["id"]], threshold)
            accepted, wrong, manual = totals
            report["confidence"][name] = {"accepted": accepted, "accepted_wrong": wrong, "manual_entry": manual,
                                          "accepted_but_wrong_rate": wrong / accepted if accepted else None,
                                          "expected_fields": expected, "left_for_manual_entry": left,
                                          "manual_entry_rate": left / expected if expected else None}
    if include_copies:
        copies = [(c, predict(c["png"], c["document_id"])) for c in dataset["copies"]]
        for kind in sorted({c["degradation"] for c, _ in copies}):
            for name in ("development", "held_out"):
                rows = [(p, truth[c["document_id"]]) for c, p in copies
                        if c["degradation"] == kind and split[c["document_id"]] == name]
                report["degraded"].setdefault(kind, {})[name] = _score(rows)
    return report


def to_json(report):
    return json.dumps(report, sort_keys=True, indent=2)


# ---- text-level OCR metrics (step 9 mechanism): CER, WER, exact match, empty and failure rates

def normalize_text(text):
    """NFC and whitespace collapsed to single spaces: the only normalisation applied before scoring.
    No script-specific folding (for example of danda forms) is done here; a protocol that needs one
    must state it. Raises ValueError for anything but text."""
    import unicodedata
    if not isinstance(text, str):
        raise ValueError("scoring needs text, not " + type(text).__name__)
    return " ".join(unicodedata.normalize("NFC", text).split())


def edit_distance(a, b):
    """Levenshtein distance between two sequences (strings for characters, lists for words)."""
    previous = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        current = [i]
        for j, y in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (x != y)))
        previous = current
    return previous[-1]


def cer(reference, hypothesis):
    """Character error rate of one pair after normalisation, or None when the reference is empty."""
    ref, hyp = normalize_text(reference), normalize_text(hypothesis)
    return edit_distance(ref, hyp) / len(ref) if ref else None


def wer(reference, hypothesis):
    """Word error rate of one pair after normalisation, or None when the reference has no words."""
    ref, hyp = normalize_text(reference).split(), normalize_text(hypothesis).split()
    return edit_distance(ref, hyp) / len(ref) if ref else None


def text_report(samples):
    """Corpus-level text metrics. Each sample is {"reference": str, "hypothesis": str or None} (None:
    the engine failed on it) and may carry "seconds" and "peak_memory_bytes", which are only reported
    when given (this module measures neither). CER and WER are micro-averaged (total edits over total
    reference length) over the samples that did not fail (an insertion against an empty reference
    counts as an edit, and the rates are None when no reference text exists); failures and empty
    outputs are counted separately, never hidden inside CER. Every rate is None for an empty corpus.
    This measures reading text against a reference, not clinical correctness."""
    total = len(samples)
    for s in samples:  # fail clearly before scoring anything
        if not (isinstance(s, dict) and isinstance(s.get("reference"), str)
                and (s.get("hypothesis") is None or isinstance(s["hypothesis"], str))):
            raise ValueError("each sample needs a text reference and a text or None hypothesis")
    failed = [s for s in samples if s["hypothesis"] is None]
    done = [s for s in samples if s["hypothesis"] is not None]
    char_edits = char_total = word_edits = word_total = exact = empty = 0
    for s in done:
        ref, hyp = normalize_text(s["reference"]), normalize_text(s["hypothesis"])
        char_edits, char_total = char_edits + edit_distance(ref, hyp), char_total + len(ref)
        word_edits += edit_distance(ref.split(), hyp.split())
        word_total += len(ref.split())
        exact += ref == hyp
        empty += hyp == ""
    seconds = [s["seconds"] for s in samples if isinstance(s.get("seconds"), (int, float))]
    memory = [s["peak_memory_bytes"] for s in samples if isinstance(s.get("peak_memory_bytes"), int)]
    return {"samples": total, "failed": len(failed),
            "failure_rate": len(failed) / total if total else None,
            "empty_output_rate": empty / len(done) if done else None,
            "exact_match_rate": exact / len(done) if done else None,
            "cer": char_edits / char_total if char_total else None,
            "wer": word_edits / word_total if word_total else None,
            "mean_seconds": sum(seconds) / len(seconds) if seconds else None,
            "max_seconds": max(seconds) if seconds else None,
            "max_peak_memory_bytes": max(memory) if memory else None}


# ---- distributions and the upload quality gate (step 9A): raw numbers only, no pass marks (D11)

def percentile(values, p):
    """Nearest-rank percentile (the smallest value with at least p% of the values at or below it), or None if empty."""
    if not values:
        return None
    if not 0 < p <= 100:
        raise ValueError("p must be in (0, 100]")
    ordered = sorted(values)
    return ordered[math.ceil(p / 100 * len(ordered)) - 1]


def latency_report(seconds):
    """p50, p95, max and mean of per-page wall-clock seconds (nearest rank), with the sample count."""
    seconds = [s for s in seconds if isinstance(s, (int, float)) and not isinstance(s, bool)]
    return {"samples": len(seconds), "p50_seconds": percentile(seconds, 50), "p95_seconds": percentile(seconds, 95),
            "max_seconds": max(seconds) if seconds else None,
            "mean_seconds": sum(seconds) / len(seconds) if seconds else None}


def _gate(pages, limits):
    from swasthyoid.capture import imaging
    reasons, refused = Counter(), 0
    for png in pages:
        found = imaging.check_measures(imaging.measure(png), limits)
        refused += bool(found)
        reasons.update(found)
    return {"pages": len(pages), "refused": refused, "refusal_rate": refused / len(pages) if pages else None,
            "reasons": dict(sorted(reasons.items()))}


def quality_gate_report(dataset, limits=None):
    """How the Phase 5 upload quality check (capture/imaging.py, provisional LIMITS unless `limits` is given) treats the
    synthetic pages. Clean pages are never meant to be refused, so their refusal rate IS the false-refusal rate. For a
    degraded copy, whether it should be refused is a policy not decided (D11), so only its refusal rate and reasons are
    reported, per degradation and amount, never called detection accuracy."""
    from swasthyoid.capture import imaging
    clean = _gate([d["png"] for d in dataset["documents"]], limits)
    report = {"limits": {**imaging.LIMITS, **(limits or {})}, "clean": {**clean, "false_refusal_rate": clean["refusal_rate"]},
              "degraded": {}}
    for kind in sorted({c["degradation"] for c in dataset["copies"]}):
        for amount in sorted({c["amount"] for c in dataset["copies"] if c["degradation"] == kind}):
            pages = [c["png"] for c in dataset["copies"] if c["degradation"] == kind and c["amount"] == amount]
            report["degraded"].setdefault(kind, {})[str(amount)] = _gate(pages, limits)
    return report
