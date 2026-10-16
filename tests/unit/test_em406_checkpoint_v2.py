"""EM-406 — checkpoint v2: the evidence archive and the deterministic handoff.

The card's contract, provider-side (adapted from hermes'
``tests/agent/test_pre_compress_checkpoint_contract.py``):

* **evidence arrives as the positional ``messages`` list** and every
  user/assistant message is archived into ``transcript_chunks`` under
  ``source='precompress'`` in one transaction — list content flattened by the
  shared EM-101 normaliser, tool-call-stripped assistant rows keeping their
  prose, rows with no prose producing no chunk. The host's own normaliser has
  already dropped tool/system rows before this hook runs; the provider's role
  filter is the defence-in-depth half, and these tests drive the provider
  directly with the raw shape to pin it.
* **one episode per compression**: the handoff episode is keyed by the
  evidence fingerprint, so a retried compression converges onto its window
  while new evidence opens the next one; retried chunk upserts insert
  nothing (content-addressed digests).
* **fail-closed, fail-soft**: an injected ``upsert_chunks`` failure raises
  under ``require_checkpoint=True`` and otherwise logs and returns "" —
  never a silent "".
* **v2 stores are unchanged**: no ``transcript_chunks`` exists there, so the
  checkpoint stays the A2 constraints episode, byte-for-byte.

Invented data only (rule 4). The live store is never touched.
"""

from __future__ import annotations

import logging
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

from em.facade.engine import V3Engine  # noqa: E402
from em.store.db import Store  # noqa: E402
from em.store.episodes import EpisodeStore  # noqa: E402
from em.store.memories import MemoryStore  # noqa: E402
from em.store.types import MemoryDraft, Scope  # noqa: E402
from memory_engine import MemoryEngine  # noqa: E402
from session_digest import (  # noqa: E402
    extract_constraints,
    handoff_fingerprint,
)

SESSION = "sess-em406"

#: A raw-shaped transcript: the system row and tool rows are never evidence,
#: the list content must be flattened, the prose-bearing tool-call row keeps
#: its prose, and the tool-calls-only row carries no prose and so no chunk.
MESSAGES = [
    {"role": "system", "content": "you are a helpful agent"},
    {"role": "user", "content": "Please always stage on the blue host from now on."},
    {"role": "assistant", "content": "I ran the staging scan.", "tool_calls": [{"id": "c1"}]},
    {
        "role": "assistant",
        "content": [
            {"type": "text", "text": "scanning"},
            {"type": "text", "text": "the logs"},
        ],
    },
    {"role": "assistant", "content": "", "tool_calls": [{"id": "c2"}]},
    {"role": "tool", "content": "tool output noise"},
    {"role": "user", "content": "TODO: rotate the staging keys next week."},
]


def _evidence(messages: list) -> list:
    """The provider's own filter, restated so fingerprints can be recomputed."""
    return [
        m for m in messages if isinstance(m, dict) and m.get("role") in ("user", "assistant")
    ]


# --- fixtures ---------------------------------------------------------------


def _rows(db: Path, sql: str, params: tuple = ()) -> list:
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, params)]
    finally:
        conn.close()


def _chunks(db: Path, session: str = SESSION) -> list:
    return _rows(
        db,
        "SELECT seq, role, text, source FROM transcript_chunks"
        " WHERE session_id=? ORDER BY seq",
        (session,),
    )


def _episodes(db: Path, kind: str = "precompress") -> list:
    return _rows(
        db,
        "SELECT id, kind, window_seq, session_id, legacy_id, summary FROM episodes"
        " WHERE kind=? ORDER BY window_seq",
        (kind,),
    )


def _v3_db(tmp_path: Path) -> Path:
    db = tmp_path / "memory.db"
    V3Engine(db).close()
    return db


def _v2_db(tmp_path: Path) -> Path:
    db = tmp_path / "memory.db"
    MemoryEngine(db, profile_id="default").close()
    return db


def _provider(tmp_path: Path, db: Path, *, init_kwargs: dict | None = None) -> EntropicMemMemoryProvider:
    provider = EntropicMemMemoryProvider(config={"core_memory_enabled": False, "touch_on_inject": False})
    provider.initialize(SESSION, hermes_home=str(tmp_path), **(init_kwargs or {}))
    provider._scripts_dir = SCRIPTS
    provider._memory_db = db
    provider._profile_id = "default"
    return provider


# --- the v3 checkpoint ------------------------------------------------------


def test_the_provider_advertises_checkpoint_api_v2():
    assert EntropicMemMemoryProvider.pre_compress_checkpoint_api_version == 2


