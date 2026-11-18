# Deployment guide for the M2 extraction worker (owner decision Q4, 2026-11-14)

Approved: a **process supervisor** runs the worker, `EXTRACTION_POLL_SECONDS` is set by the operator, and **schema
migrations stay with the API**. Not decided (operator choices, not recorded decisions): the hosting provider, the
supervisor product, the interval value, a database `connect_timeout`, key rotation, and the alert mechanism (D13).
Nothing below has been run on a real server; the unit file is a template, untested.

**Production extraction is still blocked.** Interface version 0 is test-only, so outside test mode no OCR adapter is
available and the worker claims nothing (D18, 4B). The worker can be deployed and supervised now; it will idle.

## Processes

| Process | Command | Role |
|---|---|---|
| API | `uvicorn swasthyoid.api.main:app` | serves requests, **applies the schema at startup** (additive, idempotent) |
| Worker | `python -m swasthyoid.workers.extract` | claims due documents and extracts them; **never applies or alters the schema** |

Start the API first. The worker refuses to start (exit 1) if the tables or columns it needs are missing.

## Environment

| Variable | Used by | Notes |
|---|---|---|
| `DATABASE_URL` | both | a `postgresql://` URI or keyword string; no default |
| `DOCUMENT_STORE`, `DOCUMENT_KEY` | both | encrypted originals on disk; `DOCUMENT_KEY` is a Fernet key |
| `PII_KEY`, `HMAC_KEY`, `JWT_SECRET` | API | phone and name encryption, keyed hashes, tokens |
| `EXTRACTION_KEY` | both | **Fernet key for extracted text (D2).** The API refuses to start and the worker exits 2 without it |
| `EXTRACTION_POLL_SECONDS` | worker, loop mode | positive number of seconds; no default; not needed for `--once` |
| `OCR_ADAPTER`, `OCR_ADAPTERS_APPROVED` | worker | adapter reference and the approved-artifact list |
| `DRUG_CATALOG_PATH`, `DRUG_CATALOG_SOURCE`, `DRUG_CATALOG_VERSION` | worker, optional | drug-name candidates (Phase 7B). Unset: off. Set: `DRUG_CATALOG_PATH` is an absolute `medicine.csv`, `DRUG_CATALOG_SOURCE` (the owner's statement of source and terms) is **required**, and a bad value makes the worker **exit 2**. Do not enable until the data's licence is settled (FRD Q1) |
| `APP_ENV`, `SWASTHYOID_TEST_MODE_CONFIRM` | both | test mode needs **both**; never set in production |

Generate a key: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
Keep every key outside the database and outside backups of it.

## Supervising the worker: exit codes

| Exit code | Meaning | Supervisor policy |
|---|---|---|
| 0 | a `--once` cycle finished, or a graceful stop after the first signal | do not restart unless it was not asked to stop |
| 1 | infrastructure failure (database unreachable or lost, schema missing) | restart after a delay; unlimited |
| 2 | invalid usage or configuration (missing `EXTRACTION_KEY`, bad `DATABASE_URL`, test mode misconfigured) | **do not restart**: it will fail the same way; alert a person |
| 3 | aborted by a second signal | restart; the interrupted attempt is recovered when its lease expires |

The first stop signal ends the loop before the next claim and lets the running attempt finish; a second signal exits
at once. Give the supervisor a stop timeout longer than one attempt (the hard timeout, 10 minutes by default).
A killed worker loses nothing: its claim expires and a later worker recovers the document, with one stored result per
version.

systemd template (untested):

```ini
[Service]
ExecStart=/opt/swasthyoid/venv/bin/python -m swasthyoid.workers.extract
EnvironmentFile=/etc/swasthyoid/worker.env        # root-only; holds the keys and EXTRACTION_POLL_SECONDS
Restart=on-failure
RestartSec=10
RestartPreventExitStatus=2
TimeoutStopSec=660
```

## Retry policy (owner decision 2026-11-14: lifetime budget of 5 OCR executions)

A document gets at most **5 actual OCR executions in its whole life** (`MAX_LIFETIME_ATTEMPTS`, stored in
`documents.extraction_lifetime_attempts`). Automatic retries, patient-triggered retries and recovery after a crash share that one
counter; asking for a retry, a claim and a failure before OCR starts are not counted, a crash or timeout during OCR is. Each run (the
first, and each patient retry) may make up to 3 automatic executions, with 1 then 2 minutes of waiting between them, always limited by
what remains of the 5. Failures that retrying cannot fix are not retried (the patient is told to enter the document by hand). After the
5th execution the document ends in `extraction_failed` and the retry endpoint answers 409 `retry_limit_reached`; manual entry always
works. **Apply the schema (it adds one column) before starting a worker that has this change;** the worker never migrates and refuses to
run (exit 1, `schema_unavailable`) if the column is missing. Operators can expect at most 5 OCR runs for one stubbornly failing document
(previously up to 18; see `docs/DECISIONS.md`, "Worker reliability fix").

## What operators can see

One line per cycle on stderr, counts only: `runner: code=cycle_done attempts=N due=N in_flight=N lease_expired=N failed=N`.
A growing `due` with no `attempts` means the worker is down or no adapter is available. No document text, key,
connection string or exception message is ever written.

## Extracted text at rest (D2)

- `extractions.fields` is stored sealed with `EXTRACTION_KEY`; the raw text is a token in `extraction_raw_texts` and
  only its SHA-256 stays in the append-only row; **the raw text is deleted when a document is verified or rejected**.
- Losing `EXTRACTION_KEY` makes stored extracted text unreadable; there is no recovery and **no key rotation yet**.
- A database backup holds only sealed data and the retained hashes; the key must be stored and backed up separately.
- Rows written before D2 are plain and cannot be rewritten (the table is append-only). Synthetic data only.
- The worker and the API both hold the key; whoever holds it can read the text.

# W4: the whole stack (2026-11-18)

Everything below uses **synthetic data only**. Nothing here has been run against a real host, because Docker was not
available where it was written. The compose file, nginx config and scripts are checked by review and by
`swasthyoid/tests/test_deploy_files.py` (the CSP hash matches the pre-render script; the example env holds no secret).
S3 (hosting and data location) is still open, so this is for a demo or staging, not for real patients.

## Docker Compose (one machine)

```
cp deploy/.env.example deploy/.env      # fill every value; never commit it
docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d --build
```

| Service | What it runs | Notes |
|---|---|---|
| `postgres` | PostgreSQL 16 | data in the `pgdata` volume |
| `api` | uvicorn, `--proxy-headers` | applies the schema at startup; `RATE_LIMIT_PER_MINUTE` per client address |
| `worker-extract` | `python -m swasthyoid.workers.extract` | idles until an OCR adapter is approved (D18) |
| `worker-safety` | `python -m swasthyoid.workers.safety` | no catalog: every check is `blocked: catalog_unavailable` (fail closed) |
| `worker-notify` | `python -m swasthyoid.workers.deliver` | `NOTIFY_CHANNEL` = `in_app` or `sms_console`; `sms_gateway` exits 2 until S2 |
| `web` | the built web app (live API mode, landing pre-rendered) | static files only |
| `nginx` | edge proxy on port 80 | `/api` to api, the rest to web; CSP, HSTS, nosniff, no-referrer; 10 r/s per address on `/api`, 10 a minute on sign-in codes |

Workers restart on failure up to five times; exit 2 is a configuration error and fails the same way each time.
**TLS:** terminate it in front of nginx (a load balancer, or a `listen 443 ssl` block with your certificates). HSTS only
takes effect over HTTPS. The CSP pins the one inline script by its hash: if `web/scripts/prerender.mjs` changes that
script, update the hash in `deploy/nginx.conf` and `deploy/vercel.json` (the test fails until you do).

**Synthetic demo data:** set `APP_ENV=development` in `deploy/.env`, then
`docker compose -f deploy/docker-compose.yml --env-file deploy/.env --profile demo run --rm seed`. It fills an empty
database only. With `DEV_LOG_CODES=1` the API writes sign-in codes to its own log (there is no SMS gateway until S2):
acceptable for a synthetic demo, **never with real people**.

## Backup and restore

- `deploy/backup.sh` writes `deploy/backups/swasthyoid-<UTC time>.dump` (pg_dump custom format).
- `deploy/restore.sh <file.dump> --yes` stops the API and workers, replaces the database in one transaction, starts them.
- The keys are **not** in the dump. Keep `PII_KEY`, `DOCUMENT_KEY`, `EXTRACTION_KEY`, `HMAC_KEY` and `JWT_SECRET` in a
  separate place; a dump without its keys cannot be read. Back up the `documents` volume at the same time.
- A restore rehearsal is still to be done and written down (W4 exit condition).

## Free tier: Vercel (web) + Render (API) + Neon (database)

Check each provider's current free-tier terms before relying on them; they change.

1. **Neon:** create a project and database; copy its connection string (keep `sslmode=require`). Free compute suspends
   when idle, so the first request after a pause is slow.
2. **Render:** new Web Service from this repository, Docker, `deploy/Dockerfile.api`. Environment: `DATABASE_URL` (Neon),
   the five keys, `APP_ENV`, `RATE_LIMIT_PER_MINUTE`, `DOCUMENT_STORE=/tmp/documents`. Health check path `/health`.
   Free services sleep when idle and have no persistent disk: **uploaded documents are lost on every restart**, so this
   demonstrates the screens, not storage.
3. **Vercel:** import the repository with root `web`, build command `npm run build`, output `dist`, environment
   `VITE_API_MODE=live`. Copy `deploy/vercel.json` to `web/vercel.json` and set your Render address. `/api` is rewritten
   to Render, so the browser sees one origin and the refresh cookie (`SameSite=Strict`, path `/api/v1/auth`) works.
4. **Workers:** free plans have no always-on background workers. Without them notifications still appear in the in-app
   inbox (B3), but prescription checks stay queued and nothing is extracted. When you need one, run a worker with
   `--once` by hand (`python -m swasthyoid.workers.deliver --once`) against the same `DATABASE_URL`, or use a paid worker.
   Run the seed once from your own machine with `APP_ENV=development` and the Neon `DATABASE_URL`.

## Demo backend on Hugging Face (sarwarcss/swasthyoid-api, 2026-11-18)

Running, synthetic data only. `deploy/hf-space/` is a Gradio Space on ZeroGPU hardware (a ZeroGPU Space cannot move down
to CPU basic without a PRO subscription). `app.py` starts PostgreSQL in the container (as the `postgres` user; Spaces run as
root), seeds the synthetic accounts, starts the extract (PaddleOCR English, **test mode**), safety and deliver workers,
and serves the API. Gradio must own port 7860 on ZeroGPU, with SSR off, and forwards `/api` and `/health` to the API on
7870. The PaddleOCR weights are downloaded on first start and pinned by their SHA-256 manifest in an approved list built
from exactly those files.

- **Update it:** `python deploy/hf-space/push.py sarwarcss/swasthyoid-api` (needs your own `huggingface_hub` login).
- **Sign-in codes:** in the Space's Logs tab (`DEV one-time code for ...`). There is no SMS gateway until S2.
- **Restarts:** the database, uploads and keys start fresh; the synthetic seed runs again.
- **Checked live:** `/health`, sign-in as the seeded patient, a synthetic English prescription uploaded, PaddleOCR read
  it (document moved to `needs_review`, no failed attempts). Reading is English only; Bangla needs Jonaki.
- **Vercel:** `web/vercel.json` rewrites `/api/*` to `https://sarwarcss-swasthyoid-api.hf.space`. Set
  `VITE_API_MODE=live` in the Vercel project, or the site keeps using the mock and nothing is read.
