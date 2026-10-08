"""P0b — the v3 facade's read half, served from §3.6's pipeline behind a flag.

The seam is ``V3Engine.recall_with_relevance``: with ``ENTROPICMEM_V3_RETRIEVAL=1``
it calls ``em.retrieval.pipeline.retrieve`` — the one shared pipeline the eval
adapter and the shadow read call — and maps the memory rankings back into v2
``StoredFact``s; with the flag unset it is the v2 scoring the facade borrows,
byte-identical to the pre-P0b code (pinned as a golden captured before the flag
existed, not re-derived here).

What is asserted, rather than inspected:

* the flag is strict (``"1"`` only) and defaults off;
* the off path cannot reach the v3 pipeline — a ``retrieve`` that raises is never
  called — and still returns the golden answer;
* the on path really goes through ``pipeline.retrieve`` with the gate, and serves
  what v2 scoring cannot: a §3.6 pinned constraint, including ``kind='constraint'``
  rows (the gate loads both forms — a defect P0b's end-to-end run found);
* the on path keeps the v2 fact shape (legacy ids, fields, a flat why list) so the
  provider's renderer is untouched, and skips episode rankings — the one recorded
  omission, because a fact has no episode shape and §3.6's renderer is EM-307's;
* ``top_k``, ``domain``, empty queries and the §3.5 owner-only tier still hold.

Invented data only (rule 4): Acme / Globex / Initech, Alice / Bob Example.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
for _entry in (str(REPO), str(SCRIPTS)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from em.facade.engine import (  # noqa: E402
    V3_RETRIEVAL_ENV,
    V3Engine,
    v3_retrieval_enabled,
)
from em.store.db import Store  # noqa: E402
from em.store.episodes import EpisodeStore  # noqa: E402
from em.store.memories import MemoryStore  # noqa: E402
from em.store.types import MemoryDraft, Scope  # noqa: E402
from memory_engine import StoredFact  # noqa: E402

PROFILE = Scope(profile="default")
#: Fixed stamps, so a score/count assertion cannot drift with the wall clock.
STAMP = "2026-01-15T00:00:00Z"
QUERY = "what port does the staging server use"
STAGING = "the staging server runs on port 9090"
CONSTRAINT = "never deploy on fridays"
EPISODE_QUERY = "hub fleet migration"

#: The pre-P0b golden: ``recall_with_relevance`` over the fixture below, captured
#: from the commit before the flag existed. Changing it because *v2 scoring* changed
#: is allowed, but then the change to the off path needs its own reasoning and a
#: CHANGELOG line — the whole point of the golden is that the flag's off path does
#: not silently become the v3 ranking.
OFF_GOLDEN = [
    {
        "id": StoredFact.make_id(STAGING),
        "content": STAGING,
        "domain": "Infrastructure",
        "importance": 0.8,
        "score": 0.8856,
        "why": ["fts", "recency", "importance", {"signal": "coverage", "value": 0.75}],
    }
]


@dataclass
class Seeded:
    db: Path
    staging_v2_id: str
    constraint_id: str
    episode_id: str


def seed(tmp_path: Path, *, constraint: bool = True) -> Seeded:
    """One v3 store: a staging fact (profile-wide, so it carries a legacy id), a
    billing fact, optionally a ``kind='constraint'`` row, and one episode."""
    db = tmp_path / "memory.db"
    engine = V3Engine(db)
    engine.remember(
        STAGING, title="Staging server", domain="Infrastructure", importance=0.8
    )
    engine.remember(
        "nightly billing job reconciles invoices", domain="Knowledge", importance=0.5
    )
    engine.close()

    store = Store(str(db))
    constraint_id = ""
    with store.transaction() as conn:
        if constraint:
            result = MemoryStore(conn).add(
                MemoryDraft(
                    content=CONSTRAINT,
                    kind="constraint",
                    importance=0.9,
                    source="agent",
                    status="active",
                ),
                scope=PROFILE,
                actor="tester",
            )
            assert result.ok, result
            constraint_id = result.id
        episode_id = EpisodeStore(conn).add_episode(
            scope=PROFILE,
            kind="manual",
            title="Hub fleet migration",
            summary="decided the object numbers are hub ids",
        )
    with store.transaction() as conn:
        conn.execute(
            "UPDATE memories SET created_at=?, updated_at=?, last_accessed_at=NULL",
            (STAMP, STAMP),
        )
    store.close()
    assert episode_id, "the fixture must have an episode to skip"
    return Seeded(
        db=db,
        staging_v2_id=StoredFact.make_id(STAGING),
        constraint_id=constraint_id,
        episode_id=episode_id,
    )


@pytest.fixture(autouse=True)
def _flag_off_by_default(monkeypatch):
    """Tests must not inherit an ambient flag; each one sets what it needs."""
    monkeypatch.delenv(V3_RETRIEVAL_ENV, raising=False)


def _view(hit) -> dict:
    return {
        "id": hit.id,
        "content": hit.content,
        "domain": hit.domain,
        "importance": hit.importance,
        "score": round(hit.relevance_score, 4),
        "why": hit.why_retrieved,
    }


# --- the flag -------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, False), ("1", True), ("0", False), ("true", False), ("yes", False), ("", False)],
)
def test_the_flag_is_strict_and_defaults_off(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv(V3_RETRIEVAL_ENV, raising=False)
    else:
        monkeypatch.setenv(V3_RETRIEVAL_ENV, value)
    assert v3_retrieval_enabled() is expected


# --- the off path is the pre-P0b behaviour --------------------------------


def test_the_off_path_is_byte_identical_to_the_pre_p0b_golden(monkeypatch, tmp_path):
    seeded = seed(tmp_path)
    with V3Engine(seeded.db) as engine:
        hits = engine.recall_with_relevance(QUERY, top_k=5, min_relevance=0.0)
    assert [_view(hit) for hit in hits] == OFF_GOLDEN


def test_the_off_path_cannot_reach_the_v3_pipeline(monkeypatch, tmp_path):
    """The golden above could in principle be reproduced by a v3 ranking.

    A ``retrieve`` that raises proves the off path never calls it and still
    answers — the two guards are independent.
    """
    seeded = seed(tmp_path)

    import em.retrieval.pipeline as pipeline

    def explode(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("pipeline.retrieve ran with the flag off")

    monkeypatch.setattr(pipeline, "retrieve", explode)
    with V3Engine(seeded.db) as engine:
        hits = engine.recall_with_relevance(QUERY, top_k=5, min_relevance=0.0)
    assert [_view(hit) for hit in hits] == OFF_GOLDEN


# --- the on path is the one shared pipeline -------------------------------


def test_the_on_path_calls_the_shared_pipeline_with_the_gate(monkeypatch, tmp_path):
    seeded = seed(tmp_path)

    import em.retrieval.pipeline as pipeline

    calls = []
    real = pipeline.retrieve

    def spy(conn, **kwargs):  # noqa: ANN001, ANN003
        calls.append(kwargs)
        return real(conn, **kwargs)

    monkeypatch.setattr(pipeline, "retrieve", spy)
    monkeypatch.setenv(V3_RETRIEVAL_ENV, "1")
    with V3Engine(seeded.db) as engine:
        hits = engine.recall_with_relevance(QUERY, top_k=5)

    assert len(calls) == 1, "the facade must call the one pipeline, once"
    assert calls[0]["query"] == QUERY
    assert calls[0]["scope"] == PROFILE
    assert calls[0]["with_gate"] is True, "prefetch is the gated view"
    assert [hit.id for hit in hits] == [seeded.staging_v2_id, seeded.constraint_id]


def test_the_on_path_serves_the_constraint_v2_scoring_cannot_see(monkeypatch, tmp_path):
    """The differential, end to end: §3.6's pinned generator surfaces a
    ``kind='constraint'`` row with no lexical overlap, and the gate lets it
    through (REMAINING_PLAN §6.2's generator table: "bypasses gate")."""
    seeded = seed(tmp_path)
    with V3Engine(seeded.db) as engine:
        off = engine.recall_with_relevance(QUERY, top_k=5)
    assert [hit.id for hit in off] == [seeded.staging_v2_id]

    monkeypatch.setenv(V3_RETRIEVAL_ENV, "1")
    with V3Engine(seeded.db) as engine:
        on = engine.recall_with_relevance(QUERY, top_k=5)
    assert [hit.id for hit in on] == [seeded.staging_v2_id, seeded.constraint_id]
    assert on[-1].why_retrieved == ["pinned"]


def test_the_on_path_abstains_when_nothing_survives_the_gate(monkeypatch, tmp_path):
    seeded = seed(tmp_path, constraint=False)
    monkeypatch.setenv(V3_RETRIEVAL_ENV, "1")
    with V3Engine(seeded.db) as engine:
        hits = engine.recall_with_relevance(
            "orbital decay of a geosynchronous satellite", top_k=5
        )
    assert hits == []


def test_the_on_path_skips_episode_rankings(monkeypatch, tmp_path):
    """A recorded omission: the pipeline ranks episodes, a v2 fact has no episode
    shape, and §3.6's renderer is EM-307's — so the served list is memories only."""
    seeded = seed(tmp_path, constraint=False)

    from em.retrieval.pipeline import retrieve

    with V3Engine(seeded.db) as engine:
        ranked = retrieve(
            engine._reader(), scope=PROFILE, query=EPISODE_QUERY, with_gate=True
        )
    assert seeded.episode_id in ranked.ids, "the fixture must rank the episode at all"

    monkeypatch.setenv(V3_RETRIEVAL_ENV, "1")
    with V3Engine(seeded.db) as engine:
        served = engine.recall_with_relevance(EPISODE_QUERY, top_k=5)
    assert [hit.id for hit in served] == []


# --- the fact shape the provider renders -----------------------------------


def test_the_on_path_returns_v2_shaped_facts(monkeypatch, tmp_path):
    seeded = seed(tmp_path)
    monkeypatch.setenv(V3_RETRIEVAL_ENV, "1")
    with V3Engine(seeded.db) as engine:
        hits = engine.recall_with_relevance(QUERY, top_k=5)

    staging = hits[0]
    assert staging.id == seeded.staging_v2_id == StoredFact.make_id(STAGING)
    assert staging.content == STAGING
    assert staging.title == "Staging server"
    assert staging.domain == "Infrastructure"
    assert staging.importance == 0.8
    assert staging.source == "agent"
    assert staging.created_at == STAMP and staging.updated_at == STAMP
    assert isinstance(staging.tags, list)
    assert 0.0 <= staging.relevance_score <= 1.0
    assert isinstance(staging.why_retrieved, list) and staging.why_retrieved


def test_the_on_path_honours_top_k_domain_and_empty_queries(monkeypatch, tmp_path):
    seeded = seed(tmp_path)
    monkeypatch.setenv(V3_RETRIEVAL_ENV, "1")
    with V3Engine(seeded.db) as engine:
        assert [hit.id for hit in engine.recall_with_relevance(QUERY, top_k=1)] == [
            seeded.staging_v2_id
        ]
        assert [
            hit.id
            for hit in engine.recall_with_relevance(QUERY, top_k=5, domain="Infrastructure")
        ] == [seeded.staging_v2_id]
        assert engine.recall_with_relevance(QUERY, top_k=5, domain="People") == []
        # An empty query is empty on both paths, even though a pinned row exists.
        assert engine.recall_with_relevance("", top_k=5) == []
        # top_k=0 is "up to none" on both paths, not "the first one".
        assert engine.recall_with_relevance(QUERY, top_k=0) == []


def test_the_read_verbs_all_follow_the_one_seam(monkeypatch, tmp_path):
    seeded = seed(tmp_path)
    monkeypatch.setenv(V3_RETRIEVAL_ENV, "1")
    with V3Engine(seeded.db) as engine:
        direct = [hit.id for hit in engine.recall_with_relevance(QUERY, top_k=5)]
        via_recall = [hit.id for hit in engine.recall(QUERY, top_k=5)]
        via_hybrid = [hit.id for hit in engine.recall_hybrid(QUERY, top_k=5)]
    assert via_recall == direct
    assert via_hybrid == direct


def test_the_on_path_still_applies_the_owner_only_tier(monkeypatch, tmp_path):
    """§3.5 rides on the pipeline's own scope clause and the row re-read."""
    seeded = seed(tmp_path)
    sensitive = "sensitive content about Acme's payroll run."
    store = Store(str(seeded.db))
    with store.transaction() as conn:
        result = MemoryStore(conn).add(
            MemoryDraft(
                # `sensitive`, not `secret`: the write policy blocks a secret tier
                # outright (only a migration can produce one), as the owner-only
                # suite records.
                content=sensitive,
                sensitivity="sensitive",
                importance=0.9,
                source="agent",
                status="active",
            ),
            scope=PROFILE,
            actor="tester",
        )
    assert result.ok, result
    store.close()

    monkeypatch.setenv(V3_RETRIEVAL_ENV, "1")
    with V3Engine(seeded.db, scope_user="alice", is_owner=False) as guest:
        guest_hits = guest.recall_with_relevance("Acme payroll run", top_k=5)
    assert sensitive not in [hit.content for hit in guest_hits]
    assert [hit.content for hit in guest_hits] == [CONSTRAINT], (
        "the owner-only row is gone; only the profile-wide pinned constraint remains"
    )
    with V3Engine(seeded.db, is_owner=True) as owner:
        owner_hits = owner.recall_with_relevance("Acme payroll run", top_k=5)
    assert sensitive in [hit.content for hit in owner_hits], "the owner still reads it"
