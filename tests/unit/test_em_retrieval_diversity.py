"""EM-305 — supersession/duplicate collapse and MMR diversity (§3.6).

The card's second AC row: "`update` scenarios return only the latest version by
default and both with `include_history=True`". The collapse delivers the "latest
only" half and `load_predecessors` the "both" half; the tool-level
`include_history` flag is the provider's, and that split is asserted at the bottom.

Every mapping here is keyed by `(owner_type, owner_id)` — a `Ranking.key` — because
that is what the fusion and gate stages use, and a test that keys them by bare id
silently degenerates to "no text, no scope" and passes for the wrong reason.

Invented data only (rule 4): Acme / Globex / Initech, Alice / Bob Example.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from em.retrieval.candidates import OWNER_TYPE_MEMORY  # noqa: E402
from em.retrieval.diversity import (  # noqa: E402
    MMR_LAMBDA,
    MMR_TOP,
    SUPERSEDED_NOTE_FLAG,
    SUPERSEDED_NOTE_WINDOW,
    Predecessor,
    collapse,
    jaccard,
    load_predecessors,
    mmr,
    render_superseded_note,
    tokens,
)
from em.retrieval.fusion import Ranking, Signal  # noqa: E402
from em.store.db import Store  # noqa: E402
from em.store.memories import MemoryStore  # noqa: E402
from em.store.migrations import migrate  # noqa: E402
from em.store.types import MemoryDraft, Scope  # noqa: E402

ALICE = Scope(profile="default", user="alice")
BOB = Scope(profile="default", user="bob")
OWNER = Scope(profile="default")
NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path / "memory.db"))
    with s.writer() as conn:
        migrate(conn)
    yield s
    s.close()


def key(owner_id: str):
    return (OWNER_TYPE_MEMORY, owner_id)


def keyed(**pairs) -> dict:
    """``keyed(a="text", b="text")`` → the mapping shape the stage actually takes."""
    return {key(name): value for name, value in pairs.items()}


def ranking(owner_id: str, score: float = 0.9, *, why: tuple = ()) -> Ranking:
    return Ranking(
        owner_type=OWNER_TYPE_MEMORY,
        owner_id=owner_id,
        score=score,
        rrf=0.0,
        rrf_n=0.0,
        recency=0.0,
        feedback=0.0,
        signals=(Signal("bm25", 1, 0.0),),
        why=why,
    )


def remember(store, content, *, scope=ALICE, **kw) -> str:
    with store.transaction() as conn:
        result = MemoryStore(conn).add(
            MemoryDraft(content=content, **kw), scope=scope, actor="tester"
        )
    assert result.ok, result
    return result.id


# --- similarity ------------------------------------------------------------


def test_jaccard():
    assert jaccard(tokens("staging server"), tokens("staging server")) == pytest.approx(1.0)
    assert jaccard(tokens("staging server"), tokens("invoice friday")) == pytest.approx(0.0)
    assert jaccard(tokens("staging server"), tokens("staging port")) == pytest.approx(1 / 3)
    assert jaccard(frozenset(), frozenset()) == pytest.approx(0.0)
    assert jaccard(tokens("x"), frozenset()) == pytest.approx(0.0)


def test_tokens_are_casefolded_word_runs():
    assert tokens("Staging, the Server!") == frozenset({"staging", "the", "server"})


# --- MMR -------------------------------------------------------------------


def test_the_defaults_are_3_6s():
    assert MMR_LAMBDA == 0.7
    assert MMR_TOP == 20
    assert SUPERSEDED_NOTE_WINDOW == timedelta(days=30)


def test_lambda_one_is_pure_relevance():
    a, b, c = ranking("a", 0.9), ranking("b", 0.8), ranking("c", 0.1)
    texts = keyed(a="staging server", b="staging server", c="invoice friday")
    assert [r.owner_id for r in mmr([a, b, c], texts=texts, lambda_=1.0)] == ["a", "b", "c"]


def test_lambda_zero_is_pure_diversity():
    a, b, c = ranking("a", 0.9), ranking("b", 0.8), ranking("c", 0.1)
    texts = keyed(a="staging server", b="staging server", c="invoice friday")
    assert [r.owner_id for r in mmr([a, b, c], texts=texts, lambda_=0.0)] == ["a", "c", "b"]


def test_lambda_point_seven_pushes_a_near_duplicate_below_a_diverse_hit():
    """The parameter's whole job: relevance, penalised for redundancy."""
    best = ranking("best", 0.90)
    near_duplicate = ranking("near_duplicate", 0.89)
    diverse = ranking("diverse", 0.60)
    texts = keyed(
        best="the staging server port",
        near_duplicate="the staging server port note",
        diverse="invoice cycle closes friday",
    )
    assert [r.owner_id for r in mmr([best, near_duplicate, diverse], texts=texts)] == [
        "best", "diverse", "near_duplicate",
    ]


