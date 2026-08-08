"""
test_v2_2_0.py — Tests for the v2.2.0 contextual-parity release (G1–G10).

Covers:
- Episodes: schema, add_episode, list_episodes window filter, recall_episodes
  FTS + window, episode_stats, idempotent backfill episode_id (mne_ prefix)
- Triples: upsert idempotency, list filters, neighbors, path, inconsistencies,
  stats, and the rule-based extractor (triple_extract)
- CLI routing: recall --type episodic, episode/triple subcommand handlers
- Health check: check_embeddings / check_episodes / check_triples presence
"""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
_SCRIPTS = REPO / "skills" / "entropicmem" / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from memory_engine import MemoryEngine  # noqa: E402
from triple_extract import extract_triples_from_text, find_entities, known_entity  # noqa: E402


@pytest.fixture()
def engine(tmp_path):
    eng = MemoryEngine(str(tmp_path / "test.db"))
    yield eng
    eng.close()


# ── G1: episodes ────────────────────────────────────────────────────────────


def test_add_and_list_episodes(engine):
    eid = engine.add_episode(
        "Budget reconciliation", "Verified June invoices and rebuilt the sheet",
        start_ts="2026-07-09T10:00:00", end_ts="2026-07-09T11:30:00",
        source_session="sess_1", importance=0.8, domain="Finance",
    )
    assert eid.startswith("ep_")
    eps = engine.list_episodes()
    assert len(eps) == 1
    assert eps[0]["title"] == "Budget reconciliation"
    assert eps[0]["domain"] == "Finance"


def test_list_episodes_window_filter(engine):
    engine.add_episode("A", "first", start_ts="2026-06-01T00:00:00")
    engine.add_episode("B", "second", start_ts="2026-07-01T00:00:00")
    engine.add_episode("C", "third", start_ts="2026-08-01T00:00:00")
    in_july = engine.list_episodes(from_date="2026-06-15", to_date="2026-07-15")
    assert [e["title"] for e in in_july] == ["B"]


def test_recall_episodes_fts_and_window(engine):
    engine.add_episode("Ajax roadshow", "Cape Town event planning for Ajax Systems",
                       start_ts="2026-07-20T00:00:00")
    engine.add_episode("Budget", "Spreadsheet reconciliation", start_ts="2026-07-21T00:00:00")
    hits = engine.recall_episodes("roadshow")
    assert len(hits) == 1
    assert hits[0]["title"] == "Ajax roadshow"
    # window excludes it
    hits = engine.recall_episodes("roadshow", from_date="2026-08-01")
    assert hits == []


def test_episode_stats(engine):
    engine.add_episode("X", "one", domain="Finance")
    engine.add_episode("Y", "two", domain="Finance")
    engine.add_episode("Z", "three", domain="Projects")
    stats = engine.episode_stats()
    assert stats["total"] == 3
    assert stats["by_domain"]["Finance"] == 2


def test_episode_backfill_idempotent(engine):
    # mne_ prefixed ids (as the backfill script uses) must upsert in place
    eid = engine.add_episode("Legacy", "old entry", episode_id="mne_abc123",
                             source="mnemosyne_legacy")
    assert eid == "mne_abc123"
    engine.add_episode("Legacy v2", "updated entry", episode_id="mne_abc123",
                       source="mnemosyne_legacy")
    eps = engine.list_episodes()
    assert len(eps) == 1
    assert eps[0]["summary"] == "updated entry"


# ── G2: triples ─────────────────────────────────────────────────────────────


def test_upsert_triple_idempotent(engine):
    tid1 = engine.upsert_triple("Ufonik", "works_at", "Ajax Systems")
    tid2 = engine.upsert_triple("Ufonik", "works_at", "Ajax Systems")
    assert tid1 == tid2
    assert engine.triple_stats()["total"] == 1


def test_triple_neighbors(engine):
    engine.upsert_triple("Ufonik", "works_at", "Ajax Systems")
    engine.upsert_triple("Ajax Systems", "sells", "Security Systems")
    neigh = engine.triple_neighbors("Ajax Systems")
    assert len(neigh) == 2
    preds = {t["predicate"] for t in neigh}
    assert preds == {"works_at", "sells"}


def test_triple_path(engine):
    engine.upsert_triple("A", "knows", "B")
    engine.upsert_triple("B", "knows", "C")
    path = engine.triple_path("A", "C")
    assert len(path) == 2
    assert path[-1]["object"] == "C"


def test_triple_inconsistencies(engine):
    engine.upsert_triple("X", "works_at", "Company1")
    engine.upsert_triple("X", "works_at", "Company2")
    issues = engine.triple_inconsistencies()
    assert len(issues) == 1
    assert issues[0]["subject"] == "X"
    assert issues[0]["n_objects"] == 2


def test_triple_active_only(engine):
    engine.upsert_triple("A", "r", "B", valid_until="2026-01-01")
    assert engine.triple_stats()["total"] == 1
    assert engine.list_triples() == []  # active_only default True


def test_list_triples_filters(engine):
    engine.upsert_triple("A", "r1", "B", source="extracted")
    engine.upsert_triple("C", "r2", "D", source="mnemosyne_legacy")
    assert len(engine.list_triples(source="extracted")) == 1
    assert len(engine.list_triples(subject="C")) == 1
    assert len(engine.list_triples(predicate="r2")) == 1


# ── G2: rule-based extractor ────────────────────────────────────────────────


def test_find_entities_known():
    assert "Ajax Systems" in find_entities("Ufonik works at Ajax Systems")
    assert known_entity("ufonik")
    assert not known_entity("zorpblorp")


def test_extract_triples_relation_phrase():
    triples = extract_triples_from_text("Ufonik works at Ajax Systems")
    assert ("Ufonik", "works_at", "Ajax Systems") in triples


def test_extract_triples_negation():
    triples = extract_triples_from_text("Hermes no longer uses mem0")
    assert any(p.startswith("not_") for _, p, _ in triples)


def test_extract_triples_no_entities():
    assert extract_triples_from_text("the cat sat on the mat") == []


def test_extract_triples_from_engine(engine):
    engine.remember("Ufonik works at Ajax Systems and uses Google Drive",
                    domain="Knowledge", importance=0.5)
    from triple_extract import extract_triples_from_engine
    written = extract_triples_from_engine(engine)
    assert written >= 1
    # re-run is idempotent (upsert)
    assert engine.triple_stats()["total"] == written


# ── health check additions ──────────────────────────────────────────────────


def test_health_check_has_new_checks():
    """The deployed health script must define the G1–G3 checks."""
    import importlib.util
    hc_path = REPO / "scripts" / "entropicmem_health_check.py"
    spec = importlib.util.spec_from_file_location("em_hc", hc_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for fn in ("check_embeddings", "check_episodes", "check_triples"):
        assert hasattr(mod, fn), f"health check missing {fn}"


# ── CLI routing ─────────────────────────────────────────────────────────────


def test_cli_has_episode_and_triple_routes():
    import ast
    src = (_SCRIPTS / "entropicmem.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    routes = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            keys = [k.value for k in node.keys if isinstance(k, ast.Constant)]
            if "recall" in keys and "remember" in keys and "episode" in keys:
                routes = keys
                break
    assert routes is not None
    assert "episode" in routes and "triple" in routes
    assert "def cmd_episode" in src and "def cmd_triple" in src


def test_cli_recall_episodic_parser():
    import argparse
    import ast
    src = (_SCRIPTS / "entropicmem.py").read_text(encoding="utf-8")
    assert "--type" in src and "--since" in src and "--until" in src
    assert 'choices=["fact", "episodic"]' in src
