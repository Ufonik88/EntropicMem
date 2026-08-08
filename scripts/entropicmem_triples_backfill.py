#!/usr/bin/env python3
"""
entropicmem_triples_backfill.py — G2 backfill: import legacy Mnemosyne
knowledge triples into the EntropicMem `triples` table.

Source: ~/.hermes/mnemosyne/data/triples.db, table triples
(subject, predicate, object, valid_from, valid_until, source, confidence).

Imports DISTINCT (subject, predicate, object) rows only — the legacy table
holds 316k rows of mostly duplicate/inferred noise; the distinct set is the
usable relational seed. Idempotent via the UNIQUE(subject, predicate, object)
constraint + upsert. Safe to run any time.

Usage: python3 entropicmem_triples_backfill.py [--source PATH] [--dry-run]
"""

import argparse
import os
import sqlite3
import sys
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
MEMORY_DB = HERMES_HOME / "entropicmem" / "memory.db"
DEFAULT_SOURCE = HERMES_HOME / "mnemosyne" / "data" / "triples.db"
SCRIPTS_DIR = HERMES_HOME / "skills" / "entropicmem" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from memory_engine import MemoryEngine  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", default=str(DEFAULT_SOURCE), help="Mnemosyne triples.db path")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0,
                    help="Max triples to import (0 = all distinct)")
    args = ap.parse_args()

    if not Path(args.source).exists():
        print(f"triples-backfill: source DB not found: {args.source}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(args.source)
    conn.row_factory = sqlite3.Row
    query = (
        "SELECT subject, predicate, object, valid_from, valid_until, "
        "       source, confidence "
        "FROM (SELECT *, ROW_NUMBER() OVER ("
        "         PARTITION BY lower(subject), lower(predicate), lower(object) "
        "         ORDER BY confidence DESC) AS rn FROM triples) "
        "WHERE rn = 1"
    )
    if args.limit:
        query += f" LIMIT {int(args.limit)}"
    rows = conn.execute(query).fetchall()
    conn.close()
    if not rows:
        print("triples-backfill: no triples found")
        return 0

    engine = MemoryEngine(str(MEMORY_DB))
    try:
        written = 0
        for r in rows:
            subject = (r["subject"] or "").strip()
            predicate = (r["predicate"] or "").strip()
            object_ = (r["object"] or "").strip()
            if not subject or not predicate or not object_:
                continue
            if args.dry_run:
                print(f"  would import: {subject} --{predicate}--> {object_}")
                continue
            engine.upsert_triple(
                subject, predicate, object_,
                valid_from=r["valid_from"],
                valid_until=r["valid_until"],
                source="mnemosyne_legacy",
                confidence=float(r["confidence"] or 1.0),
            )
            written += 1

        print(f"triples-backfill: imported {written}/{len(rows)} distinct triples")
        return 0
    finally:
        engine.close()


if __name__ == "__main__":
    sys.exit(main())
