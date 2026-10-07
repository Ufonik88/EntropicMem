"""EM-304 — fusion, rerank, explainability (§3.6).

The card's AC, in its own words: "unit tests with synthetic ranks reproduce
hand-computed scores to 1e-9." Every number below is written out by hand from the
formulas, not read off the implementation.

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

from em.retrieval.candidates import (  # noqa: E402
    OWNER_TYPE_EPISODE,
    OWNER_TYPE_MEMORY,
    Candidate,
)
from em.retrieval.fusion import (  # noqa: E402
    DEFAULT_RANK_WEIGHTS,
    GENERATOR_WEIGHTS,
    RRF_K,
    Features,
    RankWeights,
    age_days,
    feature_score,
    feedback_factor,
    fuse,
    legacy_tokens,
    load_features,
    rank,
    rank_candidates,
    recency_factor,
    weights_for,
)
from em.store.db import Store  # noqa: E402
from em.store.episodes import EpisodeStore  # noqa: E402
from em.store.memories import MemoryStore  # noqa: E402
from em.store.migrations import migrate  # noqa: E402
from em.store.types import MemoryDraft, Scope  # noqa: E402

ALICE = Scope(profile="default", user="alice")
BOB = Scope(profile="default", user="bob")
OWNER = Scope(profile="default")
OTHER_PROFILE = Scope(profile="other")
NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
APPROX = {"abs": 1e-9}


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path / "memory.db"))
    with s.writer() as conn:
        migrate(conn)
    yield s
    s.close()


def mem(owner_id: str, score: float = 1.0) -> Candidate:
    return Candidate(OWNER_TYPE_MEMORY, owner_id, score)


def ep(owner_id: str, score: float = 1.0) -> Candidate:
    return Candidate(OWNER_TYPE_EPISODE, owner_id, score)


def remember(store, content, *, scope=ALICE, **kw) -> str:
    with store.transaction() as conn:
        result = MemoryStore(conn).add(
            MemoryDraft(content=content, **kw), scope=scope, actor="tester"
        )
    assert result.ok, result
    return result.id


def make_episode(store, *, scope=ALICE, title="a session", summary="about migrations") -> str:
    with store.transaction() as conn:
        return EpisodeStore(conn).add_episode(
            scope=scope, kind="manual", title=title, summary=summary
        )


# --- the weight table is §3.6's, verbatim ---------------------------------


def test_the_generator_weight_table_matches_3_6_exactly():
    assert GENERATOR_WEIGHTS == {
        "lookup": {"bm25": 1.0, "vector": 1.0, "entity": 0.7, "episodic": 0.3, "recent": 0.2, "pinned": 0.5},
        "profile": {"bm25": 0.6, "vector": 0.8, "entity": 0.6, "episodic": 0.1, "recent": 0.1, "pinned": 1.0},
        "temporal": {"bm25": 0.7, "vector": 0.6, "entity": 0.5, "episodic": 1.0, "recent": 0.8, "pinned": 0.3},
        "procedural": {"bm25": 1.0, "vector": 1.0, "entity": 0.5, "episodic": 0.4, "recent": 0.2, "pinned": 0.5},
    }
    assert weights_for("profile")["pinned"] == 1.0
    assert weights_for("temporal")["episodic"] == 1.0
    assert weights_for("not-an-intent") == GENERATOR_WEIGHTS["lookup"]


def test_the_rerank_weights_are_3_6s():
    assert DEFAULT_RANK_WEIGHTS == RankWeights(
        rrf=0.60, importance=0.15, recency=0.10, confidence=0.10, feedback=0.05,
        standard_half_life_days=180.0, volatile_half_life_days=14.0, standard_floor=0.5,
    )
    assert RRF_K == 60.0


# --- fusion: hand-computed ------------------------------------------------


def test_a_single_generator_single_hit_normalises_to_one():
    fused = fuse({"bm25": [mem("a")]}, intent="lookup")
    (entry,) = fused.values()
    assert entry.rrf == pytest.approx(1.0 / 61.0, **APPROX)
    assert entry.rrf_n == pytest.approx(1.0, **APPROX)
    assert entry.signals == (entry.signals[0],)
    assert entry.signals[0].signal == "bm25"
    assert entry.signals[0].rank == 1
    assert entry.signals[0].contrib == pytest.approx(1.0, **APPROX)


def test_two_generators_normalise_over_the_active_pair():
    # lookup weights: bm25 1.0, entity 0.7. Both hit at rank 1.
    fused = fuse({"bm25": [mem("a")], "entity": [mem("b")]}, intent="lookup")
    assert fused[("memory", "a")].rrf == pytest.approx(1.0 / 61.0, **APPROX)
    assert fused[("memory", "b")].rrf == pytest.approx(0.7 / 61.0, **APPROX)
    denominator = (1.0 + 0.7) / 61.0
    assert fused[("memory", "a")].rrf_n == pytest.approx((1.0 / 61.0) / denominator, **APPROX)
    assert fused[("memory", "b")].rrf_n == pytest.approx((0.7 / 61.0) / denominator, **APPROX)
    # and the shares of one candidate sum to its rrf_n
    assert sum(s.contrib for s in fused[("memory", "a")].signals) == pytest.approx(
        fused[("memory", "a")].rrf_n, **APPROX
    )


def test_the_g_active_trap_a_single_generator_hit_is_not_capped_at_a_quarter():
    """§3.6's explicit warning.

    Normalising over *all six configured* generators would give
    ``(1/61) / ((1.0+1.0+0.7+0.3+0.2+0.5)/61) = 1/3.7 ≈ 0.270``, under a
    ``gate.min_score`` of 0.30, and a perfectly good lexical hit would be thrown
    away. Only the generators that ran and returned something count.
    """
    fused = fuse({"bm25": [mem("a")]}, intent="lookup")
    assert fused[("memory", "a")].rrf_n == pytest.approx(1.0, **APPROX)
    all_six = sum(GENERATOR_WEIGHTS["lookup"].values()) / 61.0
    assert (1.0 / 61.0) / all_six == pytest.approx(1.0 / 3.7, **APPROX)
    assert (1.0 / 61.0) / all_six < 0.30, "the trap the plan names"


def test_a_generator_that_ran_and_found_nothing_is_not_active():
    fused = fuse(
        {"bm25": [mem("a")], "vector": [], "entity": [], "episodic": [], "recent": [], "pinned": []},
        intent="lookup",
    )
    assert fused[("memory", "a")].rrf_n == pytest.approx(1.0, **APPROX)


def test_rank_within_a_generator_changes_the_contribution():
    # bm25 only: rank 1 gives 1/61, rank 2 gives 1/62; the denominator is 1/61.
    fused = fuse({"bm25": [mem("a"), mem("b")]}, intent="lookup")
    assert fused[("memory", "a")].rrf_n == pytest.approx(1.0, **APPROX)
    assert fused[("memory", "b")].rrf == pytest.approx(1.0 / 62.0, **APPROX)
    assert fused[("memory", "b")].rrf_n == pytest.approx((1.0 / 62.0) / (1.0 / 61.0), **APPROX)


def test_a_candidate_found_by_two_generators_accumulates():
    fused = fuse({"bm25": [mem("a")], "entity": [mem("a")]}, intent="lookup")
    entry = fused[("memory", "a")]
    assert entry.rrf == pytest.approx((1.0 + 0.7) / 61.0, **APPROX)
    assert entry.rrf_n == pytest.approx(1.0, **APPROX)
    assert [s.signal for s in entry.signals] == ["bm25", "entity"]
    assert [s.contrib for s in entry.signals] == pytest.approx([1.0 / 1.7, 0.7 / 1.7], **APPROX)


def test_a_duplicate_within_one_generator_counts_once_at_its_best_rank():
    fused = fuse({"bm25": [mem("a"), mem("a")]}, intent="lookup")
    assert fused[("memory", "a")].rrf == pytest.approx(1.0 / 61.0, **APPROX)
    assert len(fused[("memory", "a")].signals) == 1


def test_a_memory_and_an_episode_are_different_keys():
    fused = fuse({"episodic": [ep("x")], "bm25": [mem("x")]}, intent="lookup")
    assert set(fused) == {("memory", "x"), ("episode", "x")}


def test_an_unweighted_generator_does_not_deflate_the_others():
    """EM-308's generators will bring their own weights; until then they are 0.0."""
    fused = fuse({"bm25": [mem("a")], "note_bm25": [mem("b")]}, intent="lookup")
    assert fused[("memory", "a")].rrf_n == pytest.approx(1.0, **APPROX)
    assert fused[("memory", "b")].rrf_n == pytest.approx(0.0, **APPROX)


