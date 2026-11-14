# Drug reference catalog: D8 Phase A (provenance, scope, loader, limits)

Status 2026-11-14: Phase A is implemented locally (uncommitted) and tested on **synthetic data only**. The supplied CSV files
sit in `data/drug_catalog/`, are excluded from git, are unchanged, and are **not cleared for redistribution or deployment**
(license and provenance unconfirmed). Nothing here is clinical verification, a recommendation, or training data.

## 1. The supplied dataset

Six CSV files, described by the owner as Kaggle/MedEx-derived. The directory holds no README, license, notice, retrieval
date or version. `generic.csv` has 1,199 rows linking to `medex.com.bd`, so the data appears to derive from the MedEx
website (inferred from its contents; not verified, no network was used). Full SHA-256 of the files as received:

| File | Records | SHA-256 |
|---|---|---|
| `medicine.csv` | 21,714 | `fa0767285719e093b124a2e68958e86afab9619e499a79e466024f095b0b8791` |
| `generic.csv` | 1,711 | `d87406bd0e1765fd3740912edd09d7df355e0cd8bcaa9482da9d2c47063e8046` |
| `manufacturer.csv` | 240 | `9c41f606716ec6996a8113d1d9c0321309de55acd5cd89d39ca4bbf68ded921b` |
| `dosage form.csv` | 113 | `b4a833b22db4d7ef635a52871889e1f605af5d3324341f9d0049b40ec7243c67` |
| `drug class.csv` | 453 | `728afad1bab145078e25f0c2fcec07bb64761fb3a34b183d2f73a76d83ebe071` |
| `indication.csv` | 2,043 | `4703725a3873e02594c3e4e0e61dc0a86d17f68bd9e114c35f2dde4092892cb1` |

All six are UTF-8 with CRLF line endings. The original bytes are never modified by anything in this project.

## 2. License and provenance: UNRESOLVED (blocker, FRD Q1)

Not known: where the files were obtained, their license or terms, the retrieval date, and the terms of the underlying website.
The product listing (brand, generic, strength, form, manufacturer) is factual but may be subject to database or terms-of-use
limits. `generic.csv` embeds third-party prescribing text, likely copyrighted. Until the owner confirms the source and that
use in this project is permitted: **do not commit, push, redistribute or deploy the data**. `data/` is in `.gitignore` for
that reason (and because `.gitattributes` forces LF, which would silently rewrite these CRLF files if they were ever added).
The loader records the source statement and file hash it is given, so a result always names what it came from.

## 3. Scope: what is used and what is not

**Used (only from `medicine.csv`):** `brand id` (kept as the source record id), `brand name`, `generic`, `strength`,
`dosage form`, `manufacturer`. **Never read or imported:** prices and package text, `monograph link`, every clinical-text column
of `generic.csv` (indications, dosage, interactions, contraindications, side effects, pregnancy and lactation, precautions,
paediatric use, overdose), drug classes and indications. The other five files are never opened by the loader. The data is
reference data for candidate matching; it is never model training data.

## 4. Loader design (`capture/drugcatalog.py`, `capture/drugmatch.py`)

- `load_medicine_csv(path, source=..., version=None)` and `load_csv(stream, ...)` read one file in memory and return
  `LoadedCatalog(records, catalog, report, file_sha256)`. The version defaults to `sha256:<file hash>`.
- **Original values are kept exactly as written:** case, spacing, route qualifiers such as `(Nasal Preparation)`, combination
  strengths such as `(10 mg+30 mg)/5 ml`. A missing value stays `None`; an empty or whitespace-only cell is missing. Nothing is
  trimmed, merged, expanded, mapped or inferred. No alias, abbreviation list or threshold exists.
- **Ambiguity and conflicts are kept, not resolved:** duplicate rows, one brand with several generics, and one product from several
  manufacturers stay separate records, all returned as candidates, and are listed in the `LoadReport`.
- **Read-only:** records and the report are frozen; `drugmatch.Catalog` and its entries cannot be modified after construction;
  candidates are fresh copies.
