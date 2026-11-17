"""M6 golden-case runner (P3; FRD M6 "Done when", 8.5).

golden/safety_synthetic.json: SYNTHETIC technical cases. Passing them shows the engine behaves as specified; it is not
clinical validation. golden/clinical/*.json: the clinician-written cases, REVIEWER-PENDING (FRD Q7); none exist, so that
test is skipped and says why. Both use the same format and runner. Every case is also run with its inputs shuffled and
reversed: the same input must always give the same output.
"""
import json
import random
from pathlib import Path

import pytest

from swasthyoid.capture import drugmatch
from swasthyoid.safety import engine

GOLDEN = Path(__file__).parent / "golden"


def load(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    return data, [pytest.param(data, c, id=c["case_id"]) for c in data["cases"]]


def run(data, case, order=lambda xs: xs):
    catalog = None if case.get("no_catalog") else drugmatch.Catalog("golden", "SYNTHETIC golden catalog",
                                                                   order(list(data["catalog"])))
    rows = order([{"id": name, **data["rules"][name]} for name in case["rules"]])
    meds = [order([tuple(x) for x in case.get(k, [])]) for k in ("prescription", "recorded", "allergies")]
    try:
        return engine.evaluate(engine.load_rules(rows), *meds, catalog)
    except engine.Blocked as b:
        return {"blocked": b.args[0]}


def check(data, case):
    got = run(data, case)
    want = case["expect"]
    if "blocked" in want:
        assert got == {"blocked": want["blocked"]}
        return got
    assert [[a["rule_version_id"], a["evidence"]] for a in got["alerts"]] == want["alerts"]
    for a in got["alerts"]:
        assert a["severity"] == data["rules"][a["rule_version_id"]]["severity"]
    assert [[u["event_id"], u["reason"], u["scope"]] for u in got["unrecognised"]] == want.get("unrecognised", [])
    assert {n["check"] for n in got["not_run"]} == {"drug_disease", "allergy_class", "duplicate_class", "class_lookback"}
    return got


SYNTHETIC, SYNTHETIC_CASES = load(GOLDEN / "safety_synthetic.json")


@pytest.mark.parametrize("data,case", SYNTHETIC_CASES)
def test_synthetic_golden_case(data, case):
    got = check(data, case)
    shuffled = random.Random(case["case_id"]).sample
    assert run(data, case, lambda xs: list(reversed(xs))) == got
    assert run(data, case, lambda xs: shuffled(xs, len(xs))) == got


def test_the_synthetic_cases_say_they_are_not_clinical_validation():
    assert "NOT clinical validation" in SYNTHETIC["notice"]
    names = [n for e in SYNTHETIC["catalog"] for n in (e["generic"], *e["brands"])]
    names += [n for r in SYNTHETIC["rules"].values() for k in ("ingredients", "allergen_terms") for n in r["definition"].get(k, [])]
    assert names and all("synth" in n.lower() for n in names)  # made-up names only


CLINICAL = sorted((GOLDEN / "clinical").glob("*.json")) if (GOLDEN / "clinical").is_dir() else []


@pytest.mark.skipif(not CLINICAL, reason="REVIEWER-PENDING: no clinician-written golden cases yet (FRD Q7)")
@pytest.mark.parametrize("path", CLINICAL, ids=[p.stem for p in CLINICAL])
def test_clinical_golden_cases(path):
    data, cases = load(path)
    for param in cases:
        check(*param.values)
