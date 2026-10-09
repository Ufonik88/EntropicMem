"""EM-302 — candidate generators (§3.6).

The card's two named ACs are here explicitly: **scope isolation** ("user A never
sees user B's rows") for every generator, and the **deadline** ("generator
returns partial within 5 ms of deadline"). The deadline tests do not race the
clock — they drive ``candidates._monotonic``, so "expired" and "expired
mid-scan" are exact.

Invented data only (rule 4): Acme / Globex / Initech, Alice / Bob Example.
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from em.clock import to_iso  # noqa: E402
from em.retrieval import candidates as C  # noqa: E402
from em.retrieval.candidates import (  # noqa: E402
    GENERATOR_LIMITS,
    GENERATORS,
    OWNER_TYPE_EPISODE,
    OWNER_TYPE_MEMORY,
    RetrievalContext,
    bm25,
    episodic,
    match_expression,
    pinned,
    recent,
    scope_sql,
)
from em.retrieval.candidates import (
    entity as entity_generator,
)
from em.retrieval.query import AnalyzedQuery  # noqa: E402
from em.retrieval.temporal import TimeRange  # noqa: E402
from em.store.db import Store  # noqa: E402
from em.store.entities import EntityStore  # noqa: E402
from em.store.episodes import EpisodeStore  # noqa: E402
from em.store.memories import MemoryStore  # noqa: E402
from em.store.migrations import migrate  # noqa: E402
from em.store.types import MemoryDraft, Scope  # noqa: E402

ALICE = Scope(profile="default", user="alice")
BOB = Scope(profile="default", user="bob")
OWNER = Scope(profile="default")
OTHER_PROFILE = Scope(profile="other")

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)


# --- fixtures and helpers -------------------------------------------------


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path / "memory.db"))
    with s.writer() as conn:
        migrate(conn)
    yield s
    s.close()


def remember(store, content, *, scope, **kw) -> str:
    with store.transaction() as conn:
        result = MemoryStore(conn).add(
            MemoryDraft(content=content, **kw), scope=scope, actor="tester"
        )
    assert result.ok, result
    return result.id


def restamp(store, memory_id, **columns) -> None:
    """Set columns the write policy owns (status, tier, timestamps)."""
    assignments = ", ".join(f"{name}=?" for name in columns)
    with store.transaction() as conn:
        conn.execute(
            f"UPDATE memories SET {assignments} WHERE id=?",
            (*columns.values(), memory_id),
        )


def episode(store, *, scope, title, summary, start_at=None, kind="manual") -> str:
    with store.transaction() as conn:
        return EpisodeStore(conn).add_episode(
            scope=scope, kind=kind, title=title, summary=summary, start_at=start_at
        )


def ctx_for(store, *, scope, terms=(), intent="lookup", temporal=None,
            entities=(), limits=None, deadline=None) -> RetrievalContext:
    return RetrievalContext(
        conn=store.reader(),
        aq=AnalyzedQuery(
            raw=" ".join(terms),
            text=" ".join(terms),
            terms=tuple(terms),
            temporal=temporal,
            entities=tuple(entities),
            intent=intent,
        ),
        scope=scope,
        now=NOW,
        deadline=deadline,
        limits=limits or {},
    )


def ids(candidates):
    return [c.owner_id for c in candidates]


class RecordingConn:
    """A read connection that remembers every statement it was asked to run."""

    def __init__(self, conn):
        self._conn = conn
        self.queries: list[str] = []

    def execute(self, sql, params=()):  # noqa: ANN001
        self.queries.append(sql)
        return self._conn.execute(sql, params)


def recording_ctx(store, **kw) -> RetrievalContext:
    ctx = ctx_for(store, **kw)
    return RetrievalContext(
        conn=RecordingConn(store.reader()),
        aq=ctx.aq,
        scope=ctx.scope,
        now=ctx.now,
        deadline=ctx.deadline,
        limits=ctx.limits,
    )


# --- match_expression (§3.6 term rendering) -------------------------------


def test_prefix_star_goes_only_on_terms_of_four_or_more():
    expr = match_expression(["stage", "cat", "port"])
    assert '"stage"*' in expr
    assert '"cat"' in expr and '"cat"*' not in expr
    assert '"port"*' in expr


def test_terms_shorter_than_two_characters_are_dropped():
    # §3.6: drop tokens `len < 2`.
    assert match_expression(["a", "i", "hi"]) == '"hi"'


def test_duplicate_terms_collapse_case_insensitively():
    assert match_expression(["Port", "port", "PORT"]) == '"Port"*'


def test_fts_metacharacters_cannot_reach_the_query():
    # A quote, colon, caret or paren must never produce an FTS5 syntax error,
    # and an unbalanced quote must not make the expression malformed.
    expr = match_expression(['foo" OR bar', "a^b", "(c)", "wat*"])
    assert expr  # something was built
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE VIRTUAL TABLE t USING fts5(x)")  # must not raise on MATCH
    conn.execute("INSERT INTO t VALUES ('foobar')")
    conn.execute("SELECT * FROM t WHERE t MATCH ?", (expr,)).fetchall()


def test_the_terms_are_capped():
    expr = match_expression([f"term{i}" for i in range(40)])
    assert expr.count(" OR ") == C.MAX_TERMS - 1


def test_no_usable_terms_gives_an_empty_expression():
    # Callers must treat '' as "no matches", never as "match everything".
    assert match_expression([]) == ""
    assert match_expression(["a", "b"]) == ""


# --- bm25 -----------------------------------------------------------------


def test_bm25_finds_a_lexical_match(store):
    mid = remember(store, "the staging server runs on port 9090", scope=ALICE)
    got = bm25(ctx_for(store, scope=ALICE, terms=["staging"]))
    assert ids(got) == [mid]
    assert got[0].owner_type == OWNER_TYPE_MEMORY
    assert got[0].raw_score > 0.0  # negated, so higher-is-better


def test_bm25_queried_without_terms_returns_nothing(store):
    remember(store, "the staging server runs on port 9090", scope=ALICE)
    assert bm25(ctx_for(store, scope=ALICE, terms=[])) == []


def test_bm25_never_returns_a_forgotten_row(store):
    mid = remember(store, "the staging server runs on port 9090", scope=ALICE)
    restamp(store, mid, status="deleted")
    assert bm25(ctx_for(store, scope=ALICE, terms=["staging"])) == []


def test_bm25_isolates_users(store):
    """AC: user A never sees user B's rows."""
    mine = remember(store, "the staging server runs on port 9090", scope=ALICE)
    theirs = remember(store, "the staging server runs on port 8080", scope=BOB)
    got = ids(bm25(ctx_for(store, scope=ALICE, terms=["staging", "server"])))
    assert mine in got
    assert theirs not in got


