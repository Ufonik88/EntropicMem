"""EM-305 — the abstention gate (§3.6).

The card's first AC row: "abstention scenarios ≥ 0.95 correct". The scenario suite
is at the bottom; the unit tests above it pin the pieces it is built from, and the
first block is the trap this module exists for — coverage measured **post-stem**.

Invented data only (rule 4): Acme / Globex / Initech, Alice / Bob Example.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from em.retrieval.candidates import OWNER_TYPE_EPISODE, OWNER_TYPE_MEMORY  # noqa: E402
from em.retrieval.fusion import Ranking, Signal, fuse, load_features, rank  # noqa: E402
from em.retrieval.gate import (  # noqa: E402
    DEFAULT_GATE,
    GATE_MIN_COSINE,
    GATE_MIN_COVERAGE,
    GATE_MIN_SCORE,
    GateConfig,
    RowInfo,
    apply_gate,
    coverage,
    load_rows,
    supported,
)
from em.store.db import Store  # noqa: E402
from em.store.memories import MemoryStore  # noqa: E402
from em.store.migrations import migrate  # noqa: E402
from em.store.types import MemoryDraft, Scope  # noqa: E402

ALICE = Scope(profile="default", user="alice")
BOB = Scope(profile="default", user="bob")
OWNER = Scope(profile="default")
NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
APPROX = {"abs": 1e-9}


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path / "memory.db"))
    with s.writer() as conn:
        migrate(conn)
    yield s
    s.close()


def ranking(
    owner_id: str,
    score: float = 0.9,
    *,
    signals: tuple = ("bm25",),
    why: tuple = (),
    owner_type: str = OWNER_TYPE_MEMORY,
) -> Ranking:
    return Ranking(
        owner_type=owner_type,
        owner_id=owner_id,
        score=score,
        rrf=0.0,
        rrf_n=0.0,
        recency=0.0,
        feedback=0.0,
        signals=tuple(Signal(name, 1, 0.0) for name in signals),
        why=why,
    )


def remember(store, content, *, scope=ALICE, **kw) -> str:
    with store.transaction() as conn:
        result = MemoryStore(conn).add(
            MemoryDraft(content=content, **kw), scope=scope, actor="tester"
        )
    assert result.ok, result
    return result.id


# --- coverage, measured post-stem -----------------------------------------


def test_coverage_matches_across_stems_because_it_uses_the_fts_tokenizer():
    """The trap: `preferences` vs a stored `preferred`, `runs` vs `running`.

    A naive Python comparison gives 0.0 for both and the gate then abstains on an
    answer the generators had already found. `memories_fts` is porter-tokenized,
    so coverage has to be measured with that same tokenizer — which is what an
    FTS5 `MATCH` does and a Python `in` does not.
    """
    key = (OWNER_TYPE_MEMORY, "a")
    assert coverage(["preferences"], {key: "the user preferred concise answers"})[key] == pytest.approx(1.0)
    assert coverage(["runs"], {key: "the staging server running nightly"})[key] == pytest.approx(1.0)
    assert coverage(["staging"], {key: "the staging server"})[key] == pytest.approx(1.0)


def test_coverage_is_a_fraction_of_the_query_terms():
    key = (OWNER_TYPE_MEMORY, "a")
    texts = {key: "the staging server runs on port 9090"}
    assert coverage(["staging", "server"], texts)[key] == pytest.approx(1.0)
    assert coverage(["staging", "globex"], texts)[key] == pytest.approx(0.5)
    assert coverage(["globex"], texts)[key] == pytest.approx(0.0)


def test_coverage_is_per_candidate():
    first = (OWNER_TYPE_MEMORY, "a")
    second = (OWNER_TYPE_MEMORY, "b")
    got = coverage(["staging"], {first: "the staging server", second: "an unrelated note"})
    assert got[first] == pytest.approx(1.0)
    assert got[second] == pytest.approx(0.0)


def test_coverage_with_no_terms_is_zero_not_one():
    """A query of pure stopwords has earned no lexical claim.

    Answering "fully covered" here would let it through the gate on the strength
    of having asked nothing; 0.0 leaves it to the entity and pinned conditions.
    """
    key = (OWNER_TYPE_MEMORY, "a")
    assert coverage([], {key: "anything at all"})[key] == pytest.approx(0.0)
    assert coverage(["   "], {key: "anything at all"})[key] == pytest.approx(0.0)


def test_coverage_handles_no_texts():
    assert coverage(["staging"], {}) == {}


def test_coverage_is_safe_against_fts_metacharacters():
    """A quote or a caret in a term must not blow up the index."""
    key = (OWNER_TYPE_MEMORY, "a")
    got = coverage(['foo" OR bar', "a^b", "(c)", "wat*"], {key: "foobar and wat"})
    assert 0.0 <= got[key] <= 1.0


# --- the support test ------------------------------------------------------


def test_any_one_support_condition_is_enough():
    hit = ranking("a")
    assert supported(hit, coverage=GATE_MIN_COVERAGE, pinned=False, entity_hit=False) is True
    assert supported(hit, coverage=0.0, pinned=False, entity_hit=True) is True
    assert supported(hit, coverage=0.0, pinned=True, entity_hit=False) is True
    assert supported(hit, coverage=0.0, pinned=False, entity_hit=False) is False


def test_coverage_just_below_the_threshold_does_not_support():
    hit = ranking("a")
    assert supported(hit, coverage=0.33, pinned=False, entity_hit=False) is False
    assert supported(hit, coverage=0.34, pinned=False, entity_hit=False) is True


def test_the_cosine_condition_is_off_until_em_303_and_then_usable():
    hit = ranking("a")
    # Default: disabled, so a perfect cosine changes nothing.
    assert supported(hit, coverage=0.0, pinned=False, entity_hit=False, cosine=1.0,
                     model="all-MiniLM-L6-v2") is False

    enabled = GateConfig(cosine_enabled=True)
    assert supported(hit, coverage=0.0, pinned=False, entity_hit=False, cosine=0.5,
                     model="all-MiniLM-L6-v2", config=enabled) is True
    assert supported(hit, coverage=0.0, pinned=False, entity_hit=False, cosine=0.2,
                     model="all-MiniLM-L6-v2", config=enabled) is False
    # An unknown model has no threshold, so it cannot support on cosine alone.
    assert supported(hit, coverage=0.0, pinned=False, entity_hit=False, cosine=1.0,
                     model="some-other-model", config=enabled) is False
    # And the per-model defaults are §3.6's.
    assert GATE_MIN_COSINE == {"bge-small-en-v1.5": 0.62, "all-MiniLM-L6-v2": 0.38}


def test_the_defaults_are_3_6s():
    assert (GATE_MIN_COVERAGE, GATE_MIN_SCORE) == (0.34, 0.30)
    assert DEFAULT_GATE.min_coverage == 0.34 and DEFAULT_GATE.min_score == 0.30


# --- apply_gate ------------------------------------------------------------


def rows_for(*specs):
    return {key: RowInfo(text=text, scope_user=user, pinned=pinned)
            for key, text, user, pinned in specs}


def test_gate_keeps_supported_hits_above_the_score_threshold():
    kept = ranking("kept", 0.8)
    low = ranking("low", 0.10)
    result = apply_gate(
        [kept, low],
        rows=rows_for(
            (kept.key, "the staging server", "alice", False),
            (low.key, "the staging server", "alice", False),
        ),
        coverages={kept.key: 1.0, low.key: 1.0},
    )
    assert [r.owner_id for r in result.survivors] == ["kept"]


def test_gate_abstains_when_nothing_is_supported():
    weak = ranking("weak", 0.9)
    result = apply_gate(
        [weak],
        rows=rows_for((weak.key, "an unrelated note", "alice", False)),
        coverages={weak.key: 0.0},
    )
    assert result.empty is True
    assert result.keeps_only_pinned is False


def test_gate_lets_pinned_through_without_coverage_or_score():
    """§3.6's generator table: pinned "bypasses gate (still budgeted)"."""
    pinned = ranking("constraint", 0.01, signals=("pinned",))
    result = apply_gate(
        [pinned],
        rows=rows_for((pinned.key, "never deploy on fridays", "", True)),
        coverages={pinned.key: 0.0},
    )
    assert [r.owner_id for r in result.survivors] == ["constraint"]
    assert result.keeps_only_pinned is True


