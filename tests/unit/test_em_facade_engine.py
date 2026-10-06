"""EM-211 Chunk 4: the v3 facade engine — its READ half over em.store.

``em.facade.engine.V3Engine`` keeps the v2 ``MemoryEngine`` API (the contract in
``em.facade.contract``) on top of the v3 store. This file covers the reads
Chunk 4 owns: ``get_fact`` (including the ``legacy_id`` resolution the
provider's mirror lookup depends on), ``stats``, ``recall_with_relevance``,
``recall_hybrid``, ``next_episode_wave``, construction, and the context
manager. The write methods are correctly-shaped stubs that raise
``NotImplementedError`` until the writes chunk lands; the contract test in
``tests/unit/test_em_facade_contract.py`` pins their signatures.

Seeding goes through ``MemoryStore.add`` directly — there is no facade write
path yet — and stamps ``legacy_id`` exactly the way the v2-to-v3 migration
does, which is what the read half of BEHAVIOURS["id-from-content"] requires.

Rules: invented data only (Acme/Globex/Initech, Alice/Bob Example).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from em.facade.engine import V3Engine  # noqa: E402
from em.store.memories import MemoryStore  # noqa: E402
from em.store.types import MemoryDraft  # noqa: E402


def seed(eng: V3Engine, content: str, *, title: str = "", domain: str = "Knowledge",
         tags: tuple[str, ...] = (), source: str = "agent", status: str = "active",
         legacy: bool = True) -> str:
    """Insert one memory through MemoryStore and stamp legacy_id.

    ``status='pending'`` is reached honestly — via the policy quarantine
    (source='auto_extracted') — because ``add`` deliberately promotes a
    caller's pending draft to active when policy allows. The legacy stamp
    mirrors the migration's rule (sha256(content)[:16]) so the read half of
    ``id-from-content`` is exercised for real.
    """
    from memory_engine import StoredFact

    if status == "pending":
        source = "auto_extracted"
    with eng.store.transaction() as conn:
        result = MemoryStore(conn).add(
            MemoryDraft(content=content, summary=title, domain=domain, tags=tags,
                        source=source, status=status),
            scope=eng.scope,
            actor="unit-test",
        )
        assert result.ok and result.decision in ("created", "quarantined"), result
        if legacy:
            conn.execute("UPDATE memories SET legacy_id=? WHERE id=?",
                         (StoredFact.make_id(content), result.id))
    return result.id


def set_status(eng: V3Engine, memory_id: str, status: str, reason: str) -> None:
    """Move a row through the §3.4 state machine (audited, not a raw UPDATE)."""
    with eng.store.transaction() as conn:
        r = MemoryStore(conn).set_status(memory_id, status, actor="unit-test", reason=reason)
        assert r.ok, r


@pytest.fixture
def engine(tmp_path):
    eng = V3Engine(tmp_path / "memory.db")
    yield eng
    eng.close()


# --- construction & lifecycle ---------------------------------------------


def test_engine_opens_a_v3_store(tmp_path):
    path = tmp_path / "memory.db"
    eng = V3Engine(path)
    try:
        version = eng.store.reader().execute("PRAGMA user_version").fetchone()[0]
        assert version >= 1
        tables = {r[0] for r in eng.store.reader().execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"memories", "episodes", "memories_fts"} <= tables
    finally:
        eng.close()


def test_engine_is_a_context_manager_and_reopens(tmp_path):
    path = tmp_path / "memory.db"
    with V3Engine(path) as eng:
        seed(eng, "Acme deploys with a blue-green rollout.")
    with V3Engine(path) as eng2:
        assert eng2.stats()["fact_count"] == 1


def test_reopen_after_an_exception_inside_with(tmp_path):
    path = tmp_path / "memory.db"
    with pytest.raises(RuntimeError):
        with V3Engine(path) as eng:
            seed(eng, "Globex keeps its staging cluster in Frankfurt.")
            raise RuntimeError("boom")
    with V3Engine(path) as eng2:
        assert eng2.stats()["fact_count"] == 1


# --- get_fact: the id-from-content read ------------------------------------


def test_get_fact_resolves_the_content_derived_legacy_id(engine):
    content = "Mirrored: Alice Example uses the example.com staging tenant."
    seed(engine, content, title=content[:60], domain="People",
         tags=("mirrored", "user"), source="built_in_memory")
    from memory_engine import StoredFact
    fact = engine.get_fact(StoredFact.make_id(content))
    assert fact is not None, "the provider's mirror lookup (make_id(content)) must resolve"
    assert fact.content == content
    assert "mirrored" in fact.tags
    assert fact.domain == "People"
    assert fact.title == content[:60], "v3 summary carries the v2 title"


def test_get_fact_resolves_the_v3_id_too(engine):
    mid = seed(engine, "Initech rotates API credentials every ninety days.", legacy=False)
    fact = engine.get_fact(mid)
    assert fact is not None and fact.id == mid, "no legacy stamp -> the v3 id is the view id"


def test_get_fact_legacy_id_replaces_the_view_id(engine):
    content = "Globex uses weekly release trains."
    mid = seed(engine, content)
    from memory_engine import StoredFact

    fact = engine.get_fact(mid)
    assert fact is not None and fact.id == StoredFact.make_id(content) != mid, (
        "id = legacy_id when the row carries one — the card's rule"
    )


def test_get_fact_unknown_id_returns_none(engine):
    assert engine.get_fact("deadbeefdeadbeef") is None


def test_get_fact_hides_deleted_rows(engine):
    content = "Bob Example owns the nightly backup verification job."
    mid = seed(engine, content)
    set_status(engine, mid, "deleted", "forget")
    assert engine.get_fact(mid) is None, "a deleted memory must read as absent"


# --- stats ------------------------------------------------------------------


def test_stats_counts_live_rows_per_domain(engine):
    assert engine.stats()["fact_count"] == 0
    seed(engine, "Acme's on-call rotation changes every Monday.")
    seed(engine, "Alice Example prefers short status updates on Fridays.", domain="People")
    mid = seed(engine, "Globex uses weekly release trains.")
    st = engine.stats()
    assert st["fact_count"] == 3
    assert st["domains"] == {"Knowledge": 2, "People": 1}
    set_status(engine, mid, "deleted", "forget")
    st = engine.stats()
    assert st["fact_count"] == 2, "deleted rows leave the count (v2 forget removed the row)"


# --- recall_with_relevance ---------------------------------------------------


def _seed_recall_corpus(engine) -> None:
    for content, domain in [
        ("Acme deploys the billing service with a blue-green rollout.", "Knowledge"),
        ("Globex keeps its staging cluster in the Frankfurt region.", "Knowledge"),
        ("Alice Example prefers short status updates on Fridays.", "People"),
        ("Initech rotates API credentials every ninety days.", "Knowledge"),
        ("Bob Example owns the nightly backup verification job.", "People"),
        ("The Acme billing service exposes metrics on port 9102.", "Knowledge"),
    ]:
        seed(engine, content, title=content[:40], domain=domain)


def test_recall_with_relevance_is_scored_sorted_and_filtered(engine):
    _seed_recall_corpus(engine)
    results = engine.recall_with_relevance("Acme billing service", top_k=5, min_relevance=0.05)
    assert results, "a query matching two seeded facts must return something"
    scores = [r.relevance_score for r in results]
    assert all(0.0 <= s <= 1.0 for s in scores), scores
    assert scores == sorted(scores, reverse=True)
    assert all(s >= 0.05 for s in scores)
    assert all(isinstance(r.why_retrieved, list) for r in results)
    assert "billing" in results[0].content.lower()


def test_recall_of_an_unrelated_query_returns_nothing_relevant(engine):
    _seed_recall_corpus(engine)
    results = engine.recall_with_relevance("zzqx nonexistent vocabulary", top_k=5, min_relevance=0.35)
    assert results == []


def test_recall_skips_pending_and_superseded_rows(engine):
    seed(engine, "Acme ships the billing service behind a feature flag.", status="pending")
    mid = seed(engine, "Acme billing runs on the Frankfurt stack.")
    set_status(engine, mid, "superseded", "supersede")
    results = engine.recall_with_relevance("Acme billing", top_k=5)
    assert results == [], "only active memories are recallable"


def test_recall_domain_filter(engine):
    _seed_recall_corpus(engine)
    results = engine.recall_with_relevance("backup verification", top_k=5, domain="People")
    assert results and all(r.domain == "People" for r in results)
    assert engine.recall_with_relevance("backup verification", top_k=5, domain="Finance") == []


def test_recall_top_k_bounds(engine):
    _seed_recall_corpus(engine)
    assert len(engine.recall_with_relevance("Acme", top_k=1)) <= 1


# --- recall_hybrid ------------------------------------------------------------


def test_recall_hybrid_without_vectors_still_answers(engine):
    _seed_recall_corpus(engine)
    results = engine.recall_hybrid("staging cluster region", top_k=3,
                                   fts_weight=0.6, vec_weight=0.4, expand_links=False)
    assert results and "Frankfurt" in results[0].content
    assert all(0.0 <= r.relevance_score <= 1.0 for r in results)


# --- next_episode_wave ----------------------------------------------------------


def test_next_episode_wave_counts_up_from_existing_legacy_wave_ids(engine):
    from em.store.episodes import EpisodeStore
    base = "ep_sess_demo"
    assert engine.next_episode_wave(base) == 1
    with engine.store.transaction() as conn:
        es = EpisodeStore(conn)
        es.add_episode(scope=engine.scope, kind="session", session_id="s1",
                       title="Wave 1", summary="Discussed the Acme rollout.",
                       legacy_id=f"{base}_w1")
        es.add_episode(scope=engine.scope, kind="session", session_id="s1",
                       title="Wave 2", summary="Reviewed the Globex region move.",
                       legacy_id=f"{base}_w2")
    assert engine.next_episode_wave(base) == 3
    assert engine.next_episode_wave("ep_sess_other") == 1


# --- find_mirrored: the v3-specific rules ---------------------------------------
#
# The cross-engine behaviour (substring match, the tag filter, the empty needle,
# a forgotten row) is pinned in tests/parity/test_engine_parity.py under the
# ``mirror-scan`` behaviour. What only v3 can get wrong is scope (invariant 5)
# and the §3.4 status filter, so those live here.


def test_find_mirrored_does_not_cross_a_scope_boundary(tmp_path):
    alice = V3Engine(tmp_path / "memory.db", scope_user="alice")
    bob = V3Engine(tmp_path / "memory.db", scope_user="bob")
    try:
        alice.remember(content="Alice Example prefers window seats on flights.",
                       tags=["mirrored", "user"], source="built_in_memory")
        assert alice.find_mirrored("window seats on flights") is not None
        assert bob.find_mirrored("window seats on flights") is None, (
            "one user's mirror must not be located through another user's scope"
        )
    finally:
        alice.close()
        bob.close()


def test_find_mirrored_sees_a_profile_wide_mirror_from_any_scope(tmp_path):
    """§3.5's minimum viable read rule: a profile-wide row is visible to a user."""
    owner = V3Engine(tmp_path / "memory.db")
    guest = V3Engine(tmp_path / "memory.db", scope_user="alice")
    try:
        owner.remember(content="Globex keeps its staging cluster in Frankfurt.",
                       tags=["mirrored", "user"], source="built_in_memory")
        assert owner.find_mirrored("staging cluster in Frankfurt") is not None
        assert guest.find_mirrored("staging cluster in Frankfurt") is not None
    finally:
        owner.close()
        guest.close()


