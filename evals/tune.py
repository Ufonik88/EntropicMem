"""EM-306 — the calibration harness: split, grid, objective, holdout, result file.

**Why a harness and not a hand-run.** The card's AC is "holdout metrics reported;
defaults committed" — and that only means something if the split, the grid and the
objective are fixed *before* any number is looked at. They live here, in code, so a
rerun on a later commit scores the same holdout with the same candidates.

**The split is by id hash, not by order.** ``sha256(scenario_id)[:8] % 100 < 70`` → dev,
the rest → holdout. An order-based split changes when a dataset line moves; this one
cannot. The rule and the concrete ids are recorded in the result file, so the arming
number can be audited later.

**The objective is the card's:** ``0.4*recall@5 + 0.3*mrr + 0.3*abstain_correct -
0.2*noise_rate``, on the **dev** split. The holdout is reported, never optimised.

**Selection, stated before the committed run:** highest dev objective; ties go to the
candidate *closest to the spec*, so a flat objective never moves a threshold by accident
(the first pass over the grid found exactly such a tie in the ``min_score`` band, which
is why the rule is written down and recorded in the result file).

**What is deliberately not tuned here, recorded rather than implied:** the per-intent
generator-weight tables (§3.6's ``GENERATOR_WEIGHTS``) — a 4×6 space the card does not
name, and the analyzer's intent routing is EM-301's fixed output; and the per-model
cosine thresholds, whose grid is empty until EM-303 (no embedding backend). Both are
named in the result file's ``deferred`` block.

The tuning run is an offline act. CI checks the *rules* — split determinism, the
objective formula, the pre-declared grid, and that the committed result and
``em/config.py`` still agree — not a fresh tuning.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from evals import dataset as dataset_mod
from evals import datasets, runner

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

#: The split: a scenario whose bucket is below this goes to dev; the rest to holdout.
DEV_BUCKETS = 70
SPLIT_BUCKETS = 100

#: The card's objective, verbatim — as a string so the result file can record it.
OBJECTIVE = "0.4*recall@5 + 0.3*mrr + 0.3*abstain_correct - 0.2*noise_rate"

#: The pre-declared grid. Declared here, before any run, so it cannot be widened to
#: chase a number. ``spec`` is present by construction: the holdout report needs the
#: baseline it must beat, and ``test_the_grid_is_pre_declared...`` pins that.
DEFAULT_GRID: Mapping[str, Sequence[Any]] = {
    "gate.min_score": (0.25, 0.30, 0.35),
    "gate.min_coverage": (0.30, 0.34, 0.40),
    "ranking.weights": ("spec", "rrf_heavy", "importance_heavy"),
}

#: Rerank-weight candidates. ``spec`` must equal ``fusion.RankWeights()``'s defaults —
#: a test pins that — and every preset sums to 1.0 (the score is on a [0, 1] scale).
RANK_WEIGHT_PRESETS: Mapping[str, Mapping[str, float]] = {
    "spec": {"rrf": 0.60, "importance": 0.15, "recency": 0.10, "confidence": 0.10, "feedback": 0.05},
    "rrf_heavy": {"rrf": 0.70, "importance": 0.10, "recency": 0.08, "confidence": 0.08, "feedback": 0.04},
    "importance_heavy": {"rrf": 0.50, "importance": 0.25, "recency": 0.10, "confidence": 0.10, "feedback": 0.05},
}


def _git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=10, cwd=str(REPO),
        )
        if out.returncode == 0:
            return out.stdout.strip() or "unknown"
    except Exception:
        pass
    return "unknown"


def _bucket(scenario_id: str) -> int:
    """The id-hash bucket, fixed by this function and nothing else."""
    digest = hashlib.sha256(scenario_id.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % SPLIT_BUCKETS


def split_by_id_hash(
    scenarios: Sequence[Any], *, dev_buckets: int = DEV_BUCKETS
) -> Tuple[List[Any], List[Any]]:
    """The 70/30 dev/holdout split, deterministic and independent of input order."""
    dev: List[Any] = []
    holdout: List[Any] = []
    for scenario in scenarios:
        (dev if _bucket(scenario.scenario_id) < dev_buckets else holdout).append(scenario)
    return dev, holdout


def expand_grid(grid: Mapping[str, Sequence[Any]]) -> List[Dict[str, Any]]:
    """The Cartesian product of the grid, as one params dict per candidate."""
    keys = sorted(grid)
    return [dict(zip(keys, values)) for values in itertools.product(*(grid[k] for k in keys))]


def objective(metrics: Mapping[str, Any]) -> float:
    """The card's objective. Refuses a suite that did not exercise a needed metric."""
    for key in ("recall@5", "mrr", "abstain_correct", "noise_rate"):
        if metrics.get(key) is None:
            raise ValueError(f"the objective needs {key}; the suite did not exercise it")
    return (
        0.4 * float(metrics["recall@5"])
        + 0.3 * float(metrics["mrr"])
        + 0.3 * float(metrics["abstain_correct"])
        - 0.2 * float(metrics["noise_rate"])
    )


