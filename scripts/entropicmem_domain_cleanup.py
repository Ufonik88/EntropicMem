#!/usr/bin/env python3
"""
entropicmem_domain_cleanup.py — G8: canonical domain cleanup (v2.2.0).

Remaps stray/junk fact domains to the canonical list:
  Test, Wedding, Preference, Preferences, Operations, Security → canonical

Canonical domains (aligned to the Obsidian vault folder taxonomy):
  Knowledge, Projects, Infrastructure, Finance, Engineering, People,
  Rules, Workflow, System, Ajax Systems, X-Growth

Default is --dry-run (report only). Use --apply to write.
"""

import argparse
import os
import sqlite3
import sys
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
MEMORY_DB = HERMES_HOME / "entropicmem" / "memory.db"
INDEX_DB = HERMES_HOME / "entropicmem" / "index.db"

CANONICAL_DOMAINS = {
    "Knowledge", "Projects", "Infrastructure", "Finance", "Engineering",
    "People", "Rules", "Workflow", "System", "Ajax Systems", "X-Growth",
}

# Stray domain → canonical
DOMAIN_MAP = {
    "Test": "Knowledge",
    "Wedding": "Projects",
    "Preference": "People",
    "Preferences": "People",
    "Operations": "Infrastructure",
    "Security": "Infrastructure",
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="Write changes (default: dry-run)")
    args = ap.parse_args()

    conn = sqlite3.connect(str(MEMORY_DB))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT id, domain FROM facts").fetchall()

    strays = {}
    for r in rows:
        d = r["domain"] or "Knowledge"
        if d not in CANONICAL_DOMAINS:
            strays.setdefault(d, []).append(r["id"])

    if not strays:
        print("domain-cleanup: no stray domains found — taxonomy is canonical")
        conn.close()
        return 0

    total = sum(len(v) for v in strays.values())
    print(f"domain-cleanup: {total} fact(s) in stray domains:")
    for d, ids in sorted(strays.items()):
        target = DOMAIN_MAP.get(d, "Knowledge")
        print(f"  {d!r} ({len(ids)} facts) -> {target!r}")
        if args.apply:
            for fid in ids:
                conn.execute("UPDATE facts SET domain = ? WHERE id = ?", (target, fid))
            print(f"    applied: {len(ids)} facts remapped to {target!r}")

    if args.apply:
        conn.commit()
        # Mirror to index.db notes_meta if the table exists (vault notes carry domain)
        try:
            idx = sqlite3.connect(str(INDEX_DB))
            cols = {r[1] for r in idx.execute("PRAGMA table_info(notes_meta)").fetchall()}
            if "domain" in cols:
                n_notes = 0
                for d, ids in strays.items():
                    target = DOMAIN_MAP.get(d, "Knowledge")
                    for fid in ids:
                        cur = idx.execute(
                            "UPDATE notes_meta SET domain = ? WHERE note_id = ?",
                            (target, fid),
                        )
                        n_notes += cur.rowcount
                idx.commit()
                print(f"domain-cleanup: {n_notes} vault note(s) remapped in index.db")
            idx.close()
        except sqlite3.Error:
            pass
        print("domain-cleanup: applied (facts + index notes)")
    else:
        print("domain-cleanup: dry-run — re-run with --apply to write")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
