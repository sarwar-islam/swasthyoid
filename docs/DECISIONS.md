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
- **S2 and S3 — fixed, owner-approved (2026-11-13), commit `94210d9`.** `_run_engine` now maps a
  `BrokenPipeError` raised by `poll()` (Windows) to `AttemptFailed("WorkerDied")`, and a new
  `_release()` stops the child and gives both pipe ends a close attempt even when `child.start()` or
  an earlier cleanup step fails. Cleanup policy: an ordinary cleanup error never replaces a primary
  exception (logged by type only, never its message); `KeyboardInterrupt` and `SystemExit` during
  cleanup are never suppressed; a cleanup failure after a good result propagates. Tests:
  `swasthyoid/tests/test_run_engine.py` (25, no database). S5 Part A is fixed (next entry);
  the rest of S5 and S6–S8 stay deferred by the owner: S6 guard and a real spawn test in Step 8
  (preserved as mandatory Step 8 acceptance criteria AC1–AC6, `docs/M2_COMPLETION_PLAN.md`; D9
  must be decided before the runner is created);
  S7 after the D18 model runtime specification; S8 needs `EXPLAIN` evidence on PostgreSQL before
  any index is proposed.
- **S5 Part A — fixed, owner-approved (2026-11-13), commit `9013429`.** The lease was renewed only
  inside the engine wait loop; reading the images ran with no heartbeat. `_attempt()` now calls
  `_renew()` once after all images are read and before the engine starts. A `False` result raises
  `LeaseLost`: the engine never starts and nothing is written. The shared `LeaseLost` handler now
  logs one warning, `ocr attempt lease lost: code=LeaseLost stage=attempt document=<id>
  attempt=<n>` (no patient data, image content or text); it fires for all three sources of
  `LeaseLost` (this renewal, the heartbeat, the fence), which were silent before. Tests: 8 without
  a database in `swasthyoid/tests/test_extraction_lease.py`, and one PostgreSQL test appended to
  `test_extraction_recovery.py` (`test_a_lease_that_expires_while_reading_images_stops_before_the_engine`).
  **CI-verified: run #25 (see "CI evidence for the 4A fixes, S2–S5" below).** The PostgreSQL test
  cannot run on the development machine (no PostgreSQL); in CI it ran, by count. **Deferred, not decided:** the lease check before the cloud AI audit and
  send (Part B), a provider timeout, process isolation and idempotent sends (Part C) — FRD Q5;
  per-image renewal (A+) and storage-read timeouts — FRD Q4; a background heartbeat thread is not
  recommended (a hung call would keep renewing). Not reproducible today: cloud AI is unreachable
  (`CLOUD_AI_THRESHOLD` is `None`, `SCHEMAS` is empty, no caller passes a provider), and nothing in
  production calls `run_due` or `extract` until step 8.
- **S4 — fixed, owner-approved (2026-11-13), commit `22a2928`.** `_settings()` validates every
  option before anything is claimed or probed (rules under "Rules enforced"), and `claim()` no
  longer replaces an explicit zero with the default. Tests: `swasthyoid/tests/test_extraction_settings.py`
  (142, no database). CI-verified: run #24 (see "CI evidence for the 4A fixes, S2–S5" below).
- **Deferred risks from S4 (not confirmed failures, not measured, need PostgreSQL to test):** no upper
  bounds are enforced. (1) A very large `lease`, `backoff` or `hard_timeout` might overflow PostgreSQL
  interval or timestamp arithmetic (for example `clock_timestamp() + lease`) and fail at claim time.
  (2) `backoff * 2 ** (attempt - 1)` grows exponentially, so a large `max_attempts` might overflow
  before any cap. Review together with S8 once a database is available.
- **Remaining from the review (S2, S3, S4 and S5 Part A below are now fixed; the rest not fixed, not approved for fixing):** S2 a Windows-only pipe error
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
2. **Work** (no transaction open). Read the images, then renew the lease once (S5 Part A: reading
   has no heartbeat, and a lapsed lease ends the attempt before the engine starts), then run the
   engine in a child process. Every heartbeat the worker renews the lease; a lease that has
   already run out cannot be renewed. At the hard timeout the child process is killed and the
   attempt has failed.
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
| Reading the images takes longer than the lease | The renewal after reading finds the lease gone: the attempt ends before the engine starts, nothing is written, one warning is logged, the document is due again and the attempt stays counted |

## Bounded time to a terminal state

With at least one worker checking the queue every P seconds, a document reaches
`needs_review` or `extraction_failed` within

    3 attempts x (longest attempt + wait before retry + P)

where the longest attempt is the larger of the hard timeout (10 min) and the lease (5 min),
and the waits are 1 and 2 minutes after the first and second attempts. With the defaults that
is about 33 minutes plus three polling intervals, in the worst case where every attempt hangs
to the limit. Reading the images and shaping the result are counted as negligible here; the
single renewal after reading keeps a slow read from using up the first lease (S5 Part A).

## Rules enforced

- **In-process OCR is refused unless `APP_ENV=test`.** That mode has no heartbeat and no hard
  timeout. The refusal happens before anything is claimed.
- **The heartbeat must be shorter than the lease**, or the settings are refused (not checked when
  `hard_timeout` is `None`, the test-only in-process mode, which has no heartbeat).