def test_find_mirrored_ignores_an_archived_mirror(engine):
    mid = engine.remember(content="Initech rotated credentials in 2025.",
                          tags=["mirrored", "user"], source="built_in_memory")
    assert engine.find_mirrored("rotated credentials") is not None
    with engine.store.transaction() as conn:
        MemoryStore(conn).set_status(mid, "archived", actor="unit-test",
                                     reason="consolidate")
    assert engine.find_mirrored("rotated credentials") is None, (
        "only an active mirror is locatable; an archived one is out of the live set"
    )


def test_find_mirrored_needs_a_parsable_tag_list(engine):
    """The SQL ``LIKE`` is only a pre-filter; the parsed list decides.

    Both of these rows match ``tags LIKE '%"mirrored"%'``, so without the parse
    step the scan would call them mirrors. One cannot be parsed at all and the
    other decodes to a bare string, where ``"mirrored" in "mirrored"`` is a
    substring test rather than a membership test.
    """
    mid = engine.remember(content="Acme ships on Tuesdays.", tags=["mirrored"],
                          source="built_in_memory")
    assert engine.find_mirrored("ships on Tuesdays") is not None

    for malformed in ('["a","mirrored","b"', '"mirrored"'):
        with engine.store.transaction() as conn:
            conn.execute("UPDATE memories SET tags=? WHERE id=?", (malformed, mid))
        assert engine.find_mirrored("ships on Tuesdays") is None, (
            f"tags={malformed!r} matched the pre-filter but is not a tag list"
        )


