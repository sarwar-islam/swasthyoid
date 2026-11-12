# Decision log

P0 exit gate (FRD section 11): all five decisions below recorded.
Questions are copied from FRD section 12. Options are listed only where the FRD names them.

## Q1 — Which drug catalog source can we legally use, and on what terms?

- **Status:** OPEN
- **Options:** not listed in the FRD. Note (FRD section 12): do not reuse MedBangla AI code or catalog until its author confirms licence and origin in writing.
- **Decision:**
- **Owner:**
- **Date:**

## Q2 — MongoDB + Qdrant, or one PostgreSQL with pgvector and pg_trgm?

- **Status:** DECIDED
- **Options:** (a) MongoDB + Qdrant; (b) one PostgreSQL with pgvector and pg_trgm
- **Decision:** (b) one PostgreSQL. pgvector and pg_trgm are added when P3 needs them.
- **Owner:** Sarwar Islam
- **Date:** 2026-11-11

## Q4 — Where is the system hosted, and must health data stay in Bangladesh?

- **Status:** OPEN
- **Options:** not listed in the FRD
- **Decision:**
- **Owner:**
- **Date:**

## Q5 — Which cloud AI provider and terms, or local-only?

- **Status:** OPEN
- **Options:** (a) a cloud AI provider (which one, on what terms; patient opt-in only); (b) local-only
- **Decision:**
- **Owner:**
- **Date:**

## Q7 — Which clinician signs off rules, red flags, thresholds and emergency messages?

- **Status:** OPEN
- **Options:** a named clinical reviewer
- **Decision:**
- **Owner:**
- **Date:**

---

# Caregiver access (P2 architecture change)

Approved by Sarwar Islam, 2026-11-12. Elderly and digitally inexperienced patients may be
helped by a caregiver. This is not in the FRD yet; the FRD changes it needs are listed below.

## Decided

- A caregiver authorization is a consent: purpose `CAREGIVER` in the existing `consents` table,
  judged by the existing C1 engine and audited by C2. No separate permission system.
- A caregiver is an ordinary person account and logs in with their own phone.
- Scopes, each granted separately: `upload_documents`, `view_documents`, `view_timeline`.
- The patient is the only source of authorization, either signed in to the app or by reading
  out a code sent to the patient's own phone. The caregiver can only ask.
- Scopes never change on an existing authorization. More scopes or more time is a new request
  with a new approval, which replaces the old authorization in one transaction.
- One active and one pending authorization per patient-caregiver pair, enforced by the database.
- Verification stays patient-only. Caregivers cannot verify, and no clinical trust is placed in
  caregiver-confirmed data. The database refuses a caregiver verification scope.
- `DEV_LOG_CODES` defaults to 0. Codes are logged only with `DEV_LOG_CODES=1` and
  `APP_ENV=development`; the application refuses to start with the flag set in any other
  environment. Automated tests use mocked delivery.

## Provisional (to be confirmed against the FRD)

| Setting | Value | Where |
|---|---|---|
| Default duration | 30 days | `core/consent_authz.py` |
| Maximum duration, no permanent authorization | 90 days | `core/consent_authz.py` and the `caregiver_shape` constraint in `core/schema.sql` |
| Renewal | explicit new request and approval | by design |
| Unapproved request closes after | 24 hours, enforced at request time | `core/consent_authz.py` |

## Configurable security defaults (not FRD values)

| Setting | Value | Where |
|---|---|---|
| Code lifetime | 5 minutes | `identity/otp.py` |
| Wrong guesses before a code is dead | 5 | `identity/otp.py` |
| Codes per patient phone, per kind | 5 per 15 minutes | `identity/otp.py` |
| Codes per caregiver request | 3 | `api/caregivers.py` |
| Requests per caregiver (hits and misses alike) | 5 per 15 minutes | `api/caregivers.py` |
| Minimum response time for request and confirm | 0.3 s | `api/caregivers.py` |
| Idempotency-Key retention | 24 hours | `api/deps.py` |

## FRD changes required

*Status 2026-11-12:* all six changes below are applied in the FRD v3 revision (sections 2, 4.1,
6.2, 6.5 and 7); that revision awaits owner approval. The list is kept as originally recorded.

- **4.1 consent purposes:** add `CAREGIVER` (grantee: caregiver; bound to patient and caregiver;
  scope: the three permissions above; activates on patient approval; ends on expiry, revoke or
  replacement).
- **4.1 consent state machine:** add `pending --> declined : patient declines` and
  `declined --> [*]`. `declined` (the patient said no) is distinct from `expired` (nobody answered).
- **Section 2 roles:** add the caregiver, with can/cannot (cannot verify, grant, revoke or read
  access history for the patient).
- **Section 7 API:** add the `/caregiver-authorizations` endpoints.
- **ERD A:** `consents.requested_ttl`; `consents.grantee_id` may reference a person account.
- **ERD D:** `idempotency_keys` is keyed by caller, endpoint and key, and stores a keyed hash.

