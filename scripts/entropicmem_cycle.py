#!/usr/bin/env python3
"""EntropicMem 12-hour cycle driver.

Runs the full tandem loop:
  1. Re-migrate legacy → EntropicMem (idempotent; dedups)
  2. Analyze logs → report
  3. If errors/regressions found, hand the analysis to a Plan agent
     (delegate_task orchestrator) to plan fixes
  4. Print the report (delivered to user by the cron)

This script is the `script` target of the 12h cron. It does NOT itself
call delegate_task (the cron runs it with no_agent=False via the agent
prompt); instead it emits a structured JSON the wrapping prompt uses to
decide whether to spawn a Plan agent.

Run: python3 entropicmem_cycle.py
Emits JSON to stdout: {report, needs_plan, plan_brief}
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(os.environ.get(
    "ENTROPICMEM_REPO",
    "/home/ufonik/Documents/Coding Projects/EntropicMem"
))
sys.path.insert(0, str(REPO / "scripts"))


def run(cmd: list[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True).stdout


def main() -> int:
    # Resolve paths from env with defaults
    vault_path = os.environ.get(
        "ENTROPICMEM_VAULT_PATH",
        str(Path.home() / ".hermes" / "entropicmem" / "vault")
    )
    index_db = os.environ.get(
        "ENTROPICMEM_INDEX_DB",
        str(Path.home() / ".hermes" / "entropicmem" / "index.db")
    )
    memory_db = os.environ.get(
        "ENTROPICMEM_MEMORY_DB",
        str(Path.home() / ".hermes" / "entropicmem" / "memory.db")
    )
    log_dir = Path(
        os.environ.get(
            "ENTROPICMEM_LOG_DIR",
            str(Path.home() / ".hermes" / "entropicmem" / "migration_logs")
        )
    )

    env = dict(os.environ)
    env.update({
        "ENTROPICMEM_VAULT_PATH": vault_path,
        "ENTROPICMEM_INDEX_DB": index_db,
        "ENTROPICMEM_MEMORY_DB": memory_db,
    })

    # 1. migrate
    subprocess.run(
        ["python3", str(REPO / "skills/entropicmem/scripts/entropicmem.py"),
         "init", "--vault", vault_path, "--index-db", index_db],
        env=env, capture_output=True, text=True,
    )
    subprocess.run(
        ["python3", str(REPO / "scripts/migrate_and_monitor.py")],
        env=env, capture_output=True, text=True,
    )
    # 2. analyze
    out = subprocess.run(
        ["python3", str(REPO / "scripts/analyze_migration.py")],
        capture_output=True, text=True,
    ).stdout

    # load latest analysis JSON
    analyses = sorted(log_dir.glob("analysis_*.json"))
    rep = json.loads(analyses[-1].read_text()) if analyses else {}

    needs_plan = bool(
        rep.get("errors", 0) > 0
        or (rep.get("parity_rate") is not None and rep["parity_rate"] < 0.95)
    )

    plan_brief = ""
    if needs_plan:
        tax = rep.get("error_taxonomy", {}).get("counts", {})
        plan_brief = (
            f"EntropicMem migration parity/errors below threshold.\n"
            f"Parity: {rep.get('parity_ok')}/{rep.get('parity_total')} "
            f"({rep.get('parity_rate')}). Errors: {rep.get('errors')}.\n"
            f"Error taxonomy: {json.dumps(tax)}\n"
            f"Latest analysis: {analyses[-1]}\n"
            f"Migrate script: scripts/migrate_and_monitor.py\n"
            f"Engine: skills/entropicmem/scripts/memory_engine.py\n"
            f"Plan fixes to reach >=95% parity with 0 errors, then report the patch."
        )

    result = {
        "report": out.strip(),
        "needs_plan": needs_plan,
        "plan_brief": plan_brief,
        "reliable_enough": rep.get("reliable_enough", False),
    }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
