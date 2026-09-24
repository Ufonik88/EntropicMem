"""EM-108 (L2): safe consolidate — importance-aware, non-destructive to
durable memory.

Candidate selection requires ALL of:
  importance < 0.6 · domain not evergreen · source not built_in/promoted ·
  no 'pinned' tag · age (from max(updated_at, last_accessed)) >= max_age ·
  access_count <= min_access_count
Candidates archive lowest-importance first. Archive rows keep sensitivity.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from memory_engine import MemoryEngine


@pytest.fixture
def engine(tmp_path):
    eng = MemoryEngine(tmp_path / "m.db", profile_id="test")
    yield eng
    eng.close()


def _stamp(engine, days_ago, *, fact_id=None):
    """Age rows by ISO timestamps (integer epochs break fromisoformat)."""
    ts = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    if fact_id:
        engine.db.execute(
            "UPDATE facts SET created_at=?, updated_at=?, last_accessed=? WHERE id=?",
            (ts, ts, ts, fact_id),
        )
    else:
        engine.db.execute(
            "UPDATE facts SET created_at=?, updated_at=?, last_accessed=?",
            (ts, ts, ts),
        )
    engine.db.commit()


def _archived(engine):
    # facts_archive is created lazily by the first real archive run
    if not engine.db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='facts_archive'"
    ).fetchone():
        return []
    return [r[0] for r in engine.db.execute("SELECT content FROM facts_archive").fetchall()]


def _run(engine, **kw):
    kw.setdefault("max_age_days", 90)
    kw.setdefault("min_access_count", 0)
    return engine.consolidate(dry_run=False, confirm=True, **kw)


class TestCandidateSelection:
    def test_high_importance_shielded(self, engine):
        engine.remember("high importance durable fact about family", domain="Work", importance=0.95)
        _stamp(engine, 120)
        _run(engine)
        assert _archived(engine) == []

    def test_evergreen_domain_shielded(self, engine):
        engine.remember("the user lives in a coastal city", domain="People", importance=0.5)
        _stamp(engine, 120)
        _run(engine)
        assert _archived(engine) == []

    def test_pinned_tag_shielded(self, engine):
        eid = engine.remember("pinned operational note about backups", domain="Work", importance=0.5)
        engine.db.execute("UPDATE facts SET tags=? WHERE id=?", ("pinned", eid))
        engine.db.commit()
        _stamp(engine, 120)
        _run(engine)
        assert _archived(engine) == []

    def test_built_in_and_promoted_shielded(self, engine):
        for src in ("built_in_memory", "promoted"):
            engine.remember(f"the {src} entry must survive", domain="Work",
                            importance=0.5, source=src)
        _stamp(engine, 120)
        _run(engine)
        assert _archived(engine) == []

    def test_age_from_most_recent_activity(self, engine):
        # created 120 days ago but touched yesterday -> not old enough
        eid = engine.remember("recently used low importance trivia fact", domain="Work", importance=0.5)
        ts_old = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()
        ts_new = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        engine.db.execute(
            "UPDATE facts SET created_at=?, updated_at=?, last_accessed=? WHERE id=?",
            (ts_old, ts_old, ts_new, eid),
        )
        engine.db.commit()
        _run(engine)
        assert _archived(engine) == []

    def test_low_value_old_fact_archived(self, engine):
        engine.remember("low value old trivia about a blue car", domain="Work", importance=0.1)
        _stamp(engine, 120)
        stats = _run(engine)
        assert stats["archived"] == 1
        assert any("blue car" in c for c in _archived(engine))


class TestArchiveOrder:
    def test_low_importance_archives_first(self, engine):
        engine.remember("low importance note about a blue car", domain="Work", importance=0.1)
        engine.remember("medium importance note about a train", domain="Work", importance=0.5)
        _stamp(engine, 120)
        _run(engine)
        order = [r[0] for r in engine.db.execute(
            "SELECT content FROM facts_archive ORDER BY rowid"
        ).fetchall()]
        assert any("blue car" in c for c in order)
        assert order.index(next(c for c in order if "blue car" in c)) < \
            order.index(next(c for c in order if "train" in c))


class TestArchiveRoundTrip:
    def test_archive_preserves_sensitivity(self, engine):
        eid = engine.remember("old secret vendor negotiation stance", domain="Work", importance=0.1)
        engine.db.execute("UPDATE facts SET sensitivity='secret' WHERE id=?", (eid,))
        engine.db.commit()
        _stamp(engine, 120)
        _run(engine)
        row = engine.db.execute(
            "SELECT sensitivity FROM facts_archive WHERE id=?", (eid,)
        ).fetchone()
        assert row is not None
        assert row[0] == "secret"

    def test_dry_run_reports_without_archiving(self, engine):
        engine.remember("old low value note about weather", domain="Work", importance=0.1)
        _stamp(engine, 120)
        stats = engine.consolidate(max_age_days=90, min_access_count=0)
        assert stats["would_archive"] == 1
        assert stats["archived"] == 0
        assert _archived(engine) == []
        # EM-108: dry-run reports the candidate list (id, title, age, importance)
        assert len(stats["candidates"]) == 1
        cand = stats["candidates"][0]
        assert set(cand) == {"id", "title", "age", "importance"}
        assert cand["importance"] == 0.1
        assert cand["age"] >= 90


class TestConsolidateToolGate:
    """EM-108: entropicmem_consolidate stays dry-run unless confirm=true AND
    config allow_agent_consolidate is enabled (default false)."""

    def _provider(self, make_provider, home_a, **cfg):
        from fake_host import FakeHost

        provider = make_provider(cfg)
        host = FakeHost(provider, hermes_home=home_a, agent_identity="homeA")
        host.start()
        provider.handle_tool_call(
            "entropicmem_remember",
            {"content": "old low value note about a blue car", "domain": "Work",
             "importance": 0.1},
        )
        return provider, host

    def test_stays_dry_run_without_opt_in(self, make_provider, home_a):
        provider, host = self._provider(make_provider, home_a)
        result = json.loads(provider.handle_tool_call(
            "entropicmem_consolidate",
            {"dry_run": False, "confirm": True, "max_age_days": 0},
        ))
        host.shutdown()
        assert result["dry_run"] is True
        assert result["archived"] == 0

    def test_real_run_with_confirm_and_opt_in(self, make_provider, home_a):
        provider, host = self._provider(
            make_provider, home_a, allow_agent_consolidate=True,
        )
        result = json.loads(provider.handle_tool_call(
            "entropicmem_consolidate",
            {"dry_run": False, "confirm": True, "max_age_days": 0},
        ))
        host.shutdown()
        assert result["dry_run"] is False
        assert result["archived"] == 1