def test_only_the_head_is_diversified():
    """§3.6 scopes MMR to "the top 20"; the remainder keeps its rank order."""
    head = [ranking("a", 0.9), ranking("dup", 0.8), ranking("b", 0.7)]
    tail = [ranking("t1", 0.5), ranking("t2", 0.4)]
    texts = keyed(
        a="the staging server", dup="the staging server", b="invoicing cycle",
        t1="staging server note", t2="staging server note",
    )
    assert [r.owner_id for r in mmr(head + tail, texts=texts, top=3)[3:]] == ["t1", "t2"]


def test_the_first_hit_is_always_the_best_ranked():
    a, b, c = ranking("a", 0.9), ranking("b", 0.5), ranking("c", 0.1)
    texts = keyed(a="one", b="one", c="one")
    assert mmr([a, b, c], texts=texts)[0].owner_id == "a"


def test_mmr_is_deterministic():
    items = [ranking(name, 0.9 - index / 100) for index, name in enumerate("abcdef")]
    texts = {key(name): "staging server note" for name in "abcdef"}
    first = [r.owner_id for r in mmr(items, texts=texts)]
    for _ in range(5):
        assert [r.owner_id for r in mmr(items, texts=texts)] == first


def test_mmr_handles_zero_or_one_item():
    assert mmr([], texts={}) == []
    only = ranking("a")
    assert mmr([only], texts=keyed(a="x")) == [only]


# --- collapse: duplicates --------------------------------------------------


def test_an_exact_duplicate_across_scopes_keeps_the_narrower_one():
    """Two users storing one sentence is the case this exists for.

    `_content_hash` mixes the scope into the digest, so the hash cannot find this
    pair; the text can.
    """
    wide = ranking("profile_wide", 0.95)
    narrow = ranking("alice_own", 0.80)
    texts = keyed(profile_wide="the staging server runs on port 9090",
                  alice_own="the staging server runs on port 9090")
    scopes = keyed(profile_wide="", alice_own="alice")
    result = collapse([wide, narrow], texts=texts, scope_users=scopes)
    assert [r.owner_id for r in result.kept] == ["alice_own"]
    assert result.duplicates == (key("profile_wide"),)


def test_duplicate_collapse_ties_go_to_the_better_rank():
    first = ranking("first", 0.9)
    second = ranking("second", 0.9)
    texts = keyed(first="same text", second="same text")
    scopes = keyed(first="alice", second="alice")
    result = collapse([first, second], texts=texts, scope_users=scopes)
    assert [r.owner_id for r in result.kept] == ["first"]


def test_different_texts_both_survive_and_order_is_preserved():
    a, b = ranking("a", 0.9), ranking("b", 0.8)
    result = collapse([a, b], texts=keyed(a="one thing", b="another thing"),
                      scope_users=keyed(a="alice", b="alice"))
    assert [r.owner_id for r in result.kept] == ["a", "b"]
    assert result.duplicates == ()


