# Session handoff — SwasthyoID

Refreshed 2026-11-12. Committed at the owner's request in `2b626aa`, but still a snapshot, not
permanent documentation. Durable
facts live in `CLAUDE.md`, `docs/DECISIONS.md`, `docs/FRD.md` (v3) and
`docs/M2_COMPLETION_PLAN.md`. Where this file and those disagree, those win. **Verify Git state
yourself** (`git status`, `git log origin/main..HEAD`); do not trust this file for it.

## Next session: start here

1. Read `CLAUDE.md`, this file, `docs/DECISIONS.md` (from "AI models are owner-supplied" to the
   end), `docs/M2_COMPLETION_PLAN.md`, then FRD sections 1.3, M2 and 8.
2. Run `git status` and `git log origin/main..HEAD --oneline`.
3. **Do not write more code.** Step 1 is complete. 4A is built on branch
   `4a/ocr-infrastructure` (`7c0c148`) and waits for the owner's review and merge approval.

## OCR model: facts and rules

- **OCR model development has not started.** No architecture, framework, dataset or trained
  model has been selected.
- **The owner independently selects, trains, owns and supplies the model.** Its specification
  will determine the final adapter contract.
- **No model selection, installation, download, training, bundling, integration or deployment
  is authorised.** Fake adapters are test-only. There is no fallback engine.
- **D17 — APPROVED WITH REVISIONS (2026-11-12):** build only the model-independent 4A
  infrastructure, tested with fakes. It authorises no real adapter and no deployment.
- **Version 0 is an infrastructure-test interface only, not a production contract.** Its
  `raw_text` construction is for synthetic tests only; its items and positions are never stored.
- **D18 — OPEN:** every model-dependent item (input, page handling, hints, output, granularity,
  serialization, confidence, position format, production `raw_text`, limits, batching, timeouts,
  process model, resources, manifest format and checksum computation, model-specific retry
  semantics). Decided only after the model specification arrives.
- No real patient data in OCR execution until step 2's encryption and privacy controls are
  implemented and approved.
- The old plan to choose RapidOCR or Tesseract is obsolete.

## Git state (verified 2026-11-12 with `git status`, `git log` and `git ls-remote`)

| Item | State |
|---|---|
| `main` | `origin/main` = local `main` = `33e2aa1` (Step 1 recorded complete). Not changed by 4A |
| Commits pushed to `main` on 2026-11-12 | `1ebdb15` (Step 1), `2389991` (M2 plan, first version), `6b11e65` (S1 fix, cherry-pick of `cc836f5`), `2b626aa` (docs), `282bd44` (FRD v3, doc fixes, `.gitattributes`), `3f348d3` (handoff Git state), `33e2aa1` (Step 1 complete) |
| `4a/ocr-infrastructure` | Branched from `33e2aa1`: `7c0c148` (4A code and tests), `9f68552` (docs), `06ecf92` (review fixes), plus a docs commit; pushed to `origin`, **not merged**. Checked out in the main checkout |
| `verify/step1-1ebdb15` | On `origin` at `cc836f5` (`1ebdb15` + `cc836f5`); kept until the owner decides |
| Worktree | Verification branch checked out in the session scratchpad (`.../scratchpad/verify-step1`); kept until the owner decides |
| `.claude/` | Untracked; never commit it |
| Line endings | `.gitattributes` keeps every text file LF |

Never commit or push without the owner's explicit instruction; "commit" and "push" are separate.

## Step 1 status: COMPLETE (marked by the owner, 2026-11-12)

- **Code review (2026-11-12):** claim fencing, lease handling, retries and recovery are correct
  as designed. Findings S1–S8 are recorded in `docs/DECISIONS.md`, "Verification and the S1 fix".
- **Linux CI** (ubuntu-26.04, Python 3.12.16, PostgreSQL 16.15), all with 0 failed, 0 skipped,
  0 errors:
  - run #13, `1ebdb15` on `verify/step1-1ebdb15`: 258 passed;
  - run #14, `cc836f5` on `verify/step1-1ebdb15`: 259 passed;
  - run #15, `3f348d3` on `main`: **259 passed**.
  All database tests ran, including every recovery test, the Linux spawn and kill tests and the
  timing-sensitive tests. `pytest -q` prints no test names; the counts show it.
- **S1 fixed and accepted:** a lost database connection now raises `WorkerConnectionLost` with no
  further write; new `pg_terminate_backend` recovery test. On `main` as `6b11e65`.