def test_gate_supports_an_entity_hit_without_coverage():
    entity = ranking("e", 0.9, signals=("entity",))
    result = apply_gate(
        [entity],
        rows=rows_for((entity.key, "Acme Corp signed the contract", "alice", False)),
        coverages={entity.key: 0.0},
    )
    assert [r.owner_id for r in result.survivors] == ["e"]
    assert result.keeps_only_pinned is False


def test_gate_drops_a_ranking_with_no_row():
    """Not visible, or no longer active: the gate is not where that is discovered."""
    ghost = ranking("ghost", 0.9)
    result = apply_gate([ghost], rows={}, coverages={ghost.key: 1.0})
    assert result.empty is True


def test_gate_thresholds_are_overridable():
    weak = ranking("weak", 0.31)
    rows = rows_for((weak.key, "the staging server", "alice", False))
    assert apply_gate([weak], rows=rows, coverages={weak.key: 1.0}).survivors
    strict = GateConfig(min_score=0.95)
    assert apply_gate([weak], rows=rows, coverages={weak.key: 1.0}, config=strict).empty


def test_gate_can_use_a_cosine_when_it_is_given_one():
    hit = ranking("h", 0.9)
    rows = rows_for((hit.key, "no query words here", "alice", False))
    enabled = GateConfig(cosine_enabled=True)
    assert apply_gate([hit], rows=rows, coverages={hit.key: 0.0}).empty
    kept = apply_gate(
        [hit], rows=rows, coverages={hit.key: 0.0}, cosines={hit.key: 0.9},
        model="all-MiniLM-L6-v2", config=enabled,
    )
    assert [r.owner_id for r in kept.survivors] == ["h"]


