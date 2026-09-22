"""Tests for D1 — Explainable Recall.

Every recall() / recall_with_relevance() / recall_hybrid() result must carry
a ``why_retrieved`` field listing the deterministic reason tokens that caused
this fact to surface in the result set.

Reason tokens: fts, vector, exact, recency, importance, triple, domain,
match_error (hits surfaced by the LIKE fallback after a rejected MATCH).
"""
import os
import sys
import tempfile
from pathlib import Path
from typing import List

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory_engine import MemoryEngine, StoredFact


@pytest.fixture
def engine():
    """Create a temporary in-memory-like engine on disk."""
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "test.db"
        eng = MemoryEngine(db)
        yield eng
        eng.close()


def _add_facts(engine, *contents, domain: str = "Knowledge"):
    """Remember one or more facts under the same domain."""
    for c in contents:
        engine.remember(c, domain=domain)


# ── D1.1: recall() carries why_retrieved ──────────────────────────────────


def test_recall_includes_why_retrieved(engine):
    """Every hit from recall() must have a non-empty why_retrieved."""
    _add_facts(engine,
        "The team uses EntropicMem as the memory provider for Hermes agents",
        "EntropicMem stores facts in SQLite with FTS5 search",
        domain="Knowledge",
    )
    hits = engine.recall("EntropicMem memory provider", top_k=5)
    assert hits, "expected at least one recall hit"
    for h in hits:
        assert hasattr(h, "why_retrieved"), f"StoredFact missing why_retrieved: {h.id}"
        assert isinstance(h.why_retrieved, list), f"why_retrieved must be list, got {type(h.why_retrieved)}"
        assert len(h.why_retrieved) > 0, f"why_retrieved must not be empty for recall hit {h.id}"


def test_recall_fts_reason_present(engine):
    """When FTS5 matches, at least one hit carries an 'fts' reason token."""
    _add_facts(engine,
        "The EntropicMem engine uses SQLite FTS5 for full-text search",
        domain="Knowledge",
    )
    hits = engine.recall("EntropicMem FTS5", top_k=5)
    assert hits
    fts_found = False
    for h in hits:
        tokens = _reason_strings(h)
        if "fts" in tokens:
            fts_found = True
            break
    assert fts_found, f"Expected 'fts' reason token in hits; got {[h.why_retrieved for h in hits]}"


def test_recall_exact_reason_present(engine):
    """An exact content match boosted first should carry an 'exact' reason."""
    fact = "This is a unique identifier phrase for exact match testing"
    _add_facts(engine, fact, domain="Knowledge")
    hits = engine.recall(fact, top_k=5)
    assert hits
    assert "exact" in _reason_strings(hits[0]), (
        f"First hit should be exact match; got {hits[0].why_retrieved}"
    )


def test_recall_domain_reason_present(engine):
    """When a domain filter is passed, 'domain' reason token must appear."""
    _add_facts(engine,
        "Hercules security alarm system migration", domain="Acme Corp",
    )
    _add_facts(engine,
        "EntropicMem uses SQLite for storage", domain="Infrastructure",
    )
    hits = engine.recall("security alarm", top_k=5, domain="Acme Corp")
    assert hits
    for h in hits:
        assert "domain" in _reason_strings(h), (
            f"Expected 'domain' reason when domain filter active; got {h.why_retrieved}"
        )


def test_recall_no_hits_empty_list(engine):
    """A query that matches nothing returns empty list — no crash."""
    hits = engine.recall("xyzzy nonexistent term", top_k=5)
    assert hits == []


# ── D1.2: recall_with_relevance() carries why_retrieved ───────────────────


def test_recall_with_relevance_includes_why_retrieved(engine):
    """Every hit from recall_with_relevance() must carry why_retrieved."""
    _add_facts(engine,
        "The EntropicMem engine uses SQLite FTS5 for full-text search",
        domain="Knowledge",
    )
    hits = engine.recall_with_relevance("EntropicMem engine", top_k=5)
    assert hits
    for h in hits:
        assert hasattr(h, "why_retrieved"), f"StoredFact missing why_retrieved: {h.id}"
        assert isinstance(h.why_retrieved, list)
        assert len(h.why_retrieved) > 0, f"why_retrieved must not be empty for {h.id}"


def test_recall_with_relevance_fts_reason_present(engine):
    """FTS5 scoring must produce an 'fts' reason token."""
    _add_facts(engine,
        "EntropicMem memory retrieval is fast and deterministic",
        domain="Knowledge",
    )
    hits = engine.recall_with_relevance("memory retrieval", top_k=5)
    assert hits
    fts_found = any("fts" in _reason_strings(h) for h in hits)
    assert fts_found, f"Expected 'fts' reason; got {[h.why_retrieved for h in hits]}"


def test_recall_with_relevance_recency_reason_present(engine):
    """Temporal decay enabled → 'recency' reason token should appear."""
    _add_facts(engine,
        "EntropicMem supports temporal decay scoring",
        domain="Knowledge",
    )
    hits = engine.recall_with_relevance(
        "temporal decay", top_k=5, decay_enabled=True,
    )
    assert hits
    recency_found = any("recency" in _reason_strings(h) for h in hits)
    assert recency_found, f"Expected 'recency' reason when decay enabled; got {[h.why_retrieved for h in hits]}"


def test_recall_with_relevance_importance_reason_present(engine):
    """Importance weighting must produce an 'importance' reason token."""
    _add_facts(engine,
        "High priority task for the EntropicMem project",
        domain="Knowledge",
    )
    hits = engine.recall_with_relevance("EntropicMem project", top_k=5)
    assert hits
    imp_found = any("importance" in _reason_strings(h) for h in hits)
    assert imp_found, f"Expected 'importance' reason; got {[h.why_retrieved for h in hits]}"