def test_an_all_zero_weight_query_normalises_to_zero_instead_of_dividing_by_zero():
    """The normalising denominator can be exactly zero, and must not raise.

    Every generator that ran has weight 0.0 — which is the state EM-308's
    ``note_bm25`` is in until it brings its own weights — so there is no rank-1
    reference to normalise against. Reporting 0.0 is the honest answer: the
    candidate scored, but nothing says how good that is on this scale.
    """
    fused = fuse({"note_bm25": [mem("a")]}, intent="lookup")
    assert fused[("memory", "a")].rrf == pytest.approx(0.0, **APPROX)
    assert fused[("memory", "a")].rrf_n == pytest.approx(0.0, **APPROX)
    assert fused[("memory", "a")].signals[0].contrib == pytest.approx(0.0, **APPROX)


def test_no_candidates_fuses_to_nothing():
    assert fuse({"bm25": [], "entity": []}, intent="lookup") == {}
    assert fuse({}, intent="lookup") == {}


def test_the_intent_selects_the_weights():
    hit = {"pinned": [mem("a")]}
    assert fuse(hit, intent="profile")[("memory", "a")].rrf == pytest.approx(1.0 / 61.0, **APPROX)
    assert fuse(hit, intent="temporal")[("memory", "a")].rrf == pytest.approx(0.3 / 61.0, **APPROX)


