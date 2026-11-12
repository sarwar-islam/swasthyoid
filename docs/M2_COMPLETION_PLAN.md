# M2 completion plan (P2) — approved baseline

Status on 2026-11-12. Slices 1 and 2 are built and pushed (`e18bf48`, `63df1f9`, `6021085`):
upload, encrypted immutable originals, the extraction pipeline on a fake OCR engine, and the
recovery tests. Step 1 of this plan is committed locally as `1ebdb15` and is **not pushed and
not marked complete**. **CI status is not verified for `63df1f9`, `6021085` or `1ebdb15`.**

This plan covers what M2 still needs. It does not start M3, does not enable cloud AI, and
does not fill the clinical field list. Each step carries its own status; only step 1 has
been built, and every other step is still a plan.

## Implementation order

| Step | Task | Depends on | Blocked by a decision? |
|---|---|---|---|
| 1 | Worker reliability | — | No: lease length (D1) decided, 5 minutes |
| 2 | Extraction data privacy | — | D2 |
| 3 | Evaluation harness and synthetic document set | — | Handwriting source (D3) |
| 4 | OCR engine selection and integration | 3 | Engine choice (D4), made from step 3's measurements |
| 5 | Image quality checks and pre-processing | 3, 4 | Retake policy (D5), EXIF policy (D6) |
| 6 | Clinical schemas and document parsers | 4 | Field list approval (D7), reviewer named (FRD Q7) |
| 7 | Drug catalog matching | 6 | Catalog source (FRD Q1), matching rule sign-off (D8) |
| 8 | Running the worker, failure handling, audit | 1 | How the worker is run (D9), who may retry (D10) |
| 9 | Accuracy evaluation and sign-off | 3–7 | Targets agreed with the reviewer (D11) |

Step 1 is built and awaiting owner review. Steps 2 and 3 can start when the owner says so.
Steps 6, 7 and 9 cannot finish without the clinical reviewer.

---

## Step 1 — Worker reliability (your area 1) — IMPLEMENTED IN `1ebdb15`, AWAITING OWNER REVIEW, NOT MARKED COMPLETE

**As built** (the owner's requirements changed the proposal below; the record of what was
built is `docs/DECISIONS.md`, "Worker reliability (M2 step 1)"):

- The fence is a random **claim token** per attempt plus the lease, not the attempt number.
  It guards both the result write and the failure write.
- Lease 5 minutes, **heartbeat every 60 seconds**, maximum 3 attempts.
- OCR runs in a **child process killed at a 10-minute hard timeout**. The database timeouts
  are only a backstop, on `db.connect_worker`, which nothing uses until step 8.
- Refused settings: in-process OCR outside `APP_ENV=test`; a heartbeat not shorter than the lease.
- A database constraint (`extracting_has_time`) stops an `extracting` document having no due time.
- Worst case to a terminal state with these settings: about 33 minutes plus polling
  (`docs/DECISIONS.md`), not the "maximum attempts x lease" estimated in the proposal.
- Also touched: `capture/documents.py`, `capture/schema.sql`, `tests/fake_engines.py`.
- Open risks: OCR descendants survive the timeout; an engine that cannot be sent to a child
  process uses up a document's attempts; not verified on Linux or in CI.

### Historical record: the proposal as approved (superseded by the summary above where they differ)

- **FRD requirement.** M2: "Retries with backoff, idempotent by (document_id, version)";
  "every document ends in needs_review or extraction_failed". Section 7: tasks are
  at-least-once and a repeat does nothing. Invariant 8: fail closed.
- **Proposed implementation.** Replace "hold the row lock for the whole extraction" with a
  claim and a lease:
  1. *Claim* (short transaction): pick the oldest due document with `FOR UPDATE SKIP LOCKED`,
     set status `extracting`, add one to `extraction_attempts`, set `next_extraction_at` to
     now plus the lease, commit. If the attempt number is over the maximum, mark it
     `extraction_failed` instead. This is **SKIP LOCKED** and **attempt counting before
     extraction** in one step.
  2. *Work* with no transaction open: read the images, run OCR.
  3. *Store* (short transaction): lock the row and store the result only if the attempt
     number is still the one claimed. Otherwise another worker took over after the lease
     ran out, and this result is thrown away. This keeps it duplicate-free.
  4. *Crash or hang recovery:* a dead or stuck worker simply never stores. When the lease
     ends the document is due again and counts as a new attempt, so a poison document stops
     at the maximum. No lock is held during OCR, so one stuck worker blocks nobody.
  5. *Database timeout:* worker connections set `idle_in_transaction_session_timeout` and
     `statement_timeout` as a backstop. With step 2 outside a transaction they can be short.
