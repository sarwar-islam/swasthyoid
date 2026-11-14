"""Phase 7B: the full-catalog benchmark (tests/evaluation/catalog_benchmark.py). Synthetic data only; no test reads `data/`.
The bounds below are generous regression guards against going back to a scan of the whole catalog (about 130,000 microseconds
a lookup on 21,714 rows before the index). They are NOT performance requirements: none is set (the owner decides)."""
import hashlib
import inspect
import json

from swasthyoid.capture import drugcatalog
from swasthyoid.tests.evaluation import catalog_benchmark as bench


def parsed(text):
    import io
    return drugcatalog.load_csv(io.StringIO(text, newline=""), source="test", version="t").report


def test_the_synthetic_catalog_is_deterministic_and_has_the_requested_size():
    a, b = bench.synthetic_csv(500, seed=3), bench.synthetic_csv(500, seed=3)
    assert a == b and a != bench.synthetic_csv(500, seed=4)
    assert a.splitlines()[0] == ",".join(bench.HEADER) and parsed(a).rows == 500


def test_the_synthetic_catalog_has_about_the_proportions_of_the_audited_file():
    report = parsed(bench.synthetic_csv(10_000, seed=0))
    assert 300 <= report.missing_count("strength") <= 500  # about 4%
    assert report.duplicate_groups and report.brands_with_several_generics and report.products_with_several_manufacturers
    assert report.missing_count("brand") == 0 and report.missing_count("manufacturer") == 0


def test_the_report_has_every_metric_and_the_percentiles_are_in_order():
    result = bench.run(rows=2_000, queries=40, seed=1)
    assert result["source"] == "synthetic" and result["rows"] == 2_000 and result["matchable"] == 2_000
    for key in ("load_seconds", "index_seconds", "peak_python_memory_bytes", "max_rss_kib", "max_name_tokens", "counts", "lookups"):
        assert key in result
    assert result["load_seconds"] > 0 and result["peak_python_memory_bytes"] > 0
    assert set(result["lookups"]) == set(bench.KINDS)
    for summary in result["lookups"].values():
        assert summary["n"] > 0 and summary["p50_us"] <= summary["p95_us"] <= summary["max_us"]
    json.dumps(result)  # it prints as JSON


def test_percentiles_use_the_nearest_rank_rule():
    summary = bench._summary(list(range(1, 101)))
    assert (summary["n"], summary["p50_us"], summary["p95_us"], summary["max_us"], summary["mean_us"]) == (100, 50, 95, 100, 50.5)
    assert bench._summary([])["p50_us"] is None


def test_a_full_scale_catalog_loads_and_answers_lookups_far_faster_than_a_scan_would():
    result = bench.run(rows=25_000, queries=200, seed=0)
    assert result["rows"] == 25_000
    lookups = result["lookups"]
    assert lookups["exact_brand"]["p95_us"] < 5_000 and lookups["unmatched"]["p95_us"] < 5_000
    assert lookups["exact_generic"]["p95_us"] < 20_000 and lookups["row"]["p95_us"] < 20_000


def test_file_mode_reads_one_file_reports_numbers_only_and_leaves_it_unchanged(tmp_path, capsys):
    path = tmp_path / "medicine.csv"
    path.write_text(bench.synthetic_csv(300, seed=2), encoding="utf-8", newline="")
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    assert bench.main(["--csv", str(path), "--queries", "20"]) == 0
    out = capsys.readouterr().out
    result = json.loads(out)
    assert result["source"] == "file" and result["rows"] == 300 and result["file_sha256"] == before and result["file_unchanged"] is True
    assert "SynthBrand" not in out and "SYNTH-GENERIC" not in out and "Synth Maker" not in out  # no row content is printed
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_the_benchmark_has_no_default_path_to_any_real_data():
    import ast
    assert inspect.signature(bench.run).parameters["csv_path"].default is None
    strings = [n.value for n in ast.walk(ast.parse(inspect.getsource(bench))) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    assert not any("drug_catalog" in text or text.endswith(".csv") for text in strings)  # no file name or folder is built in
