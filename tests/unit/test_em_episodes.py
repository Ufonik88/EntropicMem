"""EM-207: episodes and transcript chunks."""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from em.clock import to_iso, utc_now  # noqa: E402
from em.store.db import Store  # noqa: E402
from em.store.episodes import (  # noqa: E402
    DEFAULT_RETENTION_DAYS,
    EpisodeStore,
    chunk_digest,
    normalise_text,
)
from em.store.migrations import migrate  # noqa: E402
from em.store.types import Scope  # noqa: E402

OWNER = Scope(profile="default", user="")


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path / "memory.db"))
    with s.writer() as conn:
        migrate(conn)
    yield s
    s.close()


@pytest.fixture
def ep(store):
    with store.writer() as conn:
        return EpisodeStore(conn)


def msgs(*texts):
    return [{"role": "user" if i % 2 == 0 else "assistant", "text": t} for i, t in enumerate(texts)]


# --- normalise -----------------------------------------------------------


def test_message_text_flattens_the_supported_shapes():
    assert normalise_text("plain") == "plain"
    assert normalise_text({"text": "hi"}) == "hi"
    assert normalise_text({"content": [{"type": "text", "text": "nested"}]}) == "nested"
    assert normalise_text(None) == ""
    assert normalise_text({"no_text_here": 1}) == ""


def test_normalise_strips_surrounding_whitespace():
    assert normalise_text({"text": "  padded  "}) == "padded"


# --- AC: retries produce zero new rows -----------------------------------


def test_upsert_chunks_inserts_then_is_idempotent(ep):
    messages = msgs("first message", "second message")
    assert ep.upsert_chunks("sess-1", messages, "gateway") == 2
    assert ep.upsert_chunks("sess-1", messages, "gateway") == 0, "a retry must insert nothing"
    assert ep.upsert_chunks("sess-1", messages, "gateway") == 0
    assert ep.chunk_count("sess-1") == 2


def test_retry_with_extra_messages_only_adds_the_new_ones(ep):
    ep.upsert_chunks("sess-1", msgs("one", "two"), "gateway")
    added = ep.upsert_chunks("sess-1", msgs("one", "two", "three"), "gateway")
    assert added == 1
    assert ep.chunk_count("sess-1") == 3


def test_same_text_at_different_positions_is_two_chunks(ep):
    """seq is part of the digest, so a repeated sentence is not collapsed."""
    ep.upsert_chunks("sess-1", msgs("same", "same"), "gateway")
    assert ep.chunk_count("sess-1") == 2


def test_same_text_in_different_sessions_is_two_chunks(ep):
    ep.upsert_chunks("sess-1", msgs("same"), "gateway")
    ep.upsert_chunks("sess-2", msgs("same"), "gateway")
    assert ep.chunk_count("sess-1") == 1 and ep.chunk_count("sess-2") == 1


def test_empty_messages_are_skipped(ep):
    assert ep.upsert_chunks("sess-1", [None, {"nothing": 1}, {"text": "  "}], "gateway") == 0


def test_seq_is_the_position_in_the_batch(ep):
    ep.upsert_chunks("sess-1", msgs("a", "b", "c"), "gateway")
    seqs = [r["seq"] for r in ep._conn.execute(
        "SELECT seq FROM transcript_chunks WHERE session_id='sess-1' ORDER BY seq")]
    assert seqs == [0, 1, 2]


def test_start_seq_offsets_the_batch(ep):
    ep.upsert_chunks("sess-1", msgs("a", "b"), "gateway", start_seq=10)
    seqs = [r["seq"] for r in ep._conn.execute(
        "SELECT seq FROM transcript_chunks WHERE session_id='sess-1' ORDER BY seq")]
    assert seqs == [10, 11]


def test_role_and_author_are_captured(ep):
    ep.upsert_chunks("sess-1", [{"role": "assistant", "author_id": "agent-1", "text": "hello"}], "gateway")
    row = ep._conn.execute("SELECT * FROM transcript_chunks").fetchone()
    assert row["role"] == "assistant" and row["author_id"] == "agent-1"


def test_sensitive_chunks_are_redacted(ep):
    ep.upsert_chunks(
        "sess-1",
        [{"role": "user", "text": "email me at test.person@example.invalid"}],
        "gateway",
        sensitivity="sensitive",
    )
    text = ep._conn.execute("SELECT text FROM transcript_chunks").fetchone()["text"]
    assert "test.person@example.invalid" not in text


def test_internal_chunks_are_not_redacted(ep):
    ep.upsert_chunks("sess-1", msgs("a plain sentence"), "gateway")
    assert ep._conn.execute("SELECT text FROM transcript_chunks").fetchone()["text"] == "a plain sentence"


