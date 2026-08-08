#!/usr/bin/env python3
"""
entropicmem_episodic_capture.py — 12h episodic-memory capture (v2.2.0 G1).

Reads recent Hermes sessions from the local LCM message store (lcm.db),
distills each session into ONE condensed episodic record ("what happened and
why it matters"), and writes it to the EntropicMem `episodes` table.

Deterministic (no LLM): title = first user message (truncated), summary =
first user message + last assistant reply (truncated), window = first/last
message timestamps. Idempotent: sessions already captured (by source_session)
are skipped, so re-runs and overlapping 12h windows never duplicate.

Cron pattern: no_agent, every 12h, silent when nothing new, prints a one-line
summary when episodes were written (delivered verbatim).

Exit codes: 0 ok, 1 error.
"""

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
STATE_DB = HERMES_HOME / "state.db"   # live session store (sessions + messages)
LCM_DB = HERMES_HOME / "lcm.db"        # legacy message store (fallback)
MEMORY_DB = HERMES_HOME / "entropicmem" / "memory.db"
SCRIPTS_DIR = HERMES_HOME / "skills" / "entropicmem" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from memory_engine import MemoryEngine  # noqa: E402

TITLE_MAX = 90
SUMMARY_MAX = 600
DEFAULT_WINDOW_HOURS = 13  # slightly more than the 12h cron cadence


def distill(session_id: str, rows: list) -> dict | None:
    """Build one episode dict from a session's messages. None if unusable."""
    # Skip cron-run sessions: their first user message is system boilerplate,
    # not a human "what happened" record. Interactive sessions are the
    # episodic signal worth keeping.
    if session_id.startswith("cron_"):
        return None
    user_msgs = [r for r in rows if r["role"] == "user"]
    assistant_msgs = [r for r in rows if r["role"] == "assistant"]
    if not user_msgs:
        return None
    first = user_msgs[0]
    raw_title = (first["content"] or "").strip().replace("\n", " ")
    # Drop leading system-ish noise from the title (model-change notes etc.)
    # BEFORE truncation — the closing bracket can sit past TITLE_MAX or be
    # absent entirely in the stored message.
    for prefix in ("[System:", "[IMPORTANT:", "[CONTEXT"):
        if raw_title.startswith(prefix):
            if "] " in raw_title:
                raw_title = raw_title.split("] ", 1)[-1]
            else:
                raw_title = raw_title[len(prefix):].lstrip(" ]")
            break
    title = raw_title[:TITLE_MAX]
    if not title:
        return None
    last_user = user_msgs[-1]["content"] or ""
    last_assistant = (assistant_msgs[-1]["content"] if assistant_msgs else "") or ""
    summary = f"Session {session_id}. Started: {title}. "
    if last_user:
        summary += f"Last request: {last_user[:200].strip()}. "
    if last_assistant:
        summary += f"Outcome: {last_assistant[:280].strip()}"
    summary = summary[:SUMMARY_MAX]
    ts = [r["timestamp"] for r in rows if r.get("timestamp")]
    start_ts = None
    end_ts = None
    if ts:
        start_ts = __import__("datetime").datetime.fromtimestamp(min(ts), __import__("datetime").timezone.utc).isoformat()
        end_ts = __import__("datetime").datetime.fromtimestamp(max(ts), __import__("datetime").timezone.utc).isoformat()
    return {
        "session_id": session_id,
        "title": title,
        "summary": summary,
        "start_ts": start_ts,
        "end_ts": end_ts,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--hours", type=float, default=DEFAULT_WINDOW_HOURS,
                    help="Look back window in hours (default: 13)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print what would be captured without writing")
    args = ap.parse_args()

    if not STATE_DB.exists() and not LCM_DB.exists():
        print(f"episodic-capture: no session store found ({STATE_DB} / {LCM_DB})", file=sys.stderr)
        return 1

    cutoff = __import__("time").time() - args.hours * 3600

    engine = MemoryEngine(str(MEMORY_DB))
    try:
        existing = {
            r["source_session"]
            for r in engine.db.execute(
                "SELECT source_session FROM episodes WHERE source_session != ''"
            ).fetchall()
        }

        # Prefer the live state.db store; fall back to the legacy lcm.db.
        db_path = STATE_DB if STATE_DB.exists() else LCM_DB
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT session_id, role, content, timestamp FROM messages "
            "WHERE timestamp >= ? AND role IN ('user', 'assistant') "
            "ORDER BY id ASC",
            (cutoff,),
        ).fetchall()
        conn.close()

        by_session: dict = {}
        for r in rows:
            m = dict(r)
            by_session.setdefault(m["session_id"], []).append(m)

        written = 0
        for session_id, msgs in by_session.items():
            if session_id in existing:
                continue
            episode = distill(session_id, msgs)
            if episode is None:
                continue
            if args.dry_run:
                print(f"  would capture: {episode['title'][:60]}")
                continue
            engine.add_episode(
                title=episode["title"],
                summary=episode["summary"],
                start_ts=episode["start_ts"],
                end_ts=episode["end_ts"],
                source_session=session_id,
                importance=0.6,
                domain="Knowledge",
                source="episodic_capture",
            )
            written += 1

        if written:
            print(f"episodic-capture: {written} new episode(s) from {len(by_session)} session(s)")
        # silent when nothing new — no_agent cron pattern
        return 0
    finally:
        engine.close()


if __name__ == "__main__":
    sys.exit(main())
