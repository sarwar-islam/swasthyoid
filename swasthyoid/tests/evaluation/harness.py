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
The threshold is an argument, never a default: no value is endorsed here (see D11).
Results are reported per split, per field and per degradation, never as one number, and printed
and degraded results stay separate. The report is deterministic: same inputs, same bytes.
"""
import hashlib
import json

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


def _score(pairs):
    """pairs: [(predicted tuples, truth tuples)] -> overall and per-field rates, plus the errors."""
    out = {"overall": None, "fields": {}, "errors": {"missed": 0, "wrong_or_extra": 0}}
    totals = {"all": [0, 0, 0], **{f: [0, 0, 0] for f in FIELDS}}
    for predicted, truth in pairs:
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
    return out


def run(dataset, predictor, *, include_copies=True, threshold=None):
    """Run the predictor over every document (and degraded copy) and score it. The predictor sees
    the image bytes and the document id only. Returns the deterministic report as a dict."""
    truth = {d["id"]: _tuples(d["truth"]["items"], d["id"]) for d in dataset["documents"]}
    split = {d["id"]: d["split"] for d in dataset["documents"]}

    def predict(png, doc_id):
        return _tuples(predictor({"id": doc_id, "image": png})["items"], doc_id)

    printed = [(d["id"], split[d["id"]], predict(d["png"], d["id"])) for d in dataset["documents"]]
    report = {"manifest_version": dataset["version"], "seed": dataset["seed"], "printed": {}, "degraded": {}}
    for name in ("development", "held_out"):
        report["printed"][name] = _score([(p, truth[i]) for i, s, p in printed if s == name])
    if threshold is not None:
        report["confidence"] = {"threshold": threshold}
        for name in ("development", "held_out"):
            totals = [0, 0, 0]
            for d in dataset["documents"]:
                if split[d["id"]] == name:
                    items = predictor({"id": d["id"], "image": d["png"]})["items"]
                    for k, n in enumerate(_confidence(items, d["id"], truth[d["id"]], threshold)):
                        totals[k] += n
            accepted, wrong, manual = totals
            report["confidence"][name] = {"accepted": accepted, "accepted_wrong": wrong, "manual_entry": manual,
                                          "accepted_but_wrong_rate": wrong / accepted if accepted else None}
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