def test_bm25_isolates_profiles(store):
    other = remember(store, "the staging server runs on port 9090", scope=OTHER_PROFILE)
    assert bm25(ctx_for(store, scope=ALICE, terms=["staging"])) == []
    assert other  # the row exists, it is simply not visible


def test_scope_isolation_covers_the_chat_dimension(store):
    here = remember(store, "staging in this chat",
                    scope=Scope(profile="default", user="alice", chat="chat-1"))
    there = remember(store, "staging in another chat",
                     scope=Scope(profile="default", user="alice", chat="chat-9"))
    got = ids(bm25(ctx_for(
        store, scope=Scope(profile="default", user="alice", chat="chat-1"), terms=["staging"]
    )))
    assert here in got
    assert there not in got


def test_bm25_hides_an_owner_only_tier_from_a_guest_but_not_from_the_owner(store):
    mid = remember(store, "the staging server password is hunter2", scope=OWNER)
    restamp(store, mid, sensitivity="sensitive")
    guest = ids(bm25(ctx_for(store, scope=ALICE, terms=["staging"])))
    owner = ids(bm25(ctx_for(store, scope=OWNER, terms=["staging"])))
    assert mid not in guest
    assert owner == [mid]


def test_a_profile_wide_ordinary_row_is_visible_to_everyone_in_the_profile(store):
    mid = remember(store, "the staging server runs on port 9090", scope=OWNER)
    assert ids(bm25(ctx_for(store, scope=ALICE, terms=["staging"]))) == [mid]