def test_an_empty_text_is_not_treated_as_a_duplicate_of_another():
    a, b = ranking("a", 0.9), ranking("b", 0.8)
    result = collapse([a, b], texts=keyed(a="", b=""), scope_users=keyed(a="alice", b="alice"))
    assert [r.owner_id for r in result.kept] == ["a", "b"]


# --- the key-shape guard (a bug class, not an incident) -------------------


def test_a_texts_mapping_keyed_by_bare_id_is_rejected_not_ignored():
    """The EM-305 draft bug, made impossible to reintroduce silently.

    Keying `texts` by bare id makes every lookup miss, which degrades MMR to pure
    relevance and the collapse to "no duplicates" while every assertion still
    passes. Both stages now refuse that mapping instead of treating it as "no
    text".
    """
    a, b = ranking("a", 0.9), ranking("b", 0.8)
    bare = {"a": "staging server", "b": "invoice friday"}
    with pytest.raises(ValueError, match="keyed by Ranking.key"):
        mmr([a, b], texts=bare)
    with pytest.raises(ValueError, match="keyed by Ranking.key"):
        collapse([a, b], texts=bare, scope_users=bare)


def test_an_empty_text_is_still_legal():
    """Presence is the guard, not length: a row with a blank summary is real."""
    a, b = ranking("a", 0.9), ranking("b", 0.8)
    assert len(mmr([a, b], texts=keyed(a="", b=""))) == 2


# --- collapse: chains ------------------------------------------------------


def test_a_live_chain_keeps_only_the_successor():
    """A `restore` can leave two live members of one chain; the older one goes."""
    successor = ranking("successor", 0.9)
    ancestor = ranking("ancestor", 0.95)
    result = collapse(
        [ancestor, successor],
        texts=keyed(successor="the new value", ancestor="the old value"),
        scope_users=keyed(successor="alice", ancestor="alice"),
        predecessors={key("successor"): (Predecessor("ancestor", "the old value", NOW),)},
    )
    assert [r.owner_id for r in result.kept] == ["successor"]


def test_unrelated_candidates_are_not_treated_as_a_chain():
    a, b = ranking("a", 0.9), ranking("b", 0.8)
    result = collapse(
        [a, b],
        texts=keyed(a="one", b="two"),
        scope_users=keyed(a="alice", b="alice"),
        predecessors={key("a"): (Predecessor("something_else", "old", NOW),)},
    )
    assert [r.owner_id for r in result.kept] == ["a", "b"]


# --- collapse: the superseded note ----------------------------------------


def test_a_recent_predecessor_earns_the_flag_and_comes_back_for_the_renderer():
    successor = ranking("successor", 0.9)
    old = Predecessor("old_id", "the old summary", NOW - timedelta(days=5))
    result = collapse(
        [successor],
        texts=keyed(successor="the new value"),
        scope_users=keyed(successor="alice"),
        predecessors={key("successor"): (old,)},
        now=NOW,
    )
    assert SUPERSEDED_NOTE_FLAG in result.kept[0].why
    assert result.predecessors[key("successor")] == (old,)
    assert render_superseded_note(old) == (
        f"(updated {(NOW - timedelta(days=5)).date().isoformat()}; was: the old summary)"
    )


def test_an_old_predecessor_does_not_earn_the_flag():
    successor = ranking("successor", 0.9)
    stale = Predecessor("old_id", "the old summary", NOW - timedelta(days=40))
    result = collapse(
        [successor],
        texts=keyed(successor="the new value"),
        scope_users=keyed(successor="alice"),
        predecessors={key("successor"): (stale,)},
        now=NOW,
    )
    assert SUPERSEDED_NOTE_FLAG not in result.kept[0].why
    assert result.predecessors == {}


