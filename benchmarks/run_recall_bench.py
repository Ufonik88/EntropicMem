#!/usr/bin/env python3
"""EntropicMem recall benchmark runner (P1 D2).

Loads a frozen corpus, runs 20 probes against the memory engine, and reports
precision@5 and Mean Reciprocal Rank (MRR).  Writes the result to
``benchmarks/last_run.json`` so CI can assert a floor.

Usage:
    cd EntropicMem
    PYTHONPATH="plugins/entropicmem/scripts" python3 benchmarks/run_recall_bench.py
"""

import json
import sys
import tempfile
from pathlib import Path

# Locate the project root (this file is at <root>/benchmarks/run_recall_bench.py)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Ensure the memory_engine module is importable
_SCRIPTS = _PROJECT_ROOT / "plugins" / "entropicmem" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def load_corpus(path: Path):
    """Yield (content, domain, importance) tuples from JSONL."""
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            obj = json.loads(line)
            yield obj.get("content", ""), obj.get("domain", "Knowledge"), obj.get("importance", 0.5)


def load_probes(path: Path):
    """Return list of probe dicts."""
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def precision_at_k(probe: dict, hits: list, k: int = 5) -> float:
    """Fraction of expected substrings found in at least one of the top-k hits."""
    expected = probe.get("expected_substrings", [])
    if not expected:
        return 0.0
    hit_contents = " ".join(h.content for h in hits[:k]).lower()
    found = sum(1 for sub in expected if sub.lower() in hit_contents)
    return found / len(expected)


def reciprocal_rank(probe: dict, hits: list) -> float:
    """Reciprocal rank: 1 / (position of first hit containing ANY expected substring).

    If no hit contains any expected substring, returns 0.0.
    """
    expected = probe.get("expected_substrings", [])
    if not expected:
        return 0.0
    expected_lower = [s.lower() for s in expected]
    for idx, h in enumerate(hits, start=1):
        content_lower = h.content.lower()
        if any(sub in content_lower for sub in expected_lower):
            return 1.0 / idx
    return 0.0


def run_benchmark(corpus_path: Path, probes_path: Path, top_k: int = 5) -> dict:
    """Run the full benchmark and return metrics."""
    from memory_engine import MemoryEngine  # local import so PYTHONPATH is set

    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "bench.db"
        engine = MemoryEngine(db)

        # Load corpus
        count = 0
        for content, domain, importance in load_corpus(corpus_path):
            engine.remember(content, domain=domain, importance=importance)
            count += 1

        # Run probes
        probes = load_probes(probes_path)
        precisions: list[float] = []
        mrr_values: list[float] = []

        for probe in probes:
            hits = engine.recall_with_relevance(probe["query"], top_k=top_k)
            p = precision_at_k(probe, hits, k=top_k)
            m = reciprocal_rank(probe, hits)
            precisions.append(p)
            mrr_values.append(m)

        engine.close()

    avg_precision = sum(precisions) / len(precisions) if precisions else 0.0
    avg_mrr = sum(mrr_values) / len(mrr_values) if mrr_values else 0.0

    return {
        "precision_at_5": round(avg_precision, 4),
        "mean_reciprocal_rank": round(avg_mrr, 4),
        "probe_count": len(probes),
        "corpus_size": count,
        "top_k": top_k,
        "per_probe_precision": [round(p, 4) for p in precisions],
        "per_probe_mrr": [round(m, 4) for m in mrr_values],
    }


def main() -> int:
    corpus = _PROJECT_ROOT / "benchmarks" / "corpus.jsonl"
    probes = _PROJECT_ROOT / "benchmarks" / "probes.json"
    output = _PROJECT_ROOT / "benchmarks" / "last_run.json"

    if not corpus.exists():
        print(f"ERROR: corpus not found at {corpus}", file=sys.stderr)
        return 1
    if not probes.exists():
        print(f"ERROR: probes not found at {probes}", file=sys.stderr)
        return 1

    result = run_benchmark(corpus, probes)

    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    print(f"precision@5          : {result['precision_at_5']}")
    print(f"mean_reciprocal_rank : {result['mean_reciprocal_rank']}")
    print(f"probes               : {result['probe_count']}")
    print(f"corpus size          : {result['corpus_size']}")
    print(f"results written to   : {output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