def test_chunk_digest_is_stable_and_content_addressed():
    a = chunk_digest("s", 0, "user", "hello")
    assert a == chunk_digest("s", 0, "user", "hello")
    assert a != chunk_digest("s", 1, "user", "hello")
    assert a != chunk_digest("s", 0, "assistant", "hello")
    assert len(a) == 64


# --- episodes ------------------------------------------------------------


def test_add_episode_creates_with_window_seq_zero(ep):
    eid = ep.add_episode(scope=OWNER, kind="session", session_id="s1", title="First session", summary="did things")
    row = ep.get_episode(eid)
    assert row["window_seq"] == 0 and row["kind"] == "session"
    assert row["title"] == "First session" and row["session_id"] == "s1"


def test_add_episode_increments_window_seq_within_a_session(ep):
    a = ep.add_episode(scope=OWNER, kind="session", session_id="s1", title="w1")
    b = ep.add_episode(scope=OWNER, kind="session", session_id="s1", title="w2")
    c = ep.add_episode(scope=OWNER, kind="session", session_id="s1", title="w3")
    assert [ep.get_episode(x)["window_seq"] for x in (a, b, c)] == [0, 1, 2]


def test_window_numbering_is_per_session(ep):
    a = ep.add_episode(scope=OWNER, kind="session", session_id="s1", title="a")
    b = ep.add_episode(scope=OWNER, kind="session", session_id="s2", title="b")
    assert ep.get_episode(a)["window_seq"] == 0
    assert ep.get_episode(b)["window_seq"] == 0, "a different session starts its own numbering"


def test_window_seq_is_independent_per_kind(ep):
    ep.add_episode(scope=OWNER, kind="session", session_id="s1", title="s1")
    ep.add_episode(scope=OWNER, kind="session", session_id="s1", title="s2")
    pre = ep.add_episode(scope=OWNER, kind="precompress", session_id="s1", title="p1")
    assert ep.get_episode(pre)["window_seq"] == 0


def test_session_id_is_required_for_non_manual_kinds(ep):
    """Guessing a session key would make every episode its own window 0."""
    for kind in ("session", "window", "precompress", "delegation"):
        with pytest.raises(ValueError):
            ep.add_episode(scope=OWNER, kind=kind, title="x")


def test_manual_episode_uses_its_own_id_as_session(ep):
    eid = ep.add_episode(scope=OWNER, kind="manual", title="a manual note")
    row = ep.get_episode(eid)
    assert row["session_id"] == eid, "a manual episode must not join a session's window numbering"
    second = ep.add_episode(scope=OWNER, kind="manual", title="another manual note")
    assert ep.get_episode(second)["window_seq"] == 0, "each manual episode is its own window 0"


def test_unknown_kind_is_rejected(ep):
    with pytest.raises(ValueError):
        ep.add_episode(scope=OWNER, kind="nonsense", title="x", session_id="s1")


def test_episode_json_fields_round_trip(ep):
    eid = ep.add_episode(
        scope=OWNER, kind="session", session_id="s1", title="t",
        decisions=["chose A", "chose B"], open_loops=["finish the thing"], entities=["llama"],
    )
    row = ep.get_episode(eid)
    import json

    assert json.loads(row["decisions"]) == ["chose A", "chose B"]
    assert json.loads(row["open_loops"]) == ["finish the thing"]


def test_list_episodes_filters_by_kind_and_scope(ep):
    ep.add_episode(scope=OWNER, kind="session", session_id="s1", title="a session")
    ep.add_episode(scope=OWNER, kind="manual", title="a manual")
    other = Scope(profile="default", user="someone-else")
    ep.add_episode(scope=other, kind="session", session_id="s2", title="not mine")
    assert len(ep.list_episodes(scope=OWNER)) == 2
    assert len(ep.list_episodes(scope=OWNER, kind="manual")) == 1
    assert len(ep.list_episodes(scope=OWNER, session_id="s1")) == 1


# --- upsert_episode -----------------------------------------------------


def test_upsert_episode_creates_then_updates_the_same_row(ep):
    a = ep.upsert_episode(scope=OWNER, kind="session", session_id="s1", window_seq=0, title="first")
    b = ep.upsert_episode(scope=OWNER, kind="session", session_id="s1", window_seq=0, title="revised",
                          summary="now with a summary")
    assert a == b, "a retry must converge on the same episode"
    row = ep.get_episode(a)
    assert row["title"] == "revised" and row["summary"] == "now with a summary"
    assert ep._conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0] == 1