- **Files.** `capture/extraction.py` (claim, store, `run_due`), `db.py` (worker connection
  options), `tests/test_extraction_recovery.py`, `tests/test_extraction.py`.
- **Dependencies and decisions.** D1: lease length. It must exceed the longest honest
  extraction (FRD target: 60 s per page, up to 10 pages). No new dependency.
- **Tests.** The two tests that pin today's limitations flip: a hung worker no longer blocks
  a second document; a document that always crashes its worker reaches `extraction_failed`
  after the maximum. New: a late result after lease expiry is discarded; two workers run two
  documents at the same time; lease expiry makes a document due again; killed-process test
  still ends with exactly one extraction.
- **Acceptance.** With any mix of crashes and hangs, every document reaches `needs_review` or
  `extraction_failed` within (maximum attempts × lease), with at most one stored extraction
  per version.
- **Risks.** A lease shorter than a slow honest run causes wasted repeat work (never a
  duplicate). Mitigation: set the lease from measured times in step 4, and log lease expiries.

## Step 2 — Extraction data privacy (your area 7)

- **FRD requirement.** Section 9: encryption at rest, field-level encryption for sensitive
  fields, "store only schema fields", no document text in logs, patient export and delete.
- **Proposed implementation.** The mitigation already written in `DECISIONS.md`: encrypt
  `extractions.fields` and `raw_text` with a key outside the database; keep `raw_text` only
  until the document is verified or rejected, in a store that allows deletion; record its
  hash in the append-only row.
- **Files.** `capture/extraction.py`, `capture/schema.sql`, `pii.py` or `capture/storage.py`.
- **Dependencies and decisions.** D2: approve encrypting, and approve deleting raw text after
  review (this changes what the ERD stores). Lawyer's view on retention (FRD Q8).
- **Tests.** A database dump contains no document text; the extraction endpoint still returns
  fields to the patient; raw text is gone after a document is closed; wrong key fails closed.
- **Acceptance.** No readable document text in any table, log or backup outside the patient's
  own API response.
- **Risks.** Encrypted fields cannot be searched in SQL. Mitigation: nothing in M2 needs to;
  search (M5) works on verified events, not extractions.

## Step 3 — Evaluation harness and synthetic document set (your area 6, first half)

- **FRD requirement.** Section 8 gate: "Field-level on a labelled synthetic set of printed and
  handwritten prescriptions". Invariant 9: synthetic data only.
- **Proposed implementation.**
  - *Printed set:* render documents from the synthetic generator with known field values, so
    the ground truth is exact by construction. Bangla, English and mixed, several layouts.
  - *Degraded copies:* rotate, skew, blur, add noise, glare and low contrast with known
    amounts. These also give labelled data for the blur and glare checks in step 5.
  - *Handwritten set:* people hand-copy generated synthetic prescriptions and photograph
    them. The content is synthetic, the handwriting is real, and the truth is already known.
  - *Harness:* a command that runs an engine over a set and reports the metrics in step 9.
  - A held-out test split that is never used for tuning.
- **Files.** `tests/synthetic.py` (extend), new `tests/evaluation/` (generator, harness, small
  fixtures). Large image sets stay out of git.
- **Dependencies and decisions.** D3: who writes the handwritten set, and how many. A Bangla
  font with a licence that allows use (for example an OFL font). Pillow.
- **Tests.** The harness scores a perfect fake engine at 100% and a deliberately wrong one
  correctly; generation is repeatable from a seed.
- **Acceptance.** A versioned, repeatable set with exact ground truth, covering printed and
  handwritten, Bangla and English.
