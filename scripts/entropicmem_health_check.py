#!/usr/bin/env python3
"""EntropicMem health check — 12h monitoring cycle.

Checks:
1. memory.db integrity (PRAGMA integrity_check)
2. Fact count + domain distribution
3. Vault directory exists + note count
4. Index freshness (index.db mtime vs memory.db mtime)
5. FTS5 index health (simple query test)
6. Backup recency (last backup age)

Exit 0 on healthy, exit 1 on issues found.
Prints JSON summary for cron consumption.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
ENTROPICMEM_DIR = HERMES_HOME / "entropicmem"
MEMORY_DB = ENTROPICMEM_DIR / "memory.db"
INDEX_DB = ENTROPICMEM_DIR / "index.db"
VAULT_DIR = ENTROPICMEM_DIR / "vault"
BACKUP_DIR = HERMES_HOME / "backups"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _file_age_hours(p: Path) -> float | None:
    if not p.exists():
        return None
    mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
    return (datetime.now(timezone.utc) - mtime).total_seconds() / 3600


def check_memory_db() -> dict:
    if not MEMORY_DB.exists():
        return {"status": "FAIL", "error": "memory.db missing"}
    try:
        conn = sqlite3.connect(str(MEMORY_DB))
        result = conn.execute("PRAGMA integrity_check").fetchone()
        ok = result[0] == "ok"
        count = conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
        domains = conn.execute(
            "SELECT domain, COUNT(*) FROM facts GROUP BY domain ORDER BY COUNT(*) DESC LIMIT 10"
        ).fetchall()
        conn.close()
        return {
            "status": "OK" if ok else "FAIL",
            "integrity": result[0],
            "fact_count": count,
            "domains": {d: c for d, c in domains},
        }
    except Exception as e:
        return {"status": "FAIL", "error": f"{type(e).__name__}: {e}"}


def check_vault() -> dict:
    if not VAULT_DIR.exists():
        return {"status": "WARN", "error": "vault directory missing"}
    count = 0
    for _, _, files in os.walk(VAULT_DIR):
        count += sum(1 for f in files if f.endswith(".md"))
    return {"status": "OK", "note_count": count}


def check_index() -> dict:
    if not INDEX_DB.exists():
        return {"status": "WARN", "error": "index.db missing"}
    try:
        conn = sqlite3.connect(str(INDEX_DB))
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        conn.close()
        age = _file_age_hours(INDEX_DB)
        # Compare index freshness against memory.db; clamp to "index behind" (never negative)
        mem_age = _file_age_hours(MEMORY_DB)
        index_behind_hours = None
        stale = False
        if age is not None and mem_age is not None:
            behind = max(age - mem_age, 0)
            index_behind_hours = round(behind, 1) if behind > 0 else 0.0
            stale = index_behind_hours > 24  # index more than 24h behind memory
        return {
            "status": "WARN" if stale else "OK",
            "tables": len(tables),
            "age_hours": round(age, 1) if age is not None else None,
            "index_behind_hours": index_behind_hours,
        }
    except Exception as e:
        return {"status": "FAIL", "error": f"{type(e).__name__}: {e}"}


def check_fts() -> dict:
    if not MEMORY_DB.exists():
        return {"status": "SKIP", "error": "memory.db missing"}
    try:
        conn = sqlite3.connect(str(MEMORY_DB))
        # Deterministic: verify FTS table exists and is queryable
        total = conn.execute("SELECT COUNT(*) FROM facts_fts").fetchone()[0]
        conn.close()
        return {"status": "OK", "fts_entries": total}
    except Exception as e:
        return {"status": "FAIL", "error": f"{type(e).__name__}: {e}"}


def check_backup() -> dict:
    if not BACKUP_DIR.exists():
        return {"status": "WARN", "error": "backup dir missing"}
    backups = sorted(BACKUP_DIR.glob("entropicmem_*.tar.gz"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not backups:
        return {"status": "WARN", "error": "no backups found"}
    age = _file_age_hours(backups[0])
    return {
        "status": "OK" if age is not None and age < 48 else "WARN",
        "latest": backups[0].name,
        "age_hours": round(age, 1) if age is not None else None,
        "total": len(backups),
    }


def main() -> int:
    checks = {
        "memory_db": check_memory_db(),
        "vault": check_vault(),
        "index": check_index(),
        "fts": check_fts(),
        "backup": check_backup(),
    }

    has_fail = any(c.get("status") == "FAIL" for c in checks.values())
    has_warn = any(c.get("status") == "WARN" for c in checks.values())

    overall = "FAIL" if has_fail else ("WARN" if has_warn else "OK")
    report = {
        "status": overall,
        "checked_at": _now_iso(),
        "checks": checks,
    }
    print(json.dumps(report, indent=2))
    return 1 if has_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
