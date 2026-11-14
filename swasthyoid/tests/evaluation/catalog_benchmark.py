"""Full-catalog benchmark for the drug catalog loader and matcher (Phase 7B; docs/DRUG_CATALOG.md). No threshold is set here
and none is endorsed: it measures and reports, and the owner decides what is fast enough.

    python -m swasthyoid.tests.evaluation.catalog_benchmark [--rows 25000] [--queries 500] [--seed 0]
    python -m swasthyoid.tests.evaluation.catalog_benchmark --csv "C:/path/to/medicine.csv" [--queries 500]

Without --csv it builds a synthetic `medicine.csv`-shaped file in memory (SYNTH names only, deterministic for a seed, with
about the same proportions of missing strengths, exact duplicates, brands with several generics and products from several
manufacturers as the audited real file). With --csv it reads that one file through the ordinary loader (read-only, the file's
SHA-256 is reported) and PRINTS NUMBERS AND COUNTS ONLY, never a row or a name. Nothing here reads `data/` unless it is given
that path, and the automated tests never do.

Reported: load_seconds (read, parse, catalog and index), index_seconds (building the catalog and its name index again from the
loaded records), peak_python_memory_bytes (tracemalloc, measured in a separate pass because tracing slows the run),
max_rss_kib (this process's peak resident size where the system reports it, else null), the loader's counts, and for each
lookup kind (exact_brand, exact_generic, row, unmatched) n, p50, p95, max and mean in microseconds (nearest-rank percentiles).
"""
import argparse
import csv
import hashlib
import io
import json
import math
import random
import time
import tracemalloc

from swasthyoid.capture import drugcatalog, drugmatch

HEADER = ["brand id", "brand name", "generic", "strength", "dosage form", "manufacturer", "package container", "Package Size"]
KINDS = ("exact_brand", "exact_generic", "row", "unmatched")


def synthetic_csv(rows=25_000, seed=0):
    """A `medicine.csv`-shaped text with `rows` records (the proportions are those of the audited file, rounded)."""
    rng = random.Random(seed)
    generics = [f"SYNTH-GENERIC-{n:04d}" + (" (Synth Route)" if n % 9 == 0 else "") for n in range(1700)]
    strengths = [f"{rng.choice([1, 2, 5, 10, 20, 25, 50, 100, 250, 500, 1000])} mg" for _ in range(120)]
    strengths += [f"({rng.choice([5, 10, 20])} mg+{rng.choice([25, 30, 50])} mg)/5 ml" for _ in range(60)]
    strengths += [f"{rng.choice([0.05, 0.1, 0.5, 1, 2])} %" for _ in range(40)]
    forms = [f"Synth Form {n:03d}" if n % 3 else f"Synth Form {n:03d} (Sustained Release)" for n in range(110)]
    makers = [f"Synth Maker {n:03d} Ltd." for n in range(240)]
    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(HEADER)
    made = []
    for i in range(1, rows + 1):
        draw = rng.random()
        if made and draw < 0.0035:  # an exact duplicate of an earlier record, with its own id
            row = [str(i), *rng.choice(made)[1:6], "", ""]
        elif made and draw < 0.0165:  # an earlier brand name for a different generic
            earlier = rng.choice(made)
            row = [str(i), earlier[1], rng.choice(generics), rng.choice(strengths), rng.choice(forms), rng.choice(makers), "", ""]
        elif made and draw < 0.0185:  # the same product from another manufacturer
            earlier = rng.choice(made)
            row = [str(i), *earlier[1:5], rng.choice(makers), "", ""]
        else:
            brand = f"SynthBrand{i:05d}" if i % 4 else f"Synth Brand {i:05d} Plus"
            row = [str(i), brand, rng.choice(generics), rng.choice(strengths), rng.choice(forms), rng.choice(makers), "", ""]
        if rng.random() < 0.04:
            row[3] = ""  # a missing strength
        if rng.random() < 0.0001:
            row[2] = ""  # a missing generic
        made.append(row)
        writer.writerow(row)
    return out.getvalue()