- **Risks.** Synthetic printed documents are easier than real ones, so results will look
  better than reality. Mitigation: report printed and handwritten separately, never as one
  number, and say so in the report. Real documents wait for the pilot.

## Step 4 — OCR engine selection and integration (your area 2)

- **FRD requirement.** 3.5: local OCR, RapidOCR or Tesseract. M2: local OCR; cloud model only
  on opt-in. Section 9: Bangla and English OCR; under 60 s per page.
- **Proposed implementation.**
  - Run both candidates over the step 3 set and choose from measured accuracy, speed, memory
    and install cost. I have not verified how well either reads Bangla, especially
    handwriting; that is what this step measures.
  - Wrap the winner as an engine with the existing contract: page images in, lines of text
    with a confidence and position each out.
  - Models are pinned with checksums and shipped with the build. No download at run time and
    no network call from the OCR process.
  - Per-page time limit, so a stuck page fails the attempt and does not hang the worker.
- **Files.** New `capture/ocr.py`, `pyproject.toml`, CI workflow (engine install).
- **Constraints from step 1.** The engine must be a module-level function that can be sent
  to a child process, and must not rely on starting processes of its own: the child is a
  daemon process, and programs it starts are not killed by the hard timeout.
- **Dependencies and decisions.** D4: engine choice, after measurement. Each option adds
  weight: Tesseract needs a system binary and language data; RapidOCR brings ONNX Runtime
  and OpenCV.
- **Tests.** Reads a known printed synthetic page in Bangla and English; runs with the
  network blocked; a page over the time limit fails cleanly; no document text appears in logs.
- **Acceptance.** Engine chosen with recorded numbers; runs offline; time per page measured
  and recorded against the 60 s target.
- **Risks.** Local OCR may read handwritten Bangla prescriptions poorly. Mitigation: that is
  what the manual-entry path is for; the report states the handwritten numbers plainly, and
  cloud AI stays off unless you separately approve it.

## Step 5 — Image quality checks and pre-processing (your area 3)

- **FRD requirement.** M2: "pre-process (rotate, deskew, denoise, contrast)"; "Blur and glare
  detection asks for a retake".
- **Proposed implementation.**
  - *At upload, before storing:* decode the image for real (today only the first bytes are
    checked), reject files that do not decode, and cap pixel count against decompression bombs.
  - *Quality checks:* sharpness score for blur, share of blown-out pixels for glare, minimum
    resolution, and whether a page is in frame. Limits are calibrated on the degraded copies
    from step 3; they are engineering values, not clinical ones.
  - *Retake guidance:* a refused page returns its page number and reason codes
    (`image_blurry`, `image_glare`, `image_too_small`) for the client to show simple Bangla
    guidance. Checking at upload means the patient or caregiver is still holding the paper.
  - *Pre-processing* (rotate from EXIF, deskew, denoise, contrast) runs in the worker on a
    working copy. The stored original is never changed.
- **Files.** New `capture/imaging.py`, `capture/documents.py`, `api/documents.py`,
  `capture/extraction.py`.
- **Dependencies and decisions.**
  - D5: retake policy. If the paper itself is poor, the best photo may still fail. I propose
    refuse-with-reasons plus an explicit "upload anyway", which goes straight to manual entry.
  - D6: photos carry EXIF data such as location. Keeping the original untouched keeps that
    data. I propose serving a copy without EXIF to anyone who is not the patient.
  - Pillow, and NumPy or OpenCV depending on the engine chosen in step 4.
- **Tests.** Detection rates on the labelled degraded set; a sharp clean page is not refused;
  a corrupt or oversized image is refused with nothing stored; the original's hash is
  unchanged after pre-processing; "upload anyway" lands in manual entry.
- **Acceptance.** Blur and glare detection meet rates agreed in D11 on the labelled set, with
  a stated false-refusal rate on good pages.
- **Risks.** Refusing good photos frustrates the very users this is for. Mitigation: tune for
  few false refusals, and always allow "upload anyway".

## Step 6 — Clinical schemas and document parsers (your area 4)

- **FRD requirement.** M2: "Parse to a typed schema with per-field confidence, validate types
  and dates". Invariant 1. CLAUDE.md: no invented clinical content.
