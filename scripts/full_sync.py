#!/usr/bin/env python3
"""Full Mnemosyne → EntropicMem sync.

Runs:
1. migrate_and_monitor.py — import memories table
2. import_canonical_facts.py — import canonical_facts table
3. Rebuild FTS5 index to fix rowid misalignment

Run: python3 full_sync.py [--dry-run]
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

SCRIPTS = Path(__file__).parent
REPO = SCRIPTS.parent
PYTHON = sys.executable


def run_step(name: str, script: Path, args: list[str] = None) -> bool:
    print(f"\n{'='*60}")
    print(f"STEP: {name}")
    print(f"{'='*60}")
    cmd = [PYTHON, str(script)] + (args or [])
    result = subprocess.run(cmd, cwd=str(REPO), capture_output=False)
    if result.returncode != 0:
        print(f"  FAILED (exit {result.returncode})")
        return False
    print(f"  OK")
    return True


def rebuild_fts5() -> bool:
    print(f"\n{'='*60}")
    print("STEP: Rebuild FTS5 index")
    print(f"{'='*60}")

    sys.path.insert(0, str(REPO / "skills" / "entropicmem" / "scripts"))
    from memory_engine import MemoryEngine

    DB = Path.home() / ".hermes" / "entropicmem" / "memory.db"
    engine = MemoryEngine(DB)

    before_fts = engine.db.execute("SELECT COUNT(*) FROM facts_fts").fetchone()[0]
    before_facts = engine.db.execute("SELECT COUNT(*) FROM facts").fetchone()[0]

    engine.db.execute("DELETE FROM facts_fts")
    engine.db.execute("""
        INSERT INTO facts_fts (rowid, content, title, tags, domain)
        SELECT rowid, content, title, tags, domain FROM facts
    """)
    engine.db.commit()

    after_fts = engine.db.execute("SELECT COUNT(*) FROM facts_fts").fetchone()[0]
    engine.close()

    print(f"  FTS5: {before_fts} → {after_fts} (facts: {before_facts})")
    if before_fts != before_facts:
        print(f"  FIXED: FTS5 was misaligned ({before_fts} vs {before_facts})")
    else:
        print(f"  OK: already aligned")
    return True


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    args = ["--dry-run"] if dry_run else []

    start = time.time()
    ok = True

    ok &= run_step("Mnemosyne memories → EntropicMem", SCRIPTS / "migrate_and_monitor.py", args)
    ok &= run_step("Canonical facts → EntropicMem", SCRIPTS / "import_canonical_facts.py", args)

    if not dry_run:
        ok &= rebuild_fts5()

    duration = round(time.time() - start, 2)
    status = "SUCCESS" if ok else "PARTIAL FAILURE"
    print(f"\n{'='*60}")
    print(f"SYNC COMPLETE: {status} in {duration}s")
    print(f"{'='*60}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
