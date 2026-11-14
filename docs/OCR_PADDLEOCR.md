# PaddleOCR (English) adapter: a second, temporary, replaceable OCR provider

Status 2026-11-14: **implemented and tested with a fake runner only; committed (`c52897b`, docs `8be3b03`) and CI-green.** The real runner and the real weights have
never been run in this repository. No accuracy of any kind is known. It sits **alongside** the Jonaki adapter
(`docs/OCR_JONAKI.md`, untouched, the Bangla reference); the two share no code.

## What it is, and what it is not

- PaddleOCR (Apache-2.0, as the owner states; the licence of the individual model files was not read here) text detection plus
  **English** text-line recognition, whole page in, lines out. Orientation classification, text-line orientation and
  document unwarping are **off** in this first slice (each is an extra weight set needing its own approved manifest entry).
- **Not a Bangla reader.** The owner first asked for Bangla; whether PaddleOCR publishes an official Bangla recognizer could not
  be confirmed (the sources disagree), so the first slice is English: medicine names, doses and schedules written in English.
  Jonaki remains the only Bangla path. Handwriting is not supported.
- It implements the existing adapter contract **version 0, which is test-only** (D17/D18 unchanged). Outside test mode the worker
  still finds no adapter and idles; documents go to manual entry. Choosing this model does not change that: it needs the owner's
  D18 / 4B decision.

## Files

| File | Role |
|---|---|
| `capture/adapters/paddleocr_adapter.py` | the adapter (standard library only), the factory `paddleocr_en`, the linkage check and a command that prints the approved-list entry |
| `capture/adapters/paddleocr_runner.py` | runs PaddleOCR in a **separate environment**, as a child process per read; JSON over stdin and stdout |
| `capture/adapters/paddleocr_requirements.txt` | optional pinned packages for that environment; not in `pyproject.toml`, not installed by CI |
| `capture/adapters/paddleocr_prepare.py` | owner-run, one-time weights download and SHA-256 manifest (the only networked step) |
| `tests/adapters/fake_paddleocr_runner.py`, `fake_paddleocr.py` | the fake runner and a test factory |
| `tests/adapters/test_paddleocr_adapter.py`, `test_paddleocr_linkage.py`, `test_paddleocr_prepare.py` | the tests |

The module is named `paddleocr_adapter.py`, **not** `paddleocr.py`: a file of that name next to the runner would shadow the real
`paddleocr` package. The runner is also started with `-I` (isolated mode), so the adapters directory is not on its import path.

## Identity and output

`engine_id` = `paddleocr-en`; `interface_versions` = `[0]`; `test_only` = true; `adapter_version` = `paddleocr-1`;
`model_version` = `<recognizer name>@<revision>; <detector name>@<detector revision>` (at most 128 characters). Per page, in explicit
reading order: `text`, the recognition score as `confidence` (a recognition score is **not** clinical correctness) and the box as
`position`. In version 0 only the text reaches the database. The reading-order and cleaning helpers are copies of Jonaki's, so
either adapter can be retired alone; one column is assumed (a two-column page comes out in row order across the columns).

## Setup (the owner; nothing here was run)

1. Create a **separate** virtual environment and install `paddleocr_requirements.txt`. The pinned versions are the ones the Jonaki
   model card reports as tested; they are **not verified** for the English PP-OCRv5 models. Confirm them.
2. Run, in that environment and with network access, **yourself**:
   `python -I swasthyoid/capture/adapters/paddleocr_prepare.py --out /srv/ocr/paddleocr-en > prepared.json`
   The default model names (`PP-OCRv5_mobile_det`, `en_PP-OCRv5_mobile_rec`) are **provisional**: confirm that they exist in the
   installed PaddleOCR (`--detector-name`, `--recognizer-name` override them; `en_PP-OCRv4_mobile_rec` is the alternative named).
   The script refuses a non-empty output directory, downloads into a private cache inside it, copies exactly the two model
   directories (no symbolic links), deletes the cache and prints a manifest with the SHA-256 of every file. It assumes PaddleX's
   cache layout and stops if a model directory is not found exactly once.