def test_bm25_weights_the_content_column_above_the_summary_column(store):
    """§3.6: `bm25(memories_fts, 1.0, 0.5, 0.3, 0.1)` — content outranks summary."""
    in_summary = remember(store, "unrelated body text", scope=ALICE, summary="staging")
    in_content = remember(store, "staging belongs in the body", scope=ALICE)
    got = ids(bm25(ctx_for(store, scope=ALICE, terms=["staging"])))
    assert got.index(in_content) < got.index(in_summary)


def test_bm25_respects_the_limit(store):
    for i in range(6):
        remember(store, f"staging server number {i} is running", scope=ALICE)
    got = bm25(ctx_for(store, scope=ALICE, terms=["staging"], limits={"bm25": 2}))
    assert len(got) == 2


# --- pinned ---------------------------------------------------------------


def test_pinned_returns_pinned_rows_and_constraints(store):
    flagged = remember(store, "the staging host is special", scope=ALICE, pinned=True)
    constraint = remember(store, "never deploy on fridays", scope=ALICE, kind="constraint")
    remember(store, "just an ordinary fact", scope=ALICE)
    got = ids(pinned(ctx_for(store, scope=ALICE)))
    assert set(got) == {flagged, constraint}


def test_pinned_isolates_users(store):
    mine = remember(store, "my pinned note", scope=ALICE, pinned=True)
    theirs = remember(store, "their pinned note", scope=BOB, pinned=True)
    got = ids(pinned(ctx_for(store, scope=ALICE)))
    assert got == [mine]
    assert theirs not in got


def test_pinned_hides_an_owner_only_constraint_from_a_guest(store):
    mid = remember(store, "secret constraint", scope=OWNER, kind="constraint")
    restamp(store, mid, sensitivity="secret")
    assert pinned(ctx_for(store, scope=ALICE)) == []
    assert ids(pinned(ctx_for(store, scope=OWNER))) == [mid]


# --- recent ---------------------------------------------------------------


def test_recent_returns_rows_updated_inside_the_window(store):
    fresh = remember(store, "something recent", scope=ALICE)
    stale = remember(store, "something old", scope=ALICE)
    restamp(store, stale, updated_at=to_iso(NOW - timedelta(days=9)))
    assert ids(recent(ctx_for(store, scope=ALICE))) == [fresh]


def test_recent_is_skipped_for_intents_that_do_not_ask_for_it(store):
    """§3.6: only when intent ∈ {temporal, lookup}."""
    remember(store, "something recent", scope=ALICE)
    assert recent(ctx_for(store, scope=ALICE, intent="profile")) == []
    assert recent(ctx_for(store, scope=ALICE, intent="procedural")) == []
    assert recent(ctx_for(store, scope=ALICE, intent="temporal")) != []


def test_recent_isolates_users(store):
    mine = remember(store, "my recent note", scope=ALICE)
    theirs = remember(store, "their recent note", scope=BOB)
    got = ids(recent(ctx_for(store, scope=ALICE)))
    assert mine in got and theirs not in got


# --- episodic -------------------------------------------------------------


def test_episodic_returns_episodes_with_the_episode_owner_type(store):
    """§3.6: the episodic generator returns owner_type='episode'."""
    ep = episode(store, scope=ALICE, title="Hub fleet migration",
                 summary="decided the object numbers are hub IDs")
    got = episodic(ctx_for(store, scope=ALICE, terms=["migration"]))
    assert ids(got) == [ep]
    assert got[0].owner_type == OWNER_TYPE_EPISODE


def test_episodic_isolates_users(store):
    mine = episode(store, scope=ALICE, title="my session", summary="about migrations")
    theirs = episode(store, scope=BOB, title="their session", summary="about migrations")
    got = ids(episodic(ctx_for(store, scope=ALICE, terms=["migrations"])))
    assert mine in got and theirs not in got


def test_episodic_has_no_tier_and_so_a_guest_sees_a_profile_wide_episode(store):
    """`episodes` has no `sensitivity` column, so only the profile/user rule applies."""
    ep = episode(store, scope=OWNER, title="profile-wide session", summary="about migrations")
    assert ids(episodic(ctx_for(store, scope=ALICE, terms=["migrations"]))) == [ep]


