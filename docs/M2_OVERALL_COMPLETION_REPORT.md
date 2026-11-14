# M2 (Capture and Extraction): overall completion report

Date: 2026-11-14. Branch `main`, equal to `origin/main` at `7ad9855`; **everything described as "this campaign" is in the
working tree, uncommitted, not pushed, and has had no CI run.** Implementation status and approval status are kept apart
throughout. Terms: IMPLEMENTED (code exists), TESTED (a test ran and passed), BLOCKED (cannot proceed without a named
dependency), NOT IMPLEMENTED, OUT OF SCOPE.

## 1. Executive summary

All M2 work that can be done without a missing owner decision, clinical sign-off, external access or the owner's model is
implemented and tested locally. The owner's decisions of 2026-11-14 (D7 field list, slice 8.6 manual entry and retry, D2
extracted-text encryption and retention, Q4 deployment) were implemented in that order. **M2 is not complete and not
production-ready:** the clinical reviewer has not been named, interface version 0 is test-only (no OCR adapter is available
outside test mode), the real Jonaki runner and weights have never been executed, drug matching has no catalog, the
reviewer's vocabularies for splitting medication and test rows are missing, and this campaign has not been through CI.

Evidence: **992 passed, 0 failed, 10 skipped** (Windows, disposable PostgreSQL); **688 passed, 0 failed, 314 skipped**
without a database. The 10 skips are platform-bound and explained in section 12.

## 2. Original M2 scope and status

From `docs/M2_COMPLETION_PLAN.md`:

