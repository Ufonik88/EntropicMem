"""EM-005 — performance bench (evals/perf.py).

Seeded synthetic corpora of N memories measured through the real v2.7 paths:

* ``remember`` p50/p95 — durable write path with embeddings disabled
  (spec: "no embedding"; the §6.4 budget excludes vector cost),
* ``prefetch`` p50/p95 cold (cache miss) / warm (cache hit),
* tool ``search`` p95 — the provider ``entropicmem_recall`` tool path
  (``handle_tool_call`` → ``recall_hybrid``),
* DB size (main file after a WAL checkpoint; avg KB per memory),
* concurrent writer test — a CLI writer process appending facts through
  ``entropicmem.py remember`` while the provider reads: prefetch p95 under
  write load, plus a write-landing check.

Usage (direct; EM-001 owns ``evals/__main__.py`` and the ``perf`` subcommand
is wired there when this branch rebases onto EM-001):

    python evals/perf.py --sizes 1000,10000 [--probes 20] [--seed 7]

Prints a table to stdout and stores the report in
``evals/results/perf-<UTC stamp>.json``. Stdlib only; no embeddings, no
network. §6.4 budgets are printed as informational flags — EM-007's
perf-smoke CI job owns enforcement. The corpus is generated from a seeded
RNG; no real user data is ever written.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import subprocess
import sys
import time
import types
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS_DIR = _REPO_ROOT / "plugins" / "entropicmem" / "scripts"
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

DOMAINS = ["Knowledge", "Projects", "Reference", "Systems"]
_TOPICS = [
    "cache", "index", "writer", "reader", "sync", "shard", "backup", "router",
    "quota", "ledger", "sensor", "valve", "antenna", "turbine", "beacon",
    "gasket", "manifold", "bearing", "coupler", "regulator",
]
_VERBS = [
    "retries with", "defaults to", "expires after", "shards across",
    "rate-limits to", "mirrors onto", "validates against", "batches into",
    "hydrates from", "flushes to",
]
_UNITS = ["seconds", "rpm", "rows", "segments", "blocks", "nodes"]

# §6.4 budgets (reference machine: 4-core laptop, SSD; CI uses 2x slack).
BUDGETS = {
    "remember_p95_ms_10k": 15.0,
    "remember_p95_ms_50k": 25.0,
    "prefetch_hit_p95_ms": 10.0,
    "prefetch_miss_warm_p95_ms_10k": 80.0,
    "prefetch_miss_warm_p95_ms_50k": 150.0,
    "prefetch_hard_cap_ms": 1500.0,
    "db_avg_kb_per_memory": 2.0,
}

# Distinct index bases keep bench writes from colliding with corpus facts
# (content-hash ids; unique content ⇒ unique id).
_CORPUS_BASE = 0
_REMEMBER_BASE = 20_000_000
_WRITER_BASE = 40_000_000


# ── environment plumbing ─────────────────────────────────────────────────────

def _stub_agent() -> None:
    """Register a minimal ``agent.memory_provider`` if hermes-agent isn't
    installed, so the provider class imports for benching."""
    if "agent" in sys.modules and "agent.memory_provider" in sys.modules:
        return
    try:
        import agent  # noqa: F401
        return
    except ImportError:
        pass
    agent_mod = types.ModuleType("agent")
    agent_mod.__path__ = []  # type: ignore[attr-defined]
    mp_mod = types.ModuleType("agent.memory_provider")

    class MemoryProvider:  # minimal host-base shape, contract fields only
        pre_compress_checkpoint_api_version = 1

    mp_mod.MemoryProvider = MemoryProvider  # type: ignore[attr-defined]
    agent_mod.memory_provider = mp_mod  # type: ignore[attr-defined]
    sys.modules["agent"] = agent_mod
    sys.modules["agent.memory_provider"] = mp_mod


def _provider_class():
    _stub_agent()
    from plugins.entropicmem import EntropicMemMemoryProvider  # noqa: E402

    return EntropicMemMemoryProvider


def _memory_engine():
    if str(_SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_DIR))
    from memory_engine import MemoryEngine  # noqa: E402

    return MemoryEngine


# ── synthetic data ───────────────────────────────────────────────────────────

def _fact_text(rng: random.Random, i: int) -> str:
    """One synthetic fact. The numeric suffix keeps content unique so fuzzy
    dedup can never collapse the corpus (Jaccard ≥ 0.8 needs near-equal text;
    distinct ``{i:08d}`` tokens plus topic churn stay below it for most
    pairs, and the bench measures real write paths either way)."""
    topic_a = rng.choice(_TOPICS)
    topic_b = rng.choice(_TOPICS)
    return (
        f"Component {topic_a}-{i:08d} {rng.choice(_VERBS)} "
        f"{rng.randint(1, 999)} {rng.choice(_UNITS)} across the {topic_b} "
        f"plane of the staging deployment"
    )


def build_corpus(size: int, seed: int, db_path: Path) -> List[Dict[str, Any]]:
    """Write ``size`` seeded synthetic facts into ``db_path`` through the
    real ``MemoryEngine.remember`` path. Returns [{id, content, domain}]."""
    MemoryEngine = _memory_engine()
    db_path = Path(db_path)
    if db_path.exists():
        db_path.unlink()
    rng = random.Random(seed)
    engine = MemoryEngine(db_path, profile_id="perfbench")
    out: List[Dict[str, Any]] = []
    try:
        for i in range(size):
            content = _fact_text(rng, _CORPUS_BASE + i)
            domain = DOMAINS[i % len(DOMAINS)]
            eid = engine.remember(
                content=content,
                domain=domain,
                importance=0.3 + (i % 7) * 0.1,
                tags=["synthetic", f"bench{seed}"],
                source="agent",
                actor="perfbench",
            )
            out.append({"id": eid, "content": content, "domain": domain})
    finally:
        engine.close()
    return out


def synthetic_queries(count: int, seed: int) -> List[str]:
    """Seeded probe queries drawn from corpus vocabulary."""
    rng = random.Random(seed * 100 + 7)
    return [
        f"what does the {rng.choice(_TOPICS)} {rng.choice(_VERBS)}"
        for _ in range(count)
    ]


def percentile(values: List[float], pct: float) -> float:
    """Nearest-rank percentile (pct in 0..100); 0.0 on an empty sample set."""
    if not values:
        return 0.0
    ordered = sorted(values)
    k = max(1, math.ceil(pct / 100.0 * len(ordered)))
    return float(ordered[k - 1])


def _stats(samples: List[float]) -> Dict[str, float]:
    if not samples:
        return {"samples": 0, "p50_ms": 0.0, "p95_ms": 0.0, "max_ms": 0.0}
    return {
        "samples": len(samples),
        "p50_ms": round(percentile(samples, 50), 3),
        "p95_ms": round(percentile(samples, 95), 3),
        "max_ms": round(max(samples), 3),
    }


# ── measurements ─────────────────────────────────────────────────────────────

def _timed(fn) -> Tuple[Any, float]:
    t0 = time.perf_counter()
    result = fn()
    return result, (time.perf_counter() - t0) * 1000.0


def _make_provider(home: Path):
    """Provider wired to the bench home. Config keys pin memory_db /
    index_db / vault_path explicitly so writer and reader can never drift to
    different DBs. The vault dir exists but is empty → no Core Memory file
    reads inside prefetch."""
    prov_cls = _provider_class()
    base = home / "entropicmem"
    base.mkdir(parents=True, exist_ok=True)
    (base / "vault").mkdir(parents=True, exist_ok=True)
    provider = prov_cls(config={
        "memory_db": str(base / "memory.db"),
        "index_db": str(base / "index.db"),
        "vault_path": str(base / "vault"),
    })
    provider.initialize(session_id="perfbench", hermes_home=str(home),
                        agent_context="primary")
    return provider


def _measure_remember(base_path: Path, seed: int, probes: int) -> Dict[str, Any]:
    """remember p50/p95 with embeddings force-disabled for the loop (spec:
    'no embedding'). Restores the module flag afterwards."""
    if str(_SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_DIR))
    import memory_engine as me  # noqa: E402

    rng = random.Random(seed + 1)
    samples: List[float] = []
    original = me.EMBEDDINGS_AVAILABLE
    me.EMBEDDINGS_AVAILABLE = False
    try:
        for i in range(probes):
            content = _fact_text(rng, _REMEMBER_BASE + i)
            engine = me.MemoryEngine(base_path, profile_id="perfbench")
            try:
                _, ms = _timed(
                    lambda c=content, e=engine: e.remember(
                        content=c, domain="Knowledge", tags=["synthetic"],
                        source="agent", actor="perfbench"))
                samples.append(ms)
            finally:
                engine.close()
    finally:
        me.EMBEDDINGS_AVAILABLE = original
    return _stats(samples)


def _measure_prefetch(provider, queries: List[str]) -> Dict[str, Any]:
    """cold: every query is unique → cache miss path. warm: second identical
    call → cache hit (no conversation history in bench mode, so the
    enhanced-query cache key repeats)."""
    cold: List[float] = []
    warm: List[float] = []
    for q in queries:
        provider._conversation_history = []
        _, ms = _timed(lambda qq=q: provider.prefetch(qq, session_id="perfcold"))
        cold.append(ms)
        provider._conversation_history = []
        _, ms = _timed(lambda qq=q: provider.prefetch(qq, session_id="perfwarm"))
        warm.append(ms)
        provider._conversation_history = []
    return {"cold": _stats(cold), "warm": _stats(warm)}


def _measure_tool_search(provider, queries: List[str]) -> Dict[str, Any]:
    """Tool search latency through the provider handle_tool_call path."""
    samples: List[float] = []
    for q in queries:
        _, ms = _timed(lambda qq=q: provider.handle_tool_call(
            "entropicmem_recall", {"query": qq, "limit": 8}))
        samples.append(ms)
    return _stats(samples)


def _measure_db_size(db_path: Path, size: int) -> Dict[str, Any]:
    """Main DB file bytes after checkpointing WAL (avg KB per memory)."""
    import sqlite3

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()
    total = Path(db_path).stat().st_size
    return {
        "bytes": total,
        "mb": round(total / (1024 * 1024), 2),
        "avg_kb_per_memory": round(total / max(1, size) / 1024.0, 3),
    }


def _fact_count(db_path: Path) -> int:
    import sqlite3

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30)
    try:
        return int(conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0])
    finally:
        conn.close()


def _spawn_cli_writer(db_path: Path, home: Path, facts: List[str]) -> subprocess.Popen:
    """Writer driver process: invokes the real CLI
    (``entropicmem.py remember <fact>``) once per fact, sequentially, with
    ENTROPICMEM_* env pinned to the bench DB — a genuine external writer
    competing with the reader for the engine's flock."""
    driver = r"""
import subprocess, sys
env_key_db, cli = sys.argv[1], sys.argv[2]
n = 0
for line in sys.stdin:
    fact = line.rstrip("\n")
    if not fact:
        continue
    rc = subprocess.run([sys.executable, cli, "remember", fact],
                        capture_output=True, text=True).returncode
    n += (rc == 0)
print(n)
"""
    env = dict(os.environ)
    env.update({
        "HERMES_HOME": str(home),
        "ENTROPICMEM_MEMORY_DB": str(db_path),
        "ENTROPICMEM_VAULT_PATH": str(home / "entropicmem" / "vault"),
        "ENTROPICMEM_INDEX_DB": str(home / "entropicmem" / "index.db"),
    })
    return subprocess.Popen(  # noqa: S603
        [sys.executable, "-c", driver, str(db_path), str(_SCRIPTS_DIR / "entropicmem.py")],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=env, cwd=str(_REPO_ROOT),
    )


