"""P1 Slice 2 lifecycle hook tests.

Covers the plugin hooks built on the extractive digest helper:
  A1  on_session_end      -> one idempotent episode per session
  A5  on_turn_start       -> turn-cadence partial flush (always-on sessions)
  A2  on_pre_compress     -> constraint string + persisted episode
  C1  session-end regex extraction -> pending/quarantine only

Fake provider against a temp memory DB; real engine + real digest helper.
"""

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # so `from plugins.entropicmem import ...` resolves

from plugins.entropicmem import EntropicMemMemoryProvider  # noqa: E402

import session_digest  # noqa: E402
from memory_engine import MemoryEngine  # noqa: E402

MESSAGES = [
    {"role": "user", "content": "Please fix the session digest flush in the plugin."},
    {"role": "assistant", "content": "I will wire on_session_end into the digest."},
    {"role": "user", "content": "Remember: never use the work email for personal accounts."},
    {"role": "assistant", "content": "Noted, work email stays work-only."},
    {"role": "user", "content": "I prefer dark mode in my editor."},
]


def _make_provider(tmp_path, **config):
    prov = EntropicMemMemoryProvider(config={
        "vault_path": str(tmp_path / "vault"),
        "index_db": str(tmp_path / "index.db"),
        "memory_db": str(tmp_path / "memory.db"),
        **config,
    })
    prov._scripts_dir = ROOT / "plugins" / "entropicmem" / "scripts"
    prov._hermes_home = tmp_path
    prov._vault_path = tmp_path / "vault"
    prov._memory_db = tmp_path / "memory.db"
    prov._session_id = "sess-test-1"
    return prov


def _episodes(tmp_path, session_id="sess-test-1"):
    with MemoryEngine(tmp_path / "memory.db") as engine:
        return engine.db.execute(
            "SELECT episode_id, title, summary, source FROM episodes WHERE source_session = ?",
            (session_id,),
        ).fetchall()


def _pending_count(tmp_path):
    with MemoryEngine(tmp_path / "memory.db") as engine:
        return engine.db.execute("SELECT COUNT(*) FROM pending_facts").fetchone()[0]


def _fact_count(tmp_path):
    with MemoryEngine(tmp_path / "memory.db") as engine:
        return engine.db.execute("SELECT COUNT(*) FROM facts").fetchone()[0]


# ── A1: on_session_end ───────────────────────────────────────────────────────


def test_on_session_end_writes_one_idempotent_episode(tmp_path):
    prov = _make_provider(tmp_path)
    prov.on_session_end(MESSAGES)
    rows = _episodes(tmp_path)
    assert len(rows) == 1
    episode_id, title, summary, source = rows[0]
    assert episode_id == "ep_sess_sess-test-1"
    assert title.startswith("Please fix the session digest flush")
    assert "work email" in summary
    assert source == "session_end"

    prov.on_session_end(MESSAGES)  # re-fire must replace, not duplicate
    assert len(_episodes(tmp_path)) == 1


def test_episode_is_recallable(tmp_path):
    prov = _make_provider(tmp_path)
    prov.on_session_end(MESSAGES)
    with MemoryEngine(tmp_path / "memory.db") as engine:
        hits = engine.recall_episodes("work email")
    assert hits and hits[0]["episode_id"] == "ep_sess_sess-test-1"


def test_on_session_end_is_fail_soft(tmp_path, monkeypatch):
    prov = _make_provider(tmp_path)

    def _boom(*args, **kwargs):
        raise RuntimeError("digest exploded")

    monkeypatch.setattr(session_digest, "extractive_digest", _boom)
    prov.on_session_end(MESSAGES)  # must not raise
    assert _episodes(tmp_path) == []


def test_session_end_capture_flag_disables(tmp_path):
    prov = _make_provider(tmp_path, session_end_capture=False)
    prov.on_session_end(MESSAGES)
    assert _episodes(tmp_path) == []


