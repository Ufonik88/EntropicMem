#!/usr/bin/env python3
"""
Daily stability gate writer for EntropicMem.

Runs the health check, appends today's status to stability_gate.log,
and prints a summary for the agent to report.

This is the script called by the daily cron — it does the actual
health check + logging, not the agent.
"""

import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
ENTROPICMEM_DIR = HERMES_HOME / "entropicmem"
MEMORY_DB = ENTROPICMEM_DIR / "memory.db"
GATE_LOG = ENTROPICMEM_DIR / "stability_gate.log"
HEALTH_CHECK = Path(__file__).parent / "entropicmem_health_check.py"


def run_health_check() -> dict:
    """Run the health check script and parse its JSON output."""
    try:
        result = subprocess.run(
            [sys.executable, str(HEALTH_CHECK)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stdout.strip()
        if output:
            try:
                return json.loads(output)
            except json.JSONDecodeError:
                # Try to find the first complete JSON object
                depth = 0
                start = None
                for i, ch in enumerate(output):
                    if ch == "{":
                        if depth == 0:
                            start = i
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                        if depth == 0 and start is not None:
                            return json.loads(output[start : i + 1])
        return {"status": "FAIL", "error": "No JSON output from health check"}
    except subprocess.TimeoutExpired:
        return {"status": "FAIL", "error": "Health check timed out"}
    except Exception as e:
        return {"status": "FAIL", "error": str(e)}


def append_gate_entry(status: str) -> None:
    """Append today's entry to the stability gate log."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    entry = f"{today},{status}\n"

    # Don't duplicate today's entry
    if GATE_LOG.exists():
        existing = GATE_LOG.read_text()
        if today in existing:
            return  # already logged today

    with open(GATE_LOG, "a") as f:
        f.write(entry)


def count_consecutive_ok() -> int:
    """Count current consecutive OK days from the gate log."""
    if not GATE_LOG.exists():
        return 0
    lines = [l.strip() for l in GATE_LOG.read_text().strip().split("\n") if l.strip()]
    entries = []
    for line in lines:
        parts = line.split(",")
        if len(parts) == 2:
            try:
                d = datetime.strptime(parts[0].strip(), "%Y-%m-%d").date()
                entries.append((d, parts[1].strip() == "OK"))
            except ValueError:
                continue
    entries.sort(key=lambda x: x[0])

    from datetime import timedelta
    longest = 0
    current = 0
    for i, (d, is_ok) in enumerate(entries):
        if is_ok:
            if i == 0 or entries[i - 1][0] != d - timedelta(days=1):
                current = 0
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def main() -> int:
    # Run health check
    result = run_health_check()
    status = result.get("status", "FAIL")

    # Append to gate log
    append_gate_entry(status)

    # Count consecutive OK days
    consecutive = count_consecutive_ok()
    gate_passed = consecutive >= 7

    # Build report
    report = {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "health_status": status,
        "consecutive_ok_days": consecutive,
        "gate_passed": gate_passed,
        "days_until_gate": max(0, 7 - consecutive),
    }

    if "error" in result:
        report["error"] = result["error"]

    if "fact_count" in result:
        report["fact_count"] = result["fact_count"]

    print(json.dumps(report, indent=2))
    return 0 if status == "OK" else 1


if __name__ == "__main__":
    sys.exit(main())