def spec_params() -> Dict[str, Any]:
    """The spec-defaults candidate, read from the dataclasses rather than restated."""
    from em.retrieval import gate

    config = gate.GateConfig()
    return {
        "gate.min_score": config.min_score,
        "gate.min_coverage": config.min_coverage,
        "ranking.weights": "spec",
    }


def _selection_key(row: Mapping[str, Any], spec: Mapping[str, Any]):
    """Highest objective; then closest to the spec; then a total order for determinism."""
    params = row["params"]
    distance = sum(1 for key in params if params[key] != spec[key])
    return (-row["objective"], distance, json.dumps(params, sort_keys=True))


def _v3_adapter(params: Mapping[str, Any]):
    from em.retrieval import fusion, gate
    from evals.adapters.engine_v3 import EngineV3Adapter

    return EngineV3Adapter(
        gate_config=gate.GateConfig(
            min_score=float(params["gate.min_score"]),
            min_coverage=float(params["gate.min_coverage"]),
        ),
        rank_weights=fusion.RankWeights(**RANK_WEIGHT_PRESETS[str(params["ranking.weights"])]),
    )


def _v2_adapter(suite: str):
    from evals.adapters.engine_v2 import EngineV2Adapter

    return EngineV2Adapter(disable_embeddings=(suite in ("ci", "hard")))


def _evaluate(scenarios: Sequence[Any], params: Mapping[str, Any], suite: str, sha: str, k: int):
    adapter = _v3_adapter(params)
    try:
        return runner.run_suite(scenarios, adapter, suite=suite, git_sha=sha, k=k)["metrics"]
    finally:
        adapter.shutdown()


def _evaluate_v2(scenarios: Sequence[Any], suite: str, sha: str, k: int):
    adapter = _v2_adapter(suite)
    try:
        return runner.run_suite(scenarios, adapter, suite=suite, git_sha=sha, k=k)["metrics"]
    finally:
        adapter.shutdown()


