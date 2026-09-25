"""Eval runner: per-turn scoring, aggregation, compare, result files (EM-001).

Pure-stdlib. The adapter interface is duck-typed (see adapters/base.py), so a
FakeAdapter drives the same scoring path as the real engine_v2 adapter.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from evals import metrics
from evals.dataset import Scenario, Turn, resolve_refs

# Metrics where a smaller number is better; all others are higher-is-better.
LOWER_IS_BETTER = {"noise_rate", "prefetch_tokens", "latency_ms"}

# §6.3 gated metrics: only these fail `--compare`. prefetch_tokens is a
# deliberate trade-off metric (e.g. EM-107 provenance bullets) and belongs to
# the perf/token budgets; latency_ms is wall-clock noise on shared runners.
# Both still appear in the delta table, marked "info" when they worsen.
GATED_METRICS = frozenset({"recall@5", "ndcg@5", "abstain_correct", "noise_rate", "must_not_ok"})

_BULLET_RE = re.compile(r"^- \[([^\]]+)\]", re.MULTILINE)

_SCORED_KEYS = (
    "recall@5", "mrr", "ndcg@5", "abstain_correct", "noise_rate",
    "substring_hit", "must_not_ok", "prefetch_tokens", "latency_ms",
)


def parse_injected_ids(block: str) -> List[str]:
    """Ids of the bullets in a rendered prefetch block (injection order)."""
    return _BULLET_RE.findall(block or "")


def score_turn(
    scenario: Scenario,
    turn: Turn,
    adapter: Any,
    handle: Any,
    k: int = 5,
) -> Dict[str, Any]:
    """Run one query through the adapter and compute every per-query metric."""
    expect_real = resolve_refs(turn.expect_ids, handle.ref_ids, handle.noise_ids)
    must_not_real = set(resolve_refs(turn.must_not, handle.ref_ids, handle.noise_ids))

    t0 = time.perf_counter()
    hits = adapter.search(handle, turn.query, k=k)
    block = adapter.prefetch(handle, turn.query)
    latency_ms = (time.perf_counter() - t0) * 1000.0

    ranked_ids = [h.id for h in hits]
    injected_ids = parse_injected_ids(block)

    # abstain_correct expects "no memories injected" (spec EM-001). §6.2's
    # "non-pinned" refinement needs the v3 pinned tier; in v2 nothing is
    # pinned, so an empty block is the contract.
    abstain = metrics.abstain_correct(injected_ids, turn.expect_ids)
    noise = metrics.noise_rate(injected_ids, acceptable_ids=set(expect_real))

    combined_text = block + "\n" + "\n".join(h.content for h in hits)
    if turn.expect_substrings:
        found = sum(1 for s in turn.expect_substrings if s.lower() in combined_text.lower())
        substring_hit = found / len(turn.expect_substrings)
    else:
        substring_hit = 1.0

    must_not_ok = 0.0 if any(i in must_not_real for i in injected_ids) else 1.0

    return {
        "scenario_id": scenario.scenario_id,
        "category": scenario.category,
        "query": turn.query,
        # Ranking metrics are undefined for abstain turns (empty expect_ids):
        # None keeps them out of the means (aggregate skips None).
        "recall@5": metrics.recall_at_k(expect_real, ranked_ids, k=k) if expect_real else None,
        "mrr": metrics.mrr(expect_real, ranked_ids) if expect_real else None,
        "ndcg@5": metrics.ndcg_at_k(expect_real, ranked_ids, k=k) if expect_real else None,
        "abstain_correct": abstain,
        "noise_rate": noise,
        "substring_hit": substring_hit,
        "must_not_ok": must_not_ok,
        "prefetch_tokens": metrics.estimate_tokens(block),
        "latency_ms": latency_ms,
    }


def _mean(rows: Sequence[Dict[str, Any]], key: str) -> Optional[float]:
    vals = [r[key] for r in rows if r.get(key) is not None]
    if not vals:
        return None
    return sum(vals) / len(vals)


def aggregate(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Mean of each scored metric over rows (None values skipped, e.g.
    abstain_correct on non-abstain turns)."""
    out: Dict[str, Any] = {k: _mean(rows, k) for k in _SCORED_KEYS}
    out["n_turns"] = len(rows)
    return out


def run_suite(
    scenarios: Sequence[Scenario],
    adapter: Any,
    suite: str,
    git_sha: str,
    k: int = 5,
) -> Dict[str, Any]:
    """Score every scenario/turn through one adapter; return the results dict."""
    rows: List[Dict[str, Any]] = []
    for sc in scenarios:
        handle = adapter.load(sc)
        for turn in sc.turns:
            rows.append(score_turn(sc, turn, adapter, handle, k=k))

    by_category: Dict[str, Any] = {}
    for cat in sorted({r["category"] for r in rows}):
        by_category[cat] = aggregate([r for r in rows if r["category"] == cat])

    return {
        "suite": suite,
        "adapter": getattr(adapter, "name", adapter.__class__.__name__),
        "git_sha": git_sha,
        "k": k,
        "metrics": aggregate(rows),
        "by_category": by_category,
        "turns": rows,
    }


def load_result(path: Path) -> Dict[str, Any]:
    import json

    return json.loads(Path(path).read_text(encoding="utf-8"))


def compare_deltas(
    baseline: Dict[str, Any],
    current: Dict[str, Any],
    threshold: float = 0.02,
) -> List[Dict[str, Any]]:
    """Deltas between two metric dicts; flag regressed per direction (§6.3:
    'no drop > 0.02' — for lower-is-better metrics, a rise beyond the gate).

    ``worsened`` is the raw direction check for every metric; ``regressed``
    (the hard gate) is ``worsened`` restricted to GATED_METRICS."""
    rows: List[Dict[str, Any]] = []
    for key in sorted(set(baseline) | set(current)):
        b, c = baseline.get(key), current.get(key)
        if b is None or c is None or not isinstance(b, (int, float)) or not isinstance(c, (int, float)):
            continue
        delta = c - b
        if key in LOWER_IS_BETTER:
            worsened = delta > threshold
        else:
            worsened = delta < -threshold
        gated = key in GATED_METRICS
        rows.append({
            "metric": key,
            "baseline": round(b, 4),
            "current": round(c, 4),
            "delta": round(delta, 4),
            "gated": gated,
            "worsened": worsened,
            "regressed": worsened and gated,
        })
    return rows


def render_markdown(suite: str, adapter_name: str, m: Dict[str, Any]) -> str:
    """Markdown table of one aggregated metric dict."""
    lines = [f"### {suite} / {adapter_name}", "", "| metric | value |", "|---|---|"]
    for key in _SCORED_KEYS:
        v = m.get(key)
        lines.append(f"| {key} | {'—' if v is None else format(v, '.3f')} |")
    lines.append(f"| n_turns | {m.get('n_turns', 0)} |")
    return "\n".join(lines)


def render_compare_markdown(rows: Sequence[Dict[str, Any]]) -> str:
    lines = ["| metric | baseline | current | delta | regressed |",
             "|---|---|---|---|---|"]
    for r in rows:
        lines.append(
            f"| {r['metric']} | {r['baseline']:.3f} | {r['current']:.3f} "
            f"| {r['delta']:+.3f} | "
            f"{'YES' if r['regressed'] else ('info' if r.get('worsened') else 'no')} |"
        )
    return "\n".join(lines)
