"""Tests for EM-005 — performance bench (evals/perf.py).

The bench measures the v2.7 paths (MemoryEngine + Hermes provider) against
seeded synthetic corpora: remember p50/p95, prefetch cold/warm, tool search
p95, DB size, and prefetch p95 under a concurrent CLI writer process.

AC under test: `python -m evals.perf --sizes N` prints a table and stores
results in evals/results/perf-*.json.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from evals import perf  # noqa: E402
from evals.perf import (  # noqa: E402
    build_corpus,
    percentile,
    synthetic_queries,
)

# ── corpus generation ────────────────────────────────────────────────────────

def test_build_corpus_is_seeded_and_deterministic(tmp_path):
    """Same seed => identical fact list; different seed => different list."""
    db = tmp_path / "m1.db"
    facts_a = build_corpus(50, seed=7, db_path=db)
    facts_b = build_corpus(50, seed=7, db_path=tmp_path / "m2.db")
    assert [f["content"] for f in facts_a] == [f["content"] for f in facts_b]
    assert len({f["id"] for f in facts_a}) == 50
    assert facts_a[0]["content"] != facts_a[1]["content"]
    assert facts_a[0]["id"]  # engine-assigned entropic ids


def test_synthetic_queries_are_deterministic():
    q1 = synthetic_queries(8, seed=7)
    q2 = synthetic_queries(8, seed=7)
    assert q1 == q2
    assert len(q1) == 8
    assert all(len(q.split()) >= 2 for q in q1)


# ── math ─────────────────────────────────────────────────────────────────────

def test_percentile_nearest_rank():
    vals = list(range(1, 101))  # 1..100
    assert percentile(vals, 50) == 50
    assert percentile(vals, 95) == 95
    assert percentile([], 50) == 0.0
    # stable for unsorted input
    assert percentile([5, 1, 3], 50) == 3


# ── full small bench (end-to-end through engine + provider + writer proc) ───

@pytest.fixture()
def home(tmp_path, monkeypatch):
    h = tmp_path / "hermes-home"
    (h / "entropicmem").mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(h))
    return h


def test_run_perf_small(home, tmp_path, capsys):
    """One small size end to end: metrics present, JSON stored, table printed.

    Driven through ``main()`` — the AC is about the CLI printing a table.
    """
    out_dir = tmp_path / "results"
    rc = perf.main([
        "--sizes", "120", "--seed", "3", "--probes", "5",
        "--out-dir", str(out_dir), "--workdir", str(tmp_path / "bench"),
    ])
    assert rc == 0

    report = json.loads(next(out_dir.glob("perf-*.json")).read_text())
    assert report["sizes"] == [120]
    row = report["results"][str(120)]

    # remember: no-embedding path, engine directly
    assert row["remember"]["samples"] > 0
    assert row["remember"]["p50_ms"] >= 0
    assert row["remember"]["p95_ms"] >= row["remember"]["p50_ms"]

    # prefetch: cold (cache miss) and warm (cache hit) samples
    assert row["prefetch"]["cold"]["samples"] > 0
    assert row["prefetch"]["warm"]["samples"] > 0

    # tool search p95 through the provider handle_tool_call path
    assert row["search"]["samples"] > 0
    assert row["search"]["p95_ms"] >= 0

    # DB size
    assert row["db"]["bytes"] > 0
    assert row["db"]["avg_kb_per_memory"] > 0

    # concurrent writer test ran (CLI writer process + provider reader)
    assert row["concurrent"]["writer_facts"] > 0
    assert row["concurrent"]["prefetch_under_load"]["samples"] > 0

    # AC: results stored in evals/results/perf-*.json
    files = sorted(out_dir.glob("perf-*.json"))
    assert len(files) == 1
    stored = json.loads(files[0].read_text())
    assert stored["sizes"] == [120]
    assert "results" in stored

    # AC: prints a table
    printed = capsys.readouterr().out
    assert "remember" in printed and "prefetch" in printed
    assert "120" in printed


@pytest.mark.parametrize("probes", [0, -1])
def test_run_perf_rejects_non_positive_probes(tmp_path, probes):
    """Programmatic callers bypass the CLI's positive_int check; run_perf
    must refuse up front instead of dividing by zero mid-bench."""
    with pytest.raises(ValueError, match="probes must be a positive int"):
        perf.run_perf([10], probes=probes, out_dir=tmp_path / "out", workdir=tmp_path / "w")
    assert not (tmp_path / "out").exists()
    assert not (tmp_path / "w").exists()


def test_measure_concurrent_rejects_empty_queries(tmp_path):
    with pytest.raises(ValueError, match="at least one probe query"):
        perf._measure_concurrent(tmp_path / "m.db", tmp_path, provider=None,
                                 queries=[], writer_facts=1, seed=0)
