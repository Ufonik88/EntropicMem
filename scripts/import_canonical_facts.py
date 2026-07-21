#!/usr/bin/env python3
"""Import Mnemosyne canonical_facts into EntropicMem.

canonical_facts are always-injected identity/preference/task slots that live
in a SEPARATE table from the memories table. The main migrate_and_monitor.py
only reads from memories — this script fills the gap.

Run: python3 import_canonical_facts.py [--dry-run]
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

REPO_SCRIPTS = Path(__file__).resolve().parent.parent / "skills" / "entropicmem" / "scripts"
if str(REPO_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(REPO_SCRIPTS))

HERMES_HOME = Path.home() / ".hermes"
MNEMOSYNE_DB = HERMES_HOME / "mnemosyne" / "data" / "mnemosyne.db"
MEMORY_DB = HERMES_HOME / "entropicmem" / "memory.db"


def read_canonical_facts() -> list[dict]:
    if not MNEMOSYNE_DB.is_file():
        return []
    conn = sqlite3.connect(str(MNEMOSYNE_DB))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT category, name, body FROM canonical_facts"
        ).fetchall()
        return [{"category": r["category"], "name": r["name"], "body": r["body"]} for r in rows]
    finally:
        conn.close()


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    from memory_engine import MemoryEngine

    facts = read_canonical_facts()
    print(f"[canonical] {len(facts)} canonical facts found")

    engine = MemoryEngine(MEMORY_DB)
    written = skipped = 0

    for f in facts:
        content = f"[{f['category']}] {f['name']}: {f['body']}"
        if not content.strip():
            skipped += 1
            continue
        if dry_run:
            print(f"  DRY RUN: {content[:100]}")
            continue
        eid = engine.remember(
            content=content,
            source=f"canonical:{f['category']}",
            importance=0.85,
            domain="Knowledge",
            tags=[f["category"], "canonical", "migrated"],
        )
        if eid:
            written += 1
        else:
            skipped += 1

    engine.close()
    print(f"[canonical] written={written} skipped={skipped} dry_run={dry_run}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
