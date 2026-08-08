#!/usr/bin/env python3
"""
entropicmem_episodes_backfill.py — G1 backfill: import Mnemosyne episodic
memory (376 entries) into the EntropicMem `episodes` table.

Source: ~/.hermes/mnemosyne/data/mnemosyne.db, table episodic_memory.
Idempotent: episode ids are prefixed `mne_` + the original id, so re-runs
upsert in place (INSERT OR REPLACE). Safe to run any time.

Usage: python3 entropicmem_episodes_backfill.py [--source PATH] [--dry-run]
"""

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
MEMORY_DB = HERMES_HOME / "entropicmem" / "memory.db"
DEFAULT_SOURCE = HERMES_HOME / "mnemosyne" / "data" / "mnemosyne.db"
SCRIPTS_DIR = HERMES_HOME / "skills" / "entropicmem" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from memory_engine import MemoryEngine  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", default=str(DEFAULT_SOURCE), help="Mnemosyne DB path")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not Path(args.source).exists():
        print(f"episodes-backfill: source DB not found: {args.source}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(args.source)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, content, timestamp, session_id, importance, metadata_json, "
        "event_date FROM episodic_memory"
    ).fetchall()
    conn.close()
    if not rows:
        print("episodes-backfill: no episodic rows found")
        return 0

    engine = MemoryEngine(str(MEMORY_DB))
    try:
        written = 0
        for r in rows:
            content = (r["content"] or "").strip()
            if not content:
                continue
            # Mnemosyne episodic content is raw-ish transcript; first line is
            # usually the summary ("[conversation] SESSION SUMMARY ..." or
            # "[fact] ..."). Keep the first 400 chars as the distilled summary.
            title = content.replace("\n", " ")[:80]
            ts = r["timestamp"] or r["event_date"] or None
            session = r["session_id"] or ""
            # linked_fact_ids: metadata_json holds original fact ids in some rows
            linked: list = []
            meta = r["metadata_json"]
            if meta:
                try:
                    parsed = json.loads(meta)
                    if isinstance(parsed, dict):
                        for key in ("fact_ids", "original_ids", "ids"):
                            val = parsed.get(key)
                            if isinstance(val, list):
                                linked = [str(x) for x in val[:20]]
                                break
                except (json.JSONDecodeError, TypeError):
                    pass
            if args.dry_run:
                print(f"  would import: {title[:60]} ({ts})")
                continue
            engine.add_episode(
                title=title,
                summary=content[:400],
                start_ts=ts,
                end_ts=ts,
                source_session=session,
                linked_fact_ids=linked,
                importance=float(r["importance"] or 0.5),
                domain="Knowledge",
                source="mnemosyne_legacy",
                episode_id="mne_" + r["id"],
            )
            written += 1

        print(f"episodes-backfill: imported {written}/{len(rows)} episodic entries")
        return 0
    finally:
        engine.close()


if __name__ == "__main__":
    sys.exit(main())