# --- rerank: hand-computed ------------------------------------------------


def test_age_days_uses_the_newest_of_the_three_stamps():
    features = Features(
        updated_at=NOW - timedelta(days=100),
        last_accessed_at=NOW - timedelta(days=10),
        valid_from=NOW - timedelta(days=50),
    )
    assert age_days(features, now=NOW) == pytest.approx(10.0, **APPROX)


def test_age_days_floors_at_zero_for_a_future_stamp():
    assert age_days(Features(updated_at=NOW + timedelta(days=5)), now=NOW) == pytest.approx(0.0, **APPROX)
    assert age_days(Features(), now=NOW) == pytest.approx(0.0, **APPROX)


@pytest.mark.parametrize(
    "decay_class,pinned,age_days_value,expected",
    [
        ("evergreen", False, 10_000, 1.0),
        ("volatile", True, 10_000, 1.0),  # pinned wins over the decay class
        ("standard", False, 0, 1.0),  # 0.5 ** 0
        ("standard", False, 180, 0.5),
        ("standard", False, 360, 0.5),  # the floor wins over 0.25
        ("standard", False, 10_000, 0.5),  # the max(0.5, …) floor
        ("volatile", False, 0, 1.0),
        ("volatile", False, 14, 0.5),
        ("volatile", False, 28, 0.25),
        ("volatile", False, 10_000, 0.5 ** (10_000 / 14)),
    ],
)
def test_recency_factor(decay_class, pinned, age_days_value, expected):
    features = Features(
        decay_class=decay_class, pinned=pinned, updated_at=NOW - timedelta(days=age_days_value)
    )
    assert recency_factor(features, now=NOW) == pytest.approx(expected, **APPROX)


@pytest.mark.parametrize(
    "helpful,unhelpful,expected",
    [(0, 0, 0.5), (1, 0, 0.6), (2, 0, 0.7), (0, 1, 0.3), (0, 2, 0.1), (0, 5, 0.0), (10, 0, 1.0), (2, 2, 0.3)],
)
def test_feedback_factor(helpful, unhelpful, expected):
    assert feedback_factor(Features(helpful=helpful, unhelpful=unhelpful)) == pytest.approx(expected, **APPROX)


