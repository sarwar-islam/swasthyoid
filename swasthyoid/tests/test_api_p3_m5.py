"""P3 over HTTP: M5 template summary, provenance validator, keyword search, and the LLM and embedding adapter contracts.

Synthetic data only. Events are appended through C4 directly (the M3 mapping is covered by B4a). The LLM and embedding
adapters here are test adapters: no model is integrated (owner question 15).
"""
from datetime import date, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from swasthyoid.capture import drugmatch
from swasthyoid.core import events_provenance
from swasthyoid.summary import adapters, build, validate
from swasthyoid.tests.test_api_b2 import cast  # noqa: F401
from swasthyoid.tests.test_api_b5 import b5  # noqa: F401
from swasthyoid.tests.test_api_b6 import consent
from swasthyoid.tests.test_api_m1 import V1, api, login, people  # noqa: F401

OTHER = "+8801700000009"
FUTURE = (date.today() + timedelta(days=30)).isoformat()


@pytest.fixture
def p3(api, b5):  # noqa: F811
    login(api, OTHER, profile={"name": "Synthetic Patient 2", "dob": "1980-01-01", "sex": "M"})
    b5.other_id = api.conn.execute("SELECT id FROM patients WHERE id <> %s", [b5.patient_id]).fetchone()[0]
    yield b5
    adapters.clear_test_adapters()


def doc(api, patient_id):
    d = uuid4()
    api.conn.execute("INSERT INTO documents (id, patient_id, doc_type, status, uploaded_by) VALUES (%s, %s, 'prescription', "
                     "'verified', %s)", [d, patient_id, patient_id])
    return d


def ev(api, patient_id, event_type, payload, day="2026-11-12", status="document_verified", supersedes=None, source=None):
    verified = status == "document_verified"
    return str(events_provenance.append(
        api.conn, patient_id=patient_id, event_type=event_type, event_date=day, date_precision="day", actor_id=patient_id,
        actor_role="patient", source_type="document" if verified else "patient", verification_status=status,
        source_document_id=(source or doc(api, patient_id)) if verified else None, verified_by=patient_id if verified else None,
        verified_at="2026-11-13T00:00:00Z" if verified else None, payload=payload, supersedes=supersedes)["id"])


def record(api, b):
    """Patient A's synthetic record, and patient B's with a shared drug name."""
    e = SimpleNamespace()
    e.source = doc(api, b.patient_id)
    e.med = ev(api, b.patient_id, "medication", {"name_as_written": "SYNTH-DRUG-001 500 mg", "dose_instruction": "1+0+1",
                                                  "duration": "7 days"}, source=e.source)
    e.old = ev(api, b.patient_id, "medication", {"name_as_written": "SYNTH-DRUG-OLD"})
    e.new = ev(api, b.patient_id, "medication", {"name_as_written": "SYNTH-DRUG-NEW ৫০০ mg"}, supersedes=e.old)
    e.allergy = ev(api, b.patient_id, "allergy", {"allergy_text": "SYNTH-ALLERGEN-01"})
    e.lab2 = ev(api, b.patient_id, "lab_result", {"test_name": "SYNTH-TEST", "result": "7.1", "unit": "u"}, day="2026-10-02")
    e.lab1 = ev(api, b.patient_id, "lab_result", {"test_name": "synth-test", "result": "6.4", "unit": "u"}, day="2026-09-01")
    e.visit = ev(api, b.patient_id, "visit", {"facility_name": "Synthetic Clinic", "admission_date": "2026-08-01"})
    e.follow = ev(api, b.patient_id, "follow_up", {"follow_up_date": FUTURE}, day=FUTURE)
    e.past = ev(api, b.patient_id, "follow_up", {"follow_up_date": "2026-01-01"}, day="2026-01-01")
    e.rx = ev(api, b.patient_id, "prescription", {"prescriber_name": "Dr. Synthetic"})
    e.pending = ev(api, b.patient_id, "medication", {"name_as_written": "SYNTH-PENDING"}, status="pending")
    e.vital = ev(api, b.patient_id, "vital_reading", {"systolic": "120", "unit": "mmHg"}, status="patient_reported")
    e.theirs = ev(api, b.other_id, "medication", {"name_as_written": "SYNTH-DRUG-001 OTHER-PATIENT"})
    return e