def test_recall_with_relevance_domain_reason_present(engine):
    """Domain filter on recall_with_relevance → 'domain' reason."""
    _add_facts(engine, "Acme Corp alarm migration", domain="Acme Corp")
    hits = engine.recall_with_relevance("alarm", top_k=5, domain="Acme Corp")
    assert hits
    for h in hits:
        assert "domain" in _reason_strings(h), (
            f"Expected 'domain' reason; got {h.why_retrieved}"
        )


def test_recall_with_relevance_like_fallback(engine):
    """FTS5 returns zero → LIKE fallback. Hits still carry why_retrieved."""
    _add_facts(engine,
        "Something very specific and unique here for testing",
        domain="Knowledge",
    )
    # Query using a term unlikely to match FTS5 prefix but present in LIKE
    hits = engine.recall_with_relevance("specific and unique", top_k=5)
    assert hits
    for h in hits:
        assert len(h.why_retrieved) > 0


# ── D1.3: recall_hybrid() carries why_retrieved ───────────────────────────


def test_recall_hybrid_includes_why_retrieved(engine):
    """recall_hybrid() results must carry why_retrieved (FTS5 fallback path)."""
    _add_facts(engine,
        "EntropicMem hybrid search combines FTS5 and vector similarity",
        domain="Knowledge",
    )
    hits = engine.recall_hybrid("hybrid search", top_k=5)
    assert hits
    for h in hits:
        assert hasattr(h, "why_retrieved"), f"StoredFact missing why_retrieved: {h.id}"
        assert isinstance(h.why_retrieved, list)
        assert len(h.why_retrieved) > 0


# ── D1.4: Plugin _recall includes why_retrieved in tool output ────────────


def test_plugin_recall_output_includes_why_retrieved():
    """The _recall() tool handler must include why_retrieved in each result dict."""
    import json
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        # Create a minimal mock scripts dir and vault
        scripts_dir = td_path / "scripts"
        scripts_dir.mkdir()
        # Write a tiny psutil stub so the plugin's ensure_scripts_on_path doesn't fail
        init_file = scripts_dir / "__init__.py"
        init_file.write_text("")

        # Write memory_engine module into scripts dir
        mem_eng = scripts_dir / "memory_engine.py"
        import shutil
        src = Path(__file__).resolve().parent.parent / "plugins" / "entropicmem" / "scripts" / "memory_engine.py"
        shutil.copy(str(src), str(mem_eng))

        # Write vault stub
        vault_file = scripts_dir / "vault.py"
        vault_file.write_text("""
def derive_title(content, max_len=80):
    return content[:max_len]
""")

        import sys
        sys.path.insert(0, str(scripts_dir))

        # Create the plugin instance with temp paths
        from plugins.entropicmem import EntropicMemMemoryProvider

        prov = EntropicMemMemoryProvider(config={
            "vault_path": str(td_path / "vault"),
            "index_db": str(td_path / "index.db"),
            "memory_db": str(td_path / "memory.db"),
        })
        # Fake initialize
        prov._scripts_dir = scripts_dir
        prov._hermes_home = td_path
        prov._memory_db = td_path / "memory.db"
        prov._session_id = "test_session"
        prov._memory_db.parent.mkdir(parents=True, exist_ok=True)

        # Seed a fact via _remember
        remember_args = {"content": "EntropicMem stores durable facts in SQLite", "domain": "Knowledge"}
        prov._remember(remember_args)

        # Now recall
        recall_args = {"query": "EntropicMem SQLite", "limit": 3}
        result_json = prov._recall(recall_args)
        result = json.loads(result_json)

        assert "results" in result, f"Recall should have 'results' key; got {list(result.keys())}"
        for r in result["results"]:
            assert "why_retrieved" in r, (
                f"Plugin recall result missing why_retrieved: {r}"
            )
            assert isinstance(r["why_retrieved"], list), (
                f"why_retrieved must be a list; got {type(r['why_retrieved'])}"
            )
            assert len(r["why_retrieved"]) > 0, (
                f"why_retrieved must not be empty for result {r['id']}"
            )


# ── D1.5: reason token format ─────────────────────────────────────────────


def test_why_retrieved_accepts_both_string_and_dict(engine):
    """The field must tolerate both plain string tokens and dict-with-score formats."""
    _add_facts(engine,
        "EntropicMem is the primary memory provider for the agent team",
        domain="Knowledge",
    )
    hits = engine.recall("memory provider", top_k=5)
    assert hits
    for h in hits:
        for item in h.why_retrieved:
            if isinstance(item, str):
                assert item in ("fts", "vector", "exact", "recency", "importance", "triple", "domain", "match_error"), (
                    f"Unexpected string reason token: {item}"
                )
            elif isinstance(item, dict):
                assert "signal" in item, f"Dict reason must have 'signal' key: {item}"


def test_storedfact_why_retrieved_is_list(engine):
    """StoredFact.why_retrieved must always be a list (default empty)."""
    f = StoredFact(id="test", content="test content")
    assert f.why_retrieved == [], "Default why_retrieved should be empty list"
    assert isinstance(f.why_retrieved, list)


# ── helpers ────────────────────────────────────────────────────────────────


def _reason_strings(fact: StoredFact) -> List[str]:
    """Extract plain string reason tokens from a fact's why_retrieved."""
    return [
        item if isinstance(item, str) else item.get("signal", "")
        for item in fact.why_retrieved
    ]