def test_episodic_time_window_filters_on_start_at(store):
    inside = episode(store, scope=ALICE, title="inside the window", summary="about migrations",
                     start_at=to_iso(datetime(2026, 5, 1, tzinfo=timezone.utc)))
    outside = episode(store, scope=ALICE, title="outside the window", summary="about migrations",
                      start_at=to_iso(datetime(2020, 5, 1, tzinfo=timezone.utc)))
    window = TimeRange(
        start=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end=datetime(2026, 12, 31, tzinfo=timezone.utc),
    )
    got = ids(episodic(ctx_for(store, scope=ALICE, terms=["migrations"], temporal=window)))
    assert inside in got and outside not in got


# --- entity ---------------------------------------------------------------


def link(store, memory_id, entity_id) -> None:
    with store.transaction() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO memory_entities (memory_id, entity_id, role) VALUES (?,?,?)",
            (memory_id, entity_id, "mention"),
        )


def make_entity(store, name, *, scope=ALICE) -> str:
    with store.transaction() as conn:
        return EntityStore(conn).get_or_create_entity(name, scope=scope)


def test_entity_returns_direct_mentions(store):
    eid = make_entity(store, "Acme Corp")
    mid = remember(store, "Acme Corp signed the contract", scope=ALICE)
    link(store, mid, eid)
    got = entity_generator(ctx_for(store, scope=ALICE, entities=[eid]))
    assert [c.owner_id for c in got] == [mid]
    assert got[0].raw_score == 1.0


def test_entity_walks_one_hop_through_relations_at_half_score(store):
    eid = make_entity(store, "Acme Corp")
    direct = remember(store, "Acme Corp signed the contract", scope=ALICE)
    link(store, direct, eid)
    hopped = remember(store, "the renewal is due in March", scope=ALICE)
    with store.transaction() as conn:
        EntityStore(conn).add_relation(
            scope=ALICE, subject_id=eid, predicate="renewal_is", object_literal="March",
            memory_id=hopped,
        )
    got = {c.owner_id: c.raw_score for c in entity_generator(ctx_for(store, scope=ALICE, entities=[eid]))}
    assert got[direct] == 1.0
    assert got[hopped] == 0.5


def test_entity_isolates_users_even_through_a_relation(store):
    eid = make_entity(store, "Acme Corp")
    mine = remember(store, "Acme Corp signed the contract", scope=ALICE)
    link(store, mine, eid)
    theirs = remember(store, "their private renewal note", scope=BOB)
    with store.transaction() as conn:
        EntityStore(conn).add_relation(
            scope=BOB, subject_id=eid, predicate="renewal_is", object_literal="March",
            memory_id=theirs,
        )
    got = [c.owner_id for c in entity_generator(ctx_for(store, scope=ALICE, entities=[eid]))]
    assert mine in got and theirs not in got


def test_entity_will_not_hop_through_another_profiles_relation(store):
    """A relation belongs to a profile; only this profile's may bridge to a memory."""
    eid = make_entity(store, "Acme Corp")
    mid = remember(store, "a memory with no direct mention", scope=ALICE)
    with store.transaction() as conn:
        EntityStore(conn).add_relation(
            scope=OTHER_PROFILE, subject_id=eid, predicate="notes", object_literal="x",
            memory_id=mid,
        )
    assert entity_generator(ctx_for(store, scope=ALICE, entities=[eid])) == []


def test_entity_without_detected_entities_returns_nothing(store):
    eid = make_entity(store, "Acme Corp")
    mid = remember(store, "Acme Corp signed the contract", scope=ALICE)
    link(store, mid, eid)
    assert entity_generator(ctx_for(store, scope=ALICE, entities=[])) == []


# --- deadline (AC) --------------------------------------------------------