def test_find_mirrored_returns_an_id_the_engine_can_act_on(engine):
    """The provider feeds the result straight into forget(); it must resolve."""
    content = "Bob Example owns the nightly backup verification job."
    engine.remember(content=content, tags=["mirrored", "user"],
                    source="built_in_memory")
    found = engine.find_mirrored("nightly backup verification")
    assert found
    assert engine.get_fact(found) is not None
    assert engine.forget(found, confirm=True) is True
    assert engine.find_mirrored("nightly backup verification") is None


# --- write methods --------------------------------------------------------------


def test_write_methods_keep_their_shapes(engine):
    """The signatures the contract test binds, now on real implementations.

    Chunk 4 asserted these were stubs; Chunk 5 replaced them. What must survive
    is the *shape*, because ``PROVIDER_CALLS`` is derived from the provider's
    source by AST scan — a renamed or re-ordered parameter fails that test.
    """
    import inspect

    def sig(name):  # unbound signatures, like the contract test binds them
        return inspect.signature(getattr(V3Engine, name))

    assert sig("remember").bind(
        object(), content="x", title="", source="agent", importance=0.5,
        domain="Knowledge", tags=None, session_id="", sensitivity=None, actor=None)
    assert sig("forget").bind(object(), "id", confirm=True)
    assert sig("touch").bind(object(), ["id"])
    assert sig("add_episode").bind(object(), "t", "s", start_ts=None)
    assert sig("consolidate").bind(object(), max_age_days=90, dry_run=True)
    assert sig("extract_and_store").bind(object(), user_text="u")
    assert sig("prune_pending").bind(object(), older_than_days=30)
    for name in ("remember", "forget", "touch", "add_episode", "consolidate",
                 "extract_and_store", "prune_pending"):
        assert not getattr(V3Engine, name).__doc__.startswith("EM-211 writes chunk"), name