def summary_of(api, b):
    r = api.http.get(f"{V1}/patients/{b.patient_id}/summary", headers=b.doctor)
    assert r.status_code == 200, r.text
    return r.json()


def search(api, b, q, headers=None):
    return api.http.get(f"{V1}/patients/{b.patient_id}/search", params={"q": q}, headers=headers or b.doctor)


# ---- who may read (D1, correction 3)

@pytest.mark.parametrize("tail", ["/summary", "/search?q=synth"])
def test_only_a_doctor_with_a_timeline_consent_reads(api, p3, tail):
    url = f"{V1}/patients/{p3.patient_id}{tail}"
    for headers in (p3.patient, p3.verifier, p3.reviewer, p3.admin):
        r = api.http.get(url, headers=headers)
        assert (r.status_code, r.json()["code"]) == (403, "role_not_allowed"), r.text
    assert api.http.get(url, headers=p3.doctor).json()["code"] == "consent_required"
    consent(api, p3, ("safety",))
    assert api.http.get(url, headers=p3.doctor).json()["code"] == "category_not_allowed"
    consent(api, p3, ("timeline",))
    assert api.http.get(url, headers=p3.doctor).status_code == 200
    other = api.http.get(f"{V1}/patients/{p3.other_id}{tail}", headers=p3.doctor)  # the consent is for patient A only
    assert (other.status_code, other.json()["code"]) == (403, "consent_required")
    action = "GET /patients/{patient_id}" + tail.split("?")[0]
    assert [r[0] for r in api.conn.execute("SELECT result FROM audit_logs WHERE action = %s ORDER BY seq", [action])] == \
        ["deny", "deny", "allow", "deny"]  # C1 -> C2 for each doctor request; the four role refusals are rbac.deny
    assert api.conn.execute("SELECT count(*) FROM audit_logs WHERE action = 'rbac.deny'").fetchone()[0] == 4


def test_the_audit_never_holds_the_query(api, p3):
    consent(api, p3, ("timeline",))
    search(api, p3, "SYNTH-SECRET-WORD")
    assert "SECRET" not in str(api.conn.execute("SELECT * FROM audit_logs").fetchall())


# ---- template summary (D2, D3, D8, D10)

def test_template_summary_states_only_what_its_cited_events_hold(api, p3):
    e = record(api, p3)
    consent(api, p3, ("timeline",))
    s = summary_of(api, p3)
    assert (s["mode"], s["model_id"], s["fallback_reason"]) == ("template", None, None)
    assert [x["id"] for x in s["sections"]] == list(build.SECTION_IDS)
    sec = {x["id"]: x for x in s["sections"]}
    assert sec["diagnoses"] == {"id": "diagnoses", "note": "not_recorded", "sentences": [], "truncated": 0}  # D2
    meds = sec["medications_recorded"]["sentences"]
    assert [m["citations"] for m in meds] == [[e.new], [e.med]]  # superseded and pending left out, newest first
    assert meds[1]["text"] == "SYNTH-DRUG-001 500 mg · 1+0+1 · 7 days · 2026-11-12"  # as written, never "active" (D3)
    assert [x["citations"] for x in sec["labs"]["sentences"]] == [[e.lab1], [e.lab2]]  # one test, date order, no trend
    assert [x["citations"] for x in sec["follow_ups"]["sentences"]] == [[e.follow]]  # past date left out
    assert sec["follow_ups"]["sentences"][0]["text"] == FUTURE  # its date said once, not "date · date"
    assert [x["citations"] for x in sec["allergies"]["sentences"]] == [[e.allergy]]
    assert [x["citations"] for x in sec["visits"]["sentences"]] == [[e.visit]]
    assert [x["citations"] for x in s["patient_reported"]] == [[e.vital]]
    cited = {c for x in s["sections"] for y in x["sentences"] for c in y["citations"]}
    assert e.theirs not in cited and e.old not in cited and e.pending not in cited and e.rx not in cited
    assert "OTHER-PATIENT" not in str(s) and "active" not in str(s).lower()
    # the gate: the provenance validator passes the template over everything it may use
    events = {str(x["id"]): x for x in build.permitted_events(api.conn, p3.patient_id)}
    assert validate.validate(s, events, validate.known_names(events.values())) == []


