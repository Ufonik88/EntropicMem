#!/usr/bin/env python3
"""
entropicmem_triples_sync.py — G2 edge writer: mirror the canonical `triples`
table (memory.db) into `graph_edges` in BOTH memory.db and index.db.

Fixes the v2.2.0 split-brain: the graph server reads graph_edges from
index.db while the engine writes triples to memory.db. The triples table is
the single canonical source; graph_edges is a derived projection kept in
sync here. Idempotent (INSERT OR IGNORE on the UNIQUE(source,target,kind)).

Also used by the graph refresh cron after triple extraction.

Usage: python3 entropicmem_triples_sync.py [--dry-run]
"""

import argparse
import os
import sqlite3
import sys
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
MEMORY_DB = HERMES_HOME / "entropicmem" / "memory.db"
INDEX_DB = HERMES_HOME / "entropicmem" / "index.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS graph_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    weight INTEGER DEFAULT 1,
    kind TEXT DEFAULT 'wikilink',
    UNIQUE(source_id, target_id, kind)
);
"""


def sync(db_path: Path, dry_run: bool = False) -> int:
    """Mirror triples from memory.db into graph_edges at db_path. Returns count."""
    src = sqlite3.connect(str(MEMORY_DB))
    src.row_factory = sqlite3.Row
    triples = src.execute(
        "SELECT subject, predicate, object FROM triples "
        "WHERE (valid_until IS NULL OR valid_until = '')"
    ).fetchall()
    src.close()

    dst = sqlite3.connect(str(db_path))
    dst.executescript(SCHEMA)
    written = 0
    for t in triples:
        if not t["subject"] or not t["object"]:
            continue
        edge_kind = "triple:" + (t["predicate"] or "relation")
        if dry_run:
            written += 1
            continue
        dst.execute(
            "INSERT OR IGNORE INTO graph_edges (source_id, target_id, weight, kind) "
            "VALUES (?, ?, 1, ?)",
            (t["subject"], t["object"], edge_kind),
        )
        written += 1
    dst.commit()
    dst.close()
    return written


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not MEMORY_DB.exists():
        print(f"triples-sync: memory.db missing: {MEMORY_DB}", file=sys.stderr)
        return 1

    mem = sync(MEMORY_DB, dry_run=args.dry_run)
    idx = sync(INDEX_DB, dry_run=args.dry_run)
    verb = "would write" if args.dry_run else "wrote"
    print(f"triples-sync: {verb} {mem} edges to memory.db, {idx} edges to index.db")
    return 0


if __name__ == "__main__":
    sys.exit(main())