def test_gate_filters_but_does_not_reorder():
    """The gate is a filter; ordering is fusion's job and MMR's, not this stage's.

    The input is deliberately *not* in score order, so a gate that sorted would
    be caught rather than agreeing by luck.
    """
    lower, higher = ranking("lower", 0.4), ranking("higher", 0.9)
    rows = rows_for(
        (lower.key, "the staging server", "alice", False),
        (higher.key, "the staging server", "alice", False),
    )
    got = apply_gate([lower, higher], rows=rows, coverages={lower.key: 1.0, higher.key: 1.0})
    assert [r.owner_id for r in got.survivors] == ["lower", "higher"]


def test_the_gate_tokenizer_matches_the_index_tokenizer(store):
    """Pin the coupling, so a future index change cannot silently break coverage.

    `coverage` measures with `gate._TOKENIZE`. If migration 0002 ever changes
    `memories_fts`'s tokenizer and this constant does not follow, coverage starts
    measuring a different notion of "the same word" again — and because the gate is
    a hard filter, it would silently abstain on answers the generators had found.
    This reads the schema rather than restating the constant.
    """
    from em.retrieval.gate import index_tokenizer, tokenizer_matches_index

    assert index_tokenizer(store.reader()) == "porter unicode61 remove_diacritics 2"
    assert tokenizer_matches_index(store.reader()) is True


def test_a_missing_index_is_reported_rather_than_assumed(store):
    """A store without the FTS table reports an empty tokenizer, not a false match."""
    from em.retrieval.gate import index_tokenizer

    empty = Store(":memory:")
    with empty.writer() as conn:
        conn.execute("CREATE TABLE dummy (id INTEGER)")
    assert index_tokenizer(empty.reader()) == ""
    empty.close()


# --- load_rows -------------------------------------------------------------


def test_load_rows_returns_text_scope_and_pinned(store):
    mid = remember(store, "the staging server runs on port 9090", scope=ALICE, pinned=True)
    rows = load_rows(store.reader(), scope=ALICE, keys=[(OWNER_TYPE_MEMORY, mid)])
    info = rows[(OWNER_TYPE_MEMORY, mid)]
    assert "staging" in info.text
    assert info.scope_user == "alice"
    assert info.pinned is True


def test_load_rows_is_scoped(store):
    ours = remember(store, "alice's own", scope=ALICE)
    theirs = remember(store, "bob's own", scope=BOB)
    found = load_rows(
        store.reader(), scope=ALICE,
        keys=[(OWNER_TYPE_MEMORY, ours), (OWNER_TYPE_MEMORY, theirs)],
    )
    assert set(found) == {(OWNER_TYPE_MEMORY, ours)}