- **Option values are validated (S4)** with `TypeError` for a wrong type and `ValueError` for a bad
  range; the message names the option, never the value. `lease`, `heartbeat`, `hard_timeout` (when
  not `None`) and `availability_timeout` are `timedelta` above zero; `backoff` a `timedelta` of zero
  or more; `max_attempts` an int of at least 1; `threshold` and `ai_threshold` a number from 0 to 1
  inclusive (`ai_threshold` may be `None`: nothing is sent). Bools, NaN, infinity and non-numbers
  are refused. `availability_timeout=None` means `ocr.AVAILABILITY_TIMEOUT`. `claim()` applies the
  `lease` and `max_attempts` rules; only an omitted value or `None` selects the default.
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

# 4A implementation — MERGED INTO `main` (2026-11-13); built on branch `4a/ocr-infrastructure`

Built from the frozen 4A plan, Revision 4 (owner approved implementation on 2026-11-12), on branch
`4a/ocr-infrastructure`. **Merged into `main` on 2026-11-13** by fast-forward (`33e2aa1..a9f2abc`)
after the owner's review of the fixes and a separate merge approval; the merge is historical, not
pending. CI run #21 (branch) and #22 (`main`), both at `a9f2abc`: 444 passed, 0 skipped (see "CI
evidence for the 4A fixes, S2–S5" in the Step 1 section). The branch still exists on `origin` at
`a9f2abc`. The text below describes the build as it stood on the branch on 2026-11-12. No OCR
model, engine, framework, pretrained weights or artifact was selected, installed, bundled or
integrated.

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

## Final review decisions (owner, 2026-11-12)

- **B1 — option (a) accepted.** No worker entry module in 4A. The test-mode checks at
  `run_due()` and `extract()` (before anything is claimed) are sufficient for the current
  architecture. **Step 8 MUST call `runtime_mode.check_test_mode_config()` at independent worker
  process startup, before entering its worker loop.**
- **M1 — option (ii) approved.** The startup warning when the confirmation is set but `APP_ENV`
  is not `test` stays; test mode stays off. This settles plan section 2.4 and deviation 2.
- **M2 — fixed.** The worker reads every probe message until the channel reaches EOF, within the
  existing deadline. Only `[checksum, identity]`, `[failed]` and `[checksum, failed]` are accepted;
  duplicate, late, out-of-order or unexpected messages are refused. Probe messages are
  size-limited JSON bytes (not pickles), and the probe child closes its end when done.
- **M3 — fixed.** The worker validates the full interface v0 result again before building
  `raw_text` or storing anything.
- **L4 — fixed.** One safe warning per failure after a claim: code, stage, document id, attempt.
- **L5 — fixed.** The probe child re-checks test mode before anything else; an exception from
  `check_test_mode_config()`, or test mode off, sends `engine_unavailable` and imports no adapter
  code. This also means no adapter code runs in a probe outside test mode (audit item L6).
- **Test-package references** — fixed: `swasthyoid.tests:x` is caught (`ocr.is_test_ref`).
- Fix commit `06ecf92`. Remaining audit items L1–L3, L7–L9 accepted as reported.
- **M2 follow-up — fixed, owner-approved (2026-11-13), commit `e9253e7`.** A probe `failed`
  message with a non-string payload (list, dict) raised `TypeError` out of `_read_probe` instead of
  `AdapterError`. Only a string in `CODES` now passes through; anything else is
  `engine_unavailable`. No other protocol, EOF, deadline or timeout change. Regression test covers
  `[]`, `{}`, `5`, `None`, `["x"]`, with and without the checksum prefix.
- **CI, owner-reported, not independently verified:** CI #19 (`06ecf92`) and CI #20 (`0713df4`)
  both completed successfully. Test counts were unavailable: the GitHub Actions listing did not
  show them. They were not read by the implementer (no `gh`, no signed-in browser).
- **CI evidence for the 4A fixes, S2–S5 (read from the actual "Run pytest -q" logs, 2026-11-13).**
  GitHub Actions workflow "CI", job `test`: ubuntu, Python 3.12.16, a `postgres:16` service, so the
  database-backed tests ran. Every run: **0 failed, 0 skipped, 0 errors**, one warning (Starlette
  `httpx` deprecation in the third-party test client). Each run's last line is the pytest summary.

  | Run | Commit | Branch | What it covers | Result |
  |---|---|---|---|---|
  | #21 (`43372843363`) | `a9f2abc` | `4a/ocr-infrastructure` | 4A with the M2 non-string failure-code fix (`e9253e7`) | 444 passed in 74.22 s |
  | #22 (`43374734206`) | `a9f2abc` | `main` | the same commit after the fast-forward merge of 4A | 444 passed in 77.79 s |
  | #23 (`43377285358`) | `761cf45` | `main` | S2 and S3 (`94210d9`), 25 new tests | 469 passed in 91.08 s |
  | #24 (`43379343362`) | `b40ef4d` | `main` | S4 (`22a2928`), 142 new tests | 611 passed in 83.30 s |
  | #25 (`43382219028`) | `7b8e929` | `main` | S5 Part A (`9013429`), 8 new tests plus one PostgreSQL test | 620 passed in 88.76 s |

  The counts add up: 444 + 25 = 469; 469 + 142 = 611; 611 + 9 = 620. The local Windows run without
  a database collects the same 620 tests (377 passed, 243 skipped), so in run #25 every skipped test
  ran, among them `test_a_lease_that_expires_while_reading_images_stops_before_the_engine`.
  **Limit:** `pytest -q` prints no test names, so that test is shown to have run by the count, not by
  name. #19 and #20 stay owner-reported. The findings still deferred (S5 Parts B and C, A+,
  storage-read timeouts, S6, S7, S8) are not covered by this evidence.

## Still open