- **Proposed implementation.**
  - *Mechanism only, until approval:* extend the schema format so each field carries its kind,
    whether it is **required or optional**, and validation rules (for example a date not in
    the future for a prescription date). Store the schema version with each extraction.
  - `SCHEMAS` **stays empty** in the code until the list in `DECISIONS.md` is approved by you
    and the clinical reviewer. The existing test that pins it empty stays until then.
  - *Parsers:* one deterministic function per document type (prescription, laboratory report,
    discharge summary) that turns OCR lines into candidate fields. No language model.
  - *Field confidence:* the lowest OCR confidence among the lines a field came from, lowered
    further when the parser was unsure where the field was. Fields under 0.85 are left for
    manual entry, as now.
  - Required fields are a rule for M3's confirm step; M2 only reports which are missing.
- **Files.** `capture/extraction.py` (schema format), new `capture/parsers.py`,
  `docs/DECISIONS.md` (the signed list).
- **Dependencies and decisions.** D7: the field list, required and optional marks, and the
  five open questions, signed by you and the reviewer. The reviewer must be named (FRD Q7).
- **Tests.** Mechanism tests on a synthetic test-only schema, as today; after approval,
  parser tests per document type on the printed set; a required field missing is reported;
  an invalid value is never accepted whatever its confidence.
- **Acceptance.** The approved list is implemented exactly, with its approval recorded;
  no field exists that the approval does not list.
- **Risks.** Rule-based parsing of free-layout handwritten prescriptions is the weakest link.
  Mitigation: fields the parser cannot place are left empty for manual entry; nothing is guessed.

## Step 7 — Drug catalog matching (your area 5)

- **FRD requirement.** M2: "fuzzy-match drug names to the catalog", "keep top suggestions".
  M3: names resolve to generic ingredients "with suggestions". M6: an unrecognised drug is
  flagged, "never silently passed". Section 12: trigram brand matching may be borrowed as an idea.
- **Proposed implementation.**
  - Catalog tables for brands and generics, and an import command that records the source and
    its licence with every import.
  - Matching by trigram similarity in PostgreSQL (`pg_trgm`), returning the top few
    candidates with scores, across Bangla and English spellings.
  - **Ambiguous names:** the name as written is always kept. A match is never chosen
    automatically. If candidates are close to each other, or map to different generics, the
    field is marked ambiguous and all candidates are shown for a person to pick in M3.
  - **Unrecognised names:** marked `unrecognised`, kept verbatim, never dropped.
- **Files.** New `safety/catalog.py` and `safety/schema.sql` (shared with M6), `capture/extraction.py`.
- **Dependencies and decisions.** FRD Q1: a catalog we may legally use. Until then, a
  synthetic catalog only. D8: the reviewer signs off the matching rule, since look-alike drug
  names are a known safety hazard. `pg_trgm` must be available in the database.
- **Tests.** Exact, misspelt and Bangla-script names find the right candidate in a synthetic
  catalog; two look-alike names yield ambiguous, never a silent pick; an unknown name is
  flagged; the same input always gives the same candidates in the same order.
- **Acceptance.** No path selects a drug without a person; unrecognised is always visible.
- **Risks.** A wrong suggestion ranked first may be accepted by a hurried reviewer.
  Mitigation: show the written name beside every suggestion, and have the reviewer decide
  whether a top suggestion may be pre-selected at all (default: no).

## Step 8 — Running the worker, failure handling and audit (your area 7)

- **FRD requirement.** M2: a background job. Section 4.2: what is audited. Section 9:
  observability (queue metrics), no personal data in logs.
- **Proposed implementation.**
  - A small runner that calls `run_due` on an interval, started as its own process. Celery
    is not needed for this and can replace the runner later without changing the pipeline.
  - Endpoints for the two failure paths the state machine already has: try again, and switch
    to manual entry.
  - Audit: retries and manual-entry switches made by a person; views of documents by anyone
    but the patient (already done). Cloud AI stays off: the threshold remains unset, and the
    test that proves nothing is sent stays.
  - Counters for queue length, attempts, failures and lease expiries, with no document text.
