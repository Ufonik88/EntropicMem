"""S5 exit criterion — the system learns from a conversation with no ``remember``.

The whole deterministic chain, end to end and with no LLM configured:

1. a v3 store with capture on (``formation.mode``), one synced turn → its text
   is appended to ``transcript_chunks``;
2. ``on_turn_start`` seals the window and enqueues ``extract_window``;
3. the worker runs extraction (quarantine `pending`) and the ``reconcile`` pass
   it enqueues (the confident preference auto-commits);
4. a *second session* prefetches a question about it and the learned preference
   is served — with no explicit ``entropicmem_remember`` call anywhere.

The rule path does all of it (``formation.llm`` stays at its default and no
backend answers), which is the card's "LLM-assisted, never LLM-dependent" claim.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
for _entry in (str(REPO), str(SCRIPTS)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from plugins.entropicmem import EntropicMemMemoryProvider  # noqa: E402

from em.facade.engine import V3_RETRIEVAL_ENV, V3Engine  # noqa: E402
from em.jobs.registry import build_registry  # noqa: E402
from em.jobs.worker import JobWorker  # noqa: E402
from em.store.db import Store  # noqa: E402

SESSION1 = "s5-learning-1"
SESSION2 = "s5-learning-2"
PREFERENCE = "I prefer dark roast coffee in the morning."
QUERY = "what coffee do I prefer in the morning"


def _rows(db: Path, sql: str) -> list:
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in conn.execute(sql)]
    finally:
        conn.close()


def _real_spawn(target, name):
    import threading

    thread = threading.Thread(target=target, name=name, daemon=True)
    thread.start()
    return thread


def _provider(tmp_path: Path, db: Path, session: str, **config) -> EntropicMemMemoryProvider:
    provider = EntropicMemMemoryProvider(config={
        "core_memory_enabled": False,
        "touch_on_inject": False,
        "auto_extract_enabled": False,  # isolate the S5 path from the legacy regex extractor
        "jobs.run_in_primary": False,   # the test drives the worker explicitly
        "jobs.run_in_cron": False,
        **config,
    })
    provider.initialize(session, hermes_home=str(tmp_path))
    provider._scripts_dir = SCRIPTS
    provider._memory_db = db
    provider._profile_id = "default"
    provider._spawn = _real_spawn
    return provider


def test_a_preference_learned_in_session_one_is_served_in_session_two(tmp_path, monkeypatch):
    monkeypatch.setenv(V3_RETRIEVAL_ENV, "1")
    db = tmp_path / "memory.db"
    V3Engine(db).close()

    first = _provider(
        tmp_path,
        db,
        SESSION1,
        **{"formation.mode": "realtime", "turn_cadence_flush_turns": 1},
    )
    try:
        first.sync_turn(PREFERENCE, "Noted — dark roast it is.")
        first.on_turn_start(1, "next question")  # cadence seal (turn 1 of 1)
    finally:
        first.shutdown()

    store = Store(str(db))
    try:
        outcomes = JobWorker(store, build_registry(str(db))).run_until_idle()
    finally:
        store.close()

    types = [outcome.type for outcome in outcomes]
    assert "extract_window" in types, types
    assert "reconcile" in types, types

    rows = _rows(db, "SELECT content, status FROM memories")
    assert any("dark roast" in row["content"] and row["status"] == "active" for row in rows), rows
    assert not any(row["status"] == "pending" for row in rows), rows

    second = _provider(tmp_path, db, SESSION2)
    try:
        block = second.prefetch(QUERY)
    finally:
        second.shutdown()

    assert "dark roast" in block, block


def test_sync_turn_appends_the_turns_to_the_transcript(tmp_path):
    """§4.1: the turn's text reaches ``transcript_chunks`` with the window's seqs."""
    db = tmp_path / "memory.db"
    V3Engine(db).close()
    provider = _provider(tmp_path, db, "s5-chunks", **{"formation.mode": "realtime"})
    try:
        provider.sync_turn("I prefer dark roast coffee.", "Noted.")
    finally:
        provider.shutdown()

    chunks = _rows(db, "SELECT seq, role, text, source FROM transcript_chunks ORDER BY seq")
    assert [(c["seq"], c["role"]) for c in chunks] == [(1, "user"), (2, "assistant")]
    assert "dark roast" in chunks[0]["text"]
    assert all(c["source"] == "sync_turn" for c in chunks)
