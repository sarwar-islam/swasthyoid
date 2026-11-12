# Session handoff — SwasthyoID

Refreshed 2026-11-12. Untracked on purpose: a snapshot, not permanent documentation. Durable
facts live in `CLAUDE.md`, `docs/DECISIONS.md`, `docs/FRD.md` (v3) and
`docs/M2_COMPLETION_PLAN.md`. Where this file and those disagree, those win. **Verify Git state
yourself** (`git status`, `git log origin/main..HEAD`); do not trust this file for it.

## Next session: start here

1. Read `CLAUDE.md`, this file, `docs/DECISIONS.md` (from "AI models are owner-supplied" to the
   end), `docs/M2_COMPLETION_PLAN.md`, then FRD sections 1.3, M2 and 8.
2. Run `git status` and `git log origin/main..HEAD --oneline`.
3. **Do not write code.** Step 4A is approved in scope (D17) but its implementation waits for
   the owner's go-ahead, and Step 1 is not yet accepted.

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

## Git state (verified 2026-11-12 with `git status` and `git log origin/main..HEAD`)

| Item | State |
|---|---|
| Local branch | `main` (`6b11e65`), 3 commits ahead of `origin/main` (`6021085`) |
| `1ebdb15` | P2 step 1: worker reliability. In local `main`, **not pushed to `main`**; also on the verification branch |
| `2389991` | Docs: first version of the M2 plan. Local `main` only, not pushed |
| `6b11e65` | S1 fix on local `main`: cherry-pick (`-x`) of `cc836f5`, **accepted by the owner**. Code identical to the CI-tested `cc836f5`. Not pushed |
| `cc836f5` | The same S1 fix on `verify/step1-1ebdb15`, tested by CI run #14 |
| Remote `origin` | `main` = `6021085`; `verify/step1-1ebdb15` = `cc836f5` (`1ebdb15` + `cc836f5`) |
| Worktree | Verification branch checked out in the session scratchpad (`.../scratchpad/verify-step1`); `main` checkout unaffected |
| `docs/DECISIONS.md`, `docs/FRD.md`, `docs/M2_COMPLETION_PLAN.md` | Modified, **uncommitted**, pending owner approval |
| `docs/SESSION_HANDOFF.md`, `.claude/` | Untracked; never commit `.claude/` |
| Application code, schema, `pyproject.toml` in `main` | Same as the verification branch (`git diff main verify/step1-1ebdb15 -- swasthyoid pyproject.toml .github` is empty). Local tests without a database: 38 passed, 221 skipped. `main` itself has not run in CI |

Never commit or push without the owner's explicit instruction; "commit" and "push" are separate.

## Step 1 status: Linux CI passed, S1 fix accepted, NOT marked complete

- **Code review (2026-11-12):** claim fencing, lease handling, retries and recovery are correct
  as designed. Findings S1–S8 are recorded in `docs/DECISIONS.md`, "Verification and the S1 fix".
- **Linux CI** on `verify/step1-1ebdb15` (ubuntu-26.04, Python 3.12.16, PostgreSQL 16.15):
  - run #13, `1ebdb15`: **258 passed, 0 failed, 0 skipped, 0 errors**;
  - run #14, `cc836f5`: **259 passed, 0 failed, 0 skipped, 0 errors**.
  All database tests ran, including every recovery test, the Linux spawn and kill tests and the
  timing-sensitive tests. `pytest -q` prints no test names; the counts show it.
- **S1 fixed and accepted** (`cc836f5`): a lost database connection now raises
  `WorkerConnectionLost` with no further write; new `pg_terminate_backend` recovery test.
- **Open:** S2–S8 (not approved for fixing); the raw error still escapes if the connection drops
  during the failure write itself; one green run per commit does not rule out timing flakiness;
  CI warns that `actions/checkout@v4` and `actions/setup-python@v5` target Node 20 (workflow
  unchanged).
- **Tests on this machine:** without a database, 38 passed and 220 skipped on `main` (221 skipped
  on the verification branch). No PostgreSQL, Docker or WSL here; do not install `pgserver`,
  Docker or WSL without the owner's OK.
- **Reading CI:** `gh` is not installed. Read runs in the browser pane (the owner signed in to
  GitHub there on 2026-11-12) or ask the owner.

## Pending owner decisions and approval gates

**Gates, in order:**

1. Step 1: Linux CI checked (done), S1 fix accepted (done), S1 fix cherry-picked onto local
   `main` as `6b11e65` (done) → push of `main` approved → owner marks Step 1 complete. Also the owner's call: what to do with the verification branch and the
   scratchpad worktree, and whether any of S2–S8 are fixed.
2. Approval of the revised docs (FRD v3, M2 plan, DECISIONS entries), then a commit the owner
   asks for.
3. Go-ahead to implement 4A, plus its open sub-choices: C1, C2, D13, 4A-15, 4A-16, 4A-20, 4A-23,
   4A-24, and the identity column names and migration.
4. D4 and D18 (model specification), the 4B compatibility review, then explicit integration
   approval. Deployment is a separate approval.

**Other open decisions:** D2 and FRD Q8 (extraction privacy, retention); D3; D5–D11; D12, D14
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
