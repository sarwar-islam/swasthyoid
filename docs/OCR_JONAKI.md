# Jonaki OCR adapter — temporary, replaceable (setup, limits, blockers)

Status (2026-11-14): the adapter and its tests exist; **it has never run against the real model.**
The weights are gated and were not requested or downloaded; PaddleOCR and PaddlePaddle are not installed.

## What it is

`swasthyoid/capture/adapters/jonaki.py` implements the existing OCR adapter contract (interface version 0,
`capture/ocr.py`) for `islamsidratul/jonaki-bangla-ocr`: a PP-OCRv6 small **text-line recognizer** for
**printed Bengali**. A page also needs a PP-OCRv6 detector (`PP-OCRv6_medium_det`). Not handwriting, not
tables, English-only pages not evaluated (model card). A first-party model replaces it by being named in
`OCR_ADAPTER`; the worker, the extraction rows and M3 do not change.

## Blockers (owner actions; nothing was bypassed)

1. **Gated access.** The model page says: "Request access to Jonaki … every request is reviewed by the author."
   A Hugging Face account must request it and be approved. No download was attempted.
2. **License: CC BY-NC 4.0** (free for non-commercial use with attribution; commercial use needs a separate
   license from the author, `sidrat.saj@gmail.com`). The owner must decide whether use in this project is
   non-commercial before any use beyond local testing. The base model is Apache-2.0 (PaddlePaddle authors).
3. **Detector weights** (`PP-OCRv6_medium_det`) must be provisioned by a person into a local directory; their
   license was not reviewed here. The application never downloads anything.
4. **No permitted Bengali sample images.** The synthetic generator is English-only (no licensed Bangla font is
   chosen), so Jonaki's recognition cannot be evaluated on this repository's data, and **no accuracy figure is
   claimed**. The model card's book benchmarks say nothing about prescriptions.
5. **Interface version 0 is test-only** (D17/D18 unchanged): it runs only with `APP_ENV=test` and
   `SWASTHYOID_TEST_MODE_CONFIRM=1`; outside test mode no adapter is available. Production use needs the owner's
   approval of a real interface (D18), 4B, D2 and Q4.

## What is preserved, and what is not stored

Per line: text, recognition score (`confidence`) and box (`position`), in explicit reading order, per page. A
recognition score is **not** clinical correctness. In version 0 only the page text is stored (`raw_text`, lines in
reading order); items, scores and boxes are validated and discarded, because storing them needs the D18 interface
or a schema change (not approved). Stored provenance: `engine_id` `jonaki-bangla-ocr`, `model_version`
(`jonaki-small-rec@<revision>; PP-OCRv6_medium_det@<revision>`), `adapter_version` `jonaki-1`, interface version,
and the model checksum from the approved-artifact list (`OCR_ADAPTERS_APPROVED`).