def test_feature_score_matches_the_hand_computation():
    """0.60*1.0 + 0.15*0.5 + 0.10*0.5 + 0.10*0.8 + 0.05*0.5 = 0.83."""
    features = Features(
        importance=0.5,
        confidence=0.8,
        decay_class="standard",
        updated_at=NOW - timedelta(days=180),
    )
    assert recency_factor(features, now=NOW) == pytest.approx(0.5, **APPROX)
    assert feedback_factor(features) == pytest.approx(0.5, **APPROX)
    assert feature_score(1.0, features, now=NOW) == pytest.approx(0.83, **APPROX)


def test_feature_score_matches_the_hand_computation_again():
    """0.60*0.5 + 0.15*1.0 + 0.10*1.0 + 0.10*1.0 + 0.05*0.5 = 0.675."""
    features = Features(importance=1.0, confidence=1.0, decay_class="evergreen")
    assert feature_score(0.5, features, now=NOW) == pytest.approx(0.675, **APPROX)


def test_feature_score_stays_inside_zero_and_one():
    maximal = Features(importance=1.0, confidence=1.0, decay_class="evergreen", helpful=10)
    assert feature_score(1.0, maximal, now=NOW) == pytest.approx(1.0, **APPROX)
    minimal = Features(importance=0.0, confidence=0.0, decay_class="volatile",
                       updated_at=NOW - timedelta(days=10_000), unhelpful=5)
    assert feature_score(0.0, minimal, now=NOW) == pytest.approx(0.0, **APPROX)


def test_custom_weights_move_the_score():
    """`ranking.*` config will arrive in EM-407; the parameter works now."""
    features = Features(importance=1.0, confidence=1.0, decay_class="evergreen")
    only_rrf = RankWeights(rrf=1.0, importance=0.0, recency=0.0, confidence=0.0, feedback=0.0)
    assert feature_score(0.5, features, now=NOW, weights=only_rrf) == pytest.approx(0.5, **APPROX)


# --- ordering and explanation ---------------------------------------------


def _fused_single(owner_id: str):
    return fuse({"bm25": [mem(owner_id)]}, intent="lookup")


def test_a_candidate_without_features_is_dropped():
    """Features come from a scoped row load, so an absent key is not visible."""
    fused = fuse({"bm25": [mem("visible"), mem("hidden")]}, intent="lookup")
    features = {("memory", "visible"): Features()}
    got = rank(fused, features, now=NOW)
    assert [r.owner_id for r in got] == ["visible"]


def test_the_rerank_can_override_the_fusion_order():
    """The whole point of a rerank, and the reason the score is not just rrf_n.

    A rank-1 lexical hit and a rank-2 one differ by 0.6 * (1 - 61/62) ≈ 0.0097 in
    the final score, while the 0.10 recency term plus 0.20 for importance and
    confidence can swing far more than that. Here the rank-2 hit is a pinned,
    evergreen, important, confirmed one and the rank-1 hit is none of those.
    """
    fused = fuse({"bm25": [mem("stale"), mem("strong")]}, intent="lookup")
    assert fused[("memory", "stale")].rrf_n > fused[("memory", "strong")].rrf_n

    features = {
        ("memory", "stale"): Features(
            importance=0.0, confidence=0.0, decay_class="volatile",
            updated_at=NOW - timedelta(days=1000), unhelpful=5,
        ),
        ("memory", "strong"): Features(importance=1.0, confidence=1.0, decay_class="evergreen"),
    }
    assert [r.owner_id for r in rank(fused, features, now=NOW)] == ["strong", "stale"]


