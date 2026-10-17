"""EM-405, the lifecycle half: the turn index, the delegation row, shutdown.

Three §4.1 behaviours land here:

* **the turn index** — the provider keeps one counter per session, increments it
  in ``on_turn_start``, persists it to the v3 ``meta`` as ``turn_index:<sid>``
  so a restart continues the sequence, and stamps it on the writes made during
  the turn (the tool path and the facade's quarantine both carry
  ``source_turn``) — which is exactly what makes the retraction half's
  ``source_turn >= turn`` meaningful. A v2 store keeps the counter in memory
  only: nothing new reaches its schema.
* **``on_delegation``** — the parent's record of one subagent run: a redacted,
  capped ``delegation`` episode, and on a v3 store one ``extract_session`` job
  carrying ``source=extracted_llm`` with the 0.6 confidence cap (§4.1's row).
  The row flips from DEFERRED to IMPLEMENTED in the hook surface.
* **shutdown** — bounded: with a precompute in flight, the close path stops the
  service, checkpoints the WAL and closes the store without burning the join
  timeout.

Invented data only (rule 4). The live store is never touched.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
for _entry in (str(REPO), str(SCRIPTS)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from plugins.entropicmem import EntropicMemMemoryProvider  # noqa: E402

import em.provider.provider as surface  # noqa: E402
from em.facade.engine import V3_RETRIEVAL_ENV, V3Engine  # noqa: E402
from memory_engine import MemoryEngine  # noqa: E402

# --- fixtures ---------------------------------------------------------------


def _rows(db: Path, sql: str, params: tuple = ()) -> list:
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, params)]
    finally:
        conn.close()


def _meta(db: Path, key: str) -> str | None:
    rows = _rows(db, "SELECT value FROM meta WHERE key=?", (key,))
    return rows[0]["value"] if rows else None


def _v3_db(tmp_path: Path) -> Path:
    db = tmp_path / "memory.db"
    V3Engine(db).close()
    return db


def _v2_db(tmp_path: Path) -> Path:
    db = tmp_path / "memory.db"
    MemoryEngine(db, profile_id="default").close()
    return db


def _real_spawn(target, name):
    import threading

    thread = threading.Thread(target=target, name=name, daemon=True)
    thread.start()
    return thread


def _provider(
    tmp_path: Path,
    db: Path,
    *,
    session: str = "sess-em405",
    init_kwargs: dict | None = None,
    **config,
) -> EntropicMemMemoryProvider:
    provider = EntropicMemMemoryProvider(config={
        "core_memory_enabled": False,
        "touch_on_inject": False,
        **config,
    })
    provider.initialize(session, hermes_home=str(tmp_path), **(init_kwargs or {}))
    # `initialize` leaves these unset when the skill tree is not in the temp
    # home, so this points every hook at the real facade and the temp store.
    provider._scripts_dir = SCRIPTS
    provider._memory_db = db
    provider._profile_id = "default"
    provider._spawn = _real_spawn
    return provider


def _remember(provider: EntropicMemMemoryProvider, content: str) -> str:
    payload = json.loads(provider.handle_tool_call("entropicmem_remember", {"content": content}))
    assert payload.get("ok"), payload
    return payload["id"]


# --- the turn index ---------------------------------------------------------


def test_the_turn_index_increments_per_turn_and_persists(tmp_path):
    db = _v3_db(tmp_path)
    provider = _provider(tmp_path, db)
    try:
        provider.on_turn_start(1, "first question")
        assert provider._current_turn() == 1
        provider.on_turn_start(2, "second question")
        assert provider._current_turn() == 2
    finally:
        provider.shutdown()

    assert _meta(db, "turn_index:sess-em405") == "2", (
        "the counter is persisted per turn so a restart continues it"
    )


def test_the_turn_index_continues_after_a_restart(tmp_path):
    db = _v3_db(tmp_path)
    first = _provider(tmp_path, db)
    try:
        first.on_turn_start(1, "one")
        first.on_turn_start(2, "two")
    finally:
        first.shutdown()

    second = _provider(tmp_path, db)
    try:
        # a fresh provider — as after a restart — restores the sequence
        second.on_turn_start(3, "three")
        assert second._current_turn() == 3
    finally:
        second.shutdown()

    assert _meta(db, "turn_index:sess-em405") == "3"


def test_the_turn_index_is_per_session(tmp_path):
    db = _v3_db(tmp_path)
    provider = _provider(tmp_path, db)
    try:
        provider.on_turn_start(1, "one")
        provider.on_turn_start(2, "two")

        provider.on_session_switch("sess-next", reset=True, reason="new")
        assert provider._current_turn() is None, "a fresh session starts with no turn"
        provider.on_turn_start(1, "fresh session turn")
        assert _meta(db, "turn_index:sess-next") == "1"
        assert _meta(db, "turn_index:sess-em405") == "2", "the old session's counter is untouched"

        provider.on_session_switch("sess-em405", reason="resume")
        assert provider._current_turn() == 2, "resuming a session restores its position"
    finally:
        provider.shutdown()


def test_a_v2_store_counts_in_memory_without_touching_its_schema(tmp_path):
    db = _v2_db(tmp_path)
    provider = _provider(tmp_path, db)
    try:
        provider.on_turn_start(1, "one")
        provider.on_turn_start(2, "two")
        assert provider._current_turn() == 2
    finally:
        provider.shutdown()

    tables = {r["name"] for r in _rows(db, "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "meta" not in tables, "persistence is a v3 store concern; v2 gains no table"


def test_remember_stamps_the_turn_it_was_stated_in(tmp_path):
    db = _v3_db(tmp_path)
    provider = _provider(tmp_path, db)
    try:
        # The counter is the provider's own (that is why it is persisted): each
        # on_turn_start advances it by one, and the writes of that turn carry it.
        provider.on_turn_start(1, "turn one")
        provider.on_turn_start(2, "turn two")
        provider.on_turn_start(3, "turn three")
        stamped = _remember(provider, "The observatory code is CH-77")
    finally:
        provider.shutdown()

    row = _rows(db, "SELECT source_session, source_turn FROM memories WHERE id=?", (stamped,))[0]
    assert row["source_session"] == "sess-em405" and row["source_turn"] == 3

    # and a write before any turn is known is attributed to no turn
    other = _provider(tmp_path, db, session="sess-cold")
    try:
        unstamped = _remember(other, "The backup vault is called Archive 9")
    finally:
        other.shutdown()
    row = _rows(db, "SELECT source_turn FROM memories WHERE id=?", (unstamped,))[0]
    assert row["source_turn"] is None


def test_extraction_candidates_carry_the_turn(tmp_path):
    """A promoted candidate from an undone turn must be retractable too, so the
    facade stamps the draft it quarantines — not just the tool path."""
    db = _v3_db(tmp_path)
    engine = V3Engine(db)
    try:
        engine.extract_and_store(
            user_text="My kanban board is called Flow 7",
            session_id="sess-em405",
            source_turn=9,
            promote=False,
        )
    finally:
        engine.close()

    rows = _rows(
        db,
        "SELECT source_session, source_turn, status FROM memories WHERE source_session='sess-em405'",
    )
    assert len(rows) == 1, f"one regex candidate expected, got {rows!r}"
    assert rows[0]["source_turn"] == 9 and rows[0]["status"] == "pending"


# --- on_delegation ----------------------------------------------------------


def test_delegation_creates_a_redacted_capped_episode(tmp_path):
    db = _v3_db(tmp_path)
    provider = _provider(tmp_path, db)
    try:
        task = "T" * 700
        result = "email alice@example.com about the deploy window — " + "R" * 1600
        provider.on_delegation(task, result, child_session_id="child-1")
    finally:
        provider.shutdown()

    episodes = _rows(db, "SELECT * FROM episodes WHERE kind='delegation'")
    assert len(episodes) == 1
    episode = episodes[0]
    assert episode["session_id"] == "sess-em405", "the delegation belongs to the parent's session"
    assert episode["title"].startswith("Delegation")

    task_part, result_part = episode["summary"].split("\n\n", 1)
    assert task_part.startswith("Task: ") and len(task_part) - len("Task: ") <= 500
    assert "alice@example.com" not in episode["summary"], "the evidence is redacted"
    assert "[REDACTED]" in result_part
    assert result_part.startswith("Result: ") and len(result_part) - len("Result: ") <= 1500


def test_delegation_enqueues_an_extraction_job_with_the_confidence_cap(tmp_path):
    db = _v3_db(tmp_path)
    provider = _provider(tmp_path, db)
    try:
        provider.on_delegation("audit the config", "found two issues", child_session_id="child-9")
    finally:
        provider.shutdown()

    episode_id = _rows(db, "SELECT id FROM episodes WHERE kind='delegation'")[0]["id"]
    jobs = _rows(db, "SELECT type, payload, status FROM jobs WHERE type='extract_session'")
    assert len(jobs) == 1 and jobs[0]["status"] == "queued"
    payload = json.loads(jobs[0]["payload"])
    assert payload["session_id"] == "child-9"
    assert payload["episode_id"] == episode_id
    assert payload["source"] == "extracted_llm"
    assert payload["confidence_cap"] == 0.6
    # EM-502 slice 2: the job carries the effective turn scope.
    assert payload["scope"]["profile"] == "default"
    assert payload["scope"]["user"] == ""


def test_delegation_on_a_v2_store_writes_the_episode_only(tmp_path):
    db = _v2_db(tmp_path)
    provider = _provider(tmp_path, db)
    try:
        provider.on_delegation("audit the config", "found two issues", child_session_id="child-9")
    finally:
        provider.shutdown()

    assert _rows(db, "SELECT count(*) AS n FROM episodes")[0]["n"] == 1
    tables = {r["name"] for r in _rows(db, "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "jobs" not in tables, "the extraction queue is v3-only"


def test_delegation_in_a_non_primary_context_writes_nothing(tmp_path):
    db = _v3_db(tmp_path)
    provider = _provider(tmp_path, db, init_kwargs={"agent_context": "cron"})
    try:
        provider.on_delegation("audit the config", "found two issues", child_session_id="child-9")
    finally:
        provider.shutdown()

    assert _rows(db, "SELECT id FROM episodes") == []
    assert _rows(db, "SELECT id FROM jobs WHERE type='extract_session'") == []


# --- shutdown ---------------------------------------------------------------


def test_shutdown_with_a_prefetch_running_stays_within_budget(tmp_path, monkeypatch):
    """§4.1's shutdown budget, observed end to end: stop the service, checkpoint
    the WAL, close the store — from the turn thread, while the service is
    mid-precompute."""
    monkeypatch.setenv(V3_RETRIEVAL_ENV, "1")
    db = _v3_db(tmp_path)
    engine = V3Engine(db)
    for i in range(10):
        engine.remember(f"the staging cluster {i} runs on port {9000 + i}")
    engine.close()

    provider = _provider(tmp_path, db)
    service = provider._ensure_prefetch_service()
    assert service is not None
    service.queue_precompute(
        "what port does the staging cluster run on",
        session_id="sess-em405",
        scope=provider._state.scope.to_scope(),
    )

    started = time.monotonic()
    provider.shutdown()
    elapsed = time.monotonic() - started

    assert elapsed < 2.0, f"shutdown took {elapsed:.3f}s with a precompute in flight"
    assert provider._prefetch_service is None and provider._prefetch_store is None


# --- the hook surface -------------------------------------------------------


def test_the_surface_ships_on_delegation(tmp_path):
    assert "on_delegation" in surface.implemented()
    assert "on_delegation" not in surface.deferred()

    provider = _provider(tmp_path, _v3_db(tmp_path))
    try:
        problems = surface.audit(provider)
    finally:
        provider.shutdown()
    assert problems == (), "\n".join(problems)
