"""Supersession end-to-end through the provider (recorded gap, 2026-10-15).

The wired path (a v3 store + ``ENTROPICMEM_V3_RETRIEVAL=1``) feeds
``Retrieval.predecessors`` into ``load_pack_items`` and renders §3.6's
``(kind · updated <date>; was: <old>)`` note. Every piece was asserted *in
isolation* — ``MemoryStore.predecessors``, ``diversity.load_predecessors``,
``render_superseded_note``, the packer's ``was`` field — but **no test drove a
real supersession through the provider and read the served block**. EM-502
(extraction) and EM-503 (reconciliation) are the producers of supersessions, so
this is the surface their output is checked against; this card lands first.

Two things are pinned: the successor is served with the ``was:`` note quoting the
superseded row, and the superseded value appears only inside that note — never as
a live bullet.

Invented data only (rule 4). The live store is never touched.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
for _entry in (str(REPO), str(SCRIPTS)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from plugins.entropicmem import EntropicMemMemoryProvider  # noqa: E402

from em.facade.engine import V3_RETRIEVAL_ENV, V3Engine  # noqa: E402
from em.store.db import Store  # noqa: E402

STAMP = "2026-01-15T00:00:00Z"
QUERY = "what port does the staging server use"
OLD = "the staging server runs on port 9090"
NEW = "the staging server now runs on port 7070"
UNRELATED = "the nightly billing job reconciles invoices"


def _v3_db(tmp_path: Path) -> Path:
    """A migrated v3 store with the fact to supersede and one unrelated fact."""
    db = tmp_path / "memory.db"
    engine = V3Engine(db)
    engine.remember(OLD, domain="Infrastructure", importance=0.8)
    engine.remember(UNRELATED, domain="Knowledge", importance=0.5)
    engine.close()
    store = Store(str(db))
    try:
        with store.transaction() as conn:
            conn.execute(
                "UPDATE memories SET created_at=?, updated_at=?, last_accessed_at=NULL",
                (STAMP, STAMP),
            )
    finally:
        store.close()
    return db


def _active_memory_id(db: Path, content: str) -> str:
    conn = sqlite3.connect(str(db))
    try:
        row = conn.execute(
            "SELECT id FROM memories WHERE content=? AND status='active'", (content,)
        ).fetchone()
    finally:
        conn.close()
    assert row is not None, f"no active memory with content {content!r}"
    return str(row[0])


def _real_spawn(target, name):
    # The service captures the provider's ``_spawn`` seam when it is built; under
    # pytest the mocked host factory would serve empty blocks, so install a real
    # one first (the same reason the EM-403 slice-3 wiring harness does).
    import threading

    thread = threading.Thread(target=target, name=name, daemon=True)
    thread.start()
    return thread


def _provider(tmp_path: Path, db: Path, **config) -> EntropicMemMemoryProvider:
    provider = EntropicMemMemoryProvider(
        config={"core_memory_enabled": False, "touch_on_inject": False, **config}
    )
    provider.initialize("supersession-session", hermes_home=str(tmp_path), agent_identity="default")
    provider._scripts_dir = SCRIPTS
    provider._memory_db = db
    provider._profile_id = "default"
    provider._spawn = _real_spawn
    return provider


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    monkeypatch.setenv(V3_RETRIEVAL_ENV, "1")


def test_a_supersession_is_served_with_the_was_note_end_to_end(tmp_path):
    db = _v3_db(tmp_path)
    old_id = _active_memory_id(db, OLD)
    provider = _provider(tmp_path, db)
    try:
        # 1. the SUPERSEDE decision, through the tool the agent actually calls
        result = json.loads(
            provider.handle_tool_call(
                "entropicmem_update",
                {"id": old_id, "content": NEW, "mode": "supersede"},
            )
        )
        assert result["ok"] is True, result
        assert result["decision"] == "superseded", result

        # 2. the served block
        block = provider.prefetch(QUERY)
    finally:
        provider.shutdown()

    assert NEW in block, f"the successor must be served; got {block!r}"
    assert f"was: {OLD}" in block, f"the note must quote the superseded row; got {block!r}"

    # the superseded value lives only inside the note, never as a live bullet
    old_lines = [ln for ln in block.splitlines() if OLD in ln]
    assert old_lines, f"the note must actually name the old value; got {block!r}"
    assert all("was:" in ln for ln in old_lines), (
        f"the superseded value must appear only in the `was:` note; got {old_lines!r}"
    )


def test_without_a_supersession_the_block_carries_no_note(tmp_path):
    """The control: the note is the supersession's, not an artefact of rendering."""
    db = _v3_db(tmp_path)
    provider = _provider(tmp_path, db)
    try:
        block = provider.prefetch(QUERY)
    finally:
        provider.shutdown()
    assert OLD in block, f"the fact must be served on its own; got {block!r}"
    assert "was:" not in block