## Future requirement, not implemented

- **Assisted registration.** A patient with no phone or no account cannot be helped by this
  design, because every authorization needs the patient's own approval. A separate
  assisted-registration flow (for example staff-assisted, with identity checks) is needed and
  must be designed before it is built. Related: FRD open question 12 (minors and guardians).

---

# Extraction field list (P2 slice 2) — PROPOSED, not approved

The FRD asks M2 to "parse to a typed schema" but lists no fields. The pipeline is built and
takes the list as data (`SCHEMAS` in `swasthyoid/capture/extraction.py`), which is **empty
until this list is approved**. With it empty, every document goes to review with its raw text
only. Approval is needed from the owner and from the clinical reviewer (question 7, still open).

Every field is a transcription of what is written on the paper. Nothing is interpreted,
coded or inferred. Kinds: `text`, `number`, `date`; `[]` marks a repeated group.

## prescription

| Field | Kind |
|---|---|
| `prescription_date` | date |
| `prescriber_name` | text |
| `prescriber_registration` (BMDC number as printed) | text |
| `facility_name` | text |
| `diagnosis_text` (as written) | text |
| `medications[]`: `name_as_written`, `strength`, `form`, `dose_instruction`, `duration` | text each |
| `advice_text` | text |
| `follow_up_date` | date |

## lab_report

| Field | Kind |
|---|---|
| `report_date` | date |
| `lab_name` | text |
| `tests[]`: `test_name`, `result` (text, since results may be words), `unit`, `reference_range` | text each |

## discharge_summary

| Field | Kind |
|---|---|
| `admission_date`, `discharge_date`, `follow_up_date` | date |
| `facility_name`, `diagnosis_text` | text |
| `medications[]` as for a prescription | text each |

## other

No fields: raw text only, for manual entry.

## Questions for the reviewer

1. Which fields must be filled before a document can be confirmed?
2. Should the patient name printed on the paper be captured, to flag a document that belongs
   to someone else?
3. Should allergies noted on a prescription have their own field?
4. Is `diagnosis_text` copied from paper allowed to become a diagnosis event, or only shown
   with the document?
5. Are dose and duration kept as free text (proposed), or split into number and unit?

---

# Extraction thresholds and privacy (P2 slice 2)

## Thresholds

| Setting | Value | Status |
|---|---|---|
| Manual review (`CONFIDENCE_THRESHOLD`) | 0.85 | FRD M3 start value, configurable |
| Send to cloud AI (`CLOUD_AI_THRESHOLD`) | not set | DECISION-PENDING. The FRD gives no number and does not say it equals the review threshold. While unset, nothing is sent to a cloud AI, whatever the patient opted in to. |

The two are independent. A cloud AI answer is judged against the review threshold like any
other reading, and never replaces an accepted reading with a rejected one.

## Privacy risk: unverified document text is stored in plain form

- **What is stored.** `extractions.raw_text` holds everything the OCR read from a document,
  and `extractions.fields` holds each value read (including the `raw` reading of fields left
  for manual entry). This is unverified health data: names, drugs, diagnoses.
- **Why it is a risk.** The original images are encrypted on disk, but this text is not. Anyone
  with database access, a backup, a replica or a query log can read it. The table is
  append-only, so the text also cannot be removed once a document is verified or rejected.
  FRD section 9 asks for data minimisation ("store only schema fields"), which `raw_text`
  arguably breaks even though the ERD lists the column.
- **Current exposure.** Synthetic data only. Access through the API is limited to the patient.

**Proposed mitigation before any real patient data (not implemented):**

1. Encrypt `raw_text` and `fields` at field level, with a key separate from the database
   (the same approach as phone and name), so a database dump alone reveals nothing.
2. Stop keeping `raw_text` after review: move it out of the append-only table into a store
   that is deleted when the document is verified or rejected, keeping only its hash.
3. Keep database encryption at rest, restrict the application role to the columns it needs,
   and make sure statement logging never records these values.
4. Add extraction data to the patient export-and-delete flow the FRD requires.

Owner decision needed on 1 and 2, and a lawyer's view on retention (FRD open question 8).

---

# Extraction worker recovery (P2 slice 2) — limitation and proposed fix

**Status: record of the state at commit `6021085`. Limitations 1 to 3 were then addressed by
"Worker reliability (M2 step 1)" later in this file, which the owner marked complete on
2026-11-12. The labels below are kept as written at the time of the proposal.**

Tests: `swasthyoid/tests/test_extraction_recovery.py`.

## How it works today

- **The table is the queue.** No job is handed to a worker. A document is due when its status
  is `uploaded`, or `extracting` with its retry time reached. Every run looks for the oldest
  due document.