- (Resolved 2026-11-13, kept as history: the owner reviewed the fixes and approved the merge; 4A is
  merged into `main`.)
- Everything under D18 (unchanged): interface version 1, probe-load, final manifest format,
  timeout values, confidence meaning, output limits, batching, process model, model-specific retry.
- **New observation, not fixed (outside the approved scope):** the OCR child still returns its
  result to the worker as a pickle, so the worker unpickles data produced next to adapter code.
  Probe messages no longer do (M2). Owner decision whether to move the attempt result to the same
  JSON framing before interface version 1.

---

# D9 — How the worker is run — DECIDED

Owner: Sarwar Islam. Date: 2026-11-13. Nothing was implemented when D9 was decided; slice 8.1 (the
startup skeleton) was implemented later the same day, see "Slice 8.1 implementation record" below.
The S6 acceptance criteria AC1–AC6 in `docs/M2_COMPLETION_PLAN.md` (Step 8) apply to it.

The extraction worker runs as a plain Python process launched using:
`python -m swasthyoid.workers.extract`
It uses the existing database-backed queue through `db.connect_worker`. No Celery, Redis,
console-script entry point, or `pyproject.toml` change is required.

## Execution modes

The runner supports two modes:

1. **Loop mode (default):** Repeatedly executes polling cycles using a required, validated
   polling-interval setting. The interval is configurable, but no production value is selected by
   this decision. The interval is the wait after a polling cycle completes, so cycles do not
   overlap within one runner process.
2. **`--once` mode:** Executes exactly one polling cycle — one call to `run_due()` using its
   existing normal limit — and then exits. A cycle may process multiple due documents and is not
   equivalent to processing one document.

## Exit-code semantics

- Exit code `0`: the requested polling cycle completes, regardless of individual document
  outcomes. Per-document successes and failures are recorded through the existing extraction
  workflow.
- Non-zero exit code: startup is refused or fails, or the runner cannot complete its required
  startup or infrastructure operations.

## Startup and safety

The runner must:

- Keep all execution behavior inside `main()` behind a proper `if __name__ == "__main__":` guard.
- Preserve import purity: importing the runner must not connect to the database, start processes
  or threads, perform network operations, or produce output.
- Call `runtime_mode.check_test_mode_config()` once at startup, before entering the loop or
  spawning any child process, as required by B1.
- Satisfy all committed S6 acceptance criteria AC1–AC6.

## Shutdown behavior

On a supported stop signal, the runner stops claiming new documents, allows the current attempt
to finish, and then exits. Supported signal handling must be implemented and verified per
platform: `SIGINT` and `SIGTERM` where available, and `SIGBREAK` on Windows where supported.

The idle wait must be interruptible and short enough to notice a stop promptly rather than
waiting for the entire polling interval.

If the process is forcibly terminated before an attempt finishes, recovery relies on the existing
lease-expiry and fencing mechanisms. Computation is at-least-once: a document may be computed
again after lease expiry. A stale worker cannot store a result or failure after losing its valid
claim. At most one extraction result is stored per document version. Side effects outside the
database are not covered by this guarantee.

## Availability probe

The existing availability probe remains before queue claiming. Its idle-cycle process-spawn
overhead is accepted for this decision. No 4A-adjacent optimization is authorized.

## Deferred decisions

The following remain OPEN or deferred and are not decided by D9:

- Production hosting platform and process supervisor or scheduler (FRD Q4).
- Production polling-interval value.
- Log destination, metrics sink, environment-variable injection, and supervisor shutdown grace
  period.
- Console-script packaging.
- Celery and Redis.
- D13 alerting mechanism and other separately tracked Step 8 decisions.

This decision does not reopen frozen 4A decisions. S5 Parts B and C, per-image renewal,
storage-read timeouts, S7, and S8 remain deferred.

The selected architecture is a long-running plain Python worker with a bounded `--once` mode. A
scheduler-invoked `--once` execution remains possible where the eventual hosting environment
makes that preferable.

**Evidence recorded with the decision (investigation, 2026-11-13; Windows laptop scratch unless
stated).** Signals on Windows: `terminate()` and `kill()` are hard kills with no handler;
`CTRL_BREAK_EVENT` is caught as `SIGBREAK`; with a 10 s idle wait the process did not react to
`SIGBREAK` until the wait ended, whereas 0.2 s wait slices stopped it at once. `SIGINT` on Windows
and all Linux signal behavior are not yet verified. An availability probe took about 1.3 s and
Python start plus import about 1.0–1.3 s. Duplicate claims, stale writes and recovery after a
kill are covered by the existing tests that run in Linux CI.

---

# Step 8 runner — owner decisions of 2026-11-13 (slice 8.1 implemented; the rest not implemented)

Owner: Sarwar Islam. Date: 2026-11-13. These refine the runner design under D9; **D9 is unchanged**.
S6 acceptance criteria AC1–AC6 (`docs/M2_COMPLETION_PLAN.md`, Step 8) remain mandatory. Slices
8.1–8.5 of the Step 8 plan (revision 2) may start only when the owner says so; slice 8.6 (retry and
manual-entry endpoints) stays blocked on D10, D12 and D14.

## Decision 1 — poll interval setting

- Name: `EXTRACTION_POLL_SECONDS`. Required in loop mode. Must be a positive, finite number of
  seconds. Empty, NaN, infinity, zero, negative and boolean-like values are rejected.
- No default and no production value is selected. `--once` does not require it.
- In loop mode a missing or invalid value is a configuration error and maps to exit code `2`
  (decision 2, whose definitions are unchanged).

## Decision 2 — exit-code contract

