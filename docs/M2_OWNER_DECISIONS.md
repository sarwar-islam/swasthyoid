# M2 — consolidated owner decision sheet (2026-11-14)

One sheet for every open M2 decision. Nothing here is decided: each entry is a proposal for you to approve,
change or refuse, and each says exactly what the approval must contain. Independent work was finished first;
what these decisions block is isolated in the code and listed at the end. No clinical, privacy or retention
policy was invented.

## Priority order (what each unresolved decision costs while it stays open)

1. **D2 and FRD Q8 (privacy and retention).** Extracted text stays in plain form in PostgreSQL and cannot be removed
   from the append-only table: no real patient data may be processed, synthetic data only.
2. **D18 / 4B and the schema approval (OCR interface).** Interface version 0 stays test-only: no OCR adapter is
   available outside test mode, so no production extraction; per-line confidence, boxes, the preprocessing record and
   the schema version are never stored, so M3 receives no OCR confidence.
3. **D7 (clinical field list) and a named clinical reviewer (FRD Q7).** `SCHEMAS` stays empty and no parser can be
   written: every document reaches review with raw text only, never with parsed fields.
4. **D10, D12, D14 (manual entry and retry).** Slice 8.6 does not exist: no manual-entry or retry endpoint, so a
   document with no adapter waits as `uploaded` and cannot be moved to review through the API.
5. **Q4 (deployment).** No production hosting, supervisor, restart policy, poll interval or schema owner: the
   runner cannot be operated in production.
6. **D8 and FRD Q1 (drug matching and catalog).** The matcher runs only on synthetic fixtures; with no catalog every
   real drug name would be `unrecognised`, and no suggestion parameter exists.
7. **External model: access, license, detector, provenance, data.** Real Jonaki never runs, so no OCR accuracy of
   any kind exists and the real runner stays unexecuted.
8. **D5, D6, D11 (upload quality policy, EXIF, pass marks).** Imaging limits stay provisional and unused by upload;
   no retake policy and no confidence threshold.
9. **Residual risks (section 7), D13 alert mechanism (section 5), D3 handwritten set (Cross-cutting).** Each stays as described in that section.

## 1. Privacy

### D2 — extracted text at rest
- **Question.** May `extractions.raw_text` and `extractions.fields` be encrypted at field level with a key
  outside the database, and may `raw_text` be removed from the append-only table after a document is verified
  or rejected?
- **Why.** Today the OCR text is stored in plain form (`docs/DECISIONS.md`, "Privacy risk"). Anyone with database
  access, a backup or a query log can read it; the original images are already encrypted on disk.
- **Options.** (a) Encrypt `fields` and `raw_text` (same approach as phone and name). (b) (a) plus move `raw_text` to
  a deletable store, keeping only its hash in the append-only row. (c) Keep plain text, rely on database
  encryption at rest and role restrictions.
- **Consequences.** (a) and (b) make extracted text unsearchable in SQL (nothing in M2 needs it) and need a key
  management decision. (b) changes what the ERD stores and needs a lawyer's view on retention (FRD Q8). (c) leaves
  the exposure described above.
- **Recommended.** (b); until approved, synthetic data only.
- **Approval needed.** "D2: approve (a)/(b)/(c); retention after verification or rejection is <rule from FRD Q8>;
  the key is held in <store>."

### Q4 — deployment
- **Question.** Where does the worker run, who supervises and restarts it, what is the poll interval, who applies
  the schema, and are storage reads time-limited?
- **Why.** The runner exits on connection loss and relies on a supervisor to restart it; schema application is
  still done by the API at startup; no poll interval default exists.
- **Options.** A process supervisor (systemd or container restart policy) with the API applying the schema;
  or a scheduler running `--once`.
- **Consequences.** Without it, no production run and no restart after a crash.
- **Recommended.** Supervisor plus `EXTRACTION_POLL_SECONDS` set by the operator; schema stays with the API.
- **Approval needed.** Hosting, supervisor, interval value, schema owner.

## 2. Clinical extraction

### D7 — clinical field list (step 6B)
- **Question.** Which fields does each document type (prescription, laboratory report, discharge summary) have,
  which are required, and what are the validation and ambiguity rules?
- **Why.** `SCHEMAS` is empty by design; parsers cannot be written without it. The mechanism (kinds, required marks,
  technical rules, `missing_required`) is done and tested.
- **Options.** Approve the proposed list recorded in `docs/DECISIONS.md`, amended by the clinical reviewer.
- **Consequences.** Until then every document goes to review with raw text only.
- **Recommended.** Approve together with a named clinical reviewer (FRD Q7).
- **Approval needed.** The signed list: field names, kinds, required marks, rules, and answers to the five open
  questions in the "Questions for the reviewer" section of the proposed list in `docs/DECISIONS.md`; the
  reviewer's name.

## 3. Drug matching

### D8 and FRD Q1 — matching rule and catalog
- **Question.** What counts as "similar" for a suggestion, how many suggestions are shown, may a top suggestion ever
  be pre-selected, and which catalog (source, version, license) is used?
