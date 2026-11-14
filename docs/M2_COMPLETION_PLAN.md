# M2 completion plan (P2) — revised baseline, committed in `2b626aa`, owner approval pending

Status on 2026-11-12.

## Current status (facts only)

- Slices 1 and 2 are built and pushed (`e18bf48`, `63df1f9`, `6021085`): upload, encrypted immutable originals, the extraction pipeline on a fake OCR engine, and the recovery tests.
- **Step 1 (worker reliability) is COMPLETE, marked by the owner on 2026-11-12.** It consists of `1ebdb15` and the S1 fix `6b11e65` (cherry-pick of `cc836f5`), both on `origin/main`. CI run #15 on `main` (`3f348d3`) passed: 259 passed, 0 failed, 0 skipped, 0 errors.
- An earlier version of this plan is in `2389991`. **This revision is committed in `2b626aa` and pushed to `origin/main`. Committing and pushing it records it; owner approval of its content is still pending.**
- `main` was pushed on 2026-11-12: `origin/main` = `3f348d3` (`1ebdb15`, `2389991`, `6b11e65`, `2b626aa`, `282bd44`, `3f348d3`). Later edits to this file are uncommitted until the owner asks.
- **Linux CI verified for Step 1** on branch `verify/step1-1ebdb15` (ubuntu-26.04, Python 3.12.16, PostgreSQL 16.15): `1ebdb15` run #13, 258 passed, 0 failed, 0 skipped, 0 errors; `cc836f5` (S1 fix, accepted) run #14, 259 passed, 0 failed, 0 skipped, 0 errors. `cc836f5` was cherry-picked onto local `main` as `6b11e65`; its code is identical to what run #14 tested. `main` itself then passed CI run #15 (`3f348d3`, `43265164599`): 259 passed, 0 failed, 0 skipped, 0 errors, same environment. CI for `63df1f9` and `6021085` was never checked separately; `2389991` is docs only.
- **Decided 2026-11-12 (Option A):** a document with no OCR adapter available stays due (`uploaded`) and can go straight to manual entry; it is never marked `extraction_failed` for that reason. Design proposed in `docs/DECISIONS.md`; not implemented.
- **Steps 2–9 are plans only. None of them is implemented.**
- **No real OCR model has been selected, installed or integrated.** OCR model development **has not started**: the owner has not yet selected an architecture, framework, dataset or trained model, and will select, train, own and supply it independently.

This plan covers what M2 still needs. It does not start M3, does not enable cloud AI, and does not fill the clinical field list.

## Ground rules for OCR (owner requirements)

1. The owner trains and supplies the OCR model. No engine or architecture is chosen in this plan, and none is to be chosen by the implementer.
2. No pretrained OCR model or OCR engine is installed, downloaded, bundled or integrated.
3. No model performance or accuracy figure is stated or assumed anywhere in this plan.
4. Fake OCR engines exist for tests only and are never production engines.
5. There is no automatic production fallback to another OCR engine. A failed attempt fails; nothing else runs in its place.
6. The adapter interface is framework-neutral and **provisional**. Model-dependent details (input and output, confidence, position or box format, granularity, limits, batching, timeout values, process model, resources) stay **OPEN** until the owner supplies the model specification (D4).
7. Cloud AI stays off. The clinical field list was approved by the owner on 2026-11-14 and is in `SCHEMAS`; clinical reviewer sign-off is still pending (D7).
8. The future model is not forced to fit the provisional interface. When the specification arrives, the interface is reviewed and revised to fit the model, with the owner's approval.
9. No model artifact is bundled or deployed without the owner's explicit authorization. Model-specific implementation, integration and production deployment need the specification and explicit approval.

## Two tracks

- **Track A — model-independent.** Everything that can be built and verified without the owner's model: the OCR infrastructure with its infrastructure-test interface (version 0, not a contract), the synthetic evaluation set and harness plumbing, upload checks, the schema mechanism, the worker runner, privacy and audit work. Verified with test-only fake engines.
- **Track B — needs the owner's model.** Integrating the actual model, tuning pre-processing for it, tuning parsers on its real output, and measuring its real accuracy and speed.

Fake-engine results prove that the infrastructure works. They say nothing about how well the owner's model reads documents. Real-model results exist only after step 4B, and are reported only by step 9B.

## Readiness levels (PROPOSED)

| Level | Means | Shown by |
|---|---|---|
| **M2 infrastructure-complete** | Track A done: exit gates 1a, 1b, 1c, 2, 3 (infrastructure part), 4, 5, 6, 8 and 9 below, with test adapters under `APP_ENV=test` | Tests and CI |
| **M2 production-ready** | Infrastructure-complete, plus the owner's model integrated (4B, only after explicit approval), gate 1a re-shown on it, and the 9B report signed (gates 3 and 7 in full) | Tests, measurements, signed report |

The FRD P2 gate is infrastructure-complete. Production readiness is checked at P10 and before the pilot. Passing the first never implies the second, and infrastructure-complete does **not** freeze the provisional OCR interface: it is reviewed and revised against the owner's model specification during 4B. Whether M3 may start once M2 is infrastructure-complete is decision D15.

## Implementation order