def test_an_empty_record_has_empty_sections(api, p3):
    consent(api, p3, ("timeline",))
    s = summary_of(api, p3)
    assert all(x["sentences"] == [] for x in s["sections"]) and s["patient_reported"] == []


# ---- the provenance validator (correction 2)

def _events(api, p3):
    e = record(api, p3)
    rows = {str(x["id"]): x for x in build.permitted_events(api.conn, p3.patient_id)}
    return e, rows, validate.known_names(rows.values())


def _s(text, eid, facts):
    return {"text": text, "citations": [eid], "facts": [{"event_id": eid, "field": f, "value": v} for f, v in facts]}


def test_the_validator_rejects_every_unbacked_fact(api, p3):
    e, rows, names = _events(api, p3)
    ok = _s("Recorded SYNTH-DRUG-001 500 mg on 2026-11-12", e.med,
            [("name_as_written", "SYNTH-DRUG-001 500 mg"), ("date", "2026-11-12")])
    assert validate.check_sentence(ok, rows, names) == []
    cases = [
        (_s("Recorded SYNTH-DRUG-001 500 mg twice daily for 10 days", e.med,
            [("name_as_written", "SYNTH-DRUG-001 500 mg")]), "unbacked_number"),        # an invented duration
        (_s("Recorded SYNTH-DRUG-001 500 mg with SYNTH-DRUG-NEW ৫০০ mg", e.med,
            [("name_as_written", "SYNTH-DRUG-001 500 mg")]), "unbacked_number"),        # another event's drug, uncited
        (_s("Allergic to SYNTH-ALLERGEN-01", e.med, [("date", "2026-11-12")]), "unbacked_entity"),
        (_s("Recorded SYNTH-DRUG-002", e.med, [("name_as_written", "SYNTH-DRUG-002")]), "unsupported_fact"),
        (_s("Recorded on 2026-11-13", e.med, [("date", "2026-11-13")]), "unsupported_fact"),
        (_s("Recorded SYNTH-DRUG-001 OTHER-PATIENT", e.theirs,
            [("name_as_written", "SYNTH-DRUG-001 OTHER-PATIENT")]), "citation_not_permitted"),
        (_s("Recorded SYNTH-DRUG-OLD", e.old, [("name_as_written", "SYNTH-DRUG-OLD")]), "citation_not_permitted"),
        ({"text": "Something", "citations": [], "facts": []}, "no_citation"),
        ({"text": "Something", "citations": [e.med], "facts": []}, "unsupported_fact"),
        ({"text": "x", "citations": e.med}, "malformed"),
    ]
    for sentence, code in cases:
        assert code in validate.check_sentence(sentence, rows, names), (sentence, code)
    two = {"text": "SYNTH-DRUG-001 500 mg", "citations": [e.med, e.allergy],
           "facts": [{"event_id": e.med, "field": "name_as_written", "value": "SYNTH-DRUG-001 500 mg"}]}
    assert validate.check_sentence(two, rows, names) == ["citation_without_fact"]


