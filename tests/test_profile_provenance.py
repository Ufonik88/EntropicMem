"""P1 multi-profile provenance tests (spec: docs/MULTI_PROFILE_PROVENANCE_SPEC.md).

Covers the P1 acceptance contract:
- every insert/update stamps profile_id and bumps version
- audit_log.actor is the profile slug, never 'agent'
- writes are rejected while migration.lock is present (fail-closed)
- `migrate()` backfills legacy rows and stamps schema_info/profile_registry
- fact_timestamp is set at creation and preserved on update unless explicitly provided
"""
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "entropicmem" / "scripts"))
from memory_engine import MemoryEngine  # noqa: E402

OLD_SCHEMA = """
CREATE TABLE facts (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    title TEXT DEFAULT '',
    source TEXT DEFAULT 'agent',
    importance REAL DEFAULT 0.5,
    domain TEXT DEFAULT 'Knowledge',
    tags TEXT DEFAULT '',
    session_id TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_accessed TIMESTAMP,
    access_count INTEGER DEFAULT 0
);
CREATE VIRTUAL TABLE facts_fts USING fts5(
    content, title, tags, domain, tokenize='porter unicode61', content_rowid='rowid'
);
CREATE INDEX idx_facts_domain ON facts(domain);
"""


@pytest.fixture()
def engine(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "profiles" / "alpha"))
    eng = MemoryEngine(tmp_path / "memory.db", profile_id="alpha")
    yield eng
    eng.close()


def test_remember_stamps_profile_id_and_timestamp(engine):
    eid = engine.remember("provenance probe fact", source="test")
    row = engine.db.execute(
        "SELECT profile_id, fact_timestamp, version, deleted FROM facts WHERE id = ?", (eid,)
    ).fetchone()
    assert row["profile_id"] == "alpha"
    assert row["fact_timestamp"] is not None
    assert row["version"] == 1
    assert row["deleted"] == 0


def test_dedup_update_bumps_version_and_stamps_owner(engine):
    eid = engine.remember("version bump probe", source="test")
    eid2 = engine.remember("version bump probe", source="test")
    assert eid == eid2  # content-keyed dedup
    row = engine.db.execute(
        "SELECT profile_id, version FROM facts WHERE id = ?", (eid,)
    ).fetchone()
    assert row["profile_id"] == "alpha"
    assert row["version"] == 2


def test_fact_timestamp_preserved_on_update_unless_provided(engine):
    eid = engine.remember("timestamp probe", source="test", fact_timestamp="2026-01-01T00:00:00")
    engine.remember("timestamp probe", source="test")  # update without new timestamp
    row = engine.db.execute("SELECT fact_timestamp FROM facts WHERE id = ?", (eid,)).fetchone()
    assert row["fact_timestamp"] == "2026-01-01T00:00:00"  # never overwritten by a later writer
    engine.remember("timestamp probe", source="test", fact_timestamp="2026-02-01T00:00:00")
    row = engine.db.execute("SELECT fact_timestamp FROM facts WHERE id = ?", (eid,)).fetchone()
    assert row["fact_timestamp"] == "2026-02-01T00:00:00"  # explicit stamp wins


def test_audit_actor_is_profile_slug_never_agent(engine):
    engine.remember("audit actor probe", source="test")
    rows = engine.list_audit(limit=5)
    assert rows and all(r["actor"] == "alpha" for r in rows)
    assert not any(r["actor"] == "agent" for r in rows)


def test_writes_rejected_while_migration_lock_present(engine):
    lock = engine.db_path.parent / MemoryEngine.MIGRATION_LOCK_FILENAME
    lock.write_text("pid=test\n")
    try:
        with pytest.raises(RuntimeError, match="EM_MIGRATION_IN_PROGRESS"):
            engine.remember("must not land", source="test")
        count = engine.db.execute(
            "SELECT COUNT(*) FROM facts WHERE content = 'must not land'"
        ).fetchone()[0]
        assert count == 0
        # rejection is audited
        events = [r for r in engine.list_audit(limit=10) if r["action"] == "write_rejected"]
        assert events and events[0]["ok"] == 0
    finally:
        lock.unlink()


def test_migrate_backfills_legacy_rows(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "profiles" / "beta"))
    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(db)
    conn.executescript(OLD_SCHEMA)
    conn.execute(
        "INSERT INTO facts (id, content, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        ("legacy1", "old fact", "Old", "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
    )
    conn.commit()
    conn.close()

    eng = MemoryEngine(db, profile_id="beta")
    result = eng.migrate()
    assert result["profile"] == "beta"
    assert result["facts_backfilled"] == 1
    row = eng.db.execute(
        "SELECT profile_id, fact_timestamp, version FROM facts WHERE id = 'legacy1'"
    ).fetchone()
    assert row["profile_id"] == "beta"
    assert row["fact_timestamp"] == "2026-01-01T00:00:00"  # = created_at
    assert row["version"] == 1
    si = eng.db.execute("SELECT schema_version, phase FROM schema_info").fetchone()
    assert (si["schema_version"], si["phase"]) == (1, 1)
    reg = eng.db.execute("SELECT slug FROM profile_registry").fetchall()
    assert [r["slug"] for r in reg] == ["beta"]

    # idempotent: re-running is safe and reports zero newly-backfilled rows
    result2 = eng.migrate()
    assert result2["facts_backfilled"] == 0
    eng.close()


def test_migrate_is_fresh_store_safe(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "profiles" / "gamma"))
    eng = MemoryEngine(tmp_path / "fresh.db", profile_id="gamma")
    result = eng.migrate()
    assert result["facts_backfilled"] == 0
    si = eng.db.execute("SELECT schema_version, phase FROM schema_info").fetchone()
    assert (si["schema_version"], si["phase"]) == (1, 1)
    eng.close()


def test_profile_id_resolves_from_hermes_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "profiles" / "delta"))
    eng = MemoryEngine(tmp_path / "resolved.db")
    assert eng.profile_id() == "delta"
    eng.close()
    monkeypatch.delenv("HERMES_HOME")
    eng2 = MemoryEngine(tmp_path / "resolved2.db")
    assert eng2.profile_id() == "default"
    eng2.close()