def render_summary(result: Mapping[str, Any]) -> str:
    lines = [
        f"### tune {result['suite']} / dev ({len(result['dev'])} candidates)",
        "",
        "| min_score | min_coverage | weights | objective | recall@5 | mrr | abstain | noise |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in result["dev"]:
        params, metrics = row["params"], row["metrics"]
        lines.append(
            f"| {params['gate.min_score']} | {params['gate.min_coverage']} "
            f"| {params['ranking.weights']} | {row['objective']:.4f} "
            f"| {metrics['recall@5']:.3f} | {metrics['mrr']:.3f} "
            f"| {metrics['abstain_correct']:.3f} | {metrics['noise_rate']:.3f} |"
        )
    lines += [
        "",
        "### holdout (never optimised)",
        "",
        "| candidate | recall@5 | mrr | abstain | noise | objective |",
        "|---|---|---|---|---|---|",
    ]
    for name in ("chosen", "spec", "v2"):
        metrics = result["holdout"][name]["metrics"]
        lines.append(
            f"| {name} | {metrics['recall@5']:.3f} | {metrics['mrr']:.3f} "
            f"| {metrics['abstain_correct']:.3f} | {metrics['noise_rate']:.3f} "
            f"| {objective(metrics):.4f} |"
        )
    lines += [
        "",
        f"v2 holdout miss rate (1 - recall@5) = **{result['v2_miss_rate']:.6f}** "
        "-> the value that arms `max_v2_miss_rate`",
    ]
    return "\n".join(lines)


def cmd_tune(args: Any) -> int:
    try:
        paths = datasets.suite_paths(args.suite)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    scenarios = [sc for path in paths for sc in dataset_mod.load_scenarios(path)]
    dev, holdout = split_by_id_hash(scenarios)
    if not dev or not holdout:
        print("error: the id-hash split left an empty side; refusing to tune", file=sys.stderr)
        return 2

    grid = DEFAULT_GRID
    if args.grid:
        try:
            grid = json.loads(Path(args.grid).read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"error: cannot read grid {args.grid}: {exc}", file=sys.stderr)
            return 2

    sha = _git_sha()
    spec = spec_params()
    dev_rows: List[Dict[str, Any]] = []
    for params in expand_grid(grid):
        metrics = _evaluate(dev, params, args.suite, sha, args.k)
        dev_rows.append(
            {"params": params, "objective": round(objective(metrics), 6), "metrics": metrics}
        )
    dev_rows.sort(key=lambda row: _selection_key(row, spec))
    chosen = dev_rows[0]

    spec_row = next((row for row in dev_rows if row["params"] == spec), None)
    if spec_row is None:  # a custom grid may omit the spec candidate; still report it
        metrics = _evaluate(dev, spec, args.suite, sha, args.k)
        spec_row = {"params": spec, "objective": round(objective(metrics), 6), "metrics": metrics}

    holdout_chosen = _evaluate(holdout, chosen["params"], args.suite, sha, args.k)
    holdout_spec = _evaluate(holdout, spec, args.suite, sha, args.k)
    v2_metrics = _evaluate_v2(holdout, args.suite, sha, args.k)
    if v2_metrics["recall@5"] is None:
        print("error: the holdout has no v2 recall@5; refusing to derive a ceiling", file=sys.stderr)
        return 2
    v2_miss_rate = round(1.0 - float(v2_metrics["recall@5"]), 6)

    result: Dict[str, Any] = {
        "suite": args.suite,
        # Tune builds its adapters with the default `disable_embeddings=True`
        # (see `_v3_adapter`), so its numbers are lexical by construction.
        "retrieval_mode": "lexical",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": sha,
        "k": args.k,
        "objective": OBJECTIVE,
        "selection": (
            "highest dev objective; ties prefer the candidate closest to the spec "
            "(a flat objective must not move a threshold); then params order"
        ),
        "split": {
            "rule": f"sha256(scenario_id)[:8] % {SPLIT_BUCKETS} < {DEV_BUCKETS} -> dev, else holdout",
            "dev_ids": [sc.scenario_id for sc in dev],
            "holdout_ids": [sc.scenario_id for sc in holdout],
        },
        "grid": {key: list(values) for key, values in grid.items()},
        "dev": dev_rows,
        "chosen": chosen,
        "holdout": {
            "chosen": {"params": chosen["params"], "metrics": holdout_chosen},
            "spec": {"params": spec_row["params"], "metrics": holdout_spec},
            "v2": {"metrics": v2_metrics},
        },
        "v2_miss_rate": v2_miss_rate,
        "deferred": {
            "per_model_cosine": "EM-303: no embedding backend yet, so the cosine grid is empty",
            "generator_weights": "§3.6's per-intent GENERATOR_WEIGHTS held at spec values; not in this card's grid",
        },
    }

    results_dir = (
        Path(args.results_dir) if args.results_dir else Path(__file__).resolve().parent / "results"
    )
    out_path = Path(args.out) if args.out else results_dir / f"tune-{args.suite}-{sha}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")

    print(render_summary(result))
    print(f"\nwrote {out_path}")
    return 0