def test_the_validator_knows_catalog_drugs_and_the_fixed_sections(api, p3):
    e, rows, _ = _events(api, p3)
    catalog = drugmatch.Catalog("synthetic-1", "SYNTHETIC test catalog",
                                [{"id": "S1", "generic": "synthgenerica", "brands": ["SYNTHBRAND"]}])
    names = validate.known_names(rows.values(), catalog)
    s = _s("Recorded SYNTH-DRUG-001 500 mg and synthbrand", e.med, [("name_as_written", "SYNTH-DRUG-001 500 mg")])
    assert validate.check_sentence(s, rows, names) == ["unbacked_entity"]  # a drug from nowhere
    base = {"sections": [{"id": i, "sentences": []} for i in build.SECTION_IDS]}
    assert validate.validate(base, rows, names) == []
    stated = {"sections": [{"id": i, "sentences": [_s("x", e.med, [("date", "2026-11-12")])] if i == "diagnoses" else []}
                           for i in build.SECTION_IDS]}
    assert ("diagnoses", None, "diagnosis_stated") in validate.validate(stated, rows, names)
    assert validate.validate({"sections": base["sections"][1:]}, rows, names) == [(None, None, "sections_not_fixed")]


# ---- LLM adapter contract (test adapters only, D9 / question 15)

class Llm:
    def __init__(self, make):
        self.make, self.requests = make, []

    def summarize(self, request):
        self.requests.append(request)
        return self.make(request)