| Step | Scope | Implementation | Approval / blocker |
|---|---|---|---|
| 1 | Worker reliability | IMPLEMENTED, TESTED (CI #42) | owner-complete since 2026-11-12 |
| 2 | Extraction privacy | IMPLEMENTED, TESTED locally (this campaign) | D2, Q8, Q4 approved 2026-11-14; no lawyer's view recorded |
| 3 | Synthetic dataset and evaluation harness | IMPLEMENTED, TESTED (generator, harness, CER/WER, confidence analysis) | handwritten set (3B) BLOCKED on D3; no Bangla font |
| 4 | OCR infrastructure (4A) and owner model (4B) | 4A IMPLEMENTED, TESTED; Jonaki adapter infrastructure IMPLEMENTED, TESTED with a fake runner | 4B, D18 BLOCKED (owner's model and specification); real Jonaki BLOCKED (gated access, CC BY-NC 4.0) |
| 5 | Image checks and pre-processing | 5A measures and `process()` IMPLEMENTED, TESTED; `preprocess` worker option off by default | upload refusal BLOCKED (D5, D6, D11) |
| 6 | Clinical schemas and parsers | 6A mechanism, the approved field list and transcription parsers IMPLEMENTED, TESTED locally | **clinical reviewer not named (FRD Q7); row splitting BLOCKED (reviewer vocabularies)** |
| 7 | Drug matching | catalog-independent matcher IMPLEMENTED, TESTED on synthetic fixtures; not wired into extraction | BLOCKED (D8, FRD Q1: no catalog, no suggestion parameters) |
| 8 | Runner, endpoints, audit (8.1 to 8.6) | IMPLEMENTED, TESTED (8.1 to 8.5 in CI #42; 8.6 locally) | Q4 approved; provider, supervisor product, interval value open |
| 9 | Accuracy evaluation | harness IMPLEMENTED, TESTED | real evaluation BLOCKED (no model run, no permitted Bengali data) |

## 3. Tasks that were uncompleted at the start of this campaign, and their final status

| Task | Final status |
|---|---|
| D7 schemas and parsers | IMPLEMENTED, TESTED; reviewer sign-off pending; row splitting BLOCKED |
| Slice 8.6 manual-entry and retry endpoints | IMPLEMENTED, TESTED locally |
| D2 encryption, raw-text store, retention | IMPLEMENTED, TESTED locally |
| Q4 deployment work (key check at startup, deployment guide) | IMPLEMENTED, TESTED; guide's systemd template untested on a server |
| Integration, privacy, error-handling regression | DONE (section 6); two hardening additions found in the final audit |
| Drug matching wired into extraction | BLOCKED (D8, FRD Q1) |
| Final OCR interface and persistence of confidence and boxes | BLOCKED (D18, 4B, schema approval; a migration proposal is in `docs/M2_OWNER_DECISIONS.md`) |
| Real Jonaki execution, OCR accuracy | BLOCKED (gated access, license decision, detector weights, no permitted Bengali data) |
| Clinical reviewer identity and sign-off | BLOCKED (name not supplied); not invented |
| CI verification of this campaign | NOT DONE |

## 4. Approved owner decisions and how each was implemented

| Decision (2026-11-14) | Implementation |
|---|---|
| D2 (b): encrypt `fields`; raw text in a deletable encrypted store with only its hash in the append-only row | `capture/extraction_crypto.py`; `fields` stored as `{"v":1,"enc":<Fernet token>}`; token in new table `extraction_raw_texts`; `extractions.raw_text` stays `''`; new column `raw_text_sha256` |
| Q8: delete raw text at verification or rejection | database trigger `extraction_raw_texts_retention` on `documents`: deletes the rows when status becomes `verified` or `rejected`, for every writer |
| Key `EXTRACTION_KEY` (environment-held Fernet) | validated by the API at startup, by `run_due`/`extract` before any claim, and by the runner at startup (exit 2); wrong key fails closed (`Undecryptable`, API 500 `extraction_unreadable`) |
| Q4: supervisor, `EXTRACTION_POLL_SECONDS`, migrations stay with the API | schema applied only by the API (additive, idempotent); runner checks the schema read-only; `docs/DEPLOYMENT.md` |
| D10: patient only | `require("patient")` on both endpoints; staff roles get 403 (audited by the gateway chain); other patients 404 |
| D12: manual entry always allowed | allowed from `uploaded`, `extracting` without a live claim, `extraction_failed`, also with an adapter configured |
| D14: no audit of 409; audit successes | conflicts raise before any write; `document.manual_entry` and `document.retry` written in the same transaction |
| Retry cap 5 | `MAX_RETRIES = 5`, counted from the audit entries of successful retries (no column); **owner-approved Option A**: 1 initial run + 5 patient-triggered retries, each run with up to 3 automatic attempts, so at most 18 claimed attempts (`MAX_TOTAL_ATTEMPTS`, a documented bound); 6th retry gives 409 `retry_limit_reached`; manual entry stays possible |
| D7: approved field list, no required fields, `printed_patient_name`, `allergy_text` | `SCHEMAS` equals `tests/approved_fields.py`; all optional; `allergy_text` on prescription and discharge summary and `printed_patient_name` on all three (placement chosen where the approval was silent) |
| D7 Q4: `diagnosis_text` never promoted | no code outside the extraction modules may name it (guard test); no event is created by any extraction path (asserted by tests) |
| D7 Q5: dose and duration free text | stay text fields, never split |
| D7 Q2: printed name as encrypted mismatch flag | stored sealed; `latest()` returns an advisory `printed_name_check`; never blocks anything |

## 5. Files and migrations

**Created (10):** `capture/extraction_crypto.py`, `capture/parsers.py`, `docs/DEPLOYMENT.md`, `docs/M2_OVERALL_COMPLETION_REPORT.md`,
`tests/approved_fields.py`, `tests/test_parsers.py`, `tests/test_parsers_e2e.py`, `tests/test_manual_entry_retry.py`,
`tests/test_extraction_crypto.py`, `tests/test_extraction_privacy_pg.py`.

**Modified (20):** docs `DECISIONS.md`, `M2_COMPLETION_PLAN.md`, `M2_OWNER_DECISIONS.md`, `SESSION_HANDOFF.md`; code `api/deps.py`,
`api/documents.py`, `capture/documents.py`, `capture/extraction.py`, `capture/schema.sql`, `workers/extract.py`; tests
`adapters/fake_adapters.py`, `adapters/test_ocr_conformance.py`, `conftest.py`, `test_documents.py`, `test_extraction.py`,
`test_extraction_integration.py`, `test_jonaki_worker.py`, `test_m2_end_to_end.py`, `test_runner_startup.py`,
`test_schema_mechanism.py`. Untouched: M3, M4 (`verification`, `timeline`, `safety`), `core/`, `identity/`, `pyproject.toml`,
workflows, `.claude/`.

**Migration** (`capture/schema.sql`, additive and idempotent, applied by the API): column `extractions.raw_text_sha256` with a
CHECK; table `extraction_raw_texts` (extraction id, document id, ciphertext, created_at) with an index; function and
trigger `extraction_raw_texts_retention`. Nothing was altered or dropped; existing rows are untouched.

## 6. Architecture and integration changes

- `documents.TRANSITIONS` gained `uploaded -> needs_review` (the patient's manual entry). The older narrow `manual_entry()`
  keeps its contract; `start_manual_entry` and `retry_extraction` are the patient flow.
- The worker's OCR path now builds fields with `parsers.parse` (confidence = lowest of the source lines' confidences) and
  stores them sealed; `latest()` is the single decrypting reader (tests that read tables directly now use it).
- The runner requires `EXTRACTION_KEY` (exit 2, before connecting, after the test-mode safety check) and lists the new
  column and table in its schema inventory.
- Hardening found in the final audit: retention moved into the database (so M3 or any future writer cannot skip it) and a
  controlled API error for an unreadable extraction.

## 7. Security, privacy, encryption and data lifecycle

**Technically enforced and tested:** no table holds extracted text or field values in plain form (a test scans every row of
every table); the append-only row keeps only the raw text's SHA-256; raw-text rows are deleted at verification or rejection by
a database trigger; the key is required at API start, before any claim and at runner start; a wrong key fails closed with no
content; the runner child gets an allowlisted environment; no temporary files, no traceback or exception-value logging, no
file writes outside the encrypted store (static guards); originals are byte-identical after extraction; no event is ever
created by extraction.

**Only requested from libraries, not enforced:** the Jonaki runner's offline settings (they do not block the network).

**Needs policy or was not shown:** a lawyer's view on the retention rule (not recorded); key rotation (none); who holds the key
in operations; backup handling of the key; protection against a compromised application host (the key is in its environment).

**Residual limits:** rows written before D2 stay plain (the table is append-only); the existing idempotency store keeps the
response of a manual-entry call, which holds only a blank manual extraction; `printed_name_check` compares only after NFC,
case-folding and collapsed spaces; `SCHEMA_VERSION` is not stored per extraction (needs a column).

## 8. Clinical safety boundaries and remaining reviewer requirements

AI/OCR output stays an unverified candidate: M2 never creates a verified event (event counts asserted 0 in tests). Fields are
transcriptions; ambiguous or conflicting readings stay empty; invalid values are never accepted whatever their confidence;
low or missing confidence goes to manual entry. **Still required from the clinical reviewer:** name and sign-off (FRD Q7);
vocabularies (units, forms, frequencies) so medication and test rows can be split; reviewed non-English label lists (Bangla
labels were deliberately not guessed); the matching rule and catalog for drugs (D8); required-field marks for M3's confirm
step. Confidence meaning is open until D18; nothing here treats an OCR confidence as clinical correctness.

## 9. OCR and Jonaki: executed versus not executed

**Executed:** the adapter contract, probe, OCR child, reading order, artifact linkage, environment allowlist and fail-closed
behavior, using a **fake runner** speaking the real runner's JSON protocol (CI #41, #42 and local runs). **Not executed, ever:** the
real PaddleOCR runner (`jonaki_runner.py`), the Jonaki weights, the PP-OCRv6 detector, any inference, any Bengali recognition,
any accuracy figure. Blockers: gated access (the author reviews each request), CC BY-NC 4.0 (owner's decision on
non-commercial use), detector weights and license, permitted Bengali sample images, and interface v0 being test-only
(D18, 4B). Nothing was downloaded or bypassed.

## 10. Test commands and results

| Command | Result |
|---|---|
| `python -m pytest -q` (no `DATABASE_URL`), `.venv` Python 3.12.11 | **688 passed, 0 failed, 314 skipped**, 1 warning, 125.55 s |
| `DATABASE_URL=<disposable pgserver> python -m pytest -q -rs` | **992 passed, 0 failed, 10 skipped**, 1 warning, 607.19 s |
| `python -m compileall -q swasthyoid` | clean |
| pyflakes (throwaway venv, since removed) | one pre-existing unused variable (`capture/documents.py:55`); the rest is the repository's deliberate pytest-fixture import pattern |
| `git diff --check` | clean |

1002 tests in all when those two runs were made (992 + 10 = 688 + 314). The retry-boundary test (Option A: 18 attempts) was added afterwards, so the suite is now **1003 tests**: without a database 688 passed, 315 skipped (179 s); the retry, extraction and privacy tests including the new one passed on a disposable PostgreSQL (201 passed, 0 failed); the full PostgreSQL run was not repeated for one added test. The one warning is the existing `httpx` deprecation. Last CI run (#42, Linux,
PostgreSQL 16, before this campaign): **907 passed, 0 skipped**, summary line supplied by the owner. **This campaign has not
been through CI.**

New tests this campaign (84): parsers 31, parser end-to-end 4, manual entry and retry 21, crypto 12, PostgreSQL privacy 16.
About a dozen existing tests were changed where the approved behavior changed (an empty field list became the approved list;
raw text and fields are read through the decrypting reader; `uploaded -> needs_review` is legal; a TRUNCATE must name both
extraction tables; the runner's missing-table list includes the new table).

## 11. Counts

Passed 992, failed 0, skipped 10, warnings 1 (PostgreSQL run). Passed 688, failed 0, skipped 314, warnings 1 (no database).

## 12. Platform coverage and limitations

All local runs are Windows. The 10 skips are: 3 Linux-only process-group kill tests (`test_ocr_conformance.py`), 4 Linux-only
runner signal and kill tests (`test_runner_process.py`), 3 symlink tests that need privileges this machine lacks
(`test_ocr_config.py`, two in `test_jonaki_linkage.py`). All 10 are platform-dependent, none is dependency-dependent. The 7
Linux-only tests last passed in CI #42; the 3 symlink tests passed there as well (907 passed, 0 skipped, inferred from the
totals, not shown by name). The 314 skips without a database are the PostgreSQL-backed tests, which did run in the PostgreSQL
run. Timing-sensitive tests have passed in several CI runs, which does not rule out flakiness.

## 13. Known defects, residual risks, unresolved blockers

- No known failing test. Pre-existing: an unused variable at `capture/documents.py:55`.
- Residual risks R1 to R6 in `docs/M2_OWNER_DECISIONS.md` (time of check versus use, hard links, network not blocked, runner
  reading outside the verified directories, unit case-folding, never-executed checks).
- Retry cap: owner-approved Option A (up to 18 claimed attempts per document); allergy and printed-name placement chosen where the approval was silent.
- No key rotation; legacy plain rows; the key is the root of the protection.
- Blockers: reviewer identity (FRD Q7) and vocabularies; D8 and FRD Q1; D18 and 4B with a schema approval; Jonaki access,
  license, detector, data; D5, D6, D11; D13 alert mechanism; D3; hosting provider, supervisor product, poll interval value,
  `connect_timeout`; a lawyer's view on retention.

## 14. Production-readiness assessment

**Not production-ready.** Reasons: interface v0 is test-only, so no OCR adapter is available outside test mode and the worker
idles; no real model has run, so no accuracy exists; the reviewer is unnamed and the vocabularies are missing; no catalog; no
CI run on this campaign; the deployment guide is untested on a server; no key rotation or key-management decision; retention
unreviewed by a lawyer; synthetic data only. Passing tests do not change this.

## 15. Completion checklist with evidence

| Requirement | Implemented | Tested | Approval | Evidence |
|---|---|---|---|---|
| Field list for four document types | yes | yes | owner yes; reviewer pending | `test_parsers.py` (equality with the signed copy) |
| Transcription parsers | yes | yes | owner yes | `test_parsers.py`, `test_parsers_e2e.py` |
| Row splitting (strength, dose, unit, range) | no | n/a | BLOCKED: vocabularies | none by design |
| Manual entry endpoint | yes | yes | D10, D12, D14 yes | `test_manual_entry_retry.py` |
| Retry endpoint and cap 5 (Option A, at most 18 attempts) | yes | yes | yes | `test_manual_entry_retry.py` (boundary test: 18 attempts, 6th retry refused) |
| `fields` encrypted | yes | yes | D2 yes | `test_extraction_privacy_pg.py`, `test_extraction_crypto.py` |
| Raw text in deletable store, hash in row | yes | yes | yes | same |
| Deletion at verification or rejection | yes (database trigger) | yes | Q8 yes | same |
| Key missing or invalid handling | yes | yes | yes | `test_extraction_crypto.py`, `test_runner_startup.py` |
| Deployment guide, supervisor policy | yes | untested on a server | Q4 yes | `docs/DEPLOYMENT.md` |
| Worker lifecycle (start, `--once`, loop, signals, recovery) | yes | yes | yes | CI #42, local runs |
| OCR adapter contract, model integrity | yes | yes (fake runner) | v0 test-only | adapter and linkage tests |
| Real OCR execution and accuracy | runner written | no | BLOCKED | never executed |
| Drug matcher | yes | yes (synthetic) | BLOCKED for catalog | `test_drugmatch.py` |
| Evaluation harness, CER, WER | yes | yes | no thresholds set | `test_evaluation_harness.py` |
| No verified events from M2 | yes | yes | n/a | event counts asserted 0 |
| CI verification of this campaign | n/a | no | n/a | NOT DONE |
| M3, M4 | n/a | n/a | n/a | OUT OF SCOPE, untouched |

## 16. Recommended next steps (no M3 or M4 work)

1. Review and commit this campaign (suggested grouping in the terminal summary), push, and read the CI log: first Linux run
   with the new tests; expect `1003 passed, 0 skipped` if all pass.
2. Name the clinical reviewer; obtain vocabularies and non-English label lists; confirm the retry-cap reading.
3. Decide D8 and FRD Q1, D18 and 4B with the schema approval, D5, D6, D11, and the key-management and rotation approach.
4. Request Jonaki access, decide the license question, provision the detector, and supply permitted Bengali data; only then
   run the real runner on CPU and evaluate with the harness.
5. Try the deployment guide on a staging server; settle provider, supervisor and interval value.