def _summary(microseconds):
    values = sorted(microseconds)
    n = len(values)
    if not n:
        return {"n": 0, "p50_us": None, "p95_us": None, "max_us": None, "mean_us": None}

    def rank(q):
        return round(values[max(1, math.ceil(q * n)) - 1], 1)

    return {"n": n, "p50_us": rank(0.50), "p95_us": rank(0.95), "max_us": round(values[-1], 1),
            "mean_us": round(sum(values) / n, 1)}


def _queries(catalog, per_kind, seed):
    """Names and rows drawn from the catalog itself (and names that are not in it), deterministic for a seed."""
    rng = random.Random(seed)
    picked = [catalog.entries[rng.randrange(len(catalog.entries))] for _ in range(per_kind)]
    named = [e for e in picked if e["brands"]]
    return {
        "exact_brand": [e["brands"][0] for e in named],
        "exact_generic": [e["generic"] for e in picked if e["generic"]],
        "row": [f"Tab. {(e['brands'] or [e['generic']])[0]} {e['strength'] or ''} twice daily" for e in picked],
        "unmatched": [f"NOT-IN-THE-CATALOG-{rng.randrange(10 ** 9)}" for _ in range(per_kind)],
    }


def _time_lookups(catalog, queries):
    out = {}
    for kind in KINDS:
        call = drugmatch.match_row if kind == "row" else drugmatch.match
        micros = []
        for text in queries[kind]:
            started = time.perf_counter_ns()
            call(text, catalog)
            micros.append((time.perf_counter_ns() - started) / 1000)
        out[kind] = _summary(micros)
    return out


def _max_rss_kib():
    try:
        import resource
    except ImportError:  # Windows
        return None
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss  # KiB on Linux, bytes on macOS (reported as is)


def run(*, rows=25_000, queries=500, seed=0, csv_path=None):
    """The benchmark as a dict (see the module note). `csv_path` None uses the synthetic file."""
    def load():
        if csv_path is None:
            return drugcatalog.load_csv(io.StringIO(text, newline=""), source="benchmark (synthetic)", version="bench")
        return drugcatalog.load_medicine_csv(csv_path, source="benchmark run", version=None)

    text = synthetic_csv(rows, seed) if csv_path is None else None
    tracemalloc.start()
    load()
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    started = time.perf_counter()
    loaded = load()
    load_seconds = time.perf_counter() - started
    catalog = loaded.catalog
    entries = [dict(e) for e in catalog.entries]
    started = time.perf_counter()
    drugmatch.Catalog(catalog.version, catalog.source, entries)
    index_seconds = time.perf_counter() - started
    report = loaded.report
    result = {
        "source": "synthetic" if csv_path is None else "file", "seed": seed if csv_path is None else None,
        "rows": report.rows, "matchable": report.matchable, "load_seconds": round(load_seconds, 3),
        "index_seconds": round(index_seconds, 3), "peak_python_memory_bytes": peak, "max_rss_kib": _max_rss_kib(),
        "max_name_tokens": catalog._limits["name"],
        "counts": {"missing": dict(report.missing), "duplicate_groups": len(report.duplicate_groups),
                   "brands_with_several_generics": len(report.brands_with_several_generics),
                   "products_with_several_manufacturers": len(report.products_with_several_manufacturers)},
        "lookups": _time_lookups(catalog, _queries(catalog, queries, seed)),
    }
    if csv_path is not None:
        result["file_sha256"] = loaded.file_sha256
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m swasthyoid.tests.evaluation.catalog_benchmark")
    parser.add_argument("--csv", help="a local medicine.csv to measure instead of the synthetic catalog (numbers only)")
    parser.add_argument("--rows", type=int, default=25_000)
    parser.add_argument("--queries", type=int, default=500)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)
    before = hashlib.sha256(open(args.csv, "rb").read()).hexdigest() if args.csv else None
    result = run(rows=args.rows, queries=args.queries, seed=args.seed, csv_path=args.csv)
    if before is not None:
        result["file_unchanged"] = result["file_sha256"] == hashlib.sha256(open(args.csv, "rb").read()).hexdigest() == before
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
