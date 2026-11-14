"""In-memory drug reference catalog loader (M2 step 7, D8 Phase A; docs/DRUG_CATALOG.md).

Reads ONE file in the shape of the supplied `medicine.csv` (one row per brand product) into the read-only
`drugmatch.Catalog`. Strictly reference data: never model training data, never clinical content.

What it reads, and nothing else: `brand id` (kept as the source record id), `brand name`, `generic`, `strength`,
`dosage form`, `manufacturer`. Every other column is discarded the moment a row is read: prices, package text,
links. The other supplied files (generic, class, indication, manufacturer and dosage-form lists) carry third-party
clinical text and are never opened by this module.

What it refuses to do, on purpose:
- Original values are kept exactly as written (case, spacing, route qualifiers such as "(Nasal Preparation)",
  combination strengths such as "(10 mg+30 mg)/5 ml"). Nothing is trimmed, merged, expanded, mapped or inferred.
- A missing value stays missing (None). An empty or whitespace-only cell is missing; no default is filled in.
- Duplicate rows, one brand with several generics, and one product from several manufacturers are KEPT as separate
  records and REPORTED, never collapsed or resolved. The matcher then returns every one of them as a candidate.
- No threshold, alias, abbreviation list or similarity setting lives here. Matching rules are D8 decisions that need
  the clinical reviewer, who is not named yet.
- No network, no database, no write of any kind. The loaded catalog cannot be modified.

Fail closed: a missing required column, a duplicate column name, a row whose number of cells differs from the header,
a NUL byte, a cell too large for the csv reader, a blank or duplicate source record id, a file that is not UTF-8, a file
over the size limit, a file named like one of the other supplied files, or an explicitly empty version raises
CatalogError (args[0] is a fixed reason word, never file content).
"""
import csv
import hashlib
import io
from dataclasses import dataclass
from pathlib import Path

from swasthyoid.capture import drugmatch

# the only columns that are ever read, by their header names in the supplied medicine.csv
COLUMNS = {"source_id": "brand id", "brand": "brand name", "generic": "generic", "strength": "strength",
           "form": "dosage form", "manufacturer": "manufacturer"}
FIELDS = ("brand", "generic", "strength", "form", "manufacturer")
# Size limit for load_medicine_csv (configurable per call). The supplied medicine.csv is about 3.7 MiB; 32 MiB leaves
# roughly eight times that for growth and still refuses a wrong or runaway file before it is parsed.
MAX_FILE_BYTES = 32 * 1024 * 1024
# the other supplied files (clinical text, class and indication lists, lookup lists): never opened by this loader
OTHER_FILES = frozenset({"generic", "manufacturer", "dosage form", "drug class", "indication"})


class CatalogError(Exception):
    """The file cannot be used. args[0] is a fixed reason word; nothing from the file is ever in it."""


@dataclass(frozen=True)
class CatalogRecord:
    """One source row, as written. Absent values are None."""
    source_id: str
    brand: object
    generic: object
    strength: object
    form: object
    manufacturer: object


@dataclass(frozen=True)
class LoadReport:
    """What the loader saw, without having changed any of it. Groups hold source record ids."""
    rows: int
    matchable: int                       # records with a brand name or a generic name
    unmatchable: tuple                   # records with neither: kept in `records`, absent from the catalog
    missing: tuple                       # ((field, count), ...) cells that were empty or whitespace-only
    whitespace_only: tuple               # ((field, count), ...) of those, cells that held only spaces
    duplicate_groups: tuple              # identical on all five values as written
    near_duplicate_groups: tuple         # identical after case-folding and collapsing spaces, but not as written
    brands_with_several_generics: tuple  # same brand (case/spacing aside), more than one generic as written
    products_with_several_manufacturers: tuple  # same brand, form, generic and strength, several manufacturers

    def missing_count(self, field):
        return dict(self.missing).get(field, 0)


@dataclass(frozen=True)
class LoadedCatalog:
    records: tuple
    catalog: drugmatch.Catalog
    report: LoadReport
    file_sha256: object = None           # SHA-256 of the file's bytes when loaded from a path, else None


def _clean(value):
    """(value as written or None, whether it was whitespace-only)."""
    if value is None or value == "":
        return None, False
    if not value.strip():
        return None, True
    return value, False


def _norm_key(record):
    return tuple(drugmatch.normalize(getattr(record, f) or "") for f in FIELDS)


def _groups(buckets):
    return tuple(sorted(tuple(sorted(ids)) for ids in buckets.values() if len(ids) > 1))