- **Open, not part of Step 1:** S5 Parts B and C and A+, S6 (mandatory Step 8 acceptance criteria
  AC1–AC6 in the plan; D9 first), S7, S8 (deferred by the owner; S2, S3
  and S4 are fixed and S5 Part A is implemented; all CI-verified, runs #21–#25, see
  `docs/DECISIONS.md` "CI evidence for the 4A fixes, S2–S5"); the raw error still escapes if the
  connection drops during the failure write itself; one green run per commit does not rule out
  timing flakiness; CI warns that `actions/checkout@v4` and `actions/setup-python@v5` target
  Node 20, and `ubuntu-latest` is now Ubuntu 26 (workflow unchanged).
- **Tests on this machine:** without a database, 38 passed and 221 skipped on `main`; 377 passed
  and 243 skipped on `main` at `9013429` (S2/S3, S4 with 142 new tests, then S5 Part A with 8 new
  tests and one skipped PostgreSQL test). 4A is merged into `main`. No PostgreSQL, Docker or WSL here; do not install
  `pgserver`, Docker or WSL without the owner's OK.
- **Test mode (4A, Option C):** needs `APP_ENV=test` **and** `SWASTHYOID_TEST_MODE_CONFIRM=1`.
  Exporting `APP_ENV=test` alone makes the API and the worker refuse to start (intended).
- **Reading CI:** `gh` is not installed. Read runs in the browser pane (the owner signed in to
  GitHub there on 2026-11-12) or ask the owner.

## Pending owner decisions and approval gates

**Gates, in order:**

1. Step 1: **complete** (Linux CI, S1 fix, push of `main`, CI on `main` and the owner's sign-off
   all done on 2026-11-12). Still the owner's call: what to do with the verification branch and
   the scratchpad worktree, and whether any of S2–S8 are fixed.
2. Approval of the revised docs: `DECISIONS.md`, the M2 plan, FRD v3 and this file are
   committed in `2b626aa` and `282bd44`; owner approval of the FRD and plan content is pending.
3. 4A: built on `4a/ocr-infrastructure`. Final review decisions applied (B1 option a, M1 option
   (ii), M2, M3, L4, L5 and the test-package reference fix in `06ecf92`); see `DECISIONS.md`,
   "4A implementation". Waiting for the owner's review of the fixes, then separate merge approval.
4. D4 and D18 (model specification), the 4B compatibility review, then explicit integration
   approval. Deployment is a separate approval.

**Other open decisions:** D2 and FRD Q8 (extraction privacy, retention); D3; D5–D8, D10, D11 (D9 decided 2026-11-13); D12, D14
(manual entry); D15 (M3 start); D16 (P0 deviation); FRD Q1, Q3, Q4, Q5, Q7, Q12, Q15; Option A
sub-decisions (mapped to D10, D12, D13, D14); whether `CLAUDE.md` gets an AI-model rule line;
provisional values (caregiver 30/90 days and 24 h, rate limits, Luhn check digit).

**Unresolved document issue:** the "infrastructure-complete" level (plan, FRD P2 gate) includes
M2 exit gates 4, 5 and 6, which need clinical decisions (D7, D8, D11, FRD Q1, Q7). Owner to decide
whether those gates move to production-ready or stay.

## How the owner works

- Plan or design first, then wait for approval. One step at a time.
- Report separately: implemented, tested, committed, pushed, CI status. Never claim CI passed
  unless the owner confirms it.
- Do not fill the clinical field list, enable cloud AI, or start M3 without approval.
- Synthetic data only.

## Running the tests

- Without `DATABASE_URL`, `pytest` skips the database tests (38 pass, 220 skip).
- With PostgreSQL 16 in `DATABASE_URL`, the last full local run (Windows, before `1ebdb15` was
  committed) gave 258 passed. The role needs `CREATE DATABASE`.
- This machine has no PostgreSQL, Docker or WSL. An earlier session used the `pgserver` pip
  package in a throwaway virtualenv outside the repo; it is not installed now. Do not add it to
  the project.
- `APP_ENV=test` allows in-process OCR; the extraction test fixtures set it.
- Windows: write Python to a script file rather than a shell heredoc with triple quotes; after an
  interrupted run, kill leftover `postgres.exe` and use a fresh data directory.

## Code map

- `swasthyoid/core/` — `consent_authz.py`, `audit.py`, `notification.py`, `events_provenance.py`
- `swasthyoid/identity/` — `accounts.py`, `otp.py`, `sessions.py`, `health_id.py`
- `swasthyoid/capture/` — `documents.py`, `storage.py`, `extraction.py`
- `swasthyoid/api/` — `deps.py`, `m1.py`, `caregivers.py`, `documents.py`, `main.py`
- `swasthyoid/pii.py`, `swasthyoid/db.py`; one `schema.sql` each in core, identity, capture,
  applied idempotently at startup in that order
