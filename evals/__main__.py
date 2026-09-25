"""`python -m evals` — eval runner CLI (EM-001).

Usage:
    python -m evals run --suite ci --adapter v2 [--compare <file>] [--k 5]
                        [--results-dir <dir>] [--out <file>]

Exit codes: 0 = ran clean (absolute §6.3 misses are printed as warnings),
1 = regression vs the --compare baseline (hard gate), 2 = usage error.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from evals import dataset as dataset_mod
from evals import datasets, runner

# Absolute thresholds from plan §6.3 ("Gate from 2.8.0"). Reported as
# warnings, not hard failures, on the current suite: S0's job is measuring
# the known-broken v2 baseline, and those numbers are the fix targets for
# S1+. The hard gate — exit 1 — is regression against a --compare baseline
# (§0.2: "does not regress any gated metric", §6.3: "no drop > 0.02").
GATES: Dict[str, Any] = {
    "overall": {
        "recall@5": (">=", 0.75),
        "noise_rate": ("<=", 0.25),
    },
    "abstention": {"abstain_correct": (">=", 0.90)},
    "ageing": {"recall@5": (">=", 0.90)},
    "update": {"recall@5": (">=", 0.70)},
}

_COMPARATORS = {
    ">=": lambda v, t: v >= t,
    "<=": lambda v, t: v <= t,
}


def _git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=10,
            cwd=str(Path(__file__).resolve().parent.parent),
        )
        if out.returncode == 0:
            return out.stdout.strip() or "unknown"
    except Exception:
        pass
    return "unknown"


def make_adapter(name: str, disable_embeddings: bool = True):
    if name == "v2":
        from evals.adapters.engine_v2 import EngineV2Adapter

        return EngineV2Adapter(disable_embeddings=disable_embeddings)
    raise ValueError(f"unknown adapter: {name!r} (v3 lands with S2)")


def check_gates(result: Dict[str, Any]) -> list:
    """Absolute §6.3 thresholds — reported as warnings on the v2 baseline.

    The hard CI gate is regression vs a `--compare` baseline (compare_deltas,
    exit 1). These numbers are S1+ fix targets; failing here pre-fix would
    make the S0 baseline itself unmergeable. Returns violation strings.
    """
    violations = []
    scope = {"overall": result.get("metrics", {})}
    scope.update({cat: vals for cat, vals in result.get("by_category", {}).items()})
    for group, gates in GATES.items():
        metrics = scope.get(group, {})
        for metric, (op, target) in gates.items():
            value = metrics.get(metric)
            if value is None:
                continue  # not exercised by this suite
            if not _COMPARATORS[op](value, target):
                violations.append(
                    f"{group}.{metric} = {value:.3f} violates {op} {target}"
                )
    return violations


def cmd_run(args: argparse.Namespace) -> int:
    try:
        paths = datasets.suite_paths(args.suite)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if not paths:
        print(f"error: suite '{args.suite}' has no dataset files yet", file=sys.stderr)
        return 2

    scenarios = []
    for p in paths:
        scenarios.extend(dataset_mod.load_scenarios(p))

    try:
        # ci and hard must never touch the ML stack (plan line 704); the
        # vector backend belongs to suite full (plan line 1269).
        adapter = make_adapter(args.adapter, disable_embeddings=(args.suite in ("ci", "hard")))
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    sha = _git_sha()
    try:
        result = runner.run_suite(scenarios, adapter, suite=args.suite, git_sha=sha, k=args.k)
    finally:
        adapter.shutdown()

    result["generated_at"] = datetime.now(timezone.utc).isoformat()

    results_dir = Path(args.results_dir) if args.results_dir else Path(__file__).resolve().parent / "results"
    out_path = Path(args.out) if args.out else results_dir / f"{args.suite}-{sha}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")

    print(runner.render_markdown(args.suite, result["adapter"], result["metrics"]))
    for cat, m in sorted(result["by_category"].items()):
        print(runner.render_markdown(f"{args.suite}/{cat}", result["adapter"], m))
    print(f"\nwrote {out_path}")

    rc = 0
    violations = check_gates(result) if args.suite == "ci" else []
    if violations:
        print("\n§6.3 threshold warnings (informational pre-2.8.0):", file=sys.stderr)
        for v in violations:
            print(f"  - {v}", file=sys.stderr)

    if args.compare:
        try:
            baseline = runner.load_result(Path(args.compare))
        except Exception as e:
            print(f"error: cannot read baseline {args.compare}: {e}", file=sys.stderr)
            return 2
        rows = runner.compare_deltas(baseline.get("metrics", {}), result["metrics"])
        print("\n### delta vs baseline")
        print(runner.render_compare_markdown(rows))
        if any(r["regressed"] for r in rows):
            print("\nREGRESSION vs baseline", file=sys.stderr)
            rc = 1

    return rc


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m evals", description="EntropicMem eval framework")
    sub = ap.add_subparsers(dest="command", required=True)
    run_p = sub.add_parser("run", help="run a suite and write results")
    run_p.add_argument("--suite", default="ci", help="ci | full | hard | external")
    run_p.add_argument("--adapter", default="v2", help="engine adapter (v2; v3 in S2)")
    run_p.add_argument("--k", type=int, default=5, help="ranking depth for recall/ndcg")
    run_p.add_argument("--compare", default=None, metavar="FILE",
                       help="baseline results JSON; prints deltas and gates regression")
    run_p.add_argument("--results-dir", default=None,
                       help="where to write <suite>-<git-sha>.json (default: evals/results)")
    run_p.add_argument("--out", default=None, help="explicit output file (overrides --results-dir)")
    run_p.set_defaults(func=cmd_run)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