def test_an_unknown_change_time_still_earns_the_note():
    successor = ranking("successor", 0.9)
    result = collapse(
        [successor],
        texts=keyed(successor="the new value"),
        scope_users=keyed(successor="alice"),
        predecessors={key("successor"): (Predecessor("old_id", "old", None),)},
        now=NOW,
    )
    assert SUPERSEDED_NOTE_FLAG in result.kept[0].why
    assert render_superseded_note(Predecessor("old_id", "old", None)) == (
        "(updated unknown; was: old)"
    )


def test_collapse_leaves_the_rest_of_the_explanation_alone():
    successor = ranking(
        "successor", 0.9,
        why=({"signal": "bm25", "rank": 1, "contrib": 1.0}, "temporal_filter"),
    )
    result = collapse(
        [successor],
        texts=keyed(successor="the new value"),
        scope_users=keyed(successor="alice"),
        predecessors={key("successor"): (Predecessor("old_id", "old", NOW),)},
        now=NOW,
    )
    why = result.kept[0].why
    assert why[0] == {"signal": "bm25", "rank": 1, "contrib": 1.0}
    assert why[1:] == ("temporal_filter", SUPERSEDED_NOTE_FLAG)


# --- the store: predecessors and the `update` AC ---------------------------


def supersede(store, old_id: str, content: str, *, scope=ALICE, reason="update") -> str:
    with store.transaction() as conn:
        result = MemoryStore(conn).supersede(
            old_id, MemoryDraft(content=content), scope=scope, actor="tester", reason=reason
        )
    assert result.ok, result
    return result.id


def test_load_predecessors_reads_the_superseded_rows(store):
    old = remember(store, "the staging port is 8080", scope=ALICE)
    new = supersede(store, old, "the staging port is 9090")
    found = load_predecessors(store.reader(), scope=ALICE, keys=[key(new)])
    (predecessor,) = found[key(new)]
    assert predecessor.memory_id == old


def test_load_predecessors_is_scoped(store):
    old = remember(store, "bob's staging port is 8080", scope=BOB)
    new = supersede(store, old, "bob's staging port is 9090", scope=BOB)
    assert load_predecessors(store.reader(), scope=ALICE, keys=[key(new)]) == {}
    assert key(new) in load_predecessors(store.reader(), scope=BOB, keys=[key(new)])


def test_load_predecessors_ignores_episodes(store):
    from em.retrieval.candidates import OWNER_TYPE_EPISODE

    assert load_predecessors(
        store.reader(), scope=ALICE, keys=[(OWNER_TYPE_EPISODE, "ep_whatever")]
    ) == {}


def test_an_update_returns_only_the_latest_version_by_default(store):
    """AC, first half: the predecessor is not `active`, so it is never a candidate."""
    old = remember(store, "the staging port is 8080", scope=ALICE)
    new = supersede(store, old, "the staging port is 9090")

    with store.transaction() as conn:
        statuses = {
            row["id"]: row["status"]
            for row in conn.execute(
                "SELECT id, status FROM memories WHERE id IN (?,?)", (old, new)
            )
        }
    assert statuses[new] == "active"
    assert statuses[old] == "superseded"
    live = store.reader().execute(
        "SELECT id FROM memories WHERE status='active' AND id IN (?,?)", (old, new)
    ).fetchall()
    assert [row["id"] for row in live] == [new]


def test_and_both_versions_with_history(store):
    """AC, second half: the predecessor is reachable on request.

    The `include_history` *flag* lives on the memory tool (the provider's card);
    what this layer owes it is the predecessor, and that is what is asserted. The
    full chain is `history()`'s job — note it returns `memory_versions` rows, so
    the memory id is `memory_id`, not `id`.
    """
    old = remember(store, "the staging port is 8080", scope=ALICE)
    new = supersede(store, old, "the staging port is 9090")

    default = load_predecessors(store.reader(), scope=ALICE, keys=[key(new)])
    assert [p.memory_id for p in default[key(new)]] == [old]

    with store.transaction() as conn:
        chain = MemoryStore(conn).history(new)
    assert {row["memory_id"] for row in chain} == {old, new}