def _measure_concurrent(db_path: Path, home: Path, provider,
                        queries: List[str], writer_facts: int,
                        seed: int) -> Dict[str, Any]:
    """CLI writer process + provider reader: prefetch p95 under write load,
    then verify every concurrent write landed."""
    rng = random.Random(seed + 99)
    facts = [_fact_text(rng, _WRITER_BASE + i) for i in range(writer_facts)]
    before = _fact_count(db_path)
    writer = _spawn_cli_writer(db_path, home, facts)
    assert writer.stdin is not None
    writer.stdin.write("\n".join(facts) + "\n")
    writer.stdin.close()

    samples: List[float] = []
    deadline = time.time() + 300.0
    while writer.poll() is None and time.time() < deadline:
        q = queries[len(samples) % len(queries)] + f" load sample {len(samples)}"
        provider._conversation_history = []
        _, ms = _timed(lambda qq=q: provider.prefetch(qq, session_id="perfload"))
        samples.append(ms)
    writer.wait(timeout=60)
    landed = _fact_count(db_path) - before
    return {
        "writer_facts": writer_facts,
        "facts_landed": landed,
        "writer_rc": writer.returncode,
        "prefetch_under_load": _stats(samples),
    }


# ── driver ───────────────────────────────────────────────────────────────────