**When the stored checksum proves the loaded weights, and when it does not.** Without an approved-adapter entry
(the case in every worker test so far) the test-mode checksum is the SHA-256 of empty input, a constant, and
proves nothing. With an entry in `OCR_ADAPTERS_APPROVED`, the factory now requires both model directories to lie
under the entry's `artifact_root` and **every file in them to be listed** (`check_linkage`; a symlink is refused),
so the manifest checksum covers exactly the files the runner is pointed at. That linkage is tested with
synthetic files only, never with real weights. Unresolved residual risks (not approved limitations; see
`docs/M2_OWNER_DECISIONS.md`): a file can change between the check and the runner reading it, hard links are not
detected, and the revisions are operator-stated strings. To produce an entry for exactly the files in the two
directories (a convenience; approving it is the owner's act):
`python -m swasthyoid.capture.adapters.jonaki --root ROOT --recognizer DIR --detector DIR`.

## Reading order

One column: rows by vertical centre (tolerance half the median line height), left to right within a row. Two-column
or two-page layouts come out in row order across the columns (the model card's gutter detection is not reproduced).

## Failure behavior (fail closed)

An undecodable page, a crashed or hung runner, or malformed runner output raises a coded adapter error (no message,
no text): the attempt fails, is retried, then the document goes to manual entry. A decodable page with no text is a
valid empty page. The runner gets an allowlisted environment (no token, no database URL, no keys), its stderr is discarded, and
offline mode is set. **The offline library settings (`HF_HUB_OFFLINE` and similar) only ask the libraries not to use
the network; they do not technically block network access.**

## Optional setup (separate environment; not part of the core install)

```bash
python -m venv /opt/jonaki-venv
/opt/jonaki-venv/bin/pip install -r swasthyoid/capture/adapters/jonaki_requirements.txt   # CPU PaddlePaddle
# after access is granted, by a person:
hf auth login
hf download islamsidratul/jonaki-bangla-ocr --local-dir /opt/models/jonaki
# provision the PP-OCRv6_medium_det detector into /opt/models/det (see PaddleOCR's documentation)
```

Environment for the worker (test mode only): `OCR_ADAPTER=swasthyoid.capture.adapters.jonaki:jonaki`,
`JONAKI_PYTHON=/opt/jonaki-venv/bin/python`, `JONAKI_MODEL_DIR`, `JONAKI_DETECTOR_DIR` (absolute paths),
`JONAKI_MODEL_REVISION` and `JONAKI_DETECTOR_REVISION` (the Hugging Face commit hashes), optional
`JONAKI_PAGE_SECONDS` (default 120 per page, provisional), and `OCR_ADAPTERS_APPROVED` listing the model files with
their SHA-256 manifest checksum. On CPU the model card says the PP-OCRv6 detector fails with oneDNN under
PaddlePaddle 3.3, so the runner leaves oneDNN off unless `JONAKI_ENABLE_MKLDNN=1`; a page takes 13-16 s on CPU.
GPU was not assessed.

## Tests

`tests/adapters/test_jonaki_adapter.py` (no database, fake runner) and `tests/test_jonaki_worker.py` (PostgreSQL,
fake runner) show the contract, ordering, provenance, fail-closed handling and isolation. They do not run the real
runner (`jonaki_runner.py`), which is unexecuted.

## CI verification (read 2026-11-14 from the run page and the expanded pytest log)

- **Commit and run:** `72589e8`, which includes the Jonaki code commit `cbc4f31`; GitHub Actions run #41.
  GitHub starts one run per push, so `cbc4f31` has no run of its own.
- **Result:** Success. Pytest: **812 passed, 0 failed, 0 skipped, 1 warning** (the existing `httpx` deprecation
  warning), in 149.45 s (2m 29s; the job took 3m 2s).
- **Environment:** Linux CI with PostgreSQL 16, as defined by `.github/workflows/ci.yml` (`ubuntu-latest`, Python 3.12,
  a `postgres:16` service); the versions were not re-read from this run's setup log. This was the first Linux CI run
  that included the Jonaki adapter tests.

**Inferred from totals, not shown by name.** `pytest -q` prints no test names, so no individual Jonaki test is
named in the log. That the Jonaki tests ran and passed is an inference: the run shows 0 skipped and 0 failed, and
812 equals the previous CI total (766, run #40) plus the 46 tests added by the Jonaki commit
(37 in `test_jonaki_adapter.py`, 9 in `test_jonaki_worker.py`). For the same reason the Linux `killpg` path for a
hung runner is inferred to have run, not shown.

**Verified by this run:** the adapter's fake-runner plumbing passes on Linux, with the Jonaki adapter class driven
through the existing worker and PostgreSQL against a fake runner that speaks the runner's JSON protocol.

**Still unverified (nothing in this run bears on these):**
- the real PaddleOCR runner (`jonaki_runner.py`): it has never been executed with PaddleOCR, and its use of the
  PaddleOCR result keys and input types is assumed from the model card;
- the actual Jonaki weights and the PP-OCRv6 detector, which have not been requested, downloaded or run;
- model provenance linkage with real weights: the linkage check (see above) has run only on synthetic files, and no
  approved-adapter entry has been exercised with real weights;
- Bengali OCR accuracy of any kind, and prescription accuracy;
- production readiness (interface version 0 is test-only; D18, 4B, D2 and Q4 remain open), and the license and access
  decisions.

One green run: it does not rule out timing flakiness in the hang and kill tests.