@pytest.fixture
def test_mode(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("SWASTHYOID_TEST_MODE_CONFIRM", "1")
    monkeypatch.setenv("SUMMARY_LLM_ADAPTER", "synthetic-llm")


def _llm_output(request, text=None, value="SYNTH-DRUG-001 500 mg"):
    med = next(x for x in request["events"] if x["payload"].get("name_as_written") == "SYNTH-DRUG-001 500 mg")
    eid = med["event_id"]
    sentence = {"text": text or f"Recorded {value} ({med['date']})", "citations": [eid],
                "facts": [{"event_id": eid, "field": "name_as_written", "value": value},
                          {"event_id": eid, "field": "date", "value": med["date"]}]}
    return {"model_id": "synthetic-llm-0", "sections": [{"id": "medications_recorded", "sentences": [sentence]}]}


def test_a_valid_llm_summary_is_returned_with_its_model_id(api, p3, test_mode):
    e = record(api, p3)
    consent(api, p3, ("timeline",))
    llm = Llm(_llm_output)
    adapters.register_test_adapter("llm", "synthetic-llm", llm)
    s = summary_of(api, p3)
    assert (s["mode"], s["model_id"], s["fallback_reason"]) == ("llm", "synthetic-llm-0", None)
    assert [x["id"] for x in s["sections"]] == list(build.SECTION_IDS)
    assert [x["citations"] for x in s["patient_reported"]] == [[e.vital]]  # readings stay template lines
    sent = llm.requests[0]
    assert sent["interface_version"] == 1 and "diagnoses" not in sent["sections"] and sent["rules"]
    ids = {x["event_id"] for x in sent["events"]}
    assert e.med in ids and not ids & {e.theirs, e.old, e.pending, e.vital}  # permitted, verified events only


@pytest.mark.parametrize("make,reason", [
    (lambda r: _llm_output(r, text="Recorded SYNTH-DRUG-001 500 mg (2026-11-12), likely for 30 days"), "validation_failed"),
    (lambda r: _llm_output(r, value="SYNTH-DRUG-999"), "validation_failed"),
    (lambda r: {**_llm_output(r), "sections": [{"id": "diagnoses", "sentences": _llm_output(r)["sections"][0]["sentences"]}]},
     "validation_failed"),
    (lambda r: {"sections": []}, "invalid_output"),
    (lambda r: {"model_id": "m", "sections": [{"id": "prognosis", "sentences": []}]}, "invalid_output"),
    (lambda r: (_ for _ in ()).throw(RuntimeError("synthetic provider failure")), "provider_error"),
])
def test_a_failing_llm_falls_back_to_the_template(api, p3, test_mode, make, reason):
    record(api, p3)
    consent(api, p3, ("timeline",))
    adapters.register_test_adapter("llm", "synthetic-llm", Llm(make))
    s = summary_of(api, p3)
    assert (s["mode"], s["model_id"], s["fallback_reason"]) == ("template", None, reason)
    assert s["sections"][0]["sentences"]  # the template, complete


def test_adapters_are_refused_outside_test_mode(api, p3, monkeypatch):
    with pytest.raises(adapters.AdapterRefused):
        adapters.register_test_adapter("llm", "synthetic-llm", Llm(_llm_output))
    consent(api, p3, ("timeline",))
    monkeypatch.setenv("SUMMARY_LLM_ADAPTER", "anything")
    assert summary_of(api, p3)["fallback_reason"] == "no_approved_adapter"
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("SWASTHYOID_TEST_MODE_CONFIRM", "1")
    assert summary_of(api, p3)["fallback_reason"] == "adapter_not_registered"


# ---- search (D10, correction 3)

def test_search_finds_only_this_patients_current_events(api, p3):
    e = record(api, p3)
    consent(api, p3, ("timeline",))
    hits = search(api, p3, "synth-drug-001").json()
    assert [h["event_id"] for h in hits] == [e.med]  # patient B's row shares the words and is never returned
    assert hits[0] == {"event_id": e.med, "event_type": "medication", "date": "2026-11-12", "source_document_id": None,
                       "snippet": "SYNTH-DRUG-001 500 mg · 1+0+1 · 7 days", "match": "keyword"}
    assert [h["event_id"] for h in search(api, p3, "SYNTH-DRUG 500").json()] == [e.new, e.med]  # ৫০০ is 500
    assert [h["event_id"] for h in search(api, p3, "৫০০ new").json()] == [e.new]
    assert search(api, p3, "synth-drug-old").json() == []  # superseded
    assert search(api, p3, "synth-pending").json() == []    # pending
    assert [h["event_id"] for h in search(api, p3, "mmHg").json()] == [e.vital]  # a patient-reported reading
    assert search(api, p3, "name_as_written").json() == []  # keys are never searched
    assert search(api, p3, "%").json() == [] and search(api, p3, "_").json() == []  # no wildcards
    for q, code in (("", "query_required"), ("   ", "query_required"), ("x" * 201, "query_too_long")):
        r = search(api, p3, q)
        assert (r.status_code, r.json()["code"]) == (422, code)


def test_source_document_links_need_a_documents_consent(api, p3):
    e = record(api, p3)
    consent(api, p3, ("timeline", "documents"))
    assert search(api, p3, "SYNTH-DRUG-001").json()[0]["source_document_id"] == str(e.source)


class Embed:
    def __init__(self, broken=False):
        self.broken = broken

    def embed(self, texts):
        if self.broken:
            return [[1.0]]
        return [[1.0, float("ALLERGEN" in t.upper() or "ALLERGY" in t.upper())] for t in texts]


@pytest.mark.parametrize("broken", [False, True])
def test_semantic_search_uses_the_same_filters(api, p3, monkeypatch, broken):
    e = record(api, p3)
    consent(api, p3, ("timeline",))
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("SWASTHYOID_TEST_MODE_CONFIRM", "1")
    monkeypatch.setenv("SEARCH_EMBEDDING_ADAPTER", "synthetic-embed")
    adapters.register_test_adapter("embedding", "synthetic-embed", Embed(broken))
    hits = search(api, p3, "allergy").json()
    if broken:
        assert hits == []  # keyword finds nothing; a malformed adapter answer adds nothing
        return
    assert hits[0]["event_id"] == e.allergy and hits[0]["match"] == "semantic"
    assert not {h["event_id"] for h in hits} & {e.theirs, e.old, e.pending}
