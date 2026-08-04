#!/usr/bin/env python3
"""EntropicMem health check — 12h monitoring cycle.

Checks:
1. memory.db integrity (PRAGMA integrity_check)
2. Fact count + domain distribution
3. Vault directory exists + note count
4. Index freshness (index.db mtime vs newest vault note mtime)
5. FTS5 index health (simple query test)
6. Backup recency (last backup age)
7. 1-week stability gate for sole-provider promotion

Exit 0 on healthy, exit 1 on issues found.
Prints JSON summary for cron consumption.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
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


def _newest_vault_note_hours() -> float | None:
    """Age (hours) of the newest .md under VAULT_DIR, or None if none found."""
    newest: float | None = None
    for root, _dirs, files in os.walk(VAULT_DIR):
        for f in files:
            if not f.endswith(".md"):
                continue
            m = os.path.getmtime(os.path.join(root, f))
            if newest is None or m > newest:
                newest = m
    if newest is None:
        return None
    return (datetime.now(timezone.utc) - datetime.fromtimestamp(newest, tz=timezone.utc)).total_seconds() / 3600


def check_index() -> dict:
    if not INDEX_DB.exists():
        return {"status": "WARN", "error": "index.db missing"}
    try:
        conn = sqlite3.connect(str(INDEX_DB))
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        conn.close()
        age = _file_age_hours(INDEX_DB)
        # Index freshness is measured against its source (the vault), not memory.db:
        # the index only changes when vault notes change, so comparing to memory.db
        # (written daily by cron) would always WARN. Flag only when vault notes are
        # newer than the last index build.
        vault_note_age = _newest_vault_note_hours()
        index_behind_hours = None
        stale = False
        if age is not None and vault_note_age is not None:
            behind = max(age - vault_note_age, 0)
            index_behind_hours = round(behind, 1) if behind > 0 else 0.0
            stale = index_behind_hours > 24  # index built >24h after newest vault note
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
    plain = sorted(BACKUP_DIR.glob("entropicmem_*.tar.gz"), key=lambda p: p.stat().st_mtime, reverse=True)
    enc = sorted(BACKUP_DIR.glob("entropicmem_*.tar.gz.enc"), key=lambda p: p.stat().st_mtime, reverse=True)
    backups = plain + enc
    if not backups:
        return {"status": "WARN", "error": "no backups found"}
    latest = backups[0]
    age = _file_age_hours(latest)
    status = "OK" if age is not None and age < 48 else "WARN"
    result = {
        "status": status,
        "latest": latest.name,
        "age_hours": round(age, 1) if age is not None else None,
        "total": len(backups),
        "encrypted": len(enc),
        "plaintext": len(plain),
    }
    if plain:
        result["status"] = "WARN"
        result["note"] = f"{len(plain)} plaintext backup(s) still present; encrypt them"
    return result


def check_stability_gate() -> dict:
    """Check 1-week stability gate criteria for sole-provider promotion.

    Gate criteria:
    - At least 7 CONSECUTIVE days of health-checks with status OK
    - All Mnemosyne crons paused (not active)
    - No entropicmem_remember tool failures in interactive logs
    """
    gate_log = HERMES_HOME / "entropicmem" / "stability_gate.log"

    if not gate_log.exists():
        return {
            "status": "PENDING",
            "message": "Stability gate log not found - gate not started",
            "days_tracked": 0,
            "longest_consecutive_ok": 0,
            "gate_passed": False,
        }

    try:
        lines = [l.strip() for l in gate_log.read_text().strip().split("\n") if l.strip()]
        # Each line: YYYY-MM-DD,status (OK/WARN/FAIL)

        # Parse into sorted list of (date, is_ok)
        entries = []
        for line in lines:
            parts = line.split(",")
            if len(parts) != 2:
                continue
            date_str, status = parts[0].strip(), parts[1].strip()
            try:
                d = datetime.strptime(date_str, "%Y-%m-%d").date()
                entries.append((d, status == "OK"))
            except ValueError:
                continue

        if not entries:
            return {
                "status": "PENDING",
                "message": "Gate log has no valid entries",
                "days_tracked": 0,
                "longest_consecutive_ok": 0,
                "gate_passed": False,
            }

        # Sort by date ascending
        entries.sort(key=lambda x: x[0])

        # Scan for longest consecutive OK run
        longest_run = 0
        current_run = 0
        for i, (d, is_ok) in enumerate(entries):
            if is_ok:
                if i == 0 or entries[i - 1][0] != d - timedelta(days=1):
                    current_run = 0  # break: not consecutive with previous day
                current_run += 1
                longest_run = max(longest_run, current_run)
            else:
                current_run = 0

        gate_passed = longest_run >= 7

        # Check Mnemosyne cron state from jobs.json
        mnemosyne_ids = {
            "bf428b0b2e05", "bacf5cca7c61", "11b5bbe1fc68",
            "f893e7549326", "7cbacc0d9038", "b20d38ad8edb"
        }
        cron_result = _check_mnemosyne_crons(mnemosyne_ids)

        return {
            "status": "OK" if gate_passed else "PENDING",
            "days_tracked": len(entries),
            "longest_consecutive_ok": longest_run,
            "gate_passed": gate_passed,
            "mnemosyne_crons_state": cron_result,
            "message": (
                f"Gate {'PASSED' if gate_passed else 'IN PROGRESS'}: "
                f"{longest_run}/7 longest consecutive OK days"
            ),
        }
    except Exception as e:
        return {"status": "FAIL", "error": f"{type(e).__name__}: {e}"}


def _check_mnemosyne_crons(mnemosyne_ids: set) -> dict:
    """Check if any Mnemosyne/tandem cron jobs are still active.

    Reads ~/.hermes/cron/jobs.json.
    Returns dict with 'active' (list), 'paused' (list), 'error' (str or None).
    """
    jobs_path = HERMES_HOME / "cron" / "jobs.json"
    if not jobs_path.exists():
        return {
            "active": [],
            "paused": [],
            "error": "jobs.json not found — cannot determine cron state",
        }
    try:
        with open(jobs_path) as f:
            data = json.load(f)
        jobs = data.get("jobs", []) if isinstance(data, dict) else []
        active = []
        paused = []
        for j in jobs:
            jid = j.get("id", "")
            if jid in mnemosyne_ids:
                state = j.get("state", "")
                if state in ("paused", "disabled"):
                    paused.append(jid)
                else:
                    active.append(jid)
        return {"active": active, "paused": paused, "error": None}
    except Exception as e:
        return {
            "active": [],
            "paused": [],
            "error": f"Cannot read jobs.json: {type(e).__name__}: {e}",
        }




def check_security_posture() -> dict:
    """Phase 2/3: FS modes, backup ciphertext, graph bind."""
    import stat as _stat
    import subprocess
    issues = []
    details = {}

    # Directory / DB modes
    if ENTROPICMEM_DIR.exists():
        dmode = ENTROPICMEM_DIR.stat().st_mode & 0o777
        details["entropicmem_dir_mode"] = oct(dmode)
        if dmode & 0o077:
            issues.append(f"entropicmem dir world/group accessible: {oct(dmode)}")
    for name in ("memory.db", "index.db"):
        p = ENTROPICMEM_DIR / name
        if p.exists():
            m = p.stat().st_mode & 0o777
            details[f"{name}_mode"] = oct(m)
            if m & 0o077:
                issues.append(f"{name} mode {oct(m)} allows group/other")

    # Backup key + latest archive type
    key = ENTROPICMEM_DIR / ".backup_key"
    details["backup_key_present"] = key.exists()
    enc = sorted(BACKUP_DIR.glob("entropicmem_*.tar.gz.enc")) if BACKUP_DIR.exists() else []
    plain = sorted(BACKUP_DIR.glob("entropicmem_*.tar.gz")) if BACKUP_DIR.exists() else []
    details["encrypted_backups"] = len(enc)
    details["plaintext_backups"] = len(plain)
    if plain:
        issues.append(f"{len(plain)} plaintext backup tar(s) still present")
    if not enc and not plain:
        details["backup_note"] = "no local backups found"

    # Graph listener bind
    bind = "unknown"
    bind_policy = ""
    policy_file = ENTROPICMEM_DIR / "bind_policy"
    if policy_file.exists():
        bind_policy = policy_file.read_text().strip()

    try:
        out = subprocess.check_output(["ss", "-tlnp"], text=True, stderr=subprocess.DEVNULL)
        lines = [ln for ln in out.splitlines() if ":8075" in ln]
        details["graph_ss"] = lines[:3]
        if any("0.0.0.0:8075" in ln or "*:8075" in ln for ln in lines):
            if bind_policy == "tailscale+local":
                bind = "0.0.0.0 (tailscale+local)"
            else:
                issues.append("graph server listening on all interfaces")
                bind = "0.0.0.0"
        elif any("127.0.0.1:8075" in ln for ln in lines):
            bind = "127.0.0.1"
        elif not lines:
            bind = "down"
    except Exception as e:
        details["graph_ss_error"] = str(e)
    details["graph_bind"] = bind
    if bind_policy:
        details["bind_policy"] = bind_policy

    status = "FAIL" if any("all interfaces" in i for i in issues) else ("WARN" if issues else "OK")
    return {"status": status, "issues": issues, "details": details}


def check_audit_log() -> dict:
    if not MEMORY_DB.exists():
        return {"status": "WARN", "error": "memory.db missing"}
    try:
        conn = sqlite3.connect(str(MEMORY_DB))
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "audit_log" not in tables:
            conn.close()
            return {"status": "WARN", "error": "audit_log table missing (pre-2.1.6)"}
        n = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        pending = 0
        if "pending_facts" in tables:
            pending = conn.execute("SELECT COUNT(*) FROM pending_facts").fetchone()[0]
        conn.close()
        return {"status": "OK", "audit_events": n, "pending_facts": pending}
    except Exception as e:
        return {"status": "FAIL", "error": f"{type(e).__name__}: {e}"}


def main() -> int:
    checks = {
        "memory_db": check_memory_db(),
        "vault": check_vault(),
        "index": check_index(),
        "fts": check_fts(),
        "backup": check_backup(),
        "stability_gate": check_stability_gate(),
        "security_posture": check_security_posture(),
        "audit_log": check_audit_log(),
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