def test_upsert_episode_can_fill_a_later_window(ep):
    ep.upsert_episode(scope=OWNER, kind="session", session_id="s1", window_seq=0, title="w0")
    w2 = ep.upsert_episode(scope=OWNER, kind="session", session_id="s1", window_seq=2, title="w2")
    assert ep.get_episode(w2)["window_seq"] == 2


def test_upsert_rejects_manual_and_unknown_kinds(ep):
    with pytest.raises(ValueError):
        ep.upsert_episode(scope=OWNER, kind="manual", session_id="s1", window_seq=0, title="x")
    with pytest.raises(ValueError):
        ep.upsert_episode(scope=OWNER, kind="nope", session_id="s1", window_seq=0, title="x")


# --- search --------------------------------------------------------------


def test_search_episodes_finds_by_title(ep):
    eid = ep.add_episode(scope=OWNER, kind="session", session_id="srch", title="Debugging the gateway")
    ep.add_episode(scope=OWNER, kind="session", session_id="srch", title="Unrelated topic")
    hits = ep.search_episodes("gateway", OWNER)
    assert [h["id"] for h in hits] == [eid]


def test_search_episodes_finds_by_summary(ep):
    eid = ep.add_episode(scope=OWNER, kind="session", session_id="srch", title="t", summary="the retention job misbehaved")
    assert eid in [h["id"] for h in ep.search_episodes("retention", OWNER)]


def test_search_episodes_respects_scope(ep):
    ep.add_episode(scope=Scope(profile="default", user="someone-else"), kind="session", session_id="s9", title="private gateway")
    assert ep.search_episodes("gateway", OWNER) == []


def test_search_episodes_respects_time_range(ep):
    ep.add_episode(scope=OWNER, kind="session", session_id="srch", title="gateway old")
    old = (to_iso(utc_now() - timedelta(days=365)), to_iso(utc_now() - timedelta(days=300)))
    assert ep.search_episodes("gateway", OWNER, old) == []
    recent = (to_iso(utc_now() - timedelta(days=1)), to_iso(utc_now() + timedelta(days=1)))
    assert len(ep.search_episodes("gateway", OWNER, recent)) == 1


def test_search_falls_back_when_the_query_has_no_usable_tokens(ep):
    """A bare stopword or punctuation must not raise an FTS syntax error.

    FTS cannot answer these, so they fall through to a LIKE scan on the raw
    string. An empty result is the correct answer for a query of "!!!": the
    point is that the call returns instead of raising a MATCH syntax error.
    """
    ep.add_episode(scope=OWNER, kind="session", session_id="srch", title="the plan")
    for q in ("the", "!!!", "  ", "a", "?"):
        assert isinstance(ep.search_episodes(q, OWNER), list)
    assert ep.search_episodes("!!!", OWNER) == []


def test_fallback_like_scan_still_matches_real_text(ep):
    """The LIKE fallback is a working search, not a stub that always returns []."""
    eid = ep.add_episode(scope=OWNER, kind="session", session_id="srch", title="the quarterly plan")
    assert eid in [h["id"] for h in ep.search_episodes("quarterly", OWNER)]
    assert eid in [h["id"] for h in ep.search_episodes("!!! quarterly !!!", OWNER)]


def test_search_ignores_fts_operator_characters(ep):
    """A query must never be able to become an FTS expression."""
    ep.add_episode(scope=OWNER, kind="session", session_id="srch", title="gateway")
    for hostile in ('" OR "x', "NEAR(a b)", "*", "a AND (", "col:val"):
        ep.search_episodes(hostile, OWNER)


# --- AC: retention -------------------------------------------------------


def _age_chunks(ep, days: int) -> None:
    """Backdate every chunk so retention has something to act on."""
    when = to_iso(utc_now() - timedelta(days=days))
    ep._conn.execute("UPDATE transcript_chunks SET captured_at=?", (when,))
    ep._conn.commit()


def test_prune_removes_chunks_older_than_the_window(ep):
    ep.upsert_chunks("sess-old", msgs("ancient"), "gateway")
    _age_chunks(ep, 90)
    assert ep.prune_chunks(30) == 1
    assert ep.chunk_count("sess-old") == 0


def test_prune_keeps_chunks_inside_the_window(ep):
    ep.upsert_chunks("sess-new", msgs("recent"), "gateway")
    assert ep.prune_chunks(30) == 0
    assert ep.chunk_count("sess-new") == 1


def test_prune_default_is_thirty_days():
    assert DEFAULT_RETENTION_DAYS == 30


