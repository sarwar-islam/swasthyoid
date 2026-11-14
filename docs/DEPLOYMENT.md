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