| Code | Meaning |
|---|---|
| `0` | A polling cycle completed, regardless of individual document outcomes, or the runner completed a graceful shutdown |
| `1` | Infrastructure failure: database connection loss, missing schema, or an unexpected runtime infrastructure failure |
| `2` | Invalid command-line usage or configuration error |
| `3` | The runner was forcibly aborted by the second shutdown signal |

Per-document failures (attempts that fail, retries, `extraction_failed`) are recorded through the
existing extraction workflow and do not change the exit code. Exit codes `1`, `2` and `3` describe
runner-level failures only.

## Decision 3 — shutdown signals

- **First signal:** request a graceful shutdown. No further claim is started once the claim
  operation in progress reaches a safe boundary, and the active attempt is allowed to finish.
  **Claim race:** if a claim has already committed when the stop request arrives, that claimed
  document is the active attempt and is allowed to finish. A deterministic (not timing-based) test
  of this boundary is required.
- **Second signal:** emit one code-only log line and immediately call `os._exit(3)`. A
  `KeyboardInterrupt` is not raised from the handler.
- Recovery relies on the existing lease expiry, fencing, and parent-gone cleanup of the OCR child.
  **None of this is verified until real-process tests show it.** Required real-process evidence:
  the runner exits with code `3`; the OCR child exits through the parent-gone watchdog; any open
  PostgreSQL transaction is rolled back; the lease expires; a subsequent runner recovers the
  document; and exactly one extraction result exists per document version. Unit tests alone are not
  accepted as proof.

## Decision 4 — schema ownership

- The runner never applies or alters the schema and does not import or call `db.apply_schema`.
- Before any availability probe or document claim it checks that the required tables and columns
  exist. A missing one produces a single diagnostic that names only the missing tables or columns,
  and exit code `1`. Tests must prove that no DDL runs.
- Applying the schema stays with the existing API startup until FRD Q4 determines the requirements
  of a worker-only deployment.

## Decision 5 — database connection loss

- Any database connection loss, during an attempt, between attempts or during a claim, ends the
  runner process: close the connection where possible and exit with code `1`.
- No automatic in-process reconnect is implemented. An interrupted attempt is handled by lease
  expiry and the existing recovery mechanism. A supervisor or restart configuration remains FRD Q4.

## Slice 8.1 clarifications (2026-11-13; the five decisions above are unchanged)

- **Startup order.** (1) The Python main-module guard; (2) `check_test_mode_config()` as the first
  runtime safety check, before any schema inspection, database connection, child spawn,
  availability probe or claim; (3) required configuration validation; (4) read-only schema
  validation; (5) only after all of them pass may the runner proceed toward availability probing or
  claiming. Checked against the 4A code on 2026-11-13: `check_test_mode_config()` is an
  environment-only check, `run_due()` already runs it first and then probes and claims, and no 4A
  code has to change. Details in `docs/M2_COMPLETION_PLAN.md`, Step 8.
- **Slice 8.1 acceptance versus whole-runner acceptance.** Slice 8.1 is a safe startup skeleton:
  main-module guard, import purity, ordering of the first runtime safety check, configuration
  validation, read-only schema-presence validation, no-DDL verification, no database claim or
  processing cycle before all startup checks pass, and the relevant regression tests. Real
  subprocess spawn and child-execution proof, the PostgreSQL-backed processing-cycle test, first-
  and second-signal behavior, OCR-child watchdog behavior, PostgreSQL rollback and lease-expiry
  recovery, Linux hard-kill recovery of the runner, and subsequent-runner recovery with exactly one
  extraction per document version are whole-runner requirements that 8.1 does not complete. S6
  AC1–AC6 stay mandatory for the completed runner. The later runner slices (8.2–8.5) are not yet
  written out, so no per-requirement slice ownership is recorded.
- **No `--once` execution in 8.1 (historical: slice 8.2, commit `553c3db`, added it).** Slice 8.1 did not execute `run_due()`, a `--once` processing
  cycle or the long-running polling loop; the `--once` execution path belongs to a later
  runner-execution slice. Slice 8.1 may test argument and configuration parsing but must not claim
  or process documents. The meaning of `--once` is unchanged: exactly one `run_due()` call with its
  normal limit, not exactly one document.

## Startup error and ordering contract (2026-11-13; decisions 1–5 and D9 are unchanged)

This classifies startup failures within decision 2. It adds no exit code and changes no meaning.

- **Refused test-mode configuration.** `runtime_mode.check_test_mode_config()` has exactly one
  refusal condition (code read on 2026-11-13): `APP_ENV` is exactly `test` and
  `SWASTHYOID_TEST_MODE_CONFIRM` is not exactly `1` (unset, or any other value). It then raises
  `RuntimeError("APP_ENV=test requires SWASTHYOID_TEST_MODE_CONFIRM=1")`. It only reads two
  environment variables and performs no I/O, so it cannot produce an infrastructure failure, and it
  refuses no other environment: an environment outside test mode is handled by the 4A availability
  probe, which finds no adapter and claims nothing. The runner treats this refusal as a
  configuration and safety refusal: **exit code `2`**. After it, nothing else happens: no PostgreSQL
  connection, schema inspection, child spawn, availability probe, claim or extraction. The
  diagnostic is concise and non-sensitive: the refusal text names the variables and exposes no
  environment value, and no secret or environment value is added to it. Only this `RuntimeError` is
  mapped to `2`; other exceptions are not classified as configuration failures by default.
  **Limit of this check:** it does not reject every unsafe or invalid environment. A non-test
  environment is not blocked by it. The existing adapter allowlist and availability-probe
  restrictions stay essential, and the runner must not bypass either of them or add a bypass
  switch.
