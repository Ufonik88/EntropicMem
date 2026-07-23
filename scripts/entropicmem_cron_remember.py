#!/usr/bin/env python3
"""Cron-safe durable write into EntropicMem (no Hermes memory tool required).

Why this exists
---------------
Hermes cron jobs construct AIAgent with ``skip_memory=True`` by design
(``cron/scheduler.py``: "Cron system prompts would corrupt user
representations"). That gate:

* prevents the external MemoryProvider (EntropicMem) from loading
* leaves the interactive ``memory`` tool with ``store=None`` →
  "Memory is not available"
* also withholds ``entropicmem_*`` provider tools from the cron tool list

So scheduled jobs MUST write through this helper (or the MemoryEngine API
directly). Do not call the interactive ``memory`` / ``entropicmem_*`` tools
from cron and expect them to work.

Usage
-----
  python3 ~/.hermes/scripts/entropicmem_cron_remember.py "durable fact" \\
      [--domain Knowledge] [--importance 0.7] [--source cron]
  python3 ~/.hermes/scripts/entropicmem_cron_remember.py --json \\
      '[{"content":"...","domain":"Knowledge","importance":0.7}]'
  python3 ~/.hermes/scripts/entropicmem_cron_remember.py --self-test
  python3 ~/.hermes/scripts/entropicmem_cron_remember.py --dry-run "..."

Exit codes: 0 ok, 1 usage/error, 2 recall verification failed.

Install into Hermes home
------------------------
  install -m 755 scripts/entropicmem_cron_remember.py \\
      ~/.hermes/scripts/entropicmem_cron_remember.py
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
SCRIPTS = HERMES_HOME / "skills" / "entropicmem" / "scripts"
# Prefer explicit env, then default store under HERMES_HOME.
MEMORY_DB = Path(
    os.environ.get("ENTROPICMEM_MEMORY_DB", str(HERMES_HOME / "entropicmem" / "memory.db"))
)


def _engine():
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    from memory_engine import MemoryEngine  # type: ignore

    if not MEMORY_DB.exists():
        raise FileNotFoundError(f"EntropicMem memory.db missing: {MEMORY_DB}")
    return MemoryEngine(MEMORY_DB)


def remember(
    content: str,
    domain: str = "Knowledge",
    importance: float = 0.7,
    source: str = "cron",
    title: str | None = None,
) -> dict:
    content = (content or "").strip()
    if not content:
        raise ValueError("empty content")
    with _engine() as engine:
        eid = engine.remember(
            content=content,
            title=content[:60],
            domain=domain,
            source=source,
            importance=float(importance),
        )
        hits = engine.recall(content, top_k=8)
    hit_ids = []
    for h in hits:
        hid = getattr(h, "id", None)
        if hid is None and isinstance(h, dict):
            hid = h.get("id")
        hit_ids.append(hid)
    ok = eid in hit_ids
    return {
        "ok": ok,
        "entropic_id": eid,
        "domain": domain,
        "verified_recall": ok,
        "hit_ids": hit_ids[:5],
        "memory_db": str(MEMORY_DB),
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("content", nargs="?", help="Fact text to store")
    p.add_argument("--domain", default="Knowledge")
    p.add_argument("--importance", type=float, default=0.7)
    p.add_argument("--source", default="cron")
    p.add_argument("--title", default=None, help="Explicit title (default: first 60 chars of content)")
    p.add_argument(
        "--json",
        dest="json_in",
        help='JSON array of {content,domain?,importance?}',
    )
    p.add_argument("--self-test", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    if args.self_test:
        probe = "ENTROPICMEM CRON SELF-TEST: script path healthy."
        if args.dry_run:
            print(json.dumps({"ok": True, "dry_run": True, "would_store": probe}))
            return 0
        result = remember(
            probe, domain="Knowledge", importance=0.4, source="cron_self_test", title="Self-Test Probe"
        )
        print(json.dumps(result))
        return 0 if result["ok"] else 2

    items = []
    if args.json_in:
        try:
            raw = json.loads(args.json_in)
        except json.JSONDecodeError:
            print("ERROR: invalid JSON passed to --json", file=sys.stderr)
            return 1
        if not isinstance(raw, list):
            print("ERROR: --json must be a JSON array", file=sys.stderr)
            return 1
        items = raw
    elif args.content:
        items = [
            {
                "content": args.content,
                "domain": args.domain,
                "importance": args.importance,
            }
        ]
    else:
        p.print_help()
        return 1

    if args.dry_run:
        print(
            json.dumps(
                {"ok": True, "dry_run": True, "count": len(items), "items": items},
                indent=2,
            )
        )
        return 0

    results = []
    all_ok = True
    for it in items:
        raw_content = it.get("content") if isinstance(it, dict) else it
        content = str(raw_content or "")
        domain = (it.get("domain") if isinstance(it, dict) else None) or args.domain
        importance = it.get("importance") if isinstance(it, dict) else None
        if importance is None:
            importance = args.importance
        title = (it.get("title") if isinstance(it, dict) else None) or args.title
        try:
            r = remember(
                content, title=title, domain=str(domain), importance=float(importance), source=args.source
            )
        except (FileNotFoundError, ImportError, ValueError) as e:
            r = {"ok": False, "error": f"{type(e).__name__}: {e}", "content": (content or "")[:80]}
        except Exception as e:
            r = {"ok": False, "error": f"{type(e).__name__}: {e}", "content": (content or "")[:80]}
        results.append(r)
        if not r.get("ok"):
            all_ok = False

    print(json.dumps({"ok": all_ok, "results": results}, indent=2))
    return 0 if all_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
