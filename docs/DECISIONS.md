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
"Worker reliability (M2 step 1)" at the end of this file, which is implemented and awaiting
owner review. The labels below are kept as written at the time of the proposal.**

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

# Worker reliability (M2 step 1) — IMPLEMENTED, AWAITING OWNER REVIEW

Not marked complete. Approved requirements from the owner on 2026-11-12; code in
`swasthyoid/capture/extraction.py`, tests in `swasthyoid/tests/test_extraction_recovery.py`.

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
- **Not verified on Linux or in CI.** Everything here was run on Windows against a local
  PostgreSQL 16. Process spawning and killing behave differently on Linux, and several
  recovery tests depend on short timings that a slow CI machine could miss.
- **The engine must be sendable to a child process** (a module-level function). One that is
  not fails at start-up of the child and uses up the document's attempts.
- **Killing the OCR process does not kill programs it started itself.** This matters if the
  chosen engine launches a separate program.
- **The integration tests still run the in-process mode** (under `APP_ENV=test`); only the
  recovery tests exercise the child-process path.
- **A new child process per document** means the OCR models load each time. Acceptable for a
  prototype; a long-lived OCR process is a later optimisation.
- **Clock.** Leases use the database clock only, so worker clocks do not matter, but a
  worker that stalls completely (for example a frozen machine) can only be fenced, not
  stopped: its late result is refused when it tries to store.
- **Cloud AI.** The send is now audited in its own committed step before sending, but a
  retried attempt would send again. Not reachable: no provider, threshold unset.