- **Argument parsing and the first runtime safety check.** Side-effect-free argument parsing may
  run before the safety check. It must not connect to the database, inspect the schema, start a
  process or thread, probe availability, claim a document or run extraction.
  `check_test_mode_config()` is the first runtime safety check, and no other runtime startup
  operation precedes it. Invalid command-line usage exits with `2`. After valid parsing, the safety
  check runs before any configuration-dependent infrastructure operation.

| Failure category | Exit code |
|---|---:|
| Invalid command-line usage | `2` |
| Missing or invalid `EXTRACTION_POLL_SECONDS` in loop mode (`--once` does not require it) | `2` |
| Refused test-mode configuration (`APP_ENV=test` and `SWASTHYOID_TEST_MODE_CONFIRM` not exactly `1`) | `2` |
| `DATABASE_URL` missing, empty or whitespace-only | `2` |
| `DATABASE_URL` rejected by the connection-string parser before any connection | `2` |
| Other invalid or missing required configuration | `2` |
| `DATABASE_URL` accepted by the parser, but the database connection fails | `1` |
| Required schema, table or column unavailable | `1` |
| Other infrastructure failure preventing safe startup | `1` |
| Per-document extraction failure during normal processing | does not change the exit code |
| Successful completion or graceful shutdown | `0` |
| Second-signal abort | `3` |

**`DATABASE_URL`: what exists today and what slice 8.1 must implement (code read on 2026-11-13).**
- *Today:* `db.connect()` does `psycopg.connect(os.environ["DATABASE_URL"], ...)`, and
  `db.connect_worker()` calls it. A missing variable raises a raw `KeyError`. Nothing validates the
  value before the connection call anywhere in the non-test code; the API only checks whether the
  variable is present (`api/main.py`). So a malformed URL is **not** detected before connection
  today.
- *Required in 8.1, not implemented:* a presence check for `DATABASE_URL` (exit `2`), and
  side-effect-free syntax validation of its value before any connection is attempted (exit `2`).
  A connection failure that follows a URL the validation accepted is exit `1`. Exceptions from
  the connection call are not all treated alike: a malformed value is a configuration failure where
  the pre-connection validation can tell. The mechanism is an 8.1 design item. For information,
  psycopg, an already declared dependency, has a parser that does not connect
  (`psycopg.conninfo.conninfo_to_dict`); how it treats each malformed form is not verified here.

**Empty or whitespace-only `DATABASE_URL` (owner decision, 2026-11-13).** A `DATABASE_URL` that is
missing, empty or only whitespace is invalid configuration: exit code `2`, checked before any
connection attempt, so the runner cannot fall back to the connection library's default parameters.
A non-empty value that psycopg's own connection-string parser (`psycopg.conninfo.conninfo_to_dict`,
which does not connect) rejects is also exit code `2`. A value the parser accepts whose connection
then fails is exit code `1`. "Valid" means acceptable to that parser, which covers both libpq forms
(a `postgresql://` URI and a keyword/value string), not URL-only; the existing integration tests
set `DATABASE_URL` to a keyword/value string through `make_conninfo`. The mechanism and its
behavior on each malformed form are 8.1 design items, unverified today. Source evidence behind this
(psycopg code read on 2026-11-13, nothing run): the parser path only parses and never connects;
psycopg's Python code has no check that rejects an empty string; libpq's own handling of an empty
or whitespace-only string was not inspected.

Open points, not decided here: which settings count as required configuration is an 8.1 design item,
to be derived from the actual code during the authorized design (`DATABASE_URL` is needed by
`db.connect`; no further required variable is invented here); and validating `DOCUMENT_STORE` and
`DOCUMENT_KEY` remains a proposal that needs confirmation and is not mandatory. None of this is
verified by running code: the runner does not exist yet.

## Slice 8.1 implementation record (2026-11-13)

- **What was built.** `swasthyoid/workers/extract.py`, launched as
  `python -m swasthyoid.workers.extract [--once]`, and `swasthyoid/tests/test_runner_startup.py`.
  Commits `2b8038f` (skeleton and tests) and `c4be86d` (a brittle connection-count assertion
  relaxed to `>= 3`, and the `--once` help text corrected). The slice calls no `run_due()`, runs no
  `--once` cycle or loop, handles no signals, claims and processes nothing, and never applies or
  alters the schema. No dependency, schema, workflow or package change.