def test_v3_checkpoint_archives_the_evidence_and_returns_the_handoff(tmp_path):
    db = _v3_db(tmp_path)
    provider = _provider(tmp_path, db)
    try:
        handoff = provider.on_pre_compress(MESSAGES)
    finally:
        provider.shutdown()

    assert "blue host" in handoff
    assert "TODO: rotate the staging keys next week." in handoff

    rows = _chunks(db)
    assert [r["role"] for r in rows] == ["user", "assistant", "assistant", "user"]
    assert [r["seq"] for r in rows] == [0, 1, 2, 4], (
        "seqs follow the filtered evidence; the no-prose row is skipped, not stored empty"
    )
    assert rows[2]["text"] == "scanning the logs", "list content is flattened by the EM-101 normaliser"
    assert rows[1]["text"] == "I ran the staging scan.", "prose survives the tool_calls payload"
    assert all(r["source"] == "precompress" for r in rows)

    eps = _episodes(db)
    assert len(eps) == 1, "one episode per compression"
    assert eps[0]["window_seq"] == 0
    assert eps[0]["session_id"] == SESSION
    assert eps[0]["legacy_id"] == f"ep_precomp_{SESSION}_{handoff_fingerprint(_evidence(MESSAGES))}"
    assert "blue host" in eps[0]["summary"]


def test_a_retry_converges_and_each_compression_gets_one_window(tmp_path):
    db = _v3_db(tmp_path)
    provider = _provider(tmp_path, db)
    try:
        first = MESSAGES[1:]
        handoff = provider.on_pre_compress(first)
        chunks_after_first = len(_chunks(db))

        # A re-fired compression of the same evidence: identical chunk counts,
        # and the fingerprint key converges onto the same single window.
        assert provider.on_pre_compress(first) == handoff
        assert len(_chunks(db)) == chunks_after_first, "retried upserts insert nothing"
        assert len(_episodes(db)) == 1, "one episode per compression, not one per call"

        # The next compression overlaps this one: the shared prefix inserts
        # nothing and the new message opens window 1.
        second = first + [{"role": "user", "content": "Remind me to update the runbook too."}]
        handoff2 = provider.on_pre_compress(second)
    finally:
        provider.shutdown()

    assert "Remind me to update the runbook" in handoff2
    assert len(_chunks(db)) == chunks_after_first + 1, "the overlap is not re-inserted"
    eps = _episodes(db)
    assert [e["window_seq"] for e in eps] == [0, 1]
    assert len({e["legacy_id"] for e in eps}) == 2


def test_nothing_salient_still_archives_evidence(tmp_path):
    db = _v3_db(tmp_path)
    provider = _provider(tmp_path, db)
    try:
        handoff = provider.on_pre_compress(
            [
                {"role": "user", "content": "ok"},
                {"role": "assistant", "content": "sure"},
            ]
        )
    finally:
        provider.shutdown()

    assert handoff == ""
    assert len(_chunks(db)) == 2, "evidence is persisted even when the handoff is empty"
    assert _episodes(db) == [], "no salient content, no episode"


def test_nothing_at_all_is_a_clean_no_write(tmp_path):
    db = _v3_db(tmp_path)
    provider = _provider(tmp_path, db)
    try:
        assert provider.on_pre_compress([]) == ""
    finally:
        provider.shutdown()
    assert _chunks(db) == []
    assert _episodes(db) == []


def test_upsert_chunks_failure_raises_under_require_and_returns_empty_otherwise(
    tmp_path, monkeypatch, caplog
):
    db = _v3_db(tmp_path)
    provider = _provider(tmp_path, db)

    def boom(self, *args, **kwargs):
        raise RuntimeError("injected chunk failure")

    monkeypatch.setattr(EpisodeStore, "upsert_chunks", boom)
    try:
        with pytest.raises(RuntimeError, match="injected chunk failure"):
            provider.on_pre_compress(MESSAGES, require_checkpoint=True)
        with caplog.at_level(logging.DEBUG):
            assert provider.on_pre_compress(MESSAGES) == ""
    finally:
        provider.shutdown()

    assert "pre-compress checkpoint failed" in caplog.text, "the best-effort failure is logged, not silent"
    assert _chunks(db) == [] and _episodes(db) == [], (
        "the chunks and the episode share one transaction — nothing half-writes"
    )


