"""Tests for D2 — Recall Benchmark.

Verifies the benchmark runner produces valid output and the precision@5 score
stays above the CI floor.  The floor is pinned from the first measured run.
"""

import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUN_BENCH = PROJECT_ROOT / "benchmarks" / "run_recall_bench.py"
LAST_RUN = PROJECT_ROOT / "benchmarks" / "last_run.json"

# Pinned floor from first run (2026-09-17).  The real score is 0.98 — this
# guard catches catastrophic regressions while allowing normal score variance.
PRECISION_AT_5_FLOOR = 0.50
MRR_FLOOR = 0.50


def test_bench_runner_exists():
    """The benchmark runner script must exist."""
    assert RUN_BENCH.is_file(), f"Missing {RUN_BENCH}"


def test_corpus_exists():
    """The frozen corpus must exist."""
    corpus = PROJECT_ROOT / "benchmarks" / "corpus.jsonl"
    assert corpus.is_file(), f"Missing {corpus}"
    with open(corpus, "r", encoding="utf-8") as fh:
        lines = [line for line in fh if line.strip() and not line.strip().startswith("#")]
    assert len(lines) >= 50, f"Corpus too small: {len(lines)} facts"


def test_probes_exists():
    """The probe set must exist and have at least 15 probes."""
    probes_path = PROJECT_ROOT / "benchmarks" / "probes.json"
    assert probes_path.is_file(), f"Missing {probes_path}"
    probes = json.loads(probes_path.read_text(encoding="utf-8"))
    assert len(probes) >= 15, f"Too few probes: {len(probes)}"


def test_bench_runner_exits_zero():
    """The runner must exit with code 0 and produce last_run.json."""
    # Remove stale output
    if LAST_RUN.exists():
        LAST_RUN.unlink()

    result = subprocess.run(
        [sys.executable, str(RUN_BENCH)],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(PROJECT_ROOT),
        env={**__import__("os").environ, "PYTHONPATH": f"skills/entropicmem/scripts:{__import__('os').environ.get('PYTHONPATH', '')}"},
    )
    assert result.returncode == 0, (
        f"Runner exited {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert LAST_RUN.is_file(), "Runner did not produce last_run.json"


def test_bench_metrics_plausible():
    """last_run.json must contain valid precision@5 and MRR."""
    assert LAST_RUN.is_file(), "last_run.json not found — run test_bench_runner_exits_zero first"
    data = json.loads(LAST_RUN.read_text(encoding="utf-8"))
    assert "precision_at_5" in data, f"Missing precision_at_5 in {list(data.keys())}"
    assert "mean_reciprocal_rank" in data, f"Missing mean_reciprocal_rank in {list(data.keys())}"
    assert 0.0 <= data["precision_at_5"] <= 1.0, f"precision_at_5 out of range: {data['precision_at_5']}"
    assert 0.0 <= data["mean_reciprocal_rank"] <= 1.0, f"MRR out of range: {data['mean_reciprocal_rank']}"


def test_precision_at_5_above_floor():
    """CI guard: precision@5 must stay above the pinned floor."""
    assert LAST_RUN.is_file(), "last_run.json not found — run test_bench_runner_exits_zero first"
    data = json.loads(LAST_RUN.read_text(encoding="utf-8"))
    assert data["precision_at_5"] >= PRECISION_AT_5_FLOOR, (
        f"precision@5 {data['precision_at_5']} fell below floor {PRECISION_AT_5_FLOOR}"
    )


def test_mrr_above_floor():
    """CI guard: MRR must stay above the pinned floor."""
    assert LAST_RUN.is_file(), "last_run.json not found — run test_bench_runner_exits_zero first"
    data = json.loads(LAST_RUN.read_text(encoding="utf-8"))
    assert data["mean_reciprocal_rank"] >= MRR_FLOOR, (
        f"MRR {data['mean_reciprocal_rank']} fell below floor {MRR_FLOOR}"
    )