3. Review `prepared.json` and the models' licences. Print the approved-list entry and review it:
   `python -m swasthyoid.capture.adapters.paddleocr_adapter --root /srv/ocr/paddleocr-en --recognizer /srv/ocr/paddleocr-en/recognizer --detector /srv/ocr/paddleocr-en/detector`
   Putting that entry into `OCR_ADAPTERS_APPROVED` is the owner's act.
4. Run strictly offline with: `OCR_ADAPTER=swasthyoid.capture.adapters.paddleocr_adapter:paddleocr_en`, `PADDLEOCR_PYTHON` (the
   interpreter of the separate environment), `PADDLEOCR_MODEL_DIR` and `PADDLEOCR_DETECTOR_DIR` (absolute, the two directories),
   `PADDLEOCR_MODEL_REVISION` and `PADDLEOCR_DETECTOR_REVISION` (what you say the weights are, at most 40 characters of
   `A-Za-z0-9._-`), optional `PADDLEOCR_RECOGNIZER_NAME`, `PADDLEOCR_DETECTOR_NAME` and `PADDLEOCR_PAGE_SECONDS` (default 120, a
   provisional guess, not measured). With an approved entry present, every file in both directories must be listed, or the
   adapter refuses to load (`model_integrity_failed`).

## Isolation

The runner child gets an **allowlisted** environment only (no database URL, keys or tokens; **no `HOME` or `USERPROFILE`**), plus
`HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1` and `PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True`. It receives the model directories
explicitly and refuses to start if either is missing, so it never downloads. It makes a private, empty cache directory (with
`os.mkdir`, not `tempfile`, because the privacy guard forbids `tempfile` under `capture/`; the directory holds library caches,
never page content) and deletes it. stderr is discarded, no exception message, path or page text is ever carried in an error, and
the child runs in its own session so the OCR child's process-tree cleanup ends it. **The offline settings ask the libraries not to
use the network; they do not block it** (residual risk R3, `docs/M2_OWNER_DECISIONS.md`): that needs an operating-system rule at
deployment.

## Failure behavior

A page that cannot be decoded, a crashed or hung runner, or malformed output fails the attempt with a typed code
(`engine_error`, `malformed_output`, `engine_unavailable`); a page that decodes with no text is a valid empty page. The
lifetime budget of 5 OCR executions per document applies as for any adapter (`docs/DECISIONS.md`, "Worker reliability fix").

## Not verified, stated plainly

The real runner and the preparation script were never executed here (no PaddleOCR, no weights, no network used). The PaddleOCR
call follows the Jonaki runner's usage (PaddleOCR 3.x), not this model pair's documentation. Model names, package versions, the
cache layout and the CPU time per page are all unconfirmed. **No accuracy, no Bangla support and no clinical correctness is
claimed.** Evaluation needs the weights and permitted data; the clinical reviewer's sign-off (FRD Q7) is separate.

## Tests (no PaddleOCR, no weights, no network)

The real adapter class against a fake runner: contract and validators, reading order, preserved confidence and positions, every
failure code, a hung runner killed at the limit, an allowlisted environment with no secrets and no `HOME`, isolated command with
the model names, factory refusals, linkage with synthetic files (an unlisted file, a path outside the root, symlinks, `..`),
the preparation script's pure parts and refusals, and that nothing in the core imports a model library or the preparation script.

## CI evidence

- CI run #53 (`8be3b03`; `ubuntu-latest`, Python 3.12, PostgreSQL 16): **1229 passed, 0 failed, 0 skipped**, 1 warning, 245.69 s (0:04:05).
- CI run #52 (`91a05c9`, a docs-only commit): 1145 passed, 0 failed, 0 skipped, 1 warning, 235.28 s (0:03:55), the same count as run #51 because no code changed.
- The two summary lines were pasted by the owner without run labels; they are attributed by the commits' contents (1229 = 1145 + 84, the new PaddleOCR tests: 81 passed and 3 symlink tests that run on Linux). The summary does not name tests.
- What this shows: the adapter, linkage and preparation-script tests (fake runner, synthetic files) pass on Linux, and no existing
  test regressed. What it does **not** show: anything about PaddleOCR, the weights, the real runner or accuracy: none of them ran.