- **Fail closed:** `CatalogError` with a fixed reason word and no file content for: `missing_column`, `duplicate_column`,
  `bad_row` (a row whose cell count differs from the header, so a truncated row never reads as "missing values"), `nul_byte`,
  `bad_csv` (any `csv.Error`, such as a cell over the reader's 131,072-character limit), `missing_source_id`,
  `duplicate_source_id`, `not_utf8`, `file_too_large`, `wrong_file`, `empty_version`. A completely empty line is skipped.
- **File guards (`load_medicine_csv`):** a file whose name (without extension, case-insensitive) is `generic`, `manufacturer`,
  `dosage form`, `drug class` or `indication` is refused **before it is opened**; any other file must still have the
  `medicine.csv` header or it is refused. The size limit `max_bytes` defaults to `MAX_FILE_BYTES` = 32 MiB, checked before the
  file is read: the supplied `medicine.csv` is about 3.7 MiB, so the limit leaves roughly eight times that for growth while still
  refusing a wrong or runaway file early. It is a per-call argument, not a global setting. An explicit empty `version` is
  refused (only `None` means "use the file hash").
- **Report definitions:** `near_duplicate_groups` lists every group of records that differ as written but are equal once case
  and spacing are folded, including when parts of the group are exact duplicates. A missing generic or manufacturer is not
  counted as a second, conflicting value in `brands_with_several_generics` or `products_with_several_manufacturers`.
- **Matcher changes** (still the same rules): entries may lack a generic or a brand (not both); a candidate carries `id` (the
  source record id), `brands`, `generic`, `strength`, `form`, `manufacturer` and `unconfirmed`. The manufacturer is displayed
  only and never chooses a candidate. Every result has `review_required = True`, there is no selected field, and a name match
  is still only a candidate.
- **Missing strength or form (audit correction):** when the written text states a strength or form, a record whose value
  **conflicts** is dropped, but a record that has **no** value is kept and its `unconfirmed` lists the attribute (a missing
  value can neither confirm nor exclude anything). A candidate with any unconfirmed attribute is never `exact`: one such record
  gives `ambiguous` / `attribute_unconfirmed`, several give `ambiguous` / `multiple_entries`, and the result-level `unconfirmed`
  names the attributes. If every record conflicts: `ambiguous` / `attribute_mismatch` with all of them. No threshold or rule
  was added; the exact-equality comparison is unchanged.
- **Immutability:** an initialised `Catalog` refuses a second `__init__` as well as attribute assignment and deletion.
- No network, no database, no schema change, no migration, no new dependency.

## 5. Manual check on the real file (not a test; read-only, counts only)

Loaded in 1.3 s: 21,714 rows, all matchable; missing generic 2, missing strength 849; 60 exact duplicate groups; 274 brand names
with more than one generic; 46 products from more than one manufacturer; file hash unchanged after the load. A query for an
unknown name returns `unrecognised`; a query for a generic name returns `ambiguous` with every brand row of that generic as
candidates (218 for one common generic), each needing review.

## 6. Source limitations that the loader does not hide

Heterogeneous strength formats (simple, combination, per-vial, per-puff); route qualifiers inside generic names; abbreviations
such as `Tab.` and `Cap.` are not in the data (dosage forms are long names like `Capsule (Sustained Release)`); brand names are
ASCII only, so Bangla-script names will not match; about 3,700 brand-name pairs one letter apart map to different generics (the
look-alike hazard: suggestions must never be pre-selected); declared counts in the lookup files disagree with the actual rows
(65 of 240 manufacturers, 34 of 113 forms), which suggests mixed snapshots; there is no date or version in the data.

## 7. Blockers, decisions and what Phase A does not do

- **Owner:** the source, license and permission (FRD Q1); whether `data/` may ever be committed (default: no).
- **Clinical reviewer (not named):** the suggestion floor and limit, any alias list (qualifier handling, abbreviation expansion),
  duplicate handling beyond reporting, the update policy.
- **Not in Phase A:** a generic-level index (so a generic-name query returns one candidate with its strengths, not hundreds of
  brand rows), database tables (need a schema approval), wiring into extraction, any suggestion parameter, any use of the
  clinical text. Real-data tests are deliberately absent: automated tests use synthetic fixtures only, so CI never depends on
  the local files.
- **Tests:** `tests/test_drugcatalog.py` (loading, missing values, duplicates, one brand with several generics, several
  manufacturers, combination strengths, route qualifiers, unknown names, no selection, original values, read-only, refusals,
  malformed rows, NUL and oversized cells, report definitions, empty version, other-file names, size limit, missing strength
  or form kept and unconfirmed, import and write boundary, a real `git check-ignore` that is skipped when git is unavailable)
  and the added cases in `tests/test_drugmatch.py`. Deferred: full-catalog performance measurement (Phase B).

## 8. Phase 7B (2026-11-14, owner-approved, local, uncommitted): index, generic groups, row matching, pipeline, benchmark

**Still true:** the data's source and licence are unresolved (FRD Q1). Everything below is **opt-in and off by default**; the real
`medicine.csv` never enters the repository or CI; the tests use synthetic catalogs only.

- **Name index.** `Catalog` builds a read-only index at construction: normalised brand or generic name to the records that carry it.
  Exact lookup no longer scans the catalog (about 130,000 microseconds a lookup on the real file before; see the measurements below).
  The 39 existing matcher tests and the catalog tests pass unchanged.
- **Generic-level groups.** When several records share a generic name, `match()` returns one candidate per (generic as written,
  strength, form) with `kind: "generic_group"`, every source id in `ids`, `brand_count` and `manufacturer_count`, instead of hundreds
  of brand rows. A group of several records is still `ambiguous` (reason `generic_name`): nothing is selected. A generic of one record
  stays `exact`. Brand-name hits are still listed record by record; a route qualifier keeps names apart.
- **Row matching `match_row(text, catalog)` (PROVISIONAL, marked D8-REVIEWER).** Exact normalised phrase windows over the words of one
  row's written text, longest first, a window inside a longer match dropped; a comma, full stop, semicolon or colon at the end of a word
  is ignored for a second try, nothing else is. No similarity, no floor, no abbreviation expansion (`Tab.` is not `tablet`), no alias.
  Each candidate carries `strength_check` and `form_check`: `confirmed` (the catalog's value appears in the row text as an exact word
  window; Bangla digits and a missing space as in `500mg` are normalised), `unconfirmed` (it does not: the candidate is **kept**) or
  `catalog_missing`. At most 50 candidates per row (`MAX_ROW_CANDIDATES`); `truncated` counts the rest.
- **Pipeline (worker only; never the OCR child).** `DRUG_CATALOG_PATH` (an absolute file) enables it; `DRUG_CATALOG_SOURCE` is then
  **required** (the owner's statement of where the data came from and on what terms; no default); `DRUG_CATALOG_VERSION` is optional (the
  file's SHA-256 by default). If the path is set but the setting or the file is unusable the worker **exits 2** with
  `code=invalid_configuration setting=... reason=<fixed word>` before connecting (never silent degradation); if it is unset nothing
  happens. For a prescription or discharge summary, after the parsers, each medication row's raw reading is matched and the result is
  stored under the reserved key `fields["catalog_matches"] = {catalog: {version, source}, rows: [{row, status, review_required,
  matches: [{phrase, start, end, status, reason, candidates}], truncated}]}` **inside the sealed `fields`** (D2): no new column, no
  migration, encrypted at rest. A failure for one row is recorded as `{"row": i, "status": "unavailable"}` by code only and never
  fails the extraction. Manual entries have none. The patient sees it in `fields` of the extraction endpoint; it is a list of unverified
  candidates, never a selection, never a verified event. The schema fields themselves are never filled from a candidate.
- **Benchmark.** `python -m swasthyoid.tests.evaluation.catalog_benchmark [--csv PATH] [--rows N] [--queries N] [--seed N]` reports
  `load_seconds`, `index_seconds`, `peak_python_memory_bytes` (tracemalloc), `max_rss_kib` (Linux only), the loader's counts and p50,
  p95, max and mean microseconds for exact brand, exact generic, row and unmatched lookups. No target is set (the owner decides).
  Measured here on one Windows machine (a measurement, not a requirement): **real `medicine.csv`, 21,714 rows, 300 lookups of each
  kind:** load 1.6 s, index 0.47 s, peak Python memory about 94 MB, p95 15 microseconds (exact brand), 401 (exact generic),
  596 (row), 18 (unmatched); the file's hash was unchanged. **Synthetic, 25,000 rows:** load 2.1 s, index 0.6 s, peak about 97 MB,
  row p95 679 microseconds. CI runs the synthetic benchmark with generous regression bounds only.

**Limits, stated plainly.** Matching needs the catalog's exact spelling: a misspelling, a brand written differently, an abbreviation or a
name inside brackets finds nothing (the reviewer decides any alias, abbreviation or similarity rule, and the suggestion parameters,
D8). A brand that is also an ordinary word can match inside unrelated row text, producing noise; candidates are only suggestions
for a person. A row's strength and form are not extracted into fields (reviewer vocabularies are missing); the checks only compare the
catalog's values with the row text. The PostgreSQL-backed test (sealed storage of the matches) was written but could not run here.