def test_non_primary_context_skips_the_checkpoint(tmp_path):
    db = _v3_db(tmp_path)
    provider = _provider(tmp_path, db, init_kwargs={"agent_context": "subagent"})
    try:
        assert provider.on_pre_compress(MESSAGES) == ""
        with pytest.raises(RuntimeError, match="agent_context"):
            provider.on_pre_compress(MESSAGES, require_checkpoint=True)
    finally:
        provider.shutdown()
    assert _chunks(db) == [] and _episodes(db) == []


def test_pinned_constraints_reach_the_handoff_in_scope_only(tmp_path):
    db = _v3_db(tmp_path)
    provider = _provider(tmp_path, db)
    try:
        # The engine the hook opens reads under the provider's profile id
        # (``default`` here), profile-wide; the row must live in THAT scope.
        mine = Scope(profile="default")
        theirs = Scope(profile="default", user="someone-else")
        with Store(str(db)).transaction() as conn:
            store = MemoryStore(conn)
            store.add(
                MemoryDraft(
                    content="The backup server is 10.0.0.9. Always restore from it.",
                    pinned=True,
                ),
                scope=mine,
                actor="tester",
            )
            store.add(
                MemoryDraft(
                    content="Someone else's private pin, never shared.",
                    pinned=True,
                ),
                scope=theirs,
                actor="tester",
            )
        handoff = provider.on_pre_compress([{"role": "user", "content": "plain note"}])
    finally:
        provider.shutdown()

    assert "The backup server is 10.0.0.9." in handoff
    assert "Pinned:" in handoff
    assert "Someone else's private pin" not in handoff, "the §3.5 scope rule holds for the handoff"
    eps = _episodes(db)
    assert len(eps) == 1 and "backup server" in eps[0]["summary"]


def test_v2_stubs_raise_so_a_mis_route_cannot_drop_evidence(tmp_path):
    db = _v2_db(tmp_path)
    engine = MemoryEngine(db, profile_id="default")
    try:
        with pytest.raises(RuntimeError, match="v3 store"):
            engine.pinned_constraints()
        with pytest.raises(RuntimeError, match="v3 store"):
            engine.archive_pre_compress([], session_id=SESSION, title="t")
    finally:
        engine.close()


# --- the v2 store stays byte-identical to A2 --------------------------------


def test_v2_store_keeps_the_constraints_checkpoint(tmp_path):
    db = _v2_db(tmp_path)
    provider = _provider(tmp_path, db)
    try:
        handoff = provider.on_pre_compress(MESSAGES)
    finally:
        provider.shutdown()

    assert handoff == extract_constraints(MESSAGES), (
        "the v2 path is unchanged since A2 — constraints only, no decisions/loops/pins"
    )
    eps = _rows(db, "SELECT episode_id, summary, source FROM episodes")
    assert [e["episode_id"] for e in eps] == [f"ep_precomp_{SESSION}"]
    assert eps[0]["summary"] == handoff
    assert eps[0]["source"] == "pre_compress"


# --- the handoff itself (deterministic extraction, no LLM) ------------------


def test_handoff_is_grouped_deduped_and_bounded():
    from session_digest import build_handoff

    grouped = build_handoff(
        [
            {"role": "user", "content": "Always keep the staging host blue."},
            {"role": "assistant", "content": "We decided to pin the staging image."},
            {"role": "user", "content": "TODO: rotate the staging keys."},
        ],
        pinned=["The backup server is 10.0.0.9."],
    )
    assert grouped.splitlines() == [
        "Constraints:",
        "- Always keep the staging host blue.",
        "Decisions:",
        "- We decided to pin the staging image.",
        "Open loops:",
        "- TODO: rotate the staging keys.",
        "Pinned:",
        "- The backup server is 10.0.0.9.",
    ]

    deduped = build_handoff(
        [
            {"role": "user", "content": "Always use UTC windows."},
            {"role": "assistant", "content": "always use UTC windows."},
        ]
    )
    assert deduped.lower().count("always use utc windows") == 1

    bounded = build_handoff(
        [
            {
                "role": "user",
                "content": " ".join(f"Always keep rule number {i} in force." for i in range(60)),
            }
        ]
    )
    assert len(bounded) <= 1500, "§4.6's bound holds"
    assert bounded.count("\n- ") + 1 < 60, "the bound trims from the tail"

    assert build_handoff([{"role": "user", "content": "nothing salient here"}]) == ""


def test_handoff_fingerprint_is_deterministic_and_evidence_keyed():
    one = [{"role": "user", "content": "same evidence"}]
    two = [{"role": "system", "content": "ignored"}, *one]
    assert handoff_fingerprint(one) == handoff_fingerprint(two)
    assert handoff_fingerprint(one) != handoff_fingerprint(
        [{"role": "user", "content": "different evidence"}]
    )