- **Order and exit codes as implemented.** Main-module guard; side-effect-free argument parsing
  (usage error exits `2`); `check_test_mode_config()` (its refusal exits `2`); the poll interval in
  loop mode only (`--once` ignores the variable); `DATABASE_URL` (missing, empty, whitespace-only or
  rejected by psycopg's parser exits `2`); connection (failure exits `1`); one read-only catalog
  `SELECT` for the required tables and columns (missing ones exit `1`, named). Diagnostics go to
  stderr as one line each and name settings, tables and columns only.
- **Required schema inventory (derived from the worker's SQL).** `documents`: `id`, `patient_id`,
  `doc_type`, `status`, `created_at`, `updated_at`, `extraction_attempts`, `next_extraction_at`,
  `extraction_error`, `extraction_claim`. `document_images`: `document_id`, `n`, `storage_key`,
  `content_type`, `size_bytes`, `sha256`. `extractions`: `id`, `document_id`, `version`, `engine`,
  `fields`, `raw_text`, `engine_id`, `model_version`, `model_checksum`, `adapter_interface_version`,
  `adapter_version`. `patients` and `audit_logs` are not listed because only the cloud AI path
  touches them. The check sees only what the connecting role may use, so missing privileges also
  report names as missing (fails closed), and it checks existence only, not types or constraints.
- **Evidence.** Local (Windows, no database): 54 slice tests passed and 4 skipped; whole suite 431
  passed, 247 skipped. CI run #31 (`c4be86d`, Linux, PostgreSQL 16): `678 passed, 1 warning`, 0
  skipped, 0 failed (= 620 + 58). `pytest -q` prints no test names, so the four PostgreSQL tests
  are shown to have run by that count and not by name. Parser behavior seen when run: psycopg's
  parser rejected both malformed strings used in the tests. The audit-hook event names used for
  process creation on Linux come from documentation; the probe passed on Linux CI but its coverage
  of those names was not independently confirmed.
- **CI run #32 (`d629b94`, the documentation commit recording #31).** Completed successfully on
  `main` (job `test`, 2m 9s), read from the run page; the same Node.js 20 warning and Ubuntu 26
  notice as before. The job log was not opened, so no pytest total is recorded for this run; the
  commit changes documentation only. The last verified count remains run #31's 678 passed.
  CI run #33 (`4c8c43c`, the commit that recorded #32) also completed successfully on `main`
  (1m 58s), read from the Actions list page only; no log or count was read.
- **Interpretations made in the implementation, for the owner to confirm or change.**
  "Boolean-like" poll values are read as non-numeric words (`true`, `false`, `yes`), so a plain `1`
  is accepted as one second; underscores (`1_0`) are refused. The diagnostic format
  `runner: code=<code> key=value` is the implementation's.
- **Open points, not decided by the implementation.** (1) [Superseded by slice 8.2: `--once` now runs `run_due()` and exits `0` after a completed cycle] A successful 8.1 run exited `0` after logging
  `startup_checks_passed` although no polling cycle ran, while decision 2 defines `0` as a completed
  cycle or a graceful shutdown. (2) The runner sets no `connect_timeout`, so a blackholed host could
  delay its exit; the tests set the timeout in the URL. (3) Validating `DOCUMENT_STORE` and
  `DOCUMENT_KEY` remains an unapproved proposal and is not implemented. (4) A few catch-all branches
  (`startup_failed` at the connect and schema-check stages, closing the connection on failure) have
  no test.
- **Not part of 8.1 and still to do (S6 AC1–AC6 stay mandatory for the completed runner):** the
  spawn-based half of AC1, the PostgreSQL-backed processing-cycle test (AC3), first- and
  second-signal behavior, the OCR-child watchdog, rollback and lease-expiry recovery, Linux hard-kill
  recovery and child bootstrap-failure behavior (AC5), and recovery by a later runner. The scopes
  of slices 8.2–8.5 are still not written out. D10, D12, D14, Q4 and the D13 alert mechanism stay
  open, slice 8.6 stays blocked, and the production prerequisites (4B, D2, Q4) are unchanged.

## Runner slices 8.2–8.4, step 5A and step 3A: implementation record (commit `553c3db`, pushed 2026-11-13; CI runs #35 and #36)

Written on the owner's instruction to work in larger batches. Local evidence (Windows, no
PostgreSQL): 456 passed, 257 skipped, 0 failed. CI evidence is in the next paragraph.

**CI evidence (read from the run pages and the pytest log, 2026-11-13).** GitHub starts one run per
push, so `553c3db` has no run of its own. Run #35 (`a650486`, which contains `553c3db` and the docs
commit) **failed: 712 passed, 1 failed, 0 skipped.** The failure was a test bug:
`test_two_runners_at_once_extract_every_document_exactly_once` started its runners without `--once`,
so they ran in loop mode without `EXTRACTION_POLL_SECONDS` and exited `2` (the intended behavior).
Commit `2ddb8a6` fixed the test (it passes `--once`). Run #36 (`2ddb8a6`, Linux, PostgreSQL 16)
**passed: 713 passed, 0 skipped, 0 failed, 1 warning (`httpx` deprecation)**, 2m 9s of pytest. Test
names are not printed, so each test is inferred from the totals: with 0 skipped, the PostgreSQL-backed
and Linux real-process tests ran and passed (first SIGTERM, second SIGTERM, SIGKILL recovery, dying
OCR child under 20 s, unimportable adapter, two concurrent runners, `--once` extraction and stats).
That is one green run per commit; it does not rule out timing flakiness. S6 evidence now available:
AC3 (a real `--once` process extracts a document to `needs_review`, exit `0`, "runner started"
once), the signal and hard-kill recovery evidence, and the OCR-child watchdog. **Still not shown:**
bootstrap failure of the spawned runner process itself, and PostgreSQL connection close on kill.

- **Runner (`swasthyoid/workers/extract.py`).** After the 8.1 startup checks, `--once` makes exactly
  one `run_due()` call with its normal limit and exits `0` with a `cycle_done` line. Loop mode calls
  `run_due(limit=1)` repeatedly and waits `EXTRACTION_POLL_SECONDS` (in 0.5 s slices) when nothing is
  due. The first signal (SIGINT, SIGTERM, SIGBREAK) stops the loop before the next claim and lets
  the running attempt finish; the second logs one line and calls `os._exit(3)`. A lost connection or
  `psycopg.Error` exits `1` with no reconnect; any other cycle failure exits `1` with the exception
  type only. Exit codes are unchanged from the decisions of 2026-11-13. The "exit `0` without a
  cycle" open point of 8.1 no longer applies: `0` now follows a completed cycle or graceful shutdown.
  The `startup_checks_passed` line no longer exists; it is `runner_started` then `cycle_done`.