def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(_REPO_ROOT), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        return "unknown"


def run_perf(
    sizes: List[int],
    seed: int = 7,
    probes: int = 20,
    out_dir: Optional[Path] = None,
    workdir: Optional[Path] = None,
    writer_facts: Optional[int] = None,
) -> Dict[str, Any]:
    """Bench each corpus size; return the report (also written to
    ``out_dir/perf-<UTC>.json`` and printed as a table by ``main``).

    ``workdir`` is where temp homes/DBs live; pass one to keep scratch under
    your own tree. Defaults to a temp dir.
    """
    out_dir = Path(out_dir) if out_dir else _REPO_ROOT / "evals" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    if workdir:
        workdir = Path(workdir)
        workdir.mkdir(parents=True, exist_ok=True)
    else:
        import tempfile
        workdir = Path(tempfile.mkdtemp(prefix="entropicmem-perf-"))

    results: Dict[str, Any] = {}
    for size in sizes:
        home = workdir / f"home-{size}"
        home.mkdir(parents=True, exist_ok=True)
        base = home / "entropicmem"
        base.mkdir(parents=True, exist_ok=True)
        db_path = base / "memory.db"

        t0 = time.perf_counter()
        build_corpus(size, seed, db_path)
        build_s = round(time.perf_counter() - t0, 1)

        provider = _make_provider(home)
        queries = synthetic_queries(probes, seed)
        wf = writer_facts if writer_facts is not None else max(50, min(size // 100, 200))
        row = {
            "corpus": {"size": size, "seed": seed, "build_s": build_s},
            "remember": _measure_remember(db_path, seed, max(5, probes // 2)),
            "prefetch": _measure_prefetch(provider, queries),
            "search": _measure_tool_search(provider, queries),
            "db": _measure_db_size(db_path, size),
            "concurrent": _measure_concurrent(
                db_path, home, provider, queries, wf, seed),
        }
        results[str(size)] = row

    report: Dict[str, Any] = {
        "kind": "perf",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "python": sys.version.split()[0],
        "git_sha": _git_sha(),
        "seed": seed,
        "probes": probes,
        "sizes": list(sizes),
        "budgets": BUDGETS,
        "results": results,
    }
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"perf-{stamp}.json"
    out_path.write_text(json.dumps(report, indent=2))
    report["out_path"] = str(out_path)
    return report


def budget_flags(report: Dict[str, Any]) -> List[str]:
    """Informational §6.4 violations (reference-machine values)."""
    flags: List[str] = []
    for size_str, row in report["results"].items():
        size = int(size_str)
        remember_budget = BUDGETS["remember_p95_ms_50k"] if size >= 50000 \
            else BUDGETS["remember_p95_ms_10k"]
        if row["remember"]["p95_ms"] > remember_budget:
            flags.append(f"{size}: remember p95 {row['remember']['p95_ms']}ms "
                         f"> {remember_budget}ms")
        warm_budget = BUDGETS["prefetch_miss_warm_p95_ms_50k"] if size >= 50000 \
            else BUDGETS["prefetch_miss_warm_p95_ms_10k"]
        if row["prefetch"]["warm"]["p95_ms"] > warm_budget:
            flags.append(f"{size}: prefetch warm p95 "
                         f"{row['prefetch']['warm']['p95_ms']}ms > {warm_budget}ms")
        if row["db"]["avg_kb_per_memory"] > BUDGETS["db_avg_kb_per_memory"]:
            flags.append(f"{size}: db {row['db']['avg_kb_per_memory']}KB/mem "
                         f"> {BUDGETS['db_avg_kb_per_memory']}KB")
    return flags


def render_table(report: Dict[str, Any]) -> str:
    lines = [
        f"EntropicMem perf bench — python {report['python']} "
        f"sha {report.get('git_sha', '?')} seed={report.get('seed')} "
        f"probes={report.get('probes')}",
        "",
        f"{'op':<26}{'size':>8}{'p50_ms':>10}{'p95_ms':>10}{'samples':>9}",
        "-" * 63,
    ]
    for size_str, row in report["results"].items():
        ops = [
            ("remember (no embed)", row["remember"]),
            ("prefetch cold miss", row["prefetch"]["cold"]),
            ("prefetch warm hit", row["prefetch"]["warm"]),
            ("tool search", row["search"]),
            ("prefetch under write", row["concurrent"]["prefetch_under_load"]),
        ]
        for name, s in ops:
            lines.append(f"{name:<26}{size_str:>8}{s['p50_ms']:>10.1f}"
                         f"{s['p95_ms']:>10.1f}{s['samples']:>9}")
        db = row["db"]
        lines.append(f"{'db size':<26}{size_str:>8}{'-':>10}"
                     f"{db['avg_kb_per_memory']:>10.2f}{'KB/mem':>9}")
        lines.append(f"{'writer landed':<26}{size_str:>8}"
                     f"{row['concurrent']['facts_landed']:>10}"
                     f"{row['concurrent']['writer_facts']:>10}{'facts':>9}")
        lines.append("")
    flags = budget_flags(report)
    if flags:
        lines.append("Budget flags (reference machine; CI gets 2x slack — EM-007 enforces):")
        lines.extend(f"  ! {f}" for f in flags)
    else:
        lines.append("Budget flags: none")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="evals.perf",
        description="EntropicMem performance bench (EM-005)")
    parser.add_argument("--sizes", default="1000,10000",
                        help="comma-separated corpus sizes (default: 1000,10000)")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--probes", type=int, default=20,
                        help="timed samples per metric (default: 20)")
    parser.add_argument("--writer-facts", type=int, default=None,
                        help="facts the concurrent CLI writer appends "
                             "(default: clamp(size/100, 50, 200))")
    parser.add_argument("--out-dir", default=None,
                        help="results dir (default: evals/results)")
    parser.add_argument("--workdir", default=None,
                        help="scratch dir for temp corpora (default: temp dir)")
    args = parser.parse_args(argv)

    sizes = [int(x) for x in args.sizes.split(",") if x.strip()]
    if not sizes:
        parser.error("no --sizes given")
    report = run_perf(
        sizes, seed=args.seed, probes=args.probes,
        out_dir=Path(args.out_dir) if args.out_dir else None,
        workdir=Path(args.workdir) if args.workdir else None,
        writer_facts=args.writer_facts,
    )
    print(render_table(report))
    print(f"\nResults stored: {report['out_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