def test_load_rows_will_not_load_a_profile_wide_row_stamped_visibility_user(store):
    mid = remember(store, "written for one user", scope=OWNER, visibility="user")
    assert load_rows(store.reader(), scope=ALICE, keys=[(OWNER_TYPE_MEMORY, mid)]) == {}


def test_load_rows_ignores_a_row_that_is_not_active(store):
    mid = remember(store, "forgotten", scope=ALICE)
    with store.transaction() as conn:
        conn.execute("UPDATE memories SET status='deleted' WHERE id=?", (mid,))
    assert load_rows(store.reader(), scope=ALICE, keys=[(OWNER_TYPE_MEMORY, mid)]) == {}


def test_load_rows_uses_episode_title_and_summary_and_never_pins(store):
    from em.store.episodes import EpisodeStore

    with store.transaction() as conn:
        eid = EpisodeStore(conn).add_episode(
            scope=ALICE, kind="manual", title="Hub fleet migration",
            summary="decided the object numbers are hub IDs",
        )
    info = load_rows(store.reader(), scope=ALICE, keys=[(OWNER_TYPE_EPISODE, eid)])[
        (OWNER_TYPE_EPISODE, eid)
    ]
    assert "Hub fleet migration" in info.text and "object numbers" in info.text
    assert info.pinned is False


# --- the abstention scenarios (the AC) ------------------------------------

#: (query terms, stored text, should the gate surface it?). A query with no shared
#: vocabulary is the case §3.6's gate exists for.
ABSTENTION_SCENARIOS = (
    (("staging",), "the staging server runs on port 9090", True),
    (("staging", "server"), "the staging server runs on port 9090", True),
    (("staging",), "an unrelated note about invoicing", False),
    (("city", "based"), "The user lives in Cape Town", False),
    (("globex",), "an unrelated note about invoicing", False),
    (("invoicing",), "an unrelated note about invoicing", True),
    (("deploy",), "we deployed the plugin last week", True),
    # Porter does *not* stem "deployment" to "deploy", so neither the generator's
    # MATCH nor this gate would connect them — abstaining is correct, not a miss.
    (("deployment",), "we deploy nightly", False),
    (("preferences",), "the user preferred concise answers", True),
    (("quiesce",), "the vault path is configured", False),
    (("vault",), "the vault path is configured", True),
    (("acme",), "Acme Corp signed the contract", True),
    (("initech",), "Acme Corp signed the contract", False),
)


def test_abstention_scenarios_are_at_least_95_percent_correct():
    """AC: "abstention scenarios ≥ 0.95 correct"."""
    correct = 0
    for terms, text, expected in ABSTENTION_SCENARIOS:
        key = (OWNER_TYPE_MEMORY, "candidate")
        hit = ranking("candidate", 0.9)
        result = apply_gate(
            [hit],
            rows={key: RowInfo(text=text, scope_user="alice", pinned=False)},
            coverages=coverage(list(terms), {key: text}),
        )
        if bool(result.survivors) is expected:
            correct += 1
    accuracy = correct / len(ABSTENTION_SCENARIOS)
    assert accuracy >= 0.95, f"abstention accuracy {accuracy:.1%} is under the 95% budget"


# --- end to end through fusion --------------------------------------------


def test_the_gate_runs_on_fusion_output(store):
    on_topic = remember(store, "the staging server runs on port 9090", scope=ALICE)
    off_topic = remember(store, "the invoicing cycle closes on fridays", scope=ALICE)
    from em.retrieval.candidates import Candidate

    fused = fuse(
        {"bm25": [Candidate(OWNER_TYPE_MEMORY, on_topic, 1.0),
                  Candidate(OWNER_TYPE_MEMORY, off_topic, 1.0)]},
        intent="lookup",
    )
    ranked = rank(fused, load_features(store.reader(), scope=ALICE, keys=fused.keys()), now=NOW)
    rows = load_rows(store.reader(), scope=ALICE, keys=[r.key for r in ranked])
    coverages = coverage(["staging", "server"], {key: info.text for key, info in rows.items()})
    result = apply_gate(ranked, rows=rows, coverages=coverages)

    assert [r.owner_id for r in result.survivors] == [on_topic]