# ── C1: session-end extraction lands in pending only ─────────────────────────


def test_session_end_extract_lands_in_pending_only(tmp_path):
    prov = _make_provider(tmp_path)
    facts_before = _fact_count(tmp_path)
    prov.on_session_end(MESSAGES)
    pending_after_first = _pending_count(tmp_path)
    assert pending_after_first >= 1
    assert _fact_count(tmp_path) == facts_before  # nothing auto-promoted

    prov.on_session_end(MESSAGES)  # idempotent, no double-insert
    assert _pending_count(tmp_path) == pending_after_first


def test_session_end_extract_flag_disables(tmp_path):
    prov = _make_provider(tmp_path, session_extract_pending=False)
    prov.on_session_end(MESSAGES)
    assert _pending_count(tmp_path) == 0


# ── A5: turn-cadence flush ───────────────────────────────────────────────────


def test_turn_cadence_flush(tmp_path):
    prov = _make_provider(tmp_path, turn_cadence_flush_turns=2, turn_cadence_min_interval_sec=0)
    prov.sync_turn("hello there", "hi, how can I help?", session_id="sess-test-1")
    prov.on_turn_start(1, "hello there")  # not a cadence turn
    assert _episodes(tmp_path) == []
    prov.on_turn_start(2, "hello there")  # cadence turn -> partial digest
    rows = _episodes(tmp_path)
    assert len(rows) == 1 and rows[0][3] == "cadence"


def test_turn_cadence_disabled_by_zero(tmp_path):
    prov = _make_provider(tmp_path, turn_cadence_flush_turns=0)
    prov.sync_turn("hello", "hi", session_id="sess-test-1")
    prov.on_turn_start(40, "hello")
    assert _episodes(tmp_path) == []


def test_turn_cadence_min_interval_gate(tmp_path):
    prov = _make_provider(tmp_path, turn_cadence_flush_turns=1, turn_cadence_min_interval_sec=1800)
    prov.sync_turn("hello", "hi", session_id="sess-test-1")
    prov._last_cadence_flush = time.time()  # just flushed
    prov.on_turn_start(1, "tick")
    assert _episodes(tmp_path) == []  # gated by min interval
    prov._last_cadence_flush = 0.0
    prov.on_turn_start(1, "tick")
    assert len(_episodes(tmp_path)) == 1


# ── A2: on_pre_compress ──────────────────────────────────────────────────────


def test_pre_compress_returns_constraints_and_persists(tmp_path):
    prov = _make_provider(tmp_path)
    out = prov.on_pre_compress(MESSAGES)
    assert isinstance(out, str) and "work email" in out
    rows = _episodes(tmp_path)
    assert len(rows) == 1
    assert rows[0][0] == "ep_precomp_sess-test-1"
    assert rows[0][3] == "pre_compress"
    with MemoryEngine(tmp_path / "memory.db") as engine:
        hits = engine.recall_episodes("work email")
    assert hits and hits[0]["episode_id"] == "ep_precomp_sess-test-1"

    prov.on_pre_compress(MESSAGES)  # idempotent per session
    assert len(_episodes(tmp_path)) == 1


def test_pre_compress_empty_when_nothing_salient(tmp_path):
    prov = _make_provider(tmp_path)
    out = prov.on_pre_compress([{"role": "user", "content": "What time is the meeting?"}])
    assert out == ""
    assert _episodes(tmp_path) == []


def test_pre_compress_fails_closed_on_extraction_error(tmp_path, monkeypatch):
    """Checkpoint API v2 fail-closed: an extraction failure must propagate
    instead of silently returning uncheckpointed text (with
    ``require_checkpoint=True`` the host then keeps the uncompressed
    transcript)."""
    prov = _make_provider(tmp_path)

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(session_digest, "extract_constraints", _boom)
    with pytest.raises(RuntimeError):
        prov.on_pre_compress(MESSAGES)
    assert _episodes(tmp_path) == []