def test_the_tie_break_orders_by_updated_at_then_id():
    """§3.6's `(score desc, updated_at desc, id asc)`, exercised on a *real* tie.

    `bm25` and `vector` both weigh 1.0 under `lookup`, so two keys hitting one
    each at rank 1 have identical ``rrf_n``. But ``updated_at`` also feeds
    ``recency``, so simply varying it changes the score and the tie-break never
    runs — the first version of this test proved nothing.

    ``evergreen`` is what makes the tie reachable: its recency is 1.0 whatever the
    timestamp. The equality is asserted, not assumed, so the test cannot silently
    stop testing the tie-break.
    """
    fused = fuse({"bm25": [mem("a")], "vector": [mem("b")]}, intent="lookup")
    assert fused[("memory", "a")].rrf_n == pytest.approx(fused[("memory", "b")].rrf_n, **APPROX)

    newer_wins = {
        ("memory", "a"): Features(decay_class="evergreen", updated_at=NOW - timedelta(days=5)),
        ("memory", "b"): Features(decay_class="evergreen", updated_at=NOW),
    }
    score_a = feature_score(fused[("memory", "a")].rrf_n, newer_wins[("memory", "a")], now=NOW)
    score_b = feature_score(fused[("memory", "b")].rrf_n, newer_wins[("memory", "b")], now=NOW)
    assert score_a == pytest.approx(score_b, **APPROX), "the scores must tie for this to test the tie-break"
    assert [r.owner_id for r in rank(fused, newer_wins, now=NOW)] == ["b", "a"]

    same_time = {
        ("memory", "a"): Features(decay_class="evergreen", updated_at=NOW),
        ("memory", "b"): Features(decay_class="evergreen", updated_at=NOW),
    }
    assert [r.owner_id for r in rank(fused, same_time, now=NOW)] == ["a", "b"]

    no_time = {("memory", "a"): Features(decay_class="evergreen"), ("memory", "b"): Features(decay_class="evergreen")}
    assert [r.owner_id for r in rank(fused, no_time, now=NOW)] == ["a", "b"]

    # Insertion order must not decide it. `fuse` walks generators in sorted order,
    # so 'z' (bm25) is inserted before 'a' (vector) — if the id were left out of the
    # sort key, a stable sort would keep 'z' first.
    swapped = fuse({"bm25": [mem("z")], "vector": [mem("a")]}, intent="lookup")
    both = {("memory", "z"): Features(decay_class="evergreen"), ("memory", "a"): Features(decay_class="evergreen")}
    assert [r.owner_id for r in rank(swapped, both, now=NOW)] == ["a", "z"]


def test_the_explanation_is_signal_dicts_then_flags():
    fused = fuse({"bm25": [mem("a")], "entity": [mem("a")]}, intent="lookup")
    features = {("memory", "a"): Features()}
    (entry,) = rank(fused, features, now=NOW, flags={("memory", "a"): ["entity:Acme Corp"]})
    first, second, flag = entry.why
    assert (first["signal"], first["rank"]) == ("bm25", 1)
    assert first["contrib"] == pytest.approx(1.0 / 1.7, **APPROX)
    assert (second["signal"], second["rank"]) == ("entity", 1)
    assert second["contrib"] == pytest.approx(0.7 / 1.7, **APPROX)
    assert flag == "entity:Acme Corp"
    assert legacy_tokens(entry) == ["bm25", "entity", "entity:Acme Corp"]


def test_ranking_is_deterministic():
    fused = fuse({"bm25": [mem("a"), mem("b")], "entity": [mem("b")]}, intent="lookup")
    features = {("memory", "a"): Features(), ("memory", "b"): Features()}
    first = [r.owner_id for r in rank(fused, features, now=NOW)]
    for _ in range(5):
        assert [r.owner_id for r in rank(fused, features, now=NOW)] == first


# --- loading features from the store --------------------------------------


def test_load_features_reads_the_row_columns(store):
    mid = remember(
        store, "the staging server runs on port 9090", scope=ALICE,
        importance=0.9, confidence=0.7, pinned=True,
    )
    features = load_features(store.reader(), scope=ALICE, keys=[(OWNER_TYPE_MEMORY, mid)])[
        (OWNER_TYPE_MEMORY, mid)
    ]
    assert features.importance == pytest.approx(0.9, **APPROX)
    assert features.confidence == pytest.approx(0.7, **APPROX)
    assert features.pinned is True
    assert features.decay_class == "standard"
    assert features.updated_at is not None