def test_prune_keeps_chunks_for_a_pending_episode(ep):
    """An in-flight session keeps its transcript so it can still be summarised."""
    ep.upsert_chunks("sess-pending", msgs("still being summarised"), "gateway")
    ep.add_episode(scope=OWNER, kind="session", session_id="sess-pending", title="in flight", summary="")
    _age_chunks(ep, 90)
    assert ep.prune_chunks(30, keep_if_episode_pending=True) == 0
    assert ep.chunk_count("sess-pending") == 1


def test_prune_keeps_chunks_when_any_later_window_is_still_unsummarised(ep):
    """A summarised first window must not mask an unsummarised third one.

    The keep decision is "does this session have *any* episode with no summary",
    not "does its newest episode". A long session is summarised incrementally, so
    window 0 can be done while window 2 is still waiting, and window 2's chunks
    are exactly the ones the summariser still needs.
    """
    ep.upsert_chunks("sess-long", msgs("early", "middle", "late"), "gateway")
    ep.upsert_episode(scope=OWNER, kind="session", session_id="sess-long", window_seq=0,
                      title="first", summary="already summarised")
    ep.upsert_episode(scope=OWNER, kind="session", session_id="sess-long", window_seq=1,
                      title="second", summary="already summarised")
    ep.upsert_episode(scope=OWNER, kind="session", session_id="sess-long", window_seq=2,
                      title="third", summary="")
    _age_chunks(ep, 90)
    assert ep.prune_chunks(30, keep_if_episode_pending=True) == 0, (
        "an unsummarised later window must keep the whole session's chunks"
    )
    assert ep.chunk_count("sess-long") == 3


def test_prune_reclaims_chunks_once_every_window_is_summarised(ep):
    """The counterpart: retention resumes when the session is fully summarised."""
    ep.upsert_chunks("sess-done", msgs("all summarised"), "gateway")
    ep.upsert_episode(scope=OWNER, kind="session", session_id="sess-done", window_seq=0,
                      title="only window", summary="complete")
    _age_chunks(ep, 90)
    assert ep.prune_chunks(30, keep_if_episode_pending=True) == 1
    assert ep.chunk_count("sess-done") == 0


def test_prune_deletes_a_pending_sessions_chunks_when_not_keeping(ep):
    ep.upsert_chunks("sess-pending", msgs("still being summarised"), "gateway")
    ep.add_episode(scope=OWNER, kind="session", session_id="sess-pending", title="in flight", summary="")
    _age_chunks(ep, 90)
    assert ep.prune_chunks(30, keep_if_episode_pending=False) == 1
    assert ep.chunk_count("sess-pending") == 0


def test_prune_only_removes_the_stale_sessions(ep):
    ep.upsert_chunks("sess-old", msgs("ancient"), "gateway")
    ep.upsert_chunks("sess-new", msgs("fresh"), "gateway")
    ep._conn.execute(
        "UPDATE transcript_chunks SET captured_at=? WHERE session_id='sess-old'",
        (to_iso(utc_now() - timedelta(days=90)),),
    )
    assert ep.prune_chunks(30) == 1
    assert ep.chunk_count("sess-old") == 0 and ep.chunk_count("sess-new") == 1


def test_prune_returns_zero_when_there_is_nothing_to_do(ep):
    assert ep.prune_chunks(30) == 0


def test_prune_honours_an_explicit_cutoff(ep):
    ep.upsert_chunks("sess-1", msgs("ten days old"), "gateway")
    _age_chunks(ep, 10)
    assert ep.prune_chunks(30) == 0, "10 days is inside a 30 day window"
    assert ep.prune_chunks(7) == 1, "10 days is outside a 7 day window"


def test_prune_episodes_removes_old_episodes(ep):
    eid = ep.add_episode(scope=OWNER, kind="session", session_id="srch", title="ancient")
    ep._conn.execute(
        "UPDATE episodes SET created_at=? WHERE id=?", (to_iso(utc_now() - timedelta(days=90)), eid)
    )
    assert ep.prune_episodes(30) == 1
    assert ep.get_episode(eid) is None


# --- FTS stays in sync ---------------------------------------------------


def test_episode_fts_tracks_writes(ep):
    ep.add_episode(scope=OWNER, kind="session", session_id="srch", title="zebras are striped")
    assert ep._conn.execute("SELECT COUNT(*) FROM episodes_fts").fetchone()[0] == 1
    ep.add_episode(scope=OWNER, kind="session", session_id="srch", title="llamas are tall")
    assert ep._conn.execute("SELECT COUNT(*) FROM episodes_fts").fetchone()[0] == 2