- **Why.** `capture/drugmatch.py` is finished and catalog-independent: it never selects a drug, never infers a
  strength or form, and reports multiple entries or a conflicting strength or form as ambiguous. Its two similarity
  parameters (`suggestion_floor`, `max_suggestions`) deliberately have no defaults.
- **Options.** For the parameters: values proposed by the clinical reviewer after measuring on the approved catalog.
  For pre-selection: never (recommended).
- **Consequences.** Without them only exact names match and everything else is "unrecognised", kept verbatim.
- **Recommended.** No pre-selection; reviewer-set parameters.
- **Approval needed.** The two values, the pre-selection rule, the catalog name, version, source and license.

## 4. API behavior (slice 8.6, manual entry and retry)

Blocked together; nothing was implemented. The proposed design is in `docs/DECISIONS.md` ("No OCR adapter
available ... Proposed design"): one endpoint moving a document to `needs_review` with empty fields from `uploaded`,
from `extracting` with no live claim, or from `extraction_failed`; 409 `extraction_in_progress` while a live claim
is held; one transaction; audit entry `document.manual_entry`; and an endpoint for the existing retry path.

- **D10 — who may start manual entry or a retry.** Options: patient only; patient and caregiver; plus verifiers
  (waits on FRD Q3). Recommended: patient only, like viewing the extraction. Approval: the allowed roles.
- **D12 — manual entry while an adapter is configured.** Options: always allowed; only when no adapter is available.
  Recommended: always allowed (the patient's choice). Approval: yes or no.
- **D14 — audit 409 refusals.** Options: audit them; do not (authorization denials are already audited by the
  gateway chain). Recommended: do not. Approval: yes or no.
- **Consequences.** Until approved, manual entry and retry exist only as the functions `manual_entry()` and `requeue()` in
  `capture/extraction.py` (no endpoints, no actor, no claim check, no audit entry); a document with no adapter stays `uploaded`.

## 5. OCR interface (D18, 4B)

### Final interface and persistence
- **Question.** What is interface version 1, and which of its fields are persisted?
- **Why.** Interface version 0 is test-only and validates, then discards, per-line confidence and boxes. Persisting
  them needs a schema change. Also not persisted today: the preprocessing operations applied and the schema
  version of an extraction.
- **Migration proposal (not applied).** Add nullable columns to `extractions`: `line_meta JSONB` (per page and line:
  confidence and box, no text) and `processing JSONB` (preprocessing operations, schema version, adapter timings).
  Nullable and additive, so existing rows and the append-only rule are unaffected; `IF NOT EXISTS` for the runner's
  read-only schema check, which would list the new columns only after approval.
- **Options.** (a) Approve the two columns. (b) Persist nothing beyond version 0. (c) A separate table for lines.
- **Consequences.** (b) keeps M3 without confidence, so the "left for manual entry under 0.85" rule cannot use real
  OCR confidence. (c) is heavier and stores more patient-derived data.
- **Recommended.** (a), with the model specification and the meaning of confidence from your own model (D4).
- **Approval needed.** The column list, what confidence means, and 4B (compatibility review) before any production
  adapter is allowed outside test mode.

### D13 — alert when the adapter is unavailable
- **Question.** How are operators alerted when the adapter fails its checks (no claim, documents stay due)?
- **Recommended.** Keep the queue-length counter and add the alert the supervisor already offers.
- **Approval needed.** The mechanism.

## 6. External model (Jonaki, temporary)

- **Hugging Face access.** The weights are gated; the author reviews every request. Needed: your account requests
  access. Nothing was downloaded or bypassed.
- **License (CC BY-NC 4.0).** Non-commercial only; commercial use needs the author's license. Needed: your decision
  that the intended use is non-commercial, or a commercial license. Not decided here.
- **Detector.** `PP-OCRv6_medium_det` must be provisioned by a person; its license was not reviewed. Needed: the
  source, revision, license.
- **Provenance.** Needed: the Hugging Face commit hashes and an `OCR_ADAPTERS_APPROVED` entry for the exact files
  (`python -m swasthyoid.capture.adapters.jonaki --root ... --recognizer ... --detector ...` prints one for your review).
  The adapter then refuses model directories that are not fully covered by the entry.
- **Evaluation data.** No permitted Bengali sample images exist (no licensed Bangla font; the generator is
  English-only). Needed: a permitted dataset with source, license and ground truth, or approval of a font.

## 7. Residual risks (unresolved: proposed limitations, NOT approved)

None of these has been approved by the owner as an accepted limit for the Jonaki check (R2 has a related 4A record, quoted there). Each needs: accept as stated, or mitigate.

- **R1, time of check versus time of use.** Files in the model directories can change after `check_linkage` and the
  manifest checksum and before the runner reads them. (Proposed mitigation: run the runner from a private, read-only
  copy hashed after copying. Cost: disk space and a copy step.)
- **R2, hard links.** A hard link is not detected inside a model directory. For the 4A artifact check the owner recorded
  "hard links accepted as a documented limitation" (`docs/DECISIONS.md`, "Owner decisions applied", 2026-11-12). That
  record does not mention the Jonaki directory check, so whether it also covers that check is not decided.
- **R3, network.** The offline library settings do not block network access. (Proposed mitigation: an operating-system
  level block for the runner, for example a network namespace or firewall rule; deployment-specific, so part of Q4.)
- **R4, files the runner reads outside the verified directories.** PaddleOCR may read its own cache under `HOME`, which
  the allowlist passes through. Unverified until a real execution; cannot be tested without the weights.
- **R5, unit case-folding.** Strength units are case-folded (`MG` equals `mg`) in the drug matcher.
- **R6, unexecuted checks.** Two symlink tests (`test_jonaki_linkage.py`) and the real runner have never executed.

## Linux CI verification requirements (for the current uncommitted code; nothing is pushed or triggered)

- **Prerequisite.** Your authorization to commit and push (code and docs as separate commits, as before).
- **Expected result on `ubuntu-latest`, Python 3.12, `postgres:16`:** **907 passed, 0 skipped, 0 failed** (897 passed
  and 10 skipped locally; on Linux the 7 Linux-only process tests and the 3 symlink tests run). 907 = 812 (run #41) + 95 new
  tests (36 drug matcher, 14 linkage, 37 privacy guards, 8 harness).
- **Read from the log:** the pytest summary line from the expanded `Run pytest -q` step (not the page header), a
  fresh fetch of the run status (the Actions pages lag), and that skipped is 0.
- **New tests that have never run on any machine, watch these first:** the two symlink tests in
  `swasthyoid/tests/adapters/test_jonaki_linkage.py`; a failure there would be a real defect in the symlink handling.
- **Linux-only tests that must still pass** (they passed in #38, #39, #40, #41): first and second SIGTERM, SIGKILL
  recovery, connection-close after kill, the three process-group kill tests, `WorkerDied` timing.
- **Not verified by CI whatever the result:** the real PaddleOCR runner, real weights, accuracy, R1 to R5.
- **Flakiness.** One green run does not rule out timing flakiness; the process tests passed in four earlier runs.

## Cross-cutting

- **D3 (handwritten set, plan step 3B).** Who writes the handwritten set and how many. Not built; no proposal is
  made here. Until decided, no handwritten evaluation data exists.

- **D11** pass marks (confidence thresholds, image-quality limits): none are set; the harness takes any threshold as
  an argument. **D5/D6** retake policy and EXIF handling: imaging limits are provisional and not wired into upload.
- **Schema.** Everything above that needs a column waits for your approval; nothing was migrated.

---

# M2 completion status (2026-11-14; local runs on Windows: 897 passed, 10 skipped, 0 failed with PostgreSQL; CI #41 on Linux: 812 passed, before this batch)

| M2 component | Implementation | Tests | Approval | Status |
|---|---|---|---|---|
| Capture and image processing | upload, storage, `imaging` measures, `process()`, `preprocess` option | DB-free and PostgreSQL | limits provisional (D5, D6, D11) | IMPLEMENTED AND TESTED (upload checks not wired: BLOCKED BY OWNER DECISION) |
| Extraction privacy | secret allowlist, no temp files, constant log messages, original untouched, guards | static guards, PostgreSQL | D2, Q4 open | IMPLEMENTED AND TESTED for what is enforced; plain-text storage BLOCKED BY OWNER DECISION |
| OCR infrastructure | adapter contract v0, probe, child, Jonaki adapter and linkage | adapter, worker, process tests | v0 test-only; D18, 4B open | IMPLEMENTED AND TESTED (fake runner); final interface BLOCKED BY OWNER DECISION |
| Real OCR execution | real runner written, never run | none | access, license | BLOCKED BY EXTERNAL ACCESS/LICENSE |
| Clinical schemas | mechanism (kinds, required, technical rules) | DB-free | field list (D7) | IMPLEMENTED AND TESTED; field list BLOCKED BY OWNER DECISION |
| Clinical parsers | none | none | D7 | BLOCKED BY OWNER DECISION |
| Drug catalog matching | catalog-independent matcher | DB-free | D8, FRD Q1 | IMPLEMENTED AND TESTED (synthetic fixture); real catalog BLOCKED BY OWNER DECISION |
| Worker reliability | runner: `--once`, loop, signals, recovery | DB-free, PostgreSQL, Linux CI | Q4 for deployment | IMPLEMENTED AND TESTED (CI #41) |
| Manual entry | none (design proposed) | none | D10, D12, D14 | BLOCKED BY OWNER DECISION |
| Retry endpoints | none (retry path exists in code) | worker retry tests | D10 | BLOCKED BY OWNER DECISION |
| Provenance | engine id, model version, checksum, adapter and interface versions | PostgreSQL | confidence, boxes, preprocessing not persisted: schema approval | IMPLEMENTED AND TESTED for what v0 stores |
| Evaluation harness | field scoring, integrity, confidence analysis, CER, WER, failure and empty rates | DB-free | no threshold approved | IMPLEMENTED AND TESTED |
| Real OCR evaluation | none | none | data, model | BLOCKED BY EXTERNAL ACCESS/LICENSE |

**M2 is not complete.** All independent work is done; the blocked rows above need the decisions in this sheet or
external access.
