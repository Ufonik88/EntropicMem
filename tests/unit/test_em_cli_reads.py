"""EM-211 Chunk 10.1: the facade's CLI-compatibility reads.

The CLI's `_engine()` still builds the v2 engine. These methods let it be pointed
at the facade (Chunk 10.4) without breaking the read commands, so they return the
shape **each CLI command prints** — not a v3 shape. The tests therefore assert the
CLI's keys, verbatim from the call sites in `entropicmem.py`:

* `memory list` / lint print `f.id`, `f.domain`, `f.content` (a `StoredFact`)
* `pending list` prints `r["id"], r["domain"], r["reason"], r["content"]`
* `audit` prints `r["ts"], r["action"], r["ok"], r["fact_id"], r["detail"]`
* `history` marks `versions[0]` "(current)" and prints `v["content"]`, `v["created_at"]`
* `episode list` prints `ep["episode_id"]`, `ep.get("start_ts")`, `ep["title"]`, `ep["summary"]`
* `episode stats` prints `stats["total"]` then `stats["by_domain"].items()`
* `embed` prints `stats["available"]` / `stats["message"]`

Where v2 could do something v3 cannot, the method refuses by name; the tests pin
that too, because a silent partial answer is the failure mode worth guarding.

Rules: invented data only.
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
from em.store.types import MemoryPatch  # noqa: E402


@pytest.fixture
def engine(tmp_path):
    eng = V3Engine(tmp_path / "memory.db")
    yield eng
    eng.close()


def test_list_facts_returns_storedfacts_in_importance_order(engine):
    """`memory list` does `f.id / f.domain / f.content` on each row."""
    low = engine.remember(content="Acme keeps an old runbook.", importance=0.2)
    high = engine.remember(content="Globex runs the billing service.", importance=0.9)

    facts = engine.list_facts()
    # Order is by importance DESC (v2's rule). `id` is the content-derived legacy
    # id — the same value `remember` stamped and the card's rule for StoredFact.id.
    assert [f.content for f in facts][:2] == [
        "Globex runs the billing service.",
        "Acme keeps an old runbook.",
    ]
    from memory_engine import StoredFact

    assert facts[0].id == StoredFact.make_id("Globex runs the billing service.")
    assert facts[0].domain == "Knowledge"
    assert high and low  # the v3 ids are what remember returned; reads present legacy


def test_list_facts_filters_by_domain_and_limit(engine):
    engine.remember(content="Acme ships on Tuesdays.", domain="Knowledge")
    engine.remember(content="Alice Example prefers Fridays.", domain="People")

    people = engine.list_facts(domain="People")
    assert len(people) == 1 and people[0].domain == "People"
    assert len(engine.list_facts(limit=1)) == 1


def test_list_facts_hides_owner_only_rows_from_a_guest(tmp_path):
    """A listing must not become a way around the §3.5 rule."""
    owner = V3Engine(tmp_path / "memory.db")
    owner.remember(content="Acme holds the payroll master key.", sensitivity="sensitive")
    owner.close()
    guest = V3Engine(tmp_path / "memory.db", scope_user="alice")
    try:
        assert guest.list_facts() == []
    finally:
        guest.close()


def test_list_pending_uses_the_v2_key_names(engine):
    engine.remember(content="Acme used a legacy deploy script.", source="auto_extracted")
    engine.remember(content="Globex ships on Tuesdays.")  # active, not pending

    rows = engine.list_pending()
    assert len(rows) == 1
    row = rows[0]
    assert set(row) == {"id", "content", "domain", "source", "importance", "reason", "created_at"}
    assert row["content"] == "Acme used a legacy deploy script."
    assert row["reason"], "v3's pending_reason must arrive as v2's `reason`"


def test_list_audit_uses_the_v2_key_names_and_is_newest_first(engine):
    mid = engine.remember(content="Acme deploys on Tuesdays.")

    rows = engine.list_audit(limit=10)
    assert rows, "a write is audited"
    row = rows[0]
    assert set(row) == {"id", "ts", "action", "actor", "session_id", "fact_id", "detail", "ok"}
    assert row["action"] == "add"
    assert row["fact_id"] == mid, "v3's target_id must arrive as v2's fact_id"
    assert row["ok"] is True
    ids = [r["id"] for r in rows]
    assert ids == sorted(ids, reverse=True), "newest first, as v2 ordered by id DESC"


def test_get_versions_matches_v2s_pre_edit_snapshots(engine):
    """v2's `get_versions` held *pre-edit* snapshots, newest first — verified.

    v2 wrote a version row only before an edit (`snapshot_version`); v3 also
    writes one at creation, so the first edit would list its content twice. The
    facade collapses consecutive identical contents, which reproduces v2 exactly:
    create A, update B, update C -> [B, A], and the current content C is not a
    version (v2 did not snapshot the live state either).
    """
    mid = engine.remember(content="A", importance=0.4)
    with engine.store.transaction() as conn:
        store = MemoryStore(conn)
        store.update(mid, MemoryPatch(content="B"), actor="tester", reason="edit")
        store.update(mid, MemoryPatch(content="C"), actor="tester", reason="edit")

    versions = engine.get_versions(mid)
    assert [v["content"] for v in versions] == ["B", "A"], "newest pre-edit snapshot first"
    assert set(versions[0]) == {"content", "importance", "domain", "created_at", "source"}
    assert versions[0]["created_at"], "v3's changed_at must arrive as v2's created_at"
    assert engine.get_fact(mid).content == "C", "the live content is not a version row"


def test_get_versions_resolves_a_content_derived_id(engine):
    """The CLI validates the id the user typed; a legacy id must work too."""
    from memory_engine import StoredFact

    content = "Globex uses weekly release trains."
    engine.remember(content=content)
    assert engine.get_versions(StoredFact.make_id(content)), "legacy id resolves"


def test_get_versions_of_an_unknown_id_is_empty(engine):
    assert engine.get_versions("mem_does_not_exist") == []


def test_episode_stats_counts_by_kind_not_domain(engine):
    engine.add_episode(title="Wave 1", summary="Body.", source_session="s1",
                       episode_id="ep_s1_w1")
    engine.add_episode(title="Wave 2", summary="Body.", source_session="s1",
                       episode_id="ep_s1_w2")

    stats = engine.episode_stats()
    assert stats["total"] == 2
    assert stats["by_domain"] == {}, "v3 has no per-episode domain; the key stays present"
    assert stats["by_kind"] == {"session": 2}, "the real breakdown is offered alongside"


def test_embedding_stats_reports_the_v3_state(engine):
    stats = engine.embedding_stats()
    assert stats["available"] is False, "no embedder is wired on v3 yet (EM-303)"
    assert "message" in stats


def test_list_episodes_uses_the_v2_episode_id_key(engine):
    engine.add_episode(title="First", summary="Body one.", source_session="s1",
                       episode_id="ep_s1_w1", start_ts="2026-01-01T00:00:00.000Z")
    engine.add_episode(title="Second", summary="Body two.", source_session="s1",
                       episode_id="ep_s1_w2", start_ts="2026-02-01T00:00:00.000Z")

    eps = engine.list_episodes()
    # `episode_id` is the id `add_episode` handed back (the v3 id), which is what
    # `episode add` prints — a round trip through the CLI stays consistent.
    assert [e["title"] for e in eps] == ["First", "Second"], "chronological"
    assert all(e["episode_id"].startswith("ep_") for e in eps)
    assert eps[0]["title"] == "First"
    assert eps[0]["summary"] == "Body one."
    assert eps[0]["start_ts"] == "2026-01-01T00:00:00.000Z"


def test_list_episodes_honours_the_date_window(engine):
    engine.add_episode(title="Jan", summary="b", source_session="s1",
                       episode_id="ep_a_w1", start_ts="2026-01-15T00:00:00.000Z")
    engine.add_episode(title="Feb", summary="b", source_session="s1",
                       episode_id="ep_b_w1", start_ts="2026-02-15T00:00:00.000Z")

    jan = engine.list_episodes(from_date="2026-01-01", to_date="2026-01-31")
    assert [e["title"] for e in jan] == ["Jan"]
    assert len(engine.list_episodes(from_date="2025-01-01")) == 2


def test_list_episodes_refuses_the_v2_only_domain_filter(engine):
    """v3 episodes carry `kind`. Ignoring the filter would look like a right answer."""
    with pytest.raises(ValueError, match="domain"):
        engine.list_episodes(domain="Knowledge")


def test_recall_scope_own_maps_to_the_scoring_path(engine):
    engine.remember(content="Acme deploys the billing service.")
    results = engine.recall("Acme billing service", top_k=5)
    assert results and results[0].content.startswith("Acme")


def test_recall_refuses_the_shared_scopes(engine):
    """`shared`/`all` need the shared publish store, which v3 lacks (S5)."""
    for scope in ("shared", "all"):
        with pytest.raises(ValueError, match="S5"):
            engine.recall("anything", scope=scope)