- **One transaction per attempt.** A worker locks the document row, reads it, stores the
  result and changes the status, all in one transaction. Nothing is visible to anyone else
  until it commits.
- **A worker that loses a race waits** for the winner's lock, then finds the document no longer
  waiting, does nothing, and ends its run. Whatever it did not do is still due, so the winner
  (which carries on) or the next run takes it.
- **A worker that crashes or loses its connection** has its whole transaction rolled back by
  the database. The document is exactly as it was and the next run extracts it.
- **No duplicates in any of these cases.** A result is stored only by a worker holding the row
  lock, and `(document_id, version)` is unique.

## Limitations

1. **One hung worker blocks every worker.** All workers pick the same oldest document and wait
   for its lock, so they never reach documents nobody is working on. Workers also do not run
   in parallel for the same reason.
2. **A hung worker is never timed out.** A worker stuck in OCR without crashing keeps the lock
   until its connection dies.
3. **A crash is not counted as an attempt.** The attempt counter is rolled back with everything
   else, so a document that always crashes its worker is retried for ever and never becomes
   `extraction_failed`.
4. **A cloud AI send would be audited inside the same transaction.** A crash after sending
   would lose the audit entry and send the data again on retry. Not reachable today: no
   provider exists and the cloud AI threshold is unset.

## Proposed smallest safe fix — PROPOSED, NOT IMPLEMENTED

Each item below is a proposal awaiting approval. No product code has been changed for any of them.

1. **PROPOSED, NOT IMPLEMENTED — Skip locked documents.** Pick and lock the next document in one statement with
   `FOR UPDATE SKIP LOCKED`. A busy document is passed over, so workers run in parallel and a
   hung worker holds up only its own document. About five lines; fixes limitation 1.
2. **PROPOSED, NOT IMPLEMENTED — Time out hung workers in the database.** Open worker connections with
   `idle_in_transaction_session_timeout` set to the longest extraction allowed. PostgreSQL
   then ends a stuck session and rolls it back, which is the already-tested crash path. One
   line; fixes limitation 2. The value needs a decision (FRD target: 60 seconds per page).
3. **PROPOSED, NOT IMPLEMENTED — Count the attempt before the work.** Commit `extraction_attempts + 1` in a short first
   transaction, then do the work in a second one that stores a result only if the attempt
   number is still its own. A crash or timeout then counts, and a poison document stops after
   three attempts. About fifteen lines; fixes limitation 3 and stays duplicate-free.
4. **PROPOSED, NOT IMPLEMENTED — Audit a cloud AI send before sending**, in its own committed transaction. To be done
   with the provider (question 5).

Celery and Redis are not needed for any of this; they only decide what calls the worker.

---

# Worker reliability (M2 step 1) — COMPLETE (marked by the owner, 2026-11-12)

**Marked complete by the owner on 2026-11-12** after `main` was pushed (`origin/main` =
`3f348d3`) and GitHub Actions run #15 (`43265164599`) on `main` passed: ubuntu-26.04, Python
3.12.16, PostgreSQL 16.15, 259 passed, 0 failed, 0 skipped, 0 errors. Step 1 consists of
`1ebdb15` and the S1 fix `6b11e65` (cherry-pick of `cc836f5`). Review findings S2–S8 below stay
open and are not part of Step 1.

Approved requirements from the owner on 2026-11-12; code in
`swasthyoid/capture/extraction.py`, tests in `swasthyoid/tests/test_extraction_recovery.py`.

## Verification and the S1 fix (2026-11-12)

