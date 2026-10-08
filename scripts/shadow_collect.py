#!/usr/bin/env python3
"""P0c — collect a shadow sample: v2 answers, S3 reads a copy, the log gets scored.

**Why this exists.** The promotion observable in ``plugins/entropicmem/_shadow.py``
is frozen before any data is read, and satisfying it means 200 turns of shadow
running. On a live profile those turns arrive one conversation at a time. This
script produces a sample that is real in every mechanical way — a real v2 engine
answering real queries, a real online copy of the store, a real migration of that
copy, the real S3 pipeline, real latency — over a store the operator points at.
What it cannot do is invent evidence about a user's memory: the divergence it
measures is between **two engines on the same input**, so the numbers mean "S3
agrees with v2 here", nothing more.

**It never writes the store it reads.** The source is opened ``mode=ro`` and copied
with ``sqlite3.Connection.backup``; every write goes into the working copy under
``--out``. That is repo rule 3, and a test asserts the source's bytes do not move.

    python scripts/shadow_collect.py --source ~/.hermes/entropicmem/memory.db --turns 200
    python scripts/shadow_collect.py --empty --turns 200     # plumbing smoke, zero facts

The second line is the honest shape of a dev box today: the live store holds **zero
facts**, so v2 injects nothing and S3 injects nothing, the divergence rate has no
denominator, and the report reads ``cannot conclude``. That is the correct answer,
not a failure — it proves the pipes and says plainly that it measured nothing.

``--turns`` cycles a fixed, invented query mix. The mix is synthetic by design: the
collector tests the machinery, and real turns from the host are the evidence.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import List, Optional

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugins" / "entropicmem"
SCRIPTS = PLUGIN / "scripts"
DEFAULT_LIVE = "~/.hermes/entropicmem/memory.db"

#: The query mix, cycled. Invented (rule 4) — nothing here is a real user's question.
QUERIES: tuple = (
    "what port does the staging server use",
    "who owns the nightly billing job",
    "how often are api credentials rotated",
    "where does the staging cluster live",
    "what did we decide about the fleet migration",
    "who prefers short status updates",
    "what is the backup verification cadence",
    "which domain holds the rollout notes",
)


def load_shadow():
    """The shadow module, loaded by path — **without importing the plugin package**.

    ``plugins/entropicmem/__init__.py`` imports ``agent.memory_provider``, which only
    exists inside the Hermes host, so the collector must not go through the package.
    ``_shadow.py`` is written to be loadable standalone: no relative imports, no host
    imports. That is pinned structurally in ``tests/unit/test_shadow_collect.py``,
    because a ``from . import`` added there would break this script and nothing else
    would notice.
    """
    spec = importlib.util.spec_from_file_location(
        "_entropicmem_shadow_collector", PLUGIN / "_shadow.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def copy_store(source: Optional[Path], destination: Path) -> Path:
    """The working copy every write lands in. The source is opened read-only."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source is None:
        sqlite3.connect(str(destination)).close()
        return destination
    if not source.is_file():
        raise SystemExit(f"No store at {source}")
    reader = sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        writer = sqlite3.connect(str(destination))
        try:
            reader.backup(writer)
        finally:
            writer.close()
    finally:
        reader.close()
    return destination


def v2_ids(engine, query: str, max_results: int = 5) -> List[str]:  # noqa: ANN001
    """The ids v2 would inject for this query, from the **real v2 engine**.

    The provider's own numbers are ``max_prefetch_results=5`` and
    ``min_relevance_score=0.35``, so those are the knobs used here. The result is
    candidates rather than the post-budget block: the collector compares the two
    engines' recall and says so, instead of implying it replayed the whole provider.
    """
    hits = engine.recall_with_relevance(query, top_k=max_results * 2, min_relevance=0.35)
    return [hit.id for hit in list(hits)[:max_results]]


def collect(*, source: Optional[Path], turns: int, out: Path, profile: str) -> Path:
    """Run ``turns`` shadow turns and return the divergence log."""
    shadow = load_shadow()
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    from memory_engine import MemoryEngine  # the engine under comparison, after the path

    working = copy_store(source, out / "v2" / "memory.db")
    log = out / "divergence.jsonl"
    if log.exists():
        log.unlink()  # a fresh sample, so the line count means what --turns says

    # The same env the host sets — the collector uses the real flag, not a private seam.
    # Saved and restored, because a CLI that leaks a process-wide flag into whatever
    # runs after it would turn a one-shot tool into a surprise for the whole session.
    previous = {
        key: os.environ.get(key) for key in (shadow.SHADOW_ENV, shadow.LOG_ENV)
    }
    os.environ[shadow.SHADOW_ENV] = str(out / "v3" / "memory.db")
    os.environ[shadow.LOG_ENV] = str(log)

    engine = MemoryEngine(working, profile_id=profile or "default")
    try:
        for index in range(turns):
            query = QUERIES[index % len(QUERIES)]
            written = shadow.run(
                working, profile=profile, query=query, v2_ids=v2_ids(engine, query)
            )
            if written is None:
                raise SystemExit("the shadow wrote nothing — is the copy path writable?")
    finally:
        engine.close()
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    return log


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Collect and score a v3 shadow sample")
    parser.add_argument("--source", default=None, help=f"store to read (default {DEFAULT_LIVE}); never written")
    parser.add_argument("--empty", action="store_true", help="collect against an empty store")
    parser.add_argument("--turns", type=int, default=200, help="turns to shadow (default 200)")
    parser.add_argument("--profile", default="default", help="profile the copy is read under")
    parser.add_argument("--out", default=None, help="working dir (default: a fresh temp dir)")
    arguments = parser.parse_args(argv)

    if arguments.turns < 1:
        raise SystemExit("--turns must be at least 1")
    if arguments.empty and arguments.source:
        raise SystemExit("--empty and --source cannot both be given")

    source = None if arguments.empty else Path(arguments.source or DEFAULT_LIVE).expanduser()
    out = (
        Path(arguments.out).expanduser()
        if arguments.out
        else Path(tempfile.mkdtemp(prefix="em-shadow-collect-"))
    )

    log = collect(source=source, turns=arguments.turns, out=out, profile=arguments.profile)

    shadow = load_shadow()
    report = shadow.report(log)
    print(shadow.render(report))
    print(f"\nworking copy and log kept under: {out}")
    if report["verdict"] == "cannot conclude" and not report["context"]["turns_with_injection"]:
        print(
            "note: no turn injected anything, so divergence has no denominator. On a "
            "zero-fact store that is expected — this sample proves the plumbing only."
        )
    return {"met": 0, "not met": 1}.get(report["verdict"], 2)


if __name__ == "__main__":
    raise SystemExit(main())