- **Files.** New `workers/extract.py`, `api/documents.py`, `capture/extraction.py`.
- **Dependencies and decisions.** D9: how the worker is run (plain process now, or wait for
  Redis and Celery with hosting, FRD Q4). D10: who may retry or switch to manual entry
  (patient only, or a caregiver too; verifiers wait on FRD Q3).
- **Tests.** The runner processes a queue and stops cleanly; the two endpoints follow the
  state machine and the access rules; logs contain no document text.
- **Acceptance.** An uploaded document is extracted without anyone calling a function by hand.
- **Risks.** A runner without supervision can die silently. Mitigation: documents stay due,
  so nothing is lost, and the queue-length counter shows it.

## Step 9 — Accuracy evaluation and sign-off (your area 6, second half)

- **FRD requirement.** Section 8: "Extraction accuracy — field-level on a labelled synthetic
  set of printed and handwritten prescriptions — **target agreed with the clinical reviewer**".
  The FRD sets no numbers, so this plan sets none either.
- **Proposed metrics**, each reported separately for printed and handwritten, and per field:
  - *Exact-match accuracy* after normalisation, for dates, numbers and short text.
  - *Character error rate* for longer text.
  - *Precision and recall of rows* for repeated groups such as medicines.
  - *Accepted-but-wrong rate:* fields at or above 0.85 whose value is wrong. This is the one
    that matters most for safety, because those values are shown pre-filled.
  - *Manual-entry rate:* how much is left for a person to type.
  - *Blur and glare detection rate* and *false-refusal rate* (step 5).
  - *Time per page*, against the 60 s target.
- **Files.** `tests/evaluation/`, a written report in `docs/`.
- **Dependencies and decisions.** D11: the reviewer sets the targets after seeing a first
  baseline run. I will bring the baseline; I will not propose pass marks.
- **Tests.** The evaluation is a command run before release, with a small smoke version in CI.
- **Acceptance.** The report exists, every agreed target is met on the held-out split, and
  the reviewer has signed it.
- **Risks.** Tuning until the test set passes. Mitigation: the held-out split is used once,
  for the final run.

---

## Decisions needed

| # | Decision | Needed for | Owner |
|---|---|---|---|
| D1 | Lease length per extraction attempt — **decided: 5 minutes** | Step 1 | You |
| D2 | Encrypt extraction data, and delete raw text after review | Step 2 | You, lawyer |
| D3 | Who hand-writes the synthetic handwritten set, and how many | Step 3 | You |
| D4 | OCR engine | Step 4 | You, from measurements |
| D5 | Retake policy and "upload anyway" | Step 5 | You |
| D6 | Serve images without EXIF to non-patients | Step 5 | You |
| D7 | Clinical field list, required and optional | Step 6 | You and the clinical reviewer |
| D8 | Drug matching rule | Step 7 | Clinical reviewer |
| D9 | How the worker is run | Step 8 | You |
| D10 | Who may retry or switch to manual entry | Step 8 | You |
| D11 | Accuracy and detection targets | Step 9 | Clinical reviewer |
| FRD Q1 | Drug catalog source | Step 7 | You |
| FRD Q7 | Clinical reviewer named | Steps 6, 7, 9 | You |

## M2 exit gate

M2 is complete only when all of these hold and are shown by tests or a signed report:

1. Every uploaded document reaches `needs_review` or `extraction_failed` in bounded time,
   including when workers crash or hang, with at most one extraction per version.
2. No extraction path writes an event. Only M3's confirm step can.
3. A real local OCR engine is integrated and runs with no network access.
4. Blur and glare are detected at upload, with retake guidance, at the agreed rates.
5. The approved clinical field list is implemented exactly, with required and optional
   fields, validation and a confidence per field, and its approval is recorded.
6. Drug names are matched to a catalog; no drug is selected without a person; unrecognised
   names are always flagged.
7. The accuracy report meets every target agreed with the clinical reviewer, on the
   held-out split, and is signed.
8. No readable document text sits in the database, logs or backups; cloud AI is off.
9. The full suite passes in CI, and that result has been checked, not assumed.

Not part of M2: verification (M3), the timeline (M4), the safety rules themselves (M6).