- **Linux CI on Step 1 as committed** (`1ebdb15`, branch `verify/step1-1ebdb15`, GitHub Actions
  run #13, `43259228167`): ubuntu-26.04, Python 3.12.16, PostgreSQL 16.15. **258 passed, 0
  failed, 0 skipped, 0 errors.** All 220 database tests ran, including the 22 recovery tests,
  the process spawn and kill tests, and the timing-sensitive tests.
- **S1, found in review:** when the database connection was lost during an attempt, the worker
  tried to record the failure on the dead connection, and that second error escaped `run_due`
  and `extract`. Nothing was written and lease expiry still recovered the document, but the
  docstrings promised no error.
- **S1 fix, accepted by the owner 2026-11-12** (`cc836f5` on `verify/step1-1ebdb15`;
  cherry-picked onto `main` as `6b11e65`, code identical; `main` pushed and passed run #15): new
  `WorkerConnectionLost`. Before each failure write the worker checks
  `conn.closed`; if the connection is gone it raises `WorkerConnectionLost` from the original
  error and writes nothing more. The check looks at the connection, not the error type, because
  statement and lock timeouts raise the same error class but leave the connection usable.
  Docstrings of `_attempt`, `extract` and `run_due` updated. New test
  `test_database_connection_lost_during_ocr_writes_nothing_and_is_recovered`
  (`pg_terminate_backend` mid-attempt) shows: no extraction row, attempt 1 still counted and
  claimed, the OCR child killed, recovery after real lease expiry, attempt 2 completes.
- **Linux CI on the fix** (`cc836f5`, run #14, `43260900552`), same environment: **259 passed, 0
  failed, 0 skipped, 0 errors.**
- **Remaining from the review (not fixed, not approved for fixing):** S2 a Windows-only pipe error
  may be recorded as `BrokenPipeError` instead of `WorkerDied`; S3 a child that fails to start
  leaks pipe handles and uses an attempt; S4 option values are not validated; S5 image reading
  and field shaping run outside the heartbeat; S6 the future runner needs a main-module guard for
  spawn; S7 the daemon OCR child cannot use multiprocessing itself; S8 no index for the due-row
  query. Also: if the connection drops *during* the failure write itself, the raw database
  error still escapes (nothing is written either way).
- One green run per commit does not rule out occasional failures of the timing-sensitive tests.

## Settings (configurable, owner-approved, not FRD values)

| Setting | Value | Constant |
|---|---|---|
| Lease per claim | 5 minutes | `LEASE` |
| Heartbeat (lease renewal) | every 60 seconds | `HEARTBEAT` |
| Hard timeout for the OCR process | 10 minutes | `HARD_TIMEOUT` |
| Maximum attempts, then `extraction_failed` | 3 | `MAX_ATTEMPTS` |
| Wait before a retry | 1 minute, doubling | `BACKOFF` |
| Database backstop on worker connections | 60 s statement, 60 s idle-in-transaction, 10 s lock wait | `db.connect_worker` |

## How a job runs

1. **Claim** (short transaction). Take the oldest due document that no other worker has
   locked (`FOR UPDATE SKIP LOCKED`), add one to the attempt counter, write a new random
   claim token and set the lease end. Commit.
2. **Work** (no transaction open). Read the images and run the engine in a child process.
   Every heartbeat the worker renews the lease; a lease that has already run out cannot be
   renewed. At the hard timeout the child process is killed and the attempt has failed.
3. **Store** (short transaction). Lock the row and store the result only if the claim token
   is still this attempt's **and** the lease has not run out. Otherwise nothing is written.
   A failed attempt is recorded under the same two conditions.

A document is due when it is `uploaded`, or `extracting` with its time reached. That one
time is the lease end while a claim is held, and the retry time after a recorded failure.

## What happens when things go wrong

| Situation | Outcome |
|---|---|
| Two workers want the same document | One claims it; the other skips it and takes a different one |
| Worker dies right after claiming, or during OCR | The attempt is already counted. When the lease ends the document is due again as the next attempt |
| OCR process dies | Attempt recorded as `WorkerDied`, retried after the wait |
| OCR hangs | Killed at the hard timeout, attempt recorded as `HardTimeout` |
| Worker is killed while its OCR child runs | The child sees its parent is gone and exits within about a second |
| A worker finishes after its lease ran out | Its result is refused, whether or not another worker took the document |
| A stale worker reports a failure | Ignored, whether or not another worker took the document: the token or the lease no longer holds |
| Every attempt lost without a report | The next claim closes the document as `extraction_failed` (`LeaseExpired`) |

## Bounded time to a terminal state

With at least one worker checking the queue every P seconds, a document reaches
`needs_review` or `extraction_failed` within

    3 attempts x (longest attempt + wait before retry + P)

where the longest attempt is the larger of the hard timeout (10 min) and the lease (5 min),
and the waits are 1 and 2 minutes after the first and second attempts. With the defaults that
is about 33 minutes plus three polling intervals, in the worst case where every attempt hangs
to the limit.

## Rules enforced

- **In-process OCR is refused unless `APP_ENV=test`.** That mode has no heartbeat and no hard
  timeout. The refusal happens before anything is claimed.
- **The heartbeat must be shorter than the lease**, or the settings are refused.
- **An `extracting` document always has a due time.** A database constraint
  (`extracting_has_time`) refuses a row without one, and the state-machine call sets it.

## Invariants kept

- A job is still keyed by (document, version); a repeat does nothing, and `(document_id,
  version)` is unique in the database.
- No extraction path writes an event. The child process has no database access at all.

## Remaining limitations

- **Nothing runs the worker yet.** The bound above assumes a worker is polling. The runner
  is step 8 of the M2 plan. Until it exists, `db.connect_worker` (the connection with
  database timeouts) is used only by its own test, so no real worker has that backstop.
- **Verified on Linux CI since this was written** (runs #13 and #14, see "Verification and the
  S1 fix" above); the note below is kept as written. **Not verified on Linux or in CI.**
  Everything here was run on Windows against a local
  PostgreSQL 16. Process spawning and killing behave differently on Linux, and several
  recovery tests depend on short timings that a slow CI machine could miss.
- **The engine must be sendable to a child process** (a module-level function). One that is
  not fails at start-up of the child and uses up the document's attempts.
- **Killing the OCR process does not kill programs it started itself.** This matters if the
  chosen engine launches a separate program.
  *Note added 2026-11-12:* no engine is chosen by the implementer. Read "the chosen engine" as
  "the owner-supplied model's runtime" (see "AI models are owner-supplied" below).
- **The integration tests still run the in-process mode** (under `APP_ENV=test`); only the
  recovery tests exercise the child-process path.
- **A new child process per document** means the OCR models load each time. Acceptable for a
  prototype; a long-lived OCR process is a later optimisation.
- **Clock.** Leases use the database clock only, so worker clocks do not matter, but a
  worker that stalls completely (for example a frozen machine) can only be fenced, not
  stopped: its late result is refused when it tries to store.
- **Cloud AI.** The send is now audited in its own committed step before sending, but a
  retried attempt would send again. Not reachable: no provider, threshold unset.

---

# AI models are owner-supplied — DECIDED

Owner: Sarwar Islam. Date: 2026-11-12. Replaces the earlier plan to choose an OCR engine
(RapidOCR or Tesseract), which is obsolete.

- The owner trains and supplies the OCR model (and any later AI model). The platform provides
  only model-independent infrastructure: versioned adapter contracts, loader, validators,
  conformance tests and configuration (FRD invariant 10, section 8).
- The implementer never selects, installs, downloads, bundles or integrates any AI model,
  OCR engine or pretrained weights.
- There is no automatic fallback from one model or engine to another. A failed attempt fails.
- Fake or test adapters exist for tests only and are refused outside `APP_ENV=test`.
- Integration of the owner's model (plan step 4B) starts only after the owner has supplied the
  model and its full specification (plan D4) **and** explicitly approved the integration.
  Supplying the model alone does not authorise integration or deployment.
- How the artifact enters a deployment (mounted read-only, or packaged into the build) and who
  writes the model-specific adapter module are part of D4 and need the owner's approval.

Code today: no model or engine dependency exists (`pyproject.toml`). Only fake engines in
`swasthyoid/tests/` implement the current engine contract.

---

# No OCR adapter available: stay due, direct manual entry — DECIDED (Option A)

Owner: Sarwar Islam. Date: 2026-11-12. The design below is PROPOSED and NOT IMPLEMENTED.

**Decision.** A document for which no OCR adapter is available stays due (status `uploaded`)
and can go straight to manual entry. It is never marked `extraction_failed` just because no
adapter is configured.

The code has no status named `due` or `extraction_pending`. "Due" is the condition in
`capture/extraction.py` (`uploaded`, or `extracting` with its due time reached). `uploaded` is
the state that means "waiting for extraction". No status is renamed; renaming would need a
migration and buys nothing.

## Proposed design (not implemented)

| Question | Proposal |
|---|---|
| Source states for manual entry | `uploaded`; `extracting` with no live claim (claim token empty, or lease already run out); `extraction_failed` (as today). Refused with 409 `extraction_in_progress` while a live claim is held. Refused from `needs_review`, `verified`, `rejected` |
| Target state | `needs_review`, with one extraction row at the next version: engine `manual`, empty raw text, every field marked for manual entry (the existing `manual_entry()` result). No new state |
| Checks | One transaction: lock the row (`FOR UPDATE`), check the source state and claim, clear claim and due time, store the manual row, write the audit entry |
| Audit | `document.manual_entry`: actor, role, patient, document, result `allow`, source state. No document text. Same transaction as the change, so an audit failure blocks it (fail closed). No C4 event |
| Race with a worker | Manual entry first: a claim (`SKIP LOCKED`) skips the row and afterwards finds it no longer due. Claim first: manual entry sees the live claim and gets 409. Expired-lease worker: its store and failure writes need status `extracting` and its own token, so they write nothing. `UNIQUE (document_id, version)` is the backstop |
| Migration | None. The status constraint already allows every status. Changes are application-level: add `uploaded -> needs_review` to `TRANSITIONS`; give `manual_entry()` an actor, the claim check and the audit entry; add the endpoint (plan step 8); change the test that pins manual entry to `extraction_failed` only |
| Runner rule | The runner checks that an adapter is available **before any claim**, as the in-process refusal does today. Otherwise a claim counts an attempt and a missing adapter would end in `extraction_failed` |

## Bounded-time gate, scoped

- **1a, adapter available:** every document claimed while a configured adapter is available
  reaches `needs_review` or `extraction_failed` within 3 x (max(hard timeout, lease) + retry
  wait + polling interval) of its first claim; at most one extraction per version.
- **1b, no adapter:** nothing is claimed, attempts stay 0, nothing becomes
  `extraction_failed`, every such document can be moved to `needs_review` by manual entry, and
  the queue-length counter shows them waiting.
- **1c, races:** manual entry and extraction never both store.

Time is counted from the first claim; the wait before it depends on runner capacity.
Infrastructure readiness is shown with test adapters; production readiness needs 1a again on
the integrated owner model (plan 4B, 9B).

## Sub-decisions still OPEN (recommendations, not decided)

These are tracked in `docs/M2_COMPLETION_PLAN.md` as 1 = D12, 2 = D13, 3 = D14, 4 = D10.

1. Manual entry from `uploaded` also when an adapter is configured (patient's choice)?
   Recommended: yes, always allowed.
2. Adapter that fails its checksum or load at runner start: "unavailable" (no claim, documents
   stay due, alert) or a failed attempt? Recommended: unavailable. A failure inside an attempt
   still counts as an attempt.
3. Audit 409 state-conflict refusals too? Recommended: no; authorization denials are already
   audited by the gateway chain.
4. Who may start manual entry: plan D10. Recommended: patient only, like viewing the extraction.

---

# OCR model not yet developed: provisional adapter interface only — DECIDED

Owner: Sarwar Islam. Date: 2026-11-12. Extends "AI models are owner-supplied".

**Facts.** OCR model development has **not started**. The owner has not selected an
architecture, framework, dataset or trained model. The owner will independently select, train,
own and supply it.

**Decision.**

1. Only model-independent infrastructure is built now, around a **provisional, framework-neutral
   adapter interface**. The interface is not frozen. It exists so the infrastructure can be
   exercised with test-only fake adapters.
2. **Model-dependent decisions stay OPEN** until the owner supplies the model specification (plan
   D4): page input and output details, confidence (whether present, its range and meaning),
   position or bounding-box format, text granularity, page and line limits, batching, timeout
   values (load, per page, per attempt), process model, and resource requirements.
3. **The future model is not forced to fit the provisional interface.** When the specification
   arrives, the interface is reviewed against it and revised to fit the model. Incompatibilities
   are presented to the owner with options; neither the model nor the worker design is changed
   without the owner's approval.
4. Nothing is selected, installed, downloaded, trained or integrated by the implementer. No
   model artifact is bundled or deployed without the owner's explicit authorization.
5. Model-specific adapter implementation, integration and production deployment require the
   owner's specification **and** explicit approval.
6. **Infrastructure-complete is not production-ready.** Infrastructure-complete is shown with
   test adapters only. Production-ready needs the owner's integrated model, measured and signed
   off (plan "Readiness levels").

## Status of the 4A contract proposal of 2026-11-12

A full contract proposal (lifecycle, page input and output, line text, confidence, box, identity,
availability, errors, fakes, privacy, conformance, compatibility; owner choices numbered 4A-1 to
4A-24b) was presented in the session of 2026-11-12. It was **not approved and is not recorded as
a contract.** Under this decision its items are split:

| May be settled now (model-independent) | Stays OPEN until the model specification (model-dependent) |
|---|---|
| Adapter named by a stable reference in configuration and imported where OCR runs (no pickled objects) | Lifecycle detail beyond "identify, prepare, read, release": load once or per attempt, long-lived process (4A-1), batching (4A-21) |
| Adapter availability checked before any claim (Option A); unavailable means no claim, no attempt, documents stay due | What the adapter receives: encoded image, decoded pixels, page or whole document, document-type hint (4A-2, 4A-3, 4A-10) |
| Whether an integrity or load failure before any claim means "unavailable" (D13) | What it returns: granularity, confidence and its meaning, position format, reading order, size limits, strictness on one bad item (4A-4 to 4A-9) |
| Identity recorded with every extraction: engine id, model version, model checksum, interface version, optionally adapter version (4A-20); field names provisional | How the checksum is defined for the artifact (single file or manifest) (4A-11); how deep the pre-claim check goes, including a probe load (4A-12) |
| Typed failure codes, attempts and retries as in step 1; no fallback; nothing stored from a failed attempt. (Model-specific retry semantics, including whether malformed output is retried (4A-17), wait for the contract: D17 revision 6) | Timeout values: load, per page, per attempt, and whether a per-page limit exists at all (4A-14) |
| Fake adapters refused outside `APP_ENV=test` before any claim; approved-adapter list in configuration (4A-18) | Resource limits (4A-22); whether the runtime needs its own process or a separate executable |
| Killing the whole OCR process group (4A-15); no-network enforcement in tests (production: 4A-16, FRD Q4) | Whether the provisional per-page output becomes the real contract at all |
| Privacy: no document text in logs, exception messages discarded, OCR process output streams discarded outside test; version 0 items and positions never persisted (4A-19, decided by D17) | |
| A versioned contract with an owner-approved change process (4A-24); a repository-wide import allowlist lint | |
| The platform, not the adapter, enforcing whatever time limits are set (4A-23) | |

Owner decisions remaining from that list: see D17 below. 4A-18 (allowlist) and 4A-19 (no
persistence) are decided by D17; 4A-17 moved to the model-dependent side; D13, 4A-15, 4A-16,
4A-20, 4A-23, 4A-24 remain open; the model-dependent ones wait for D4 and D18.

## Consequences for the plan

- **4A becomes 4A-infra** (model-independent, can be built after approval) **plus the
  provisional interface version 0** (test-only, expected to change). Nothing in the
  infrastructure may depend on the provisional output's details beyond passing it through a
  versioned validator.
- **The conformance suite has two parts** (named by D17: infrastructure conformance tests and
  model-output conformance tests). The infrastructure part is fixed now. The
  model-dependent output checks are written or revised after the specification is reviewed, so
  "the suite runs unchanged against the real model" no longer holds.
- **Version 0 is an infrastructure-test interface only** (D17 below). 3A-harness, 6B parsers and
  9A metrics may use it only in synthetic infrastructure tests; their production input waits for
  the model specification (D18).
- No current code or schema changes as part of this decision.

---

# D17 — 4A model-independent infrastructure scope — APPROVED WITH REVISIONS

Owner: Sarwar Islam. Date: 2026-11-12. Nothing is implemented yet. The proposal reviewed was
the "4A scope and provisional interface version 0" of 2026-11-12, revised as below.

**What D17 approves:** building the model-independent OCR infrastructure of plan step 4A,
verified with test-only fake adapters, under the revisions below.

**What D17 does not approve or authorise:**

- Version 0 as an OCR model contract. It is **not** an approved contract of any kind.
- Implementing any real OCR adapter; selecting, installing, downloading, training, bundling or
  deploying any model; production deployment of OCR. Each still needs the owner's model
  specification (D4) and explicit approval.

## Revisions recorded as decisions

1. **Version 0 is an infrastructure-test interface only.** Its shape (`identity`, `prepare`,
   `read(document)`, `release`; `pages`, `items`, `text`, `confidence`, `position`) exists only to
   exercise the infrastructure with fakes. It is not a production requirement and nothing may
   treat it as one.
2. **Model-dependent contract items stay OPEN until the trained model's specification** (D18):
   actual OCR input and output, granularity, confidence semantics, bounding-box or position
   format, page handling, document hints, batching, and output serialization.
3. **`raw_text` construction from version 0 output** (items joined in order, blank line between
   pages) may be used **only in synthetic infrastructure tests**. It is not a permanent rule. How
   production `raw_text` is formed is part of D18.
4. **Process-per-attempt** (a separate OCR process per attempt, killed at the 10-minute hard
   timeout) is the **current implementation baseline**, not a model requirement. It is
   reassessed in the 4B compatibility review.
5. **Checksum verification infrastructure is built now** (verify declared artifact files against
   expected SHA-256 values before use, fail closed). **The final artifact-manifest format, and how
   `model_checksum` is computed from it, stay OPEN** until the artifact structure is known. The
   version 0 manifest is test-only.
6. **Retry infrastructure is kept** (step 1: attempts, backoff, maximum attempts, every failure
   inside an attempt counts). **Model-specific retry semantics** (for example whether malformed
   output or a model-specific error is retried or closes the document at once) are **not
   defined** until the actual adapter contract is approved.
7. **Version 0 page items and positions are not persisted.** No real patient data is used in OCR
   execution until the required encryption and privacy controls (plan step 2, D2) are implemented
   and approved by the owner.
8. **Preserved, not weakened:** the owner-controlled adapter allowlist (only the owner changes
   it); no fallback to another adapter or engine; fake and test adapters refused outside
   `APP_ENV=test` before any claim; typed errors with only the code stored; process isolation of
   OCR from the database and the worker; explicit owner approval for integration and deployment.
9. **Conformance tests are split.** **Infrastructure conformance tests** (availability, integrity,
   allowlist, fake refusal, no fallback, typed errors, hard timeout, isolation, no network in
   tests, privacy of logs and errors, identity recorded, import lint) are in scope for 4A.
   **Model-output conformance tests** are out of scope for 4A and are written after D18.
10. **D17 authorises infrastructure only.** See "What D17 does not approve" above.

## Sub-choices proposed with D17

*Update 2026-11-12:* the owner accepted all eight recommendations below and the identity-column
approach, with `adapter_interface_version` as the canonical name (`adapter_contract_version`
retired). See "4A implementation" at the end of this file. The table is kept as proposed.

These were recommended in the proposal but were not explicitly approved at the time; they stayed OPEN for the
owner:

| # | Choice | Recommendation |
|---|---|---|
| C1 | Adapter configured by environment variables `OCR_ADAPTER` and `OCR_ADAPTERS_APPROVED` | Yes |
| C2 | Real adapter modules in `swasthyoid/capture/adapters/` (empty in 4A); fakes in `swasthyoid/tests/adapters/` | Yes |
| D13 | Integrity or availability failure before any claim means "unavailable" (no claim, alert) | Yes |
| 4A-15 | Kill the whole OCR process group (Linux); Windows keeps the single-process kill, documented | Yes |
| 4A-16 | No-network enforced in tests only; production enforcement with hosting (FRD Q4) | Yes |
| 4A-20 | Record an optional `adapter_version` | Yes |
| 4A-23 | The platform, not the adapter, enforces every time limit | Yes |
| 4A-24 | One interface version at a time; every change needs owner approval | Yes |
| — | Identity column names (`engine_id`, `model_version`, `model_checksum`, interface version) and their additive migration | Names provisional; migration only with 4A implementation approval |

Already decided elsewhere and unchanged: Option A (no adapter: stay due, direct manual entry).

---

# 4A implementation — ON BRANCH `4a/ocr-infrastructure`, AWAITING OWNER REVIEW

Built from the frozen 4A plan, Revision 4 (owner approved implementation on 2026-11-12). Not
merged into `main`; merging needs separate owner approval. No OCR model, engine, framework,
pretrained weights or artifact was selected, installed, bundled or integrated.

## Owner decisions applied

- The eight 4A choices (C1, C2, D13, 4A-15, 4A-16, 4A-20, 4A-23, 4A-24) and the identity columns.
- `AVAILABILITY_TIMEOUT` 30 s and position nesting limit 32 (provisional engineering values);
  error code `availability_timeout`; hard links accepted as a documented limitation.
- **Option C (R10):** test mode needs `APP_ENV=test` **and** `SWASTHYOID_TEST_MODE_CONFIRM=1`.
  Enforced at API startup, at `run_due`/`extract` before any claim, and in the probe and OCR
  children. A misconfiguration guard, not a security boundary.

## What exists (`7c0c148`)

- `swasthyoid/runtime_mode.py`; `swasthyoid/capture/ocr.py`; empty `capture/adapters/`.
- Probe child before any claim (artifact hash before adapter import, identity only, never
  `prepare()`, bounded by `AVAILABILITY_TIMEOUT`); a probe failure is one warning log line with
  codes only, no database write.
- OCR child per attempt, re-checks artifacts and test mode; version 0 refused outside test mode
  at the probe, the child and storage. Outside test mode no adapter is ever available.
- Five nullable identity columns and the `extraction_identity` CHECK; no backfill.
- Process-group kill on Linux (descendants that start their own session escape; Windows kills the
  child only); test-only network guard; typed error codes stored, never messages.
- Legacy engine callables: deprecated, test mode only in every execution mode, removed after 6B.

## Verification

- GitHub Actions run #17 (`43271813227`) on `7c0c148`, ubuntu-26.04, Python 3.12.16, PostgreSQL
  16.15: **411 passed, 0 failed, 0 skipped, 0 errors**.
- Local Windows without a database: 170 passed, 241 skipped (database tests; one symlink test).

## Deviations from the plan text, for owner review

1. **Function name:** the plan's `test_mode_enabled()` is `runtime_mode.is_test_mode()`, because
   pytest collects any `test_*` function imported into a test module. Behaviour is as planned.
2. **Plan section 2.4 was still open:** option (ii), a startup warning when the confirmation is
   set but `APP_ENV` is not `test`, was implemented as recommended (one line in
   `api/deps.check_config`). Test mode stays off in that case whatever is chosen.
3. **Import allowlist lint:** existing code imports `pydantic` and `starlette` directly, which
   arrive only through `fastapi` and are not declared in `pyproject.toml`. The lint lists them
   explicitly as "via fastapi" instead of changing `pyproject.toml`.
4. **Existing test changed by the planned legacy-path rule:**
   `test_in_process_ocr_is_refused_outside_tests` asserted that an engine callable with a hard
   timeout runs outside test mode; it now asserts the refusal, then runs it in test mode.

## Still open

- Owner review of `7c0c148`, then merge approval; plan section 2.4 confirmation.
- Everything under D18 (unchanged): interface version 1, probe-load, final manifest format,
  timeout values, confidence meaning, output limits, batching, process model, model-specific retry.
- Step 8 must call `runtime_mode.check_test_mode_config()` at worker start.

---

# P0 exit gate as actually passed — PENDING OWNER ACCEPTANCE

FRD section 11 asks for questions 1, 2, 4, 5 and 7 to be **answered** in P0. They were
recorded; only Q2 is decided. P1 and P2 work went ahead. Proposed: accept this as a recorded
deviation, with each open question tied to the work it blocks:

| Question | Blocks |
|---|---|
| Q1 drug catalog | Plan step 7 with a real catalog (synthetic catalog only until then) |
| Q4 hosting and residency | Pilot; any real patient data |
| Q5 cloud AI | Cloud AI stays off (`CLOUD_AI_THRESHOLD` unset) until decided |
| Q7 clinical reviewer | Plan steps 6B, 7, 9B; P3 safety rules; every clinical threshold |