- **Owner decision, 2026-11-13: keep `limit=1`; no stop hook in `run_due()`.** **Known performance
  limitation:** every `run_due()` call runs the availability probe (a child process), so loop mode
  costs one probe per document and one per idle poll.
- **Queue statistics.** `queue_stats()` is one read-only query: `due`, `in_flight` (live lease),
  `lease_expired` (also counted as due) and `failed`. Counts only, no document text.
- **Tests.** DB-free (ran): the loop, the stop request, the wait, both signal paths, the handlers and
  the exit-1 mappings. PostgreSQL-backed (written; **not run locally, passed in CI run #36**): `--once` extracts a due document to
  `needs_review` with `runner_started` exactly once; a second run adds no second result; outside test
  mode nothing is claimed; the statistics against constructed database states. Real-process
  (`tests/test_runner_process.py`, written; **not run locally, passed in CI run #36**; Linux for signals): the first SIGTERM does
  not interrupt the running attempt; a second SIGTERM (exit `3`) and a SIGKILL each leave a claim
  that a runner started before the lease ends respects, that expires, and that a later runner
  recovers with exactly one extraction; the OCR child ends through the parent-gone watchdog; no
  transaction is left open; a child that dies is recorded as `WorkerDied` within 20 s (an
  AC5 measurement, the bound is the implementation's guess); an adapter that cannot be imported claims
  nothing; two runners at once attempt each of six documents once. One 8.1 PostgreSQL test that
  expected the removed `startup_checks_passed` line was corrected; the 8.1 test that forbade
  `run_due` references was narrowed (it still forbids `claim`, `apply_schema`, adapter handling).
- **Not covered.** Bootstrap failure of the spawned runner process itself (the import-failure test
  exercises the availability probe only); connection close on kill is not asserted; real signal delivery
  on Windows. S6 AC5 is only partly shown by run #36 (see the CI evidence above).
- **Step 5A: `capture/imaging.py`.** Decodes for real (JPEG and PNG only, pixel cap checked from the
  header), measures sharpness (Laplacian variance) and blown-out share, returns reason codes
  `image_blurry`, `image_glare`, `image_too_small`, or raises `ImageRejected`. **Not called by the
  upload path** (owner decision: provisional thresholds are not integrated into uploads; D5 and D11
  decide the policy and pass marks). The `LIMITS` are provisional engineering values. Measured on the
  synthetic set (seed 1): no clean page refused; all blur and glare copies flagged; noise raises the
  sharpness score (never read as blur) and sigma-30 noise is wrongly read as glare; mild low contrast
  (0.3) is caught on 4 of 8 pages; rotation is not detected. **Dependencies added:** `pillow`,
  `numpy` (the plan names both; the import-allowlist test maps `pillow` to `PIL`).
- **Step 3A-data: `tests/evaluation/generate.py`.** Deterministic synthetic prescription pages from
  the existing `tests/synthetic.py` placeholders, exact ground truth, five degradation types at two
  amounts each recorded per copy, seeded development and held-out splits (disjoint, tested). English
  labels only: no Bangla font has been chosen. No clinical content. The harness (3A-harness), the
  handwritten set (3B, D3) and all of step 9 are not built.

## Combined M2 batch after runner slices 8.2-8.4 (commit `0ce66f8`, 2026-11-13; CI run #38 passed)

Behavior changes only; details are in the code docstrings and tests.

- **Worker option `preprocess`** (`capture/extraction.py`): names from `exif`, `deskew`, `denoise`,
  `contrast`; default `PREPROCESS = ()` (nothing on). Pages are processed in memory for one attempt;
  the stored original is never changed and no copy is stored. The cloud-AI path still receives the
  originals. A page that cannot be decoded fails the attempt with the code `ImageRejected`. **Not
  recorded in the extraction row** (that needs a column: an owner decision). The runner does not
  expose it; it waits for the model specification and the 9B measurements.
- **Imaging** (`capture/imaging.py`): sharpness on a box-filtered page, glare by block medians,
  contrast and skew measures, reason codes `image_low_contrast` and `image_skewed` added, and
  `process()`. Limits remain provisional and are not wired into upload.
- **Schema mechanism (step 6A):** a schema entry may be `{"kind", "required", "rules"}`; `RULES` holds
  two technical checks (`not_future`, `positive`); a value that breaks a rule is never accepted;
  `missing_required()` and `check_spec()` exist. `SCHEMAS` is still empty; the schema version is not
  stored (needs a column).
- **Evaluation harness** (`tests/evaluation/harness.py`): field-level scoring, manifest and integrity
  checks, and a confidence analysis whose threshold is an argument, never a default.
- **Evidence (local Windows, 2026-11-13):** without a database 504 passed, 262 skipped. With a
  throwaway local PostgreSQL (pgserver in a venv outside the repo, since deleted; the owner approved
  it for this run) **758 passed, 8 skipped, 0 failed**, including the five PostgreSQL end-to-end
  tests (`test_m2_end_to_end.py`: upload of a real PNG to `needs_review`, original bytes and hash
  unchanged, no extra image row, adapter identity on the row, no verified event created, rules
  applied to stored fields, an undecodable page failing with a code only, no duplicate attempt).
  Not executed on Windows: the Linux-only runner tests and the three Linux-only process-group kill
  tests, and one symlink test (no privileges on that machine).
- **CI evidence (read from the run page and the expanded pytest log, 2026-11-13).** Run #38
  (`0ce66f8`, Linux, PostgreSQL 16) **passed: 766 passed, 0 skipped, 0 failed, 1 warning (`httpx`
  deprecation)**, 2m 38s of pytest, 3m 11s for the job. 766 = the 758 local passes plus the 8 tests
  skipped on Windows. Test names are not printed, so each test is inferred from the totals: with 0
  skipped, the Linux-only tests ran and passed (first and second SIGTERM, SIGKILL recovery, the
  connection-close-after-kill check, `WorkerDied` timing, the three process-group kill tests) and so
  did the five PostgreSQL end-to-end tests. Run #39 (`e4ba021`, the docs-only commit that recorded
  #38) ran the same code again and also **passed: 766 passed, 0 skipped, 0 failed, 1 warning**, 2m
  47s of pytest, 3m 19s for the job (read from the expanded pytest log; the Actions pages kept
  showing "In progress" for minutes after it had finished). So the Linux-only tests have passed in
  two runs on the same code (and the signal and kill tests also in run #36). That is two green runs,
  not proof against timing flakiness; the 20 s `WorkerDied` bound remains the implementation's own
  choice.

## M2 completion batch (2026-11-14, local, uncommitted)

All M2 work that needs no owner decision or external access; the open decisions are in ONE sheet,
`docs/M2_OWNER_DECISIONS.md` (D2, Q4, D7, D8, D10, D12, D14, D18/4B, D13, the external model). Added:

- **Drug matching infrastructure** (`capture/drugmatch.py`): catalog-independent; never selects a drug, never infers
  a strength or form, reports conflicts as ambiguous, similarity suggestions only with explicit parameters (no
  defaults: they are D8 values). No catalog or drug entry exists in the code.
- **Jonaki artifact linkage** (`capture/adapters/jonaki.py`): with an approved-adapter entry the factory requires
  both model directories to lie under its root and every file in them to be listed; a helper prints an entry for
  exactly those files. Synthetic files only; never run on real weights.
- **Review fixes (same batch):** a gap inside a number is no longer removed when comparing strengths (`1 0 mg` is not
  `10 mg`); an exact drug match lists the strength or form the written text did not state (`unconfirmed`); the runner
  is pointed at the resolved, verified model directories and a symlinked directory is refused; scoring refuses
  non-text input.
- **Text metrics** (`tests/evaluation/harness.py`): CER, WER, exact match, empty-output and failure rates, optional
  time and memory fields; micro-averaged; no script-specific folding.
- **Static privacy guards** (`tests/test_privacy_guards.py`): no temporary files or traceback handling in
  `capture/` and `workers/`, constant log messages with no exception values, no file writes outside the encrypted store.
- **Not implemented, by decision:** manual-entry and retry endpoints (D10, D12, D14), clinical parsers (D7), encryption
  of extracted text (D2), persistence of confidence and boxes (D18, schema), any real OCR execution or evaluation.
- **CI evidence recorded elsewhere:** run #41 (`72589e8`, Linux, PostgreSQL 16): 812 passed, 0 failed, 0 skipped, 1
  existing `httpx` deprecation warning, 149.45 s; the first Linux run including the Jonaki adapter tests (inferred
  from totals; see `docs/OCR_JONAKI.md`). Local evidence for this batch (Windows, disposable PostgreSQL via
  pgserver, since removed): **897 passed, 10 skipped, 0 failed** in 582 s. The 10 skips are platform-bound: 3 Linux-only
  process-group kill tests, 4 Linux-only runner signal and kill tests, and 3 symlink tests that need privileges this
  machine lacks (one in `test_ocr_config.py`, two in `test_jonaki_linkage.py`). None of this batch has been through CI.

## D13 clarification (D13 stays open as a whole)

The behavior already accepted on 2026-11-12 and implemented in 4A is unchanged: before any claim, an
integrity or availability check that finds the adapter unavailable means no claim and a warning.
**The alert mechanism remains OPEN.**

## Other decisions of this date

- **AC1 negative control** (an unguarded copy of the runner that must not produce the guarded
  outcome) is optional. The required positive AC1 tests must prove, independently of it, that module
  execution happens only through the guarded entry point and that spawned children re-import the
  module without re-running `main()`. Omitting the control does not weaken AC1.
- **Linux measurement branch.** A throwaway branch is approved to measure Linux multiprocessing
  bootstrap-failure behavior before any AC5 fix. No experiments on `main`, no automatic merge of
  that branch. Observations and evidence are reported before any code correction is proposed.

## Production-data boundary (unchanged)

Production extraction stays blocked by the existing 4B, D2 and Q4 prerequisites. Outside test mode
no adapter is available (4A), so a runner started outside test mode claims nothing and documents
stay `uploaded` (Option A). Test mode is a misconfiguration guard, not a security boundary, and
"synthetic data only" remains a project rule held by process. This boundary is not weakened.

**No-bypass rule.** The runner must not bypass the existing adapter allowlist or the availability
probe. No command-line option, environment variable or runner switch may enable production
extraction by bypassing those controls, and no new production-authorization mechanism is
introduced. Production extraction remains blocked pending 4B, D2 privacy approval and the FRD Q4
deployment decisions.

## Still open

D10, D12, D14, the D13 alert mechanism, FRD Q4 (hosting, supervisor or scheduler, poll-interval
value, log destination, metrics sink, environment injection, stop grace period) and every decision
not listed above. Startup validation of `DOCUMENT_STORE` and `DOCUMENT_KEY`, the idle-wait slice
length and the `run_due` stop-hook mechanism are plan proposals, not decisions.

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