def load_csv(stream, *, source, version):
    """Load from a text stream opened with newline=''. `source` says where the data came from (provenance, as the
    owner states it) and `version` names this snapshot; both are required and recorded on the catalog."""
    reader = csv.reader(stream)
    try:
        header = next(reader, None) or []
        if len(set(header)) != len(header):
            raise CatalogError("duplicate_column")
        if any(column not in header for column in COLUMNS.values()):
            raise CatalogError("missing_column")
        at = {name: header.index(column) for name, column in COLUMNS.items()}

        records, seen, missing, blank = [], set(), dict.fromkeys(FIELDS, 0), dict.fromkeys(FIELDS, 0)
        for row in reader:
            if not row:  # a completely empty line is not a record
                continue
            if len(row) != len(header):
                raise CatalogError("bad_row")  # a short row would otherwise read as many "missing" values
            if any("\x00" in cell for cell in row):
                raise CatalogError("nul_byte")
            source_id = row[at["source_id"]]
            if not source_id.strip():
                raise CatalogError("missing_source_id")
            if source_id in seen:
                raise CatalogError("duplicate_source_id")
            seen.add(source_id)
            cells = {}
            for field in FIELDS:
                cells[field], was_blank = _clean(row[at[field]])
                missing[field] += cells[field] is None
                blank[field] += was_blank
            records.append(CatalogRecord(source_id=source_id, **cells))  # every other column is dropped here
    except csv.Error:
        raise CatalogError("bad_csv") from None  # e.g. a cell over the csv reader's field limit; never quotes the file

    exact, loose, by_brand, by_product, as_written = {}, {}, {}, {}, {}
    for r in records:
        key = (r.brand, r.generic, r.strength, r.form, r.manufacturer)
        as_written[r.source_id] = key
        exact.setdefault(key, []).append(r.source_id)
        loose.setdefault(_norm_key(r), []).append(r.source_id)
        # a missing generic or manufacturer is not a second, conflicting value: it is left out of these two reports
        if r.brand and r.generic is not None:
            by_brand.setdefault(drugmatch.normalize(r.brand), {}).setdefault(r.generic, []).append(r.source_id)
        if r.brand and r.manufacturer is not None:
            product = (drugmatch.normalize(r.brand), *_norm_key(r)[1:4])
            by_product.setdefault(product, {}).setdefault(r.manufacturer, []).append(r.source_id)
    near = {k: v for k, v in loose.items() if len({as_written[i] for i in v}) > 1}  # differ as written, equal once folded
    several_generics = tuple(sorted(tuple(sorted(i for ids in g.values() for i in ids))
                                    for g in by_brand.values() if len(g) > 1))
    several_makers = tuple(sorted(tuple(sorted(i for ids in g.values() for i in ids))
                                  for g in by_product.values() if len(g) > 1))

    usable = [r for r in records if r.brand or r.generic]
    catalog = drugmatch.Catalog(version, source, [
        {"id": r.source_id, "generic": r.generic, "brands": (r.brand,) if r.brand else (), "strength": r.strength,
         "form": r.form, "manufacturer": r.manufacturer} for r in usable])
    report = LoadReport(
        rows=len(records), matchable=len(usable), unmatchable=tuple(r.source_id for r in records if not (r.brand or r.generic)),
        missing=tuple(sorted(missing.items())), whitespace_only=tuple(sorted(blank.items())),
        duplicate_groups=_groups(exact), near_duplicate_groups=_groups(near),
        brands_with_several_generics=several_generics, products_with_several_manufacturers=several_makers)
    return LoadedCatalog(records=tuple(records), catalog=catalog, report=report)


def load_medicine_csv(path, *, source, version=None, max_bytes=MAX_FILE_BYTES):
    """Load a `medicine.csv`-shaped file from a local path (read-only). `version` defaults to the SHA-256 of the file,
    so a changed file is a different version; an explicit version must not be empty. The hash is also kept on the
    result. A file named like one of the other supplied files is refused BEFORE it is opened, and a file over
    `max_bytes` (default MAX_FILE_BYTES) is refused before it is read. The file is never modified."""
    path = Path(path)
    if path.stem.casefold() in OTHER_FILES:
        raise CatalogError("wrong_file")
    if version is not None and not (isinstance(version, str) and version.strip()):
        raise CatalogError("empty_version")
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
        raise ValueError("max_bytes must be a positive integer")
    if path.stat().st_size > max_bytes:
        raise CatalogError("file_too_large")
    raw = path.read_bytes()
    if len(raw) > max_bytes:  # the file grew between the size check and the read
        raise CatalogError("file_too_large")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise CatalogError("not_utf8") from None
    digest = hashlib.sha256(raw).hexdigest()
    loaded = load_csv(io.StringIO(text, newline=""), source=source, version=version or f"sha256:{digest}")
    return LoadedCatalog(records=loaded.records, catalog=loaded.catalog, report=loaded.report, file_sha256=digest)
