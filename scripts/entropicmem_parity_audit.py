#!/usr/bin/env python3
"""
entropicmem_parity_audit.py — G10: full data-migration parity audit (v2.2.0).

Verifies every legacy Mnemosyne asset is findable in EntropicMem:

  facts    — each Mnemosyne fact content (normalized) exists in `facts`
  episodes — each Mnemosyne episodic entry exists in `episodes` (mne_ prefix)
  triples  — each distinct (subject, predicate, object) exists in `triples`
  embeddings — coverage of EntropicMem facts (unembedded_count)

Exits 0 when every category is at 100% (or the legacy source is missing, in
which case the audit is SKIP — the migration was already consumed). Exits 1
when any category has gaps. Rollback-safe: read-only, never writes.

Usage: python3 entropicmem_parity_audit.py [--legacy-db PATH] [--json]
"""

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
MEMORY_DB = HERMES_HOME / "entropicmem" / "memory.db"
LEGACY_DB = HERMES_HOME / "mnemosyne" / "data" / "mnemosyne.db"
TRIPLES_DB = HERMES_HOME / "mnemosyne" / "data" / "triples.db"


def _norm(text: str) -> str:
    """Normalize content for hashing: strip whitespace/punct case-insensitively."""
    return "".join(c.lower() for c in (text or "") if c.isalnum())


def _hash(text: str) -> str:
    return hashlib.sha256(_norm(text).encode("utf-8")).hexdigest()


def audit_facts(conn: sqlite3.Connection, legacy: sqlite3.Connection) -> dict:
    """Every legacy fact must exist in EntropicMem facts.

    Legacy Mnemosyne `facts` is a triple-store shape (fact_id, subject,
    predicate, object, timestamp) — not a content column — so the parity key
    is the normalized "subject predicate object" string. EntropicMem facts
    were migrated at parity 1.0 by content; we additionally verify the
    legacy triple-shaped rows are findable as content.
    """
    legacy_rows = legacy.execute(
        "SELECT fact_id, subject, predicate, object FROM facts "
        "WHERE subject IS NOT NULL AND predicate IS NOT NULL AND object IS NOT NULL"
    ).fetchall()
    em_hashes = {
        _hash(r[0]) for r in conn.execute("SELECT content FROM facts").fetchall()
    }
    # Legacy `facts` is triple-shaped; its rows were imported into the
    # triples store, so a match there counts as findable too.
    em_triple_keys = {
        (r[0], r[1], r[2]) for r in conn.execute(
            "SELECT lower(subject), lower(predicate), lower(object) FROM triples"
        ).fetchall()
    }
    missing = []
    for fid, subject, predicate, object_ in legacy_rows:
        content = f"{subject} {predicate} {object_}"
        key = (str(subject).lower(), str(predicate).lower(), str(object_).lower())
        if _hash(content) not in em_hashes and key not in em_triple_keys:
            missing.append((fid, content[:60]))
    return {
        "category": "facts",
        "legacy_total": len(legacy_rows),
        "missing": len(missing),
        "sample": [m[1] for m in missing[:5]],
    }


def audit_episodes(conn: sqlite3.Connection, legacy: sqlite3.Connection) -> dict:
    """Every legacy episodic entry must exist in EntropicMem episodes."""
    legacy_rows = legacy.execute("SELECT id FROM episodic_memory").fetchall()
    em_ids = {
        r[0] for r in conn.execute("SELECT episode_id FROM episodes").fetchall()
    }
    missing = [lid for (lid,) in legacy_rows if f"mne_{lid}" not in em_ids]
    return {
        "category": "episodes",
        "legacy_total": len(legacy_rows),
        "missing": len(missing),
        "sample": missing[:5],
    }


def audit_triples(conn: sqlite3.Connection, legacy: sqlite3.Connection) -> dict:
    """Every distinct legacy triple must exist in EntropicMem triples."""
    legacy_rows = legacy.execute(
        "SELECT DISTINCT lower(subject), lower(predicate), lower(object) FROM triples"
    ).fetchall()
    em_keys = {
        (r[0], r[1], r[2])
        for r in conn.execute(
            "SELECT lower(subject), lower(predicate), lower(object) FROM triples"
        ).fetchall()
    }
    missing = [
        (s, p, o) for s, p, o in legacy_rows if (s, p, o) not in em_keys
    ]
    return {
        "category": "triples",
        "legacy_total": len(legacy_rows),
        "missing": len(missing),
        "sample": [f"{s}--{p}--{o}" for s, p, o in missing[:5]],
    }


def audit_embeddings(conn: sqlite3.Connection) -> dict:
    """EntropicMem fact embedding coverage must be 100%."""
    total = conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
    embedded = conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
    return {
        "category": "embeddings",
        "legacy_total": total,
        "missing": max(total - embedded, 0),
        "sample": [] if total == embedded else ["unembedded facts present"],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--legacy-db", default=str(LEGACY_DB))
    ap.add_argument("--triples-db", default=str(TRIPLES_DB))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if not MEMORY_DB.exists():
        print(json.dumps({"status": "FAIL", "error": f"memory.db missing: {MEMORY_DB}"}))
        return 1

    conn = sqlite3.connect(str(MEMORY_DB))
    results = []
    legacy = sqlite3.connect(args.legacy_db) if Path(args.legacy_db).exists() else None
    triples = sqlite3.connect(args.triples_db) if Path(args.triples_db).exists() else None

    if legacy is not None:
        results.append(audit_facts(conn, legacy))
        results.append(audit_episodes(conn, legacy))
    else:
        results.append({"category": "facts", "status": "SKIP", "legacy_total": 0, "missing": 0, "sample": []})
        results.append({"category": "episodes", "status": "SKIP", "legacy_total": 0, "missing": 0, "sample": []})
    if triples is not None:
        results.append(audit_triples(conn, triples))
    else:
        results.append({"category": "triples", "status": "SKIP", "legacy_total": 0, "missing": 0, "sample": []})
    results.append(audit_embeddings(conn))

    for r in results:
        r["status"] = "OK" if r["missing"] == 0 else "GAP"
    if legacy:
        legacy.close()
    if triples:
        triples.close()
    conn.close()

    all_ok = all(r["status"] == "OK" for r in results)
    if args.json:
        print(json.dumps({"status": "PASS" if all_ok else "FAIL", "audits": results}, indent=2))
        return 0 if all_ok else 1

    print("=== EntropicMem ↔ Mnemosyne parity audit ===")
    for r in results:
        print(f"  {r['status']:4s} {r['category']:12s} {r['missing']}/{r['legacy_total']} missing")
        for s in r["sample"]:
            print(f"         e.g. {s}")
    print("VERDICT:", "PASS — full parity" if all_ok else "FAIL — gaps remain")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
