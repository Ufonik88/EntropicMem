#!/usr/bin/env python3
"""EntropicMem 12-hour monitoring analyzer.

Reads the latest migration log (and any logs since last run), computes:
  - migration throughput (written / errors)
  - recall parity rate
  - error taxonomy (which operations failed, sample messages)
  - trend vs previous run (improving / regressing / stable)

Writes an ANALYSIS report JSON to entropicmem/migration_logs/analysis_<ts>.json
and prints a human report. The cron job pipes this into a Plan agent.

Run: python3 analyze_migration.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

LOG_DIR = Path.home() / ".hermes" / "entropicmem" / "migration_logs"


def _load_summaries() -> list[dict]:
    """Load all run_summary events, oldest→newest."""
    out = []
    for p in sorted(LOG_DIR.glob("run_*.jsonl")):
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                ev = json.loads(line)
                if ev.get("event") == "run_summary":
                    out.append(ev)
        except Exception:
            continue
    return out


def _error_taxonomy(log_path: Path) -> dict:
    """Group fact-level errors by message prefix."""
    tax: dict[str, int] = {}
    samples: list[dict] = []
    try:
        for line in log_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            ev = json.loads(line)
            if ev.get("event") == "fact" and ev.get("status") == "error":
                msg = (ev.get("error") or "")[:80]
                key = msg.split(":")[0][:40] or "unknown"
                tax[key] = tax.get(key, 0) + 1
                if len(samples) < 8:
                    samples.append({"legacy_id": ev.get("legacy_id"), "error": ev.get("error")})
    except Exception:
        pass
    return {"counts": tax, "samples": samples}


def analyze() -> dict:
    summaries = _load_summaries()
    if not summaries:
        return {"ok": False, "reason": "no run logs found"}

    latest = summaries[-1]
    prev = summaries[-2] if len(summaries) >= 2 else None

    latest_log = sorted(LOG_DIR.glob("run_*.jsonl"))[-1]
    errors = _error_taxonomy(latest_log)

    # parity trend
    def _rate(s):
        return s.get("parity_rate") if s.get("parity_rate") is not None else 0.0

    trend = "n/a"
    if prev:
        d = round(_rate(latest) - _rate(prev), 4)
        trend = "improving" if d > 0.001 else ("regressing" if d < -0.001 else "stable")

    report = {
        "ok": True,
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run_ts": latest["ts"],
        "total_facts": latest["total"],
        "written": latest["written"],
        "errors": latest["errors"],
        "parity_ok": latest["parity_ok"],
        "parity_total": latest["parity_total"],
        "parity_rate": latest["parity_rate"],
        "duration_s": latest["duration_s"],
        "error_taxonomy": errors,
        "prev_parity_rate": _rate(prev) if prev else None,
        "trend": trend,
        "reliable_enough": bool(
            latest["errors"] == 0
            and latest["parity_rate"] is not None
            and latest["parity_rate"] >= 0.95
        ),
    }

    out_path = LOG_DIR / f"analysis_{report['ts']}.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["analysis_file"] = str(out_path)
    return report


def human_report(r: dict) -> str:
    if not r.get("ok"):
        return f"⚠️ Analyzer: {r.get('reason')}"
    lines = [
        f"## EntropicMem Migration Report — {r['ts']}",
        "",
        f"- **Legacy facts processed:** {r['total_facts']}",
        f"- **Written to EntropicMem:** {r['written']}",
        f"- **Errors:** {r['errors']}",
        f"- **Recall parity:** {r['parity_ok']}/{r['parity_total']} "
        f"({r['parity_rate']*100:.1f}%)",
        f"- **Trend:** {r['trend']} "
        f"(prev {r['prev_parity_rate']*100:.1f}%)" if r["prev_parity_rate"] is not None
        else f"- **Trend:** {r['trend']}",
        f"- **Duration:** {r['duration_s']}s",
        "",
    ]
    if r["errors"] == 0 and r["error_taxonomy"]["counts"]:
        lines.append("**Error taxonomy (from fact-level log):**")
        for k, v in r["error_taxonomy"]["counts"].items():
            lines.append(f"  - `{k}`: {v}")
        lines.append("")
    if r["reliable_enough"]:
        lines.append("✅ **Reliable enough to consider replacing legacy tools.**")
    else:
        lines.append("⏳ **Not yet reliable** — continue tandem, fix identified errors.")
        if r["parity_rate"] is not None and r["parity_rate"] < 0.95:
            lines.append(f"   Parity {r['parity_rate']*100:.1f}% < 95% threshold.")
    return "\n".join(lines)


if __name__ == "__main__":
    rep = analyze()
    print(human_report(rep))
    print(f"\n[analysis file] {rep.get('analysis_file', 'n/a')}")
    sys.exit(0 if rep.get("ok") else 1)