def test_load_features_is_scoped_to_the_caller(store):
    """The last point before a row's content is shown, so the rule is re-applied."""
    ours = remember(store, "alice's own", scope=ALICE)
    theirs = remember(store, "bob's own", scope=BOB)
    keys = [(OWNER_TYPE_MEMORY, ours), (OWNER_TYPE_MEMORY, theirs)]
    found = load_features(store.reader(), scope=ALICE, keys=keys)
    assert set(found) == {("memory", ours)}


def test_load_features_will_not_load_a_profile_wide_row_stamped_visibility_user(store):
    """The Chunk 13 guard holds here too, through the same `scope_sql`."""
    mid = remember(store, "written for one user", scope=OWNER, visibility="user")
    assert load_features(store.reader(), scope=ALICE, keys=[(OWNER_TYPE_MEMORY, mid)]) == {}
    assert (OWNER_TYPE_MEMORY, mid) in load_features(
        store.reader(), scope=OWNER, keys=[(OWNER_TYPE_MEMORY, mid)]
    )


def test_load_features_ignores_a_row_that_is_not_active(store):
    mid = remember(store, "forgotten", scope=ALICE)
    with store.transaction() as conn:
        conn.execute("UPDATE memories SET status='deleted' WHERE id=?", (mid,))
    assert load_features(store.reader(), scope=ALICE, keys=[(OWNER_TYPE_MEMORY, mid)]) == {}


def test_load_features_maps_an_episode_with_its_named_defaults(store):
    eid = make_episode(store, scope=ALICE)
    features = load_features(store.reader(), scope=ALICE, keys=[(OWNER_TYPE_EPISODE, eid)])[
        (OWNER_TYPE_EPISODE, eid)
    ]
    assert features.confidence == pytest.approx(1.0, **APPROX)
    assert features.decay_class == "standard"
    assert features.pinned is False
    assert features.last_accessed_at is None
    assert features.helpful == 0 and features.unhelpful == 0


def test_load_features_handles_both_owner_types_at_once(store):
    mid = remember(store, "a memory", scope=ALICE)
    eid = make_episode(store, scope=ALICE)
    found = load_features(
        store.reader(),
        scope=ALICE,
        keys=[(OWNER_TYPE_MEMORY, mid), (OWNER_TYPE_EPISODE, eid)],
    )
    assert set(found) == {("memory", mid), ("episode", eid)}


# --- the end-to-end path --------------------------------------------------


def test_rank_candidates_fuses_loads_and_reranks(store):
    best = remember(store, "the staging server runs on port 9090", scope=ALICE, importance=1.0)
    also = remember(store, "another staging note", scope=ALICE, importance=0.2)
    results = {"bm25": [mem(best), mem(also)]}
    got = rank_candidates(
        store.reader(), results=results, scope=ALICE, intent="lookup", now=NOW
    )
    assert [r.owner_id for r in got] == [best, also]
    assert got[0].score > got[1].score
    assert got[0].why[0]["signal"] == "bm25"


def test_rank_candidates_drops_a_candidate_the_scope_cannot_read(store):
    ours = remember(store, "alice's own", scope=ALICE)
    theirs = remember(store, "bob's own", scope=BOB)
    got = rank_candidates(
        store.reader(),
        results={"bm25": [mem(theirs), mem(ours)]},
        scope=ALICE,
        intent="lookup",
        now=NOW,
    )
    assert [r.owner_id for r in got] == [ours]


def test_rank_candidates_flags_a_temporal_episode_hit(store):
    eid = make_episode(store, scope=ALICE, summary="about migrations")
    got = rank_candidates(
        store.reader(),
        results={"episodic": [ep(eid)]},
        scope=ALICE,
        intent="temporal",
        now=NOW,
        temporal_filter=True,
    )
    assert got[0].owner_id == eid
    assert "temporal_filter" in got[0].why


def test_rank_candidates_names_the_entity_flag(store):
    eid = remember(store, "Acme Corp signed the contract", scope=ALICE)
    got = rank_candidates(
        store.reader(),
        results={"entity": [mem(eid)]},
        scope=ALICE,
        intent="lookup",
        now=NOW,
        entity_names={"ent_1": "Acme Corp"},
    )
    assert "entity:Acme Corp" in got[0].why
    assert legacy_tokens(got[0]) == ["entity", "entity:Acme Corp"]