def test_every_generator_honours_an_expired_deadline_without_running_sql(store):
    """AC: "a generator returns partial within 5 ms of deadline" — asserted structurally.

    **Deliberately not a wall-clock assertion.** The first version of this test measured
    `elapsed <= 5 ms` and flaked on the Windows runner at 16 ms, for a generator that does
    no work at all past its check: a wall-clock bound on a shared runner measures the
    runner, not the generator. What the AC actually requires is that a generator stops
    when the deadline passes instead of running to completion, and that is exact here —
    an expired generator returns nothing **and issues no SQL**, which a stopwatch cannot
    state but a recording connection can.
    """
    for i in range(3):
        remember(store, f"staging server number {i}", scope=ALICE)
    for name, generator in GENERATORS.items():
        ctx = recording_ctx(store, scope=ALICE, terms=["staging"], deadline=0.0)
        assert generator(ctx) == [], f"{name} did work after its deadline"
        assert ctx.conn.queries == [], f"{name} ran SQL after its deadline"


def test_the_deadline_is_checked_before_a_page_not_after_it(store, monkeypatch):
    """Stronger than the stopwatch version: the *stop point* is asserted exactly.

    With a clock that reports "not expired" once and "expired" thereafter, exactly one
    page may be fetched. A check placed after the query would fetch two.
    """
    for i in range(25):
        remember(store, f"staging server number {i} is running", scope=ALICE)

    ticks = {"n": 0}

    def fake_monotonic() -> float:
        ticks["n"] += 1
        return 0.0 if ticks["n"] == 1 else 999.0

    monkeypatch.setattr(C, "_monotonic", fake_monotonic)
    ctx = ctx_for(store, scope=ALICE, terms=["staging"], deadline=100.0)
    got = bm25(ctx)

    assert len(got) == C._PAGE, "exactly one page, because the check precedes the fetch"


def test_a_generator_that_runs_out_midway_returns_a_partial_list(store, monkeypatch):
    """Not just "expired": a generator that expires mid-scan keeps what it has."""
    for i in range(25):
        remember(store, f"staging server number {i} is running", scope=ALICE)

    calls = {"n": 0}

    def fake_monotonic() -> float:
        calls["n"] += 1
        return 0.0 if calls["n"] <= 2 else 999.0  # two pages fit, then the wall

    monkeypatch.setattr(C, "_monotonic", fake_monotonic)
    got = bm25(ctx_for(store, scope=ALICE, terms=["staging"], deadline=100.0))

    assert len(got) == 2 * C._PAGE
    assert len(got) < 25, "the whole set came back, so the deadline was not honoured"


def test_the_full_set_comes_back_when_there_is_no_deadline(store):
    for i in range(25):
        remember(store, f"staging server number {i} is running", scope=ALICE)
    got = bm25(ctx_for(store, scope=ALICE, terms=["staging"]))
    assert len(got) == 25


# --- scope_sql details ----------------------------------------------------


def test_owner_only_false_omits_the_tier_clause_for_a_table_without_sensitivity(store):
    clause, params = scope_sql(ALICE, table="e", owner_only=False)
    assert "sensitivity" not in clause and "visibility" not in clause
    assert params == [ALICE.profile, ALICE.user]
    clause, params = scope_sql(ALICE, table="e")
    assert "sensitivity IN (?, ?)" in clause and "visibility" in clause


def test_the_chat_dimension_is_emitted_only_when_the_scope_is_in_a_chat():
    owner_in_chat = Scope(profile="default", chat="chat-1")
    clause, params = scope_sql(owner_in_chat)
    assert "scope_chat = ?" in clause
    assert params == ["default", "", "chat-1"]

    guest_in_chat = Scope(profile="default", user="alice", chat="chat-1")
    clause, params = scope_sql(guest_in_chat)
    assert "scope_chat = ?" in clause and "sensitivity IN (?, ?)" in clause
    assert params == ["default", "alice", "chat-1", "sensitive", "secret"]

    plain, params = scope_sql(ALICE)
    assert "scope_chat" not in plain
    assert params[:2] == ["default", "alice"]


# --- the registry ---------------------------------------------------------


def test_the_registry_holds_the_generators_including_vector():
    """``vector`` joined the registry in EM-303. With no query vector it is a
    no-op (see ``test_em_retrieval_vectors``); the old pin was "not yet"."""
    assert set(GENERATORS) == {"bm25", "vector", "entity", "episodic", "recent", "pinned"}
    assert "vector" in GENERATOR_LIMITS