| Step | Task                                                       | Track     | Depends on                         | Blocked by a decision or input?      | Can start before the model is supplied?                                            |
| ---- | ---------------------------------------------------------- | --------- | ---------------------------------- | ------------------------------------ | ---------------------------------------------------------------------------------- |
| 1    | Worker reliability                                         | A         | —                                  | No: D1 decided, 5 minutes            | **Complete** (owner, 2026-11-12): `1ebdb15` + S1 fix `6b11e65`; CI run #15 on `main` passed |
| 2    | Extraction data privacy                                    | A         | —                                  | D2 (and FRD Q8)                      | Yes, once D2 is decided                                                            |
| 3A-data | Synthetic set generator, degraded copies, splits        | A         | —                                  | None                                 | Yes                                                                                |
| 3A-harness | Harness plumbing                                     | A         | 3A-data; 4A infrastructure (D17) | None for plumbing; production input waits for D18 | Plumbing only, exercised with version 0 fakes in synthetic tests; production input per the approved contract |
| 3B   | Handwritten set                                            | A         | 3A-data                            | D3                                   | Yes (the data does not depend on the model)                                        |
| 4A   | OCR infrastructure and infrastructure-test interface       | A         | Step 1 (complete)              | Merged into `main` 2026-11-13 (fast-forward `33e2aa1..a9f2abc`; CI #21 and #22: 444 passed); historical, not pending | Yes (model-dependent items stay OPEN)                     |
| 4B   | Compatibility review and owner-model integration           | B         | 4A                                 | D4: model and specification supplied; explicit approval | **No**                                                    |
| 5A   | Upload validation and quality checks                       | A         | 3A-data                            | D5, D6                               | Yes                                                                                |
| 5B   | Pre-processing for the model                               | B         | 5A, 4B                             | Model specification                  | **No** (mechanism can exist; configuration waits)                                  |
| 6A   | Schema mechanism                                           | A         | —                                  | None                                 | Yes                                                                                |
| 6B   | Document parsers                                           | A, then B | 4A, 6A                             | D7, FRD Q7                           | Yes after D7, in synthetic tests only (version 0 allowed there); production input format waits for D18; tuning on real output waits for 4B |
| 7    | Drug catalog matching                                      | A         | 6                                  | FRD Q1, D8                           | Yes, with a synthetic catalog only                                                 |
| 8    | Running the worker, manual entry, failure handling, audit  | A         | 1, 4A                              | D10, D12, D14 (D9 decided)                    | Yes, with a test engine under `APP_ENV=test`; a production run needs 4B            |
| 9A   | Evaluation framework (model-independent)                   | A         | 3A-harness, 4A; 5A and 6 for their metrics | None                                 | Yes                                                                                |
| 9B   | Real-model evaluation and sign-off                         | B         | 4B, 5, 6, 7, 9A                    | D11; clinical reviewer               | **No**                                                                             |

Step 1 is complete (marked by the owner on 2026-11-12). Steps 3A-data, 4A, 6A and 9A can start when the owner says so; 3A-harness plumbing after 4A (scope approved by D17, implementation awaits the owner's go-ahead); 2 after D2. Steps 6B, 7 and 9B cannot finish without the clinical reviewer.

**Proposed working sequence (PROPOSED, for owner approval):** D17 approved with revisions (done) → 3A-data alongside 4A implementation → 3A-harness plumbing → 6A → 5A → 9A → 2 → 8 → 7 → 3B and 6B as their decisions arrive → **model and specification supplied** → 4B compatibility review and interface revision, approved by the owner → **integration explicitly approved** → rest of 4B → 5B → rework of version-0-based work as needed → 6B tuning → 9B.

### Dependency rationale

- **3A-data needs no contract.** The generator, degraded copies and splits produce images and ground truth only.
- **3A-harness plumbing needs the 4A infrastructure.** The existing engine contract in the code (`engine(pages, doc_type) -> {"engine", "raw_text", "fields"}`) is not kept. Version 0 is an infrastructure-test interface only (D17), so the harness uses it only in synthetic tests; its production input is whatever contract is approved after D18.
- **4A is infrastructure only.** It builds the machinery around a versioned interface and enforces the model-independent rules; it defines no OCR contract (version 0 is test-only, D17). It needs no model, so it does not depend on measurements from step 3. Choosing an engine from measurements is not part of M2.
- **5A depends on 3A-data, not on 4.** Blur, glare and size checks are calibrated on the labelled degraded copies and do not involve OCR. Only pre-processing for the model (5B) needs 4B.
- **6 depends on 4A, not on 4B.** Parser logic can be built and tested on synthetic text with exact ground truth; synthetic tests may feed it through version 0. The parsers' production input format is defined only by the contract approved after D18, and is adapted in 4B. Their real-world quality is measured only in 9B.
- **9 is split.** The framework (metrics code, report format, smoke run) is model-independent. Real accuracy exists only once a real model is integrated.
- **8 depends on 4A.** The runner needs the adapter contract and engine configuration, not a particular model. 4A supplies the "adapter available" check that the runner makes before any claim (Option A).

---

## Step 1 — Worker reliability — COMPLETE (marked by the owner, 2026-11-12)

The record of what was built is `docs/DECISIONS.md`, "Worker reliability (M2 step 1)".

**As built:**

- The fence is a random **claim token** per attempt plus the lease. It guards both the result write and the failure write.
- Lease 5 minutes, **heartbeat every 60 seconds**, maximum 3 attempts.
- OCR runs in a **child process killed at a 10-minute hard timeout**. The database timeouts are only a backstop, on `db.connect_worker`, which nothing uses until step 8.
- Refused settings: in-process OCR outside `APP_ENV=test`; a heartbeat not shorter than the lease.
- A database constraint (`extracting_has_time`) stops an `extracting` document having no due time.
- Worst case to a terminal state with these settings: about 33 minutes plus polling (`docs/DECISIONS.md`).
- Also touched: `capture/documents.py`, `capture/schema.sql`, `tests/fake_engines.py`.
- Verification: Linux CI on `verify/step1-1ebdb15` — run #13 (`1ebdb15`) 258 passed; run #14 (`cc836f5`) 259 passed; 0 failed, 0 skipped, 0 errors in both. On `main`: run #15 (`3f348d3`) 259 passed, 0 failed, 0 skipped, 0 errors. Details in `docs/DECISIONS.md`, "Verification and the S1 fix".
- **S1 fix (`cc836f5`, accepted 2026-11-12):** a lost database connection during an attempt now raises `WorkerConnectionLost` without a further write, instead of a second error from recording the failure. One new recovery test (`pg_terminate_backend`). Cherry-picked onto `main` as `6b11e65`; pushed.

**Completion (2026-11-12):** `main` pushed with the owner's approval (`origin/main` = `3f348d3`), CI run #15 on `main` passed (259 passed, 0 failed, 0 skipped, 0 errors), and the owner marked Step 1 complete. Review findings S2–S8 stay open and are not part of Step 1 unless the owner decides otherwise.

**Interaction with Option A (decided 2026-11-12; the availability check before any claim is implemented, and direct manual entry was implemented on 2026-11-14 as slice 8.6).** Step 1's claim counts an attempt before the work, so a run with no adapter would use up attempts. 4A adds the availability check before any claim (a change to `run_due` and `extract`), and step 8 adds direct manual entry (a change to `manual_entry()` and the transitions). Neither changes the claim, fence, lease, heartbeat or retry logic of step 1.

**Open risks (unchanged):**

- OCR descendants survive the timeout.
- An engine that cannot be sent to a child process uses up a document's attempts.
- Review findings (`docs/DECISIONS.md`): S2, S3, S4 are fixed and S5 Part A is implemented; all CI-verified in runs #21–#25 (620 passed, 0 skipped on `7b8e929`; `docs/DECISIONS.md`). Deferred by the owner: S5 Parts B and C (cloud AI, FRD Q5), per-image renewal and storage-read timeouts (FRD Q4), S6 (Step 8), S7 (D18), S8 (needs PostgreSQL `EXPLAIN`).
- The timing-sensitive recovery tests passed in one run per commit; occasional flakiness is not ruled out.

**FRD requirement.** M2: "Retries with backoff, idempotent by (document_id, version)"; "every document ends in needs_review or extraction_failed". Section 7: tasks are at-least-once and a repeat does nothing. Invariant 8: fail closed.

### Superseded proposal (historical context only; not implementation guidance)

The approved proposal was a claim-and-lease design fenced by attempt number, with a bound of "maximum attempts × lease" to a terminal state. The build changed the fence (claim token), added the heartbeat, the child-process hard timeout and the extra constraint. Where this section and the proposal differ, "As built" above is correct.

---

## Step 2 — Extraction data privacy

- **Status.** Implemented locally 2026-11-14 (D2 option b, key EXTRACTION_KEY, deletion at verification or rejection); see docs/DECISIONS.md, "Implementation record of the 2026-11-14 decisions". Not pushed, no CI run.
- **FRD requirement.** Section 9: encryption at rest, field-level encryption for sensitive fields, "store only schema fields", no document text in logs, patient export and delete.
- **Proposed implementation.** The mitigation already written in `DECISIONS.md`: encrypt `extractions.fields` and `raw_text` with a key outside the database; keep `raw_text` only until the document is verified or rejected, in a store that allows deletion; record its hash in the append-only row.
- **Files.** `capture/extraction.py`, `capture/schema.sql`, `pii.py` or `capture/storage.py`.
- **Dependencies and decisions.** D2: approve encrypting, and approve deleting raw text after review (this changes what the ERD stores). Lawyer's view on retention (FRD Q8).
- **Interaction with step 4A.** The engine identity columns are added by 4A, not here (see 4A). Step 2 encrypts `fields` and `raw_text` only.
- **Tests.** A database dump contains no document text; the extraction endpoint still returns fields to the patient; raw text is gone after a document is closed; wrong key fails closed.
- **Acceptance.** No readable document text in any table, log or backup outside the patient's own API response, shown by the tests above.
- **Risks.** Encrypted fields cannot be searched in SQL. Mitigation: nothing in M2 needs to; search (M5) works on verified events, not extractions.

## Step 3 — Synthetic document set and evaluation harness (your area 6, first half)

Everything in step 3 is model-independent. It produces data and plumbing; it measures no real model.

- **Status.** Partly implemented: the 3A synthetic generator (commit `553c3db`) and, in the combined M2 commit, a harness with field-level scoring, integrity checks and a confidence analysis (`tests/evaluation/harness.py`; fakes only). **Not implemented:** scoring of any real model (step 9; needs 4B), the handwritten set (3B, D3), Bangla rendering (no font chosen). Its tests passed in CI run #38 (one run).
- **FRD requirement.** Section 8 gate: "Field-level on a labelled synthetic set of printed and handwritten prescriptions". Invariant 9: synthetic data only.

### 3A — Generator, degraded copies and harness plumbing

3A is done in two parts. **3A-data** (printed set, degraded copies, splits) can start now. **3A-harness** (plumbing) follows 4A. It runs fake adapters through version 0 in synthetic infrastructure tests only; its production input is set by the contract approved after D18.

- *Printed set:* render documents from the synthetic generator with known field values, so the ground truth is exact by construction. Bangla, English and mixed, several layouts.
- *Degraded copies:* rotate, skew, blur, add noise, glare and low contrast with known amounts. These also give labelled data for the blur and glare checks in step 5A.
- *Harness (3A-harness):* a command that runs an adapter over a set and writes raw results for the metrics code (step 9A). Until the real contract is approved it runs only fakes through version 0, on synthetic data.
- *Splits:* every set has a development split and a held-out test split, assigned by seed and versioned. The held-out split is never used for tuning.
- **Files.** `tests/synthetic.py` (extend), new `tests/evaluation/` (generator, harness, small fixtures). Large image sets stay out of git.
- **Dependencies.** A Bangla font with a licence that allows use (for example an OFL font). Pillow.
- **Tests / acceptance (measurable, no real model needed).**&#x20;
  - Generation from the same seed in the same environment yields identical ground-truth files and identical image hashes.
  - Development and held-out splits are disjoint (a test asserts no shared document id).
  - The harness scores a perfect fake engine at 100% and a deliberately wrong fake engine at the exact values computed by hand for its known errors.
  - Each degraded copy records its degradation type and amount.
  - Printed results and handwritten results are written to separate outputs.

### 3B — Handwritten set

- People hand-copy generated synthetic prescriptions and photograph them. The content is synthetic, the handwriting is real, and the truth is already known.
- **Decision.** D3: who writes the handwritten set, and how many.
- **Acceptance.** A versioned set with exact ground truth, in the same format and split scheme as 3A, covering Bangla and English, each photo linked to its source document id.

### Risks (step 3)

- Synthetic printed documents are easier than real ones, so results will look better than reality. Mitigation: report printed and handwritten separately, never as one number, and say so in the report. Real documents wait for the pilot.
- **Training contamination (new).** If the owner's training data overlaps the held-out split, step 9B results are meaningless. Mitigation (PROPOSED): the held-out split is generated and kept out of the owner's training pipeline. OPEN: whether the owner wants the generator to also produce training or validation material; if so, it comes from the development split only.

## Step 4 — OCR infrastructure and owner-model integration (your area 2)

- **FRD requirement.** 3.5: local OCR. M2: local OCR; cloud model only on opt-in. Section 9: Bangla and English OCR; under 60 s per page.
- **Status.** 4A (model-independent infrastructure) is implemented, merged and CI-verified. The Jonaki adapter infrastructure is implemented and tested with a fake runner only. **4B (the owner's model) is not implemented**, and the real Jonaki runner and weights have never been executed. No model is selected, installed or integrated by the project.

**OCR model status (2026-11-12).** Development of the OCR model has **not started**. The owner has not selected an architecture, framework, dataset or trained model, and will select, train, own and supply it independently (`docs/DECISIONS.md`, "OCR model not yet developed"). Everything in 4A is therefore model-independent infrastructure plus a **provisional** interface that is expected to change.

The step has two parts that are kept apart on purpose:

- **4A — OCR infrastructure and infrastructure-test interface** (model-independent; scope approved by D17 with revisions; implementation awaits the owner's go-ahead).
- **4B — owner-model integration** (cannot start until the owner supplies the model and its specification under D4, the compatibility review is done, and the owner explicitly approves integration).

### 4A — OCR infrastructure and provisional adapter interface

**Goal.** Model-independent machinery around a versioned, framework-neutral adapter interface, verified with test-only fake adapters, so that the owner's model can later be connected **after the interface has been reviewed and, where needed, revised to fit the model**. The goal is not to fix an interface the model must conform to.

**Scope status: D17 APPROVED WITH REVISIONS (2026-11-12, `docs/DECISIONS.md`).** The model-independent infrastructure scope is approved. **Version 0 is not an approved OCR contract**; it is an infrastructure-test interface only. D17 does not authorise any real adapter, model selection, installation, bundling or production deployment. Sub-choices C1, C2, D13, 4A-15, 4A-16, 4A-20, 4A-23 and 4A-24 were accepted on 2026-11-12, and Option C (test mode needs `APP_ENV=test` and `SWASTHYOID_TEST_MODE_CONFIRM=1`) was chosen. **Implemented on branch `4a/ocr-infrastructure` (`7c0c148`), CI run #17: 411 passed, 0 failed, 0 skipped, 0 errors. Later review fixes brought the branch to `a9f2abc`. Merged into `main` on 2026-11-13 by fast-forward (`33e2aa1..a9f2abc`) after the owner's review and separate merge approval; CI run #21 (branch) and #22 (`main`) at `a9f2abc`: 444 passed, 0 skipped. The merge is historical, not pending.** Record and deviations: `docs/DECISIONS.md`, "4A implementation".

Version 0 replaces the current code contract (`engine(pages, doc_type) -> {"engine", "raw_text", "fields"}`) **inside tests only** until the real contract is approved in 4B.

**Model-independent requirements (approved scope under D17; items marked OPEN await the owner):**

1. *Reference-based loading.* One adapter per deployment, named by a stable reference in configuration and imported where OCR runs. The loader holds no assumption about a model's file format, framework, runtime, device or loading procedure. How it is configured is C1 (OPEN). Only adapters on the **owner-controlled allowlist** are accepted outside test; only the owner changes that list.
2. *Availability before claim (Option A).* The worker checks adapter availability **before claiming anything**. Unavailable means nothing is claimed, no attempt is counted, documents stay `uploaded` (due) and can go to manual entry (step 8). Whether an integrity or load failure at worker start counts as unavailable is D13.
3. *Artifact integrity.* Checksum verification infrastructure is built now: declared artifact files are verified against expected SHA-256 values before use, and a mismatch fails closed. No download at run time. Nothing enters a deployment without the owner's explicit authorization. **The final artifact-manifest format and how `model_checksum` is computed stay OPEN** until the artifact structure is known; the version 0 manifest is test-only.
4. *No network* from the OCR process (test-enforced now; production enforcement depends on hosting, FRD Q4).
5. *Versioned validation.* Every adapter result goes through a validator for the declared interface version before anything is stored. Malformed output fails the attempt; nothing is stored; an empty result is distinct from an error.
6. *Identity.* Engine id, model version, model checksum and interface version are recorded with each extraction (field names provisional; optional adapter version is 4A-20, OPEN). The existing `engine` column stays, because `extractions` is append-only; manual entries keep `engine = 'manual'` and no model identity.
7. *Typed errors and retry infrastructure.* Typed failure codes; only the code is stored. Attempts, backoff and maximum attempts as in step 1, with every failure inside an attempt counting. No failure triggers another engine. **Model-specific retry semantics** (for example whether malformed output is retried, 4A-17) are **not defined** until the actual adapter contract is approved. Whether the platform enforces every time limit is 4A-23 (OPEN; today it enforces the hard timeout).
8. *Fakes are test-only.* Outside `APP_ENV=test`, a test or fake adapter is refused when it is resolved and when a worker starts, before any claim; production adapters come only from the owner-controlled allowlist. *Gap today:* a fake engine passed with a hard timeout runs in any environment; 4A closes it.
9. *Privacy.* No document text in logs or stored error messages; OCR process output streams discarded outside test. **Version 0 page items and positions are never persisted.** **No real patient data is used in OCR execution** until the encryption and privacy controls of step 2 (D2) are implemented and approved.
10. *Import lint.* An allowlist test across the repository: every module except adapter modules may import only the standard library, the dependencies declared in `pyproject.toml`, and `swasthyoid`. No framework is named.

**What the adapter must not do:** choose or switch models; fall back to a different engine; write events; alter stored originals; send anything off the machine.

**Model-dependent items — OPEN until the trained model's specification (D4, D18), not decided by this plan or by D17:**

| Item | Status |
|---|---|
| Actual OCR input: unit (page or whole document), page handling, image encoding, dimensions, document hints such as document type | OPEN |
| Actual OCR output: granularity (line, word, character, region), reading order, output serialization | OPEN |
| How production `raw_text` is formed from the output | OPEN |
| Model-specific retry semantics (which errors retry, which close the document) | OPEN |
| Confidence: whether reported, its range, its meaning, and how the 0.85 review rule applies to it | OPEN |
| Position or bounding-box format | OPEN |
| Size limits per page or document | OPEN |
| Batching | OPEN |
| Lifecycle detail: load once or per attempt; long-lived OCR process or one per attempt; whether the runtime needs its own process or executable | OPEN; process-per-attempt is the current implementation baseline, reassessed in the 4B compatibility review |
| Timeout values: load, per page (if any), per attempt | OPEN; today's 10-minute hard timeout stays as implemented |
| Resource needs (memory, CPU or GPU) | OPEN |
| Artifact-manifest format and `model_checksum` computation | OPEN (verification infrastructure is built now) |

**Version 0 — infrastructure-test interface only (D17).** To exercise the infrastructure, fake adapters use a simple shape: `identity()`, `prepare()`, `read(document)`, `release()`, returning `pages` of `items` with `text` and optional `confidence` and `position`. **This shape is not an OCR contract and not a production requirement.** It is labelled as test-only in code and documentation and is expected to be replaced by the contract approved in 4B. Infrastructure code may depend only on going through the versioned validator, never on version 0's fields. Building `raw_text` from version 0 items (in order, blank line between pages) is allowed **only in synthetic infrastructure tests**.

**Other 4A work:**

- *Conformance tests, split (D17).* **Infrastructure conformance tests** — in scope for 4A: availability, integrity, allowlist, fakes refused, no fallback, typed errors, hard timeout, process isolation, no network in tests, privacy of logs and errors, identity recorded, import lint. **Model-output conformance tests** — **out of scope for 4A**, written after D18 for the approved contract. Only the infrastructure tests are expected to run unchanged against the real adapter.
- **Files.** New `capture/ocr.py` (interface, loader, validator; no ML imports), `capture/extraction.py` (availability check before claim), `capture/schema.sql` (identity columns), test-only fake adapters under `tests/`, new `tests/adapters/test_ocr_conformance.py` (the FRD section 13 location), the import-allowlist test, settings in the existing config. No new third-party dependency.
- **Current runtime constraints from step 1 — compatibility review required.** The worker today runs OCR in a separate process per attempt, kills it at a 10-minute hard timeout, and expects the adapter not to start processes of its own. These are the current implementation baseline, not requirements on the owner's model. Process isolation (OCR has no database access and is killed on timeout) is preserved; the process-per-attempt model itself is reassessed in 4B. Before 4B is approved, compare them with the supplied specification and runtime. If they are incompatible, stop and present the conflict and options to the owner; review the worker architecture with the owner rather than changing, replacing or restricting the owner's model without approval.
- **Tests / acceptance (measurable, no real model needed).**
  - The 4A scope is approved (D17, done with revisions) and version 0 is documented as an infrastructure-test interface, with the model-dependent items marked OPEN.
  - Malformed version 0 output from a fake fails the attempt and stores nothing.
  - No version 0 item or position is persisted (a test inspects the stored rows).
  - A fake adapter that runs past a configured time limit fails its attempt, and the limit is read from settings.
  - A fake adapter that attempts a network call is blocked and fails closed under a network guard in the test.
  - A wrong checksum refuses to load.
  - A fake or test adapter is refused outside `APP_ENV=test`, before any claim.
  - With no adapter available, the worker claims nothing: attempts stay 0 and no document becomes `extraction_failed`.
  - A module outside the adapter modules that imports a package not on the allowlist fails the lint.
  - When the configured adapter fails, no other adapter is called (a test asserts the call count of a second registered adapter is zero).
  - Log output of a run contains none of the document text of a known synthetic page.
  - The interface module imports no ML framework (a test inspects its imports).

### 4B — Owner-model integration (waits for the owner's model, a compatibility review and explicit approval)

**This work must not start merely because a model has been supplied.** Actual model-specific adapter implementation, integration and production deployment may begin only after the owner has supplied the trained model and its complete specification under D4, the compatibility review below is done, and the owner has explicitly approved the integration. Supplying the model or specification alone does not authorize implementation, bundling or deployment.

Planned work, in order, after those conditions are met:

1. Record the specification (see D4 intake) in `docs/DECISIONS.md`, when authorized.
2. **Compatibility review.** Compare the specification with provisional interface version 0 and the current worker constraints. Propose the revised interface version that fits the model, and any worker changes, to the owner. Nothing is changed to the model; nothing in the worker is changed without approval.
3. After approval, implement the approved interface version, its model-specific retry semantics, its manifest format, and the model-output conformance tests.
4. Add a model-specific runtime module that implements the approved interface. Framework and runtime choices come from the owner's specification, not from this plan. Who writes this module (the owner, or the implementer only after explicit approval) is part of D4.
5. Pin the artifact and checksum, and deliver it only by the method the owner authorized under D4 (mounted read-only, or packaged into the build).
6. Run the infrastructure conformance tests unchanged and the model-output conformance tests as approved.
7. Run it with the network blocked.
8. Measure load time, time per page and memory, and record them against the 60 s per page target (10 pages per document). Timeout values are then proposed to the owner from these measurements.

- **Tests / acceptance (measurable).**
  - The compatibility review and the approved interface version are recorded.
  - Loads from the pinned artifact, with the checksum recorded.
  - Passes the infrastructure conformance tests unchanged and the model-output conformance tests as approved.
  - No real patient data is processed until step 2's encryption and privacy controls are implemented and approved.
  - Runs with the network blocked.
  - Load time and time per page are measured and recorded. (Speed measurements only; accuracy is not an acceptance criterion of 4B and is reported only in 9B.)
- **Risks.**
  - The model may read handwritten Bangla prescriptions poorly. Mitigation: that is what the manual-entry path is for; the report states handwritten numbers plainly; cloud AI stays off unless you separately approve it.
  - **Per-attempt model load.** Step 1 runs OCR in a separate process per attempt, so the model would load in every attempt and its load time counts against the 10-minute hard timeout. Measure it in 4B; the process model is a model-dependent decision.
  - **Timeout headroom.** 10 pages at the FRD target of 60 s per page equals the 10-minute hard timeout exactly, leaving no room for model load. OPEN until 4B measurements exist. Any change goes through the owner and `DECISIONS.md`.
  - **Rework.** Version 0 is test-only (D17), so anything that uses it (3A-harness plumbing, 6B and 9A synthetic tests) is revised to the approved contract here. Their production input is defined only by that contract.
  - The step 1 risks (descendants surviving the timeout; an engine that cannot be sent to a child process) apply to the real model's runtime until the compatibility review settles the process model.

## Step 5 — Image quality checks and pre-processing (your area 3)

- **Status.** Partly implemented: the 5A imaging module (`capture/imaging.py`: decode, pixel cap, sharpness, glare, contrast and skew measures, reason codes; provisional limits), plus in the combined M2 commit a processing-copy function and a worker option `preprocess` (empty by default; transient copy, original untouched; not recorded in the extraction row). **Upload integration is not done and is unapproved** (owner decision 2026-11-13; it also needs D5 and D11), so no upload is checked or refused yet. 5B (pre-processing) is not implemented and waits for 4B. Its tests passed in CI run #38 (one run).
- **FRD requirement.** M2: "pre-process (rotate, deskew, denoise, contrast)"; "Blur and glare detection asks for a retake".

### 5A — Upload validation and quality checks (model-independent)

- *At upload, before storing:* decode the image for real (today only the first bytes are checked), reject files that do not decode, and cap pixel count against decompression bombs.
- *Quality checks:* sharpness score for blur, share of blown-out pixels for glare, minimum resolution, and whether a page is in frame. Limits are calibrated on the degraded copies from step 3A; they are engineering values, not clinical ones.
- *Retake guidance:* a refused page returns its page number and reason codes (`image_blurry`, `image_glare`, `image_too_small`) for the client to show simple Bangla guidance. Checking at upload means the patient or caregiver is still holding the paper.
- **Files.** New `capture/imaging.py`, `capture/documents.py`, `api/documents.py`.
- **Dependencies and decisions.**&#x20;
  - D5: retake policy. If the paper itself is poor, the best photo may still fail. Proposed: refuse-with-reasons plus an explicit "upload anyway", which goes straight to manual entry.
  - D6: photos carry EXIF data such as location. Keeping the original untouched keeps that data. Proposed: serve a copy without EXIF to anyone who is not the patient.
  - Pillow, and NumPy. OPEN: whether OpenCV is needed; it is chosen on the needs of 5A and 5B, not by an OCR engine.
- **Tests / acceptance (measurable, no model needed).** A sharp clean page is not refused; a corrupt or oversized image is refused with nothing stored; detection rate and false-refusal rate are measured on the labelled degraded set from 3A and reported; "upload anyway" lands in manual entry. Pass marks are those agreed in D11; until D11 exists, the rates are measured and reported without a pass or fail.

### 5B — Pre-processing for the model (waits for 4B)

- Rotate from EXIF, deskew, denoise and contrast adjustment run in the worker on a working copy. The stored original is never changed (its hash is unchanged after pre-processing).
- **PROPOSED:** each pre-processing operation is individually switchable, and which ones are enabled for the owner's model is taken from the model specification and confirmed by the measurements in 9B. A model trained on unprocessed photos may do worse with automatic deskew or denoise, so nothing is switched on by default for the real model.
- **Acceptance.** The original's hash is unchanged; the enabled operations are listed in the model's recorded configuration; a 9B comparison with and without each enabled operation is in the report.
- **Risks.** Refusing good photos frustrates the very users this is for. Mitigation: tune for few false refusals, and always allow "upload anyway".

## Step 6 — Clinical schemas and document parsers (your area 4)

- **Status.** Partly implemented locally 2026-11-14: the approved field list in SCHEMAS and label-anchored transcription parsers; row splitting waits for reviewer vocabularies; reviewer not named. See docs/DECISIONS.md. Not pushed, no CI run.
- **FRD requirement.** M2: "Parse to a typed schema with per-field confidence, validate types and dates". Invariant 1. CLAUDE.md: no invented clinical content.

### 6A — Schema mechanism (model-independent)

- Extend the schema format so each field carries its kind, whether it is **required or optional**, and validation rules (for example a date not in the future for a prescription date). Store the schema version with each extraction.
- `SCHEMAS` was empty until the list in `DECISIONS.md` was approved. **Superseded 2026-11-14:** the owner approved the list (reviewer sign-off still pending) and `SCHEMAS` now holds it; the test that pinned it empty now compares it with `tests/approved_fields.py`.
- Required fields are a rule for M3's confirm step; M2 only reports which are missing.
- **Tests.** Mechanism tests on a synthetic test-only schema, as today; a required field missing is reported; an invalid value is never accepted whatever its confidence.

### 6B — Parsers

- One deterministic function per document type (prescription, laboratory report, discharge summary) that turns OCR output (through the 4A interface, provisional until 4B) into candidate fields. No language model.
- *Field confidence (PROVISIONAL; depends on whether and how the owner's model reports confidence, which is OPEN):* the lowest OCR confidence among the lines a field came from, lowered further when the parser was unsure where the field was. Fields under 0.85 are left for manual entry, as now. Whether the owner's model reports confidence on a scale for which 0.85 is meaningful is not known; it is measured through the accepted-but-wrong rate in 9B (OPEN: whether a calibration step is needed).
- **Dependencies and decisions.** D7: the field list, required and optional marks, and the five open questions, signed by you and the reviewer. The reviewer must be named (FRD Q7).
- **Before the model exists.** Parser logic is developed and tested on synthetic text generated from exact ground truth (fed through version 0 only in tests); its production input is adapted to the contract approved after D18. Tuning on real model output waits for 4B.
- **Tests / acceptance (measurable).** After approval, parser tests per document type on the synthetic printed set; a test compares `SCHEMAS` with the signed list and fails on any field the approval does not list or any listed field that is missing; the approval is recorded.
- **Risks.** Rule-based parsing of free-layout handwritten prescriptions is the weakest link. Mitigation: fields the parser cannot place are left empty for manual entry; nothing is guessed.

## Step 7 — Drug catalog matching (your area 5)

- **Status.** Partly implemented (2026-11-14, local): the catalog-independent matcher `capture/drugmatch.py` (exact and normalised matching, ambiguity, no-match, catalog provenance, deterministic; it never selects a drug and its similarity parameters have no defaults), tested on a synthetic fixture. **Not implemented:** any real catalog (FRD Q1), the matching-rule parameters (D8), catalog tables and the `pg_trgm` path, wiring into extraction. See `docs/M2_OWNER_DECISIONS.md`.
- **FRD requirement.** M2: "fuzzy-match drug names to the catalog", "keep top suggestions". M3: names resolve to generic ingredients "with suggestions". M6: an unrecognised drug is flagged, "never silently passed". Section 12: trigram brand matching may be borrowed as an idea.
- **Proposed implementation.**&#x20;
  - Catalog tables for brands and generics, and an import command that records the source and its licence with every import.
  - Matching by trigram similarity in PostgreSQL (`pg_trgm`), returning the top few candidates with scores, across Bangla and English spellings.
  - **Ambiguous names:** the name as written is always kept. A match is never chosen automatically. If candidates are close to each other, or map to different generics, the field is marked ambiguous and all candidates are shown for a person to pick in M3.
  - **Unrecognised names:** marked `unrecognised`, kept verbatim, never dropped.
- **Files.** New `safety/catalog.py` and `safety/schema.sql` (shared with M6), `capture/extraction.py`.
- **Dependencies and decisions.** FRD Q1: a catalog we may legally use. Until then, a synthetic catalog only. D8: the reviewer signs off the matching rule, since look-alike drug names are a known safety hazard. `pg_trgm` must be available in the database.
- **Tests.** Exact, misspelt and Bangla-script names find the right candidate in a synthetic catalog; two look-alike names yield ambiguous, never a silent pick; an unknown name is flagged; the same input always gives the same candidates in the same order.
- **Acceptance.** No path selects a drug without a person; unrecognised is always visible.
- **Risks.** A wrong suggestion ranked first may be accepted by a hurried reviewer. Mitigation: show the written name beside every suggestion, and have the reviewer decide whether a top suggestion may be pre-selected at all (default: no).

## Step 8 — Running the worker, failure handling and audit (your area 7)

- **Status.** **Slice 8.1 (the runner's startup skeleton) is implemented and CI-verified** (commits `2b8038f` and `c4be86d`, 2026-11-13; CI run #31: 678 passed, 0 skipped; details in the Slice 8.1 entry below and in `docs/DECISIONS.md`, "Slice 8.1 implementation record"). **Update 2026-11-13, commit `553c3db` (pushed; CI run #35 failed on one test bug, fixed in `2ddb8a6`; CI run #36 passed: 713 passed, 0 skipped):** the `--once` cycle, the polling loop (`limit=1` per `run_due()` call; known cost: one availability probe per document and per idle poll), signal handling, queue statistics and the real-process, spawn and recovery tests are written (details in `docs/DECISIONS.md`, "Runner slices 8.2–8.4 ..."). Run #36 (Linux, PostgreSQL 16, one run, counts inferred from the totals) ran the PostgreSQL-backed and real-process tests with 0 skipped, so AC3 and the signal, hard-kill and watchdog evidence now exist; AC5 is only partly shown (a child that dies after starting is recorded as `WorkerDied` within 20 s; bootstrap failure of the spawned runner process itself is not tested). **Still plan only:** slice 8.6, and the written scopes of 8.2–8.5 are now this record, not earlier approvals.
- **FRD requirement.** M2: a background job. Section 4.2: what is audited. Section 9: observability (queue metrics), no personal data in logs.
- **Proposed implementation.**&#x20;
  - A small runner that calls `run_due` on an interval, started as its own process. Celery is not needed for this and can replace the runner later without changing the pipeline. The runner uses `db.connect_worker`.
  - **Required (owner decision B1, 2026-11-12):** the runner MUST call `runtime_mode.check_test_mode_config()` at process startup, before entering its worker loop. Until step 8, the checks at `run_due()` and `extract()` are the worker-side enforcement.
  - The runner checks adapter availability before any claim (the 4A rule). Outside test with none available, it claims nothing and documents stay `uploaded` (due).
  - **Manual entry (Option A, decided 2026-11-12; design in `docs/DECISIONS.md`):** one endpoint that moves a document to `needs_review` with every field empty, from `uploaded`, from `extracting` with no live claim, or from `extraction_failed`. Refused with 409 `extraction_in_progress` while a worker holds a live claim. One transaction: row lock, state and claim check, clear claim and due time, store the `manual` extraction row, audit entry `document.manual_entry`. No migration: add `uploaded -> needs_review` to `TRANSITIONS`; `manual_entry()` gains an actor, the claim check and the audit entry. Whether it is also allowed when an adapter is configured is D12 (recommended: yes).
  - An endpoint for the existing retry path (`extraction_failed -> extracting`).
  - Audit: retries and manual entry started by a person; views of documents by anyone but the patient (already done). Whether 409 refusals are audited is D14 (recommended: no). Cloud AI stays off: the threshold remains unset, and the test that proves nothing is sent stays.
  - Counters for queue length, attempts, failures and lease expiries, with no document text.
- **Files.** New `workers/extract.py`, `api/documents.py`, `capture/extraction.py`, `capture/documents.py` (one transition), and `tests/test_extraction.py` (the test that pins manual entry to `extraction_failed` only changes).
- **Dependencies and decisions.** D9: how the worker is run — DECIDED 2026-11-13 (`docs/DECISIONS.md`): a plain process, `python -m swasthyoid.workers.extract`, loop mode with a bounded `--once` mode; the supervisor or scheduler, poll-interval value and hosting still wait for FRD Q4. D10: who may retry or start manual entry (patient only, or a caregiver too; verifiers wait on FRD Q3). D12, D14 for manual entry.
- **Tests.** The runner processes a queue with a test engine under `APP_ENV=test` and stops cleanly; the endpoints follow the state machine and the access rules; logs contain no document text; the runner claims nothing with no real adapter available outside test.
  - Manual entry from each allowed state succeeds and writes one audit entry; from each refused state it changes nothing.
  - Races: manual entry first, then a claim, finds nothing due; a live claim first makes manual entry return 409; a worker whose lease ran out stores nothing and records no failure after manual entry; never two extraction rows for one version.
  - An audit write failure leaves the document unchanged.
- **S6 acceptance criteria (owner decision 2026-11-13: S6 is not built on its own; these are mandatory for the runner).** The worker spawns the OCR child and the availability probe, and a spawned child re-imports the runner's main module, so the runner must be safe to import. Reproduced on Windows (scratch, not in the repo): an unguarded entry script makes the probe child fail at bootstrap and the parent reports `availability_timeout`, so nothing is claimed and documents stay `uploaded`.
  - **AC1 Main-module guard.** All executable runner behavior is inside `main()`, called only under `if __name__ == "__main__":`.
  - **AC2 Import purity.** Importing the runner does not connect to PostgreSQL or touch the database, start a worker loop, spawn a process, start a thread, make a network request or produce output. Checked by importing it in a clean subprocess with an unreachable `DATABASE_URL`.
  - **AC3 Real-process test.** A real subprocess test backed by PostgreSQL, launching the runner by the mechanism D9 selects (`python -m swasthyoid.workers.extract`). In test mode it starts, one uploaded document reaches `needs_review`, the process exits with code 0, and the "runner started" log line appears exactly once.
  - **AC4 Startup order.** `check_test_mode_config()` (B1) runs before the worker loop, before any process spawn and before any database-dependent work. A test shows that `APP_ENV=test` without the confirmation refuses to start.
  - **AC5 Spawn failure behavior (to be measured, not assumed).** On Linux CI, test a child that fails while bootstrapping or importing, and a child that ends unexpectedly after starting successfully. Record whether the worker reports `WorkerDied` promptly or waits for the hard timeout. On Windows a child that crashed at bootstrap was seen to leave the parent waiting for the whole hard timeout (`HardTimeout`); Linux behavior is not known. AC5 also includes hard-kill recovery of the runner itself on Linux: the runner process is killed abruptly (for example with `SIGKILL`) while an attempt is in flight, the lease expires, a later runner recovers the document, and exactly one extraction result exists per document version. These are future acceptance requirements; none of them has been run.
  - **AC6 Regression.** The existing suite keeps passing, with every database-backed test running against PostgreSQL in CI. No fixed total is required; the test inventory changes legitimately as tests are added. The run to compare with is the CI log of the commit before the runner (run #26, `022cd74`: 620 passed, 0 skipped).
  - **Optional diagnostics (not requirements).** A clearer log reason when a probe child crashes at bootstrap (today it surfaces only as `availability_timeout`; it would touch `ocr.py`); logging a child's exit code.
  - **Deferred, not Step 8 requirements.** S5 Parts B and C and per-image renewal (cloud AI, FRD Q5), storage-read timeouts (FRD Q4), S7 (D18), S8 (needs PostgreSQL `EXPLAIN`), Celery or daemonic-process compatibility, `freeze_support()`, a static lint of runner modules.
- **Runner decisions of 2026-11-13 and the tests they add (details in `docs/DECISIONS.md`, "Step 8 runner — owner decisions"; D9 is unchanged).** Slices 8.1–8.5 are the runner; 8.6 (retry and manual-entry endpoints) stays blocked on D10, D12 and D14. Slice 8.1 is implemented and CI-verified (see its entry below); slices 8.2–8.4 exist in commit `553c3db`, local and not CI-verified (see the Status above). Slice 8.1's own scope below is historical: it did not run `run_due()`; since 8.2 `--once` does.
  - **Poll interval:** `EXTRACTION_POLL_SECONDS`, required in loop mode, positive finite seconds, no default; `--once` does not need it. In loop mode a missing or invalid value is a configuration error and exits with code `2`; the exit-code definitions below are unchanged.
  - **Exit codes:** `0` cycle completed or graceful shutdown; `1` infrastructure failure (connection loss, missing schema, unexpected runtime infrastructure failure); `2` invalid usage or configuration; `3` aborted by the second signal. Per-document failures are recorded by the extraction workflow and never change the exit code.
  - **Startup failure classification (2026-11-13, within the exit codes above; full table in `docs/DECISIONS.md`, "Startup error and ordering contract"):** exit `2` for invalid command-line usage, a missing or invalid `EXTRACTION_POLL_SECONDS` in loop mode (`--once` does not need it), a refused test-mode configuration (exactly `APP_ENV=test` with `SWASTHYOID_TEST_MODE_CONFIRM` not exactly `1`; the single `RuntimeError` of `check_test_mode_config()`, which cannot produce an infrastructure failure and does not reject every unsafe environment, so the adapter allowlist and the availability probe stay essential and are never bypassed), a `DATABASE_URL` that is missing, empty or whitespace-only, a `DATABASE_URL` rejected by the connection-string parser before any connection (psycopg's own parser, which accepts both the `postgresql://` form and the keyword/value form; owner decision 2026-11-13), and any other invalid or missing required configuration; exit `1` for a database connection failure with a value that the parser accepted, an unavailable required schema, table or column, and any other infrastructure failure that prevents a safe start; exit `0` for successful completion or a graceful shutdown; exit `3` for the second-signal abort. Not every exception is a configuration failure. **Today no `DATABASE_URL` validation exists** (`db.connect()` passes `os.environ["DATABASE_URL"]` straight to `psycopg.connect`; a missing variable is a raw `KeyError`); the presence check, the rejection of an empty or whitespace-only value and the side-effect-free syntax validation before connecting are required 8.1 behavior, not implemented. Open: the inventory of required settings (derived from the code during the 8.1 design; `DOCUMENT_STORE` and `DOCUMENT_KEY` validation stays a proposal needing confirmation, not mandatory).
  - **Signals:** the first signal stops further claims once the claim in progress reaches a safe boundary and lets the active attempt finish; a claim already committed counts as the active attempt (deterministic test required). The second signal logs one code-only line and calls `os._exit(3)`; it never raises `KeyboardInterrupt`. Required real-process evidence, unit tests alone not accepted: exit code `3`; the OCR child exits through the parent-gone watchdog; an open PostgreSQL transaction is rolled back; the lease expires; a later runner recovers the document; exactly one extraction result per document version.
  - **Schema:** the runner never applies or alters it and never imports or calls `db.apply_schema`. Before any availability probe or claim it checks the required tables and columns; a missing one gives a names-only diagnostic and exit `1`. Tests prove no DDL runs. Schema application stays with the API startup until FRD Q4.
  - **Connection loss:** any loss ends the process with exit `1`; no in-process reconnect; lease expiry recovers the interrupted attempt; the restart mechanism is FRD Q4.
  - **AC1 and AC2 test design (added).** AC1 positive tests: an AST check that the module's top level holds only imports, constants, definitions and the guarded `main()` call; and a launch with `python -m swasthyoid.workers.extract --once` where the "runner started" line appears exactly once across the process tree while the probe and OCR children demonstrably ran. The unguarded-copy negative control is optional and its omission does not weaken AC1. AC2: a local TCP tripwire as `DATABASE_URL` must see zero connections (libpq connections raise no Python audit event, which was measured on Windows), an audit hook must see no thread or process creation, and stdout, stderr, logging records and the thread count must be unchanged.
  - **AC5 measurement:** a throwaway branch (never `main`, never merged automatically) is approved to measure Linux bootstrap-failure behavior; evidence is reported before any code correction is proposed.
  - **Production-data boundary (unchanged):** a runner outside test mode claims nothing; a runner test shows that with `APP_ENV` unset or `production` and an adapter that looks real, `--once` exits `0` with the document still `uploaded`, 0 attempts and no extraction row. Production extraction stays blocked by 4B, D2 and Q4.
  - **No-bypass rule:** the runner must not bypass the existing adapter allowlist or the availability probe, and no command-line option, environment variable or runner switch may enable production extraction by bypassing those controls. No new production-authorization mechanism is introduced. Test mode is not a security boundary, and production extraction stays blocked pending 4B, D2 privacy approval and the FRD Q4 deployment decisions.
  - **Slice 8.1 — runner skeleton and startup safety (defined 2026-11-13; IMPLEMENTED 2026-11-13 in `2b8038f` and `c4be86d`; CI run #31: 678 passed, 0 skipped, 0 failed).** The text below is the definition; the status follows it.
    - **Implementation status (what exists, what was shown).** `swasthyoid/workers/extract.py` and `swasthyoid/tests/test_runner_startup.py` (58 tests: 54 without a database, 4 PostgreSQL-backed). The startup order, exit codes and `DATABASE_URL` rules above are implemented. Shown by CI run #31 on Linux with PostgreSQL 16 (the pytest log read; test names are not printed, so each test is inferred from the totals): all tests passed with none skipped, which includes the import-purity probe, the safety-check ordering tests and the four PostgreSQL tests (empty database, complete schema, dropped column, a due document left unclaimed). Not part of 8.1 and not implemented: the spawn-based half of AC1, AC3, AC5, the signal and recovery evidence, `run_due()`, `--once` execution and the loop. S6 AC1–AC6 remain mandatory for the completed runner, and none of them is claimed complete by 8.1.
    - **Open points left to the owner (not decided by the implementation):** (1) [SUPERSEDED 2026-11-13 by slice 8.2, commit `553c3db`: `--once` now runs `run_due()` after the startup checks and exits `0` after a completed cycle, so exit `0` no longer occurs without a cycle; the `startup_checks_passed` line no longer exists] a successful 8.1 run exited `0` after logging `startup_checks_passed` although no polling cycle ran, whereas decision 2 defines `0` as a completed cycle or a graceful shutdown; (2) no `connect_timeout` is set when the runner connects, so a blackholed host could delay the exit; (3) `DOCUMENT_STORE` and `DOCUMENT_KEY` are not validated (still an unapproved proposal).
    - **Scope:** a safe startup skeleton only: the runner skeleton and its startup safety. **Slice 8.1 does not execute `run_due()`, does not run a `--once` processing cycle and does not start the long-running polling loop; the `--once` execution path belongs to a later runner-execution slice.** It may test argument and configuration parsing, but it must not claim or process documents. Also not included: signal handling, retry or manual-entry endpoints (slice 8.6 stays blocked on D10, D12, D14), and any production extraction. The meaning of `--once` is unchanged (D9): when implemented later, exactly one `run_due()` call with its normal limit, not exactly one document.
    - **Startup order (checked 2026-11-13 against the 4A code; no conflict found):** (1) the Python main-module guard; (2) `check_test_mode_config()` as the first runtime safety check, before any schema inspection, database connection, child spawn, availability probe or claim; (3) required configuration validation (`EXTRACTION_POLL_SECONDS` in loop mode, plus any other required setting the 8.1 design identifies); (4) read-only schema validation; (5) only after all of these have passed may the runner proceed toward availability probing or claiming, which happen inside `run_due()` and are therefore later-slice work. No schema is applied and nothing is claimed before validation has passed. Evidence: `check_test_mode_config()` (`runtime_mode.py`) only compares two environment variables and performs no I/O; `run_due()` itself runs it first (`_settings()`), runs it again in `check_available()`, then probes, then claims, so this order fits the existing flow and no 4A code has to change; an AST check of `runtime_mode`, `db`, `extraction`, `ocr`, `documents` and `storage` found no module-level call statements (this does not replace the AC2 import-purity test). A missing or unavailable adapter is not a startup configuration error: it stays with the existing availability probe (no claim, a warning; Option A and D13). Side-effect-free argument parsing may run before step 2 (invalid usage exits `2`). It must not connect to the database, inspect the schema, start a process or thread, probe availability, claim a document or run extraction; no other runtime startup operation may precede the safety check, and after valid parsing the safety check runs before any configuration-dependent infrastructure operation (`docs/DECISIONS.md`, "Startup error and ordering contract").
    - **Acceptance (slice 8.1 only):** main-module guard (AC1 structure, AST); import purity (AC2); ordering of the first runtime safety check (AC4: `APP_ENV=test` without the confirmation is refused with exit code `2` and a concise diagnostic that exposes no environment value, before any database connection, schema inspection, spawn or probe); configuration-validation tests, including exit code `2` for invalid command-line usage and for a missing or invalid `EXTRACTION_POLL_SECONDS` in loop mode; exit code `2` for a `DATABASE_URL` that is missing, empty or whitespace-only (no connection attempted, which the tripwire of AC2 can confirm) and for one the parser rejects before any connection, with both a `postgresql://` form and a keyword/value form accepted; exit code `1` for a database connection failure with a value the parser accepted; read-only schema-presence validation with a names-only diagnostic and exit code `1`; no-DDL verification, including against an empty database; no database claim or processing cycle before all required startup checks pass; and the relevant regression tests, with the existing suite still green in PostgreSQL CI (AC6 for this slice).
    - **Whole-runner requirements not completed by 8.1 (S6 AC1–AC6 stay mandatory for the completed runner):** real subprocess spawn and child-execution proof (the spawn-based half of AC1); the PostgreSQL-backed processing-cycle test (AC3); first- and second-signal behavior; OCR-child watchdog behavior; PostgreSQL rollback and lease-expiry recovery after the second signal; Linux hard-kill recovery of the runner and child bootstrap-failure behavior (AC5); recovery by a subsequent runner with exactly one extraction per document version. They belong to the later runner slices (8.2–8.5), whose individual scopes are not yet written into this plan, so no per-requirement slice ownership is assigned here. 8.1 does not claim any of them.
    - **Rollback boundary:** the slice is independently revertible without undoing S5, S6 or the D9 decisions, and without changing the existing schema or any stored data.
    - **Exclusions:** no `apply_schema`, no schema migration, no dependency or workflow change, no production bypass, no slice 8.6 work.
    - **Implementation-design item:** the inventory of required tables and columns is established from the actual queries and code before the schema check is written. No names are fixed here.
    - **Needs confirmation, not approved:** validating `DOCUMENT_STORE` and `DOCUMENT_KEY` at startup is a plan proposal; the decisions on record do not require it.
  - **Proposals, not decisions:** validating `DOCUMENT_STORE` and `DOCUMENT_KEY` at startup, the idle-wait slice length, and the `run_due` stop-hook mechanism.
- **Acceptance.** In test, an uploaded document is extracted without anyone calling a function by hand. Production extraction without a hand call is shown only after 4B.
- **Risks.** A runner without supervision can die silently. Mitigation: documents stay due, so nothing is lost, and the queue-length counter shows it.

## Step 9 — Accuracy evaluation and sign-off (your area 6, second half)

- **Status.** Partly implemented: the evaluation harness (`tests/evaluation/harness.py`: field-level scoring, integrity checks, confidence analysis, CER, WER, failure and empty-output rates), tested with fakes only. **Real accuracy evaluation is not done**: it needs a model run and permitted data (4B, access, license), and no pass marks are set (D11).
- **FRD requirement.** Section 8: "Extraction accuracy — field-level on a labelled synthetic set of printed and handwritten prescriptions — **target agreed with the clinical reviewer**". The FRD sets no numbers, so this plan sets none either.

### Metrics (defined once; computed by 9A, reported for the real model by 9B)

Each is reported separately for printed and handwritten, and per field:

- *Exact-match accuracy* after normalisation, for dates, numbers and short text.
- *Character error rate* for longer text.
- *Precision and recall of rows* for repeated groups such as medicines.
- *Accepted-but-wrong rate:* fields at or above 0.85 whose value is wrong. This is the one that matters most for safety, because those values are shown pre-filled.
- *Manual-entry rate:* how much is left for a person to type.
- *Blur and glare detection rate* and *false-refusal rate* (step 5A).
- *Time per page*, against the 60 s target.

### 9A — Evaluation framework (model-independent; can start now)

- Metrics code, report generator and report format, and a small smoke run for CI. The report records the engine identity, adapter interface version, set version, split and seed.
- OCR-level metrics (character error rate, time per page) need only the adapter interface; they are built on the provisional version and revised if 4B changes it. Field-level metrics run on the test-only synthetic schema until D7 is approved.
- **Tests / acceptance (measurable, no real model needed).** Each metric is verified against hand-computed values for a fake engine with known errors; a perfect fake engine scores 100% and an all-wrong fake engine scores 0% where the metric defines it; the report refuses to mix printed and handwritten into one number; the CI smoke version runs on the fake engine.
- **Fake-engine output from this step is a check of the framework only and is never presented as a model result.**

### 9B — Real-model evaluation and sign-off (waits for 4B and the reviewer)

- Run the integrated model on the held-out split once, after a baseline on the development split.
- **Decisions.** D11: the reviewer sets the targets after seeing a first baseline run. I will bring the baseline; I will not propose pass marks.
- **Acceptance.** The report exists, every agreed target is met on the held-out split, and the reviewer has signed it. Until the model is integrated and D11 is set, M2 has no accuracy result and none is claimed.
- **Risks.** Tuning until the test set passes. Mitigation: the held-out split is used once, for the final run. Training contamination: see step 3.

---

## What can be done before the model is supplied, and what must wait

| Can be implemented and verified before the model is supplied (Track A)                          | Must wait (Track B)                                         |
| ----------------------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| 3A-data synthetic generator, degraded copies, splits                                            | 4B integration of the owner's model (after explicit approval) |
| 3A-harness plumbing (after 4A; fakes and synthetic data only)                                                    | 5B pre-processing configuration for the model               |
| 3B handwritten set (once D3 is decided)                                                         |                                                             |
| 4A infrastructure, version 0 test interface, loader, validator, infrastructure conformance tests, offline and no-fallback enforcement | Compatibility review and the real contract; model-output conformance tests; tuning parsers on real model output (part of 6B) |
| 5A upload validation and quality checks (once D5, D6 are decided)                               | Measuring real time per page and memory                     |
| 6A schema mechanism                                                                             | Production run of the worker with a real engine (part of 8) |
| 6B parser logic after D7, on synthetic text only                                                | 9B real accuracy evaluation and sign-off                    |
| 2 extraction data privacy (once D2 is decided)                                                  |                                                             |
| 7 catalog matching on a synthetic catalog                                                       |                                                             |
| 8 runner, manual entry, endpoints and audit with a test engine in `APP_ENV=test`                |                                                             |
| 9A evaluation framework verified with fake engines                                              |                                                             |

## Decisions needed

| #      | Decision                                                                                    | Needed for       | Owner                         | Status                                      |
| ------ | ------------------------------------------------------------------------------------------- | ---------------- | ----------------------------- | ------------------------------------------- |
| D1     | Lease length per extraction attempt: **5 minutes**                                          | Step 1           | You                           | DECIDED                                     |
| D2     | Encrypt extraction data, and delete raw text after review                                   | Step 2           | You, lawyer                   | APPROVED 2026-11-14: (b), key EXTRACTION_KEY |
| D3     | Who hand-writes the synthetic handwritten set, and how many                                 | Step 3B          | You                           | OPEN                                        |
| D4     | OCR model: **owner-trained and owner-supplied**; the specification, delivery method, who writes the adapter module, and explicit integration approval (see below) | Steps 4B, 5B, 9B | You                           | Model ownership DECIDED; the rest OPEN |
| D5     | Retake policy and "upload anyway"                                                           | Step 5A          | You                           | OPEN (proposal in step 5A)                  |
| D6     | Serve images without EXIF to non-patients                                                   | Step 5A          | You                           | OPEN (proposal in step 5A)                  |
| D7     | Clinical field list, required and optional                                                  | Step 6           | You and the clinical reviewer | APPROVED by owner 2026-11-14; reviewer not named |
| D8     | Drug matching rule                                                                          | Step 7           | Clinical reviewer             | OPEN                                        |
| D9     | How the worker is run                                                                       | Step 8           | You                           | DECIDED 2026-11-13 (DECISIONS.md)                                        |
| D10    | Who may retry or start manual entry (recommended: patient only)                             | Step 8           | You                           | APPROVED 2026-11-14: patient only           |
| D12    | Manual entry from `uploaded` also when an adapter is configured (recommended: yes)          | Step 8           | You                           | APPROVED 2026-11-14: yes                    |
| D13    | Adapter checksum or load failure at worker start: "unavailable", no claim, alert (recommended) or a failed attempt | Steps 4A, 8 | You                     | PARTLY DECIDED: unavailable = no claim + warning (accepted 2026-11-12, in 4A); alert mechanism OPEN |
| D14    | Audit 409 state-conflict refusals too (recommended: no)                                     | Step 8           | You                           | APPROVED 2026-11-14: no                     |
| D15    | M3 may start once M2 is infrastructure-complete                                             | M3 start         | You                           | OPEN                                        |
| D16    | Accept the P0 gate deviation (`docs/DECISIONS.md`)                                          | Record keeping   | You                           | OPEN                                        |
| D17    | 4A model-independent infrastructure scope; version 0 as an infrastructure-test interface only (`DECISIONS.md`) | Step 4A | You | **APPROVED WITH REVISIONS 2026-11-12**; sub-choices accepted 2026-11-12; plan Revision 4 frozen and implementation approved; built on branch `4a/ocr-infrastructure`, merged into `main` 2026-11-13 (historical) |
| D18    | Model-dependent contract items (input, page handling, document hints, output, granularity, serialization, confidence, box or position, production `raw_text`, limits, batching, timeouts, process model, resources, manifest format and checksum computation, model-specific retry semantics) | Step 4B | You, after the specification | OPEN — not decided before the model specification |
| D11    | Accuracy and detection targets                                                              | Steps 5A, 9B     | Clinical reviewer             | OPEN                                        |
| FRD Q1 | Drug catalog source                                                                         | Step 7           | You                           | OPEN                                        |
| FRD Q7 | Clinical reviewer named                                                                     | Steps 6, 7, 9    | You                           | OPEN                                        |
| FRD Q8 | Retention (lawyer's view)                                                                   | Step 2           | You, lawyer                   | DECIDED 2026-11-14: delete at verification or rejection |

### D4 — what the owner supplies (specification intake, all OPEN until supplied; integration also requires explicit owner approval)

| Item                                                                    | Why it is needed                                      |
| ----------------------------------------------------------------------- | ----------------------------------------------------- |
| Model artifact, format and runtime or framework                         | Decides the model-specific runtime module in 4B       |
| Version identifier and SHA-256 checksum                                 | Pinning and the integrity check                       |
| Ownership and licence statement                                         | Build and distribution                                |
| Scripts and languages covered (Bangla, English, mixed)                  | Maps to the FRD OCR requirement and to 9B reporting   |
| Input requirements (size, colour, scaling, any required pre-processing) | Sets 5B                                               |
| Output form (line, word or character level; box format; reading order)  | Compatibility review of the provisional 4A interface  |
| Process model the runtime needs (in-process library, own process, separate executable or server), batching | Compatibility review of the step 1 worker design |
| Status of development (architecture, framework, dataset chosen by the owner, if the owner wishes to record them) | Context for the review only; none is chosen by the implementer |
| Meaning of the confidence value                                         | Needed for the 0.85 rule and calibration in 6B and 9B |
| Resource needs (memory, CPU or GPU)                                     | Deployment and the time limits                        |
| Load time                                                               | Affects the 10-minute hard timeout                    |
| Where large artifacts are stored, and how they enter a deployment (mounted read-only, or packaged into the build) | Delivery without run-time download; nothing bundled without approval |
| Who writes the model-specific adapter module                            | The owner, or the implementer only after explicit approval |
| Whether the generator should also produce training or validation data   | Split policy in step 3                                |

## M2 exit gate

M2 is **production-ready** only when all of these hold and are shown by tests or a signed report. M2 is **infrastructure-complete** when the Track A parts hold with test adapters (see "Readiness levels"): 1a, 1b, 1c, 2, the infrastructure part of 3, and 4, 5, 6, 8, 9.

1. Bounded time, scoped to adapter availability (Option A, `docs/DECISIONS.md`):
   - **1a.** Every document claimed while a configured adapter is available reaches `needs_review` or `extraction_failed` within 3 x (max(hard timeout, lease) + retry wait + polling interval) of its first claim, including when workers crash or hang, with at most one extraction per version. Shown with test adapters for infrastructure-complete; shown again on the integrated owner model for production-ready.
   - **1b.** With no adapter available, nothing is claimed, attempts stay 0, no document becomes `extraction_failed`, every such document can be moved to `needs_review` by manual entry, and the queue-length counter shows them waiting.
   - **1c.** Manual entry and extraction never both store a result for a document.
2. No extraction path writes an event. Only M3's confirm step can.
3. *Infrastructure part:* the OCR infrastructure of 4A is implemented and enforced, with version 0 as an infrastructure-test interface only (the infrastructure conformance tests pass with test adapters); fake engines are refused outside test; no fallback engine exists. *Production part:* only after the owner has supplied the trained model and complete specification, the compatibility review has been approved, and integration has been explicitly approved, the owner-supplied model is integrated through the approved contract (4B), passes the infrastructure and model-output conformance tests, runs with no network access, and has its load time and time per page recorded.
4. Blur and glare are detected at upload, with retake guidance, at the rates agreed in D11.
5. The approved clinical field list is implemented exactly, with required and optional fields, validation and a confidence per field, and its approval is recorded.
6. Drug names are matched to a catalog; no drug is selected without a person; unrecognised names are always flagged.
7. The accuracy report is produced from the integrated owner model, meets every target agreed with the clinical reviewer on the held-out split, and is signed. Fake-engine results are not accepted for this gate.
8. No readable document text sits in the database, logs or backups; cloud AI is off.
9. The full suite passes in CI, and that result has been checked, not assumed.

Not part of M2: verification (M3), the timeline (M4), the safety rules themselves (M6), training the OCR model, and choosing an OCR engine.