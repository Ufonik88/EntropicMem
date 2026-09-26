"""0001 — baseline: bring any v2.x store (or an empty DB) to the v2.7 shape.

This is the frozen copy of v2's ``MemoryEngine._init_schema()`` required by
plan card EM-203. It is frozen deliberately: the v2 engine keeps evolving, and
a baseline migration must produce a byte-identical target shape forever or the
checksum in ``schema_migrations`` stops meaning anything.

Faithfulness notes (verified by running the real historical engines, see
``tests/fixtures/db/generate_fixtures.py``):

* Every statement is ``IF NOT EXISTS`` or guarded by a ``PRAGMA table_info``
  check, exactly as ``_init_schema`` did, so the migration is idempotent and
  safe on v2.3 / v2.5 / v2.7 / v2.8 databases alike. v2.3 lacks
  ``facts.{deleted,fact_timestamp,profile_id,version}``; the guarded ALTERs
  add them. v2.5 and v2.7 share an identical ``MEMORY_SCHEMA`` and
  ``_init_schema``, so they need no column work at all.
* ``embeddings`` is created when absent. v2 only created it when the optional
  sentence-transformer deps were importable, but the table is part of the
  product schema and EM-204 moves its rows, so having it always present is
  simpler and harmless.
* ``facts_archive`` is NOT created. ``_init_schema`` only upgraded it when
  ``consolidate()`` had already made it, and inventing DDL for it here would
  be a guess. When present, its columns are upgraded.
* ``SHARED_SCHEMA`` (``sync_events``) is intentionally excluded: that belongs
  to the separate shared store, not the per-profile memory DB.
* ``up()`` never commits. The runner owns transaction boundaries so a failure
  rolls the whole migration back (card AC).

Statements are executed one at a time rather than via ``executescript``:
``executescript`` issues an implicit COMMIT, which would break the runner's
atomicity guarantee.
"""

from __future__ import annotations

import sqlite3

VERSION = 1
NAME = "baseline_v27"

# Frozen from memory_engine.MEMORY_SCHEMA at v2.7.0 (commit 567aa00), which is
# identical to the v2.8.0 constant.
_BASE_STATEMENTS: tuple[str, ...] = (
    """CREATE TABLE IF NOT EXISTS facts (
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
        access_count INTEGER DEFAULT 0,
        profile_id TEXT DEFAULT '',
        fact_timestamp TEXT,
        version INTEGER NOT NULL DEFAULT 1,
        deleted INTEGER NOT NULL DEFAULT 0
    )""",
    """CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(
        content,
        title,
        tags,
        domain,
        tokenize='porter unicode61',
        content_rowid='rowid'
    )""",
    "CREATE INDEX IF NOT EXISTS idx_facts_domain ON facts(domain)",
    "CREATE INDEX IF NOT EXISTS idx_facts_importance ON facts(importance DESC)",
    "CREATE INDEX IF NOT EXISTS idx_facts_created ON facts(created_at DESC)",
    # P1 multi-profile provenance (2026-08-18)
    """CREATE TABLE IF NOT EXISTS schema_info (
        schema_version INTEGER NOT NULL DEFAULT 1,
        phase INTEGER NOT NULL DEFAULT 1,
        applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS profile_registry (
        slug TEXT PRIMARY KEY,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        renamed_to TEXT DEFAULT ''
    )""",
    # P2 controlled sync (2026-08-18)
    """CREATE TABLE IF NOT EXISTS sync_outbox (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fact_id TEXT NOT NULL,
        op TEXT NOT NULL,
        version INTEGER NOT NULL,
        written_at TEXT NOT NULL,
        fact_timestamp TEXT DEFAULT '',
        payload TEXT NOT NULL,
        emitted INTEGER NOT NULL DEFAULT 0
    )""",
    "CREATE INDEX IF NOT EXISTS idx_sync_outbox_emitted ON sync_outbox(emitted)",
    """CREATE TABLE IF NOT EXISTS sync_offsets (
        store_id TEXT PRIMARY KEY,
        last_event_seq INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS shared_facts (
        fact_id TEXT NOT NULL,
        origin_store TEXT NOT NULL,
        version INTEGER NOT NULL,
        written_at TEXT NOT NULL,
        fact_timestamp TEXT DEFAULT '',
        content TEXT NOT NULL,
        domain TEXT DEFAULT 'Knowledge',
        tags TEXT DEFAULT '',
        importance REAL DEFAULT 0.5,
        sensitivity TEXT DEFAULT 'internal',
        deleted INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (fact_id, origin_store)
    )""",
    # v2.2.0 G1: episodic memory
    """CREATE TABLE IF NOT EXISTS episodes (
        episode_id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        summary TEXT NOT NULL,
        start_ts TEXT,
        end_ts TEXT,
        source_session TEXT DEFAULT '',
        linked_fact_ids TEXT DEFAULT '[]',
        importance REAL DEFAULT 0.5,
        domain TEXT DEFAULT 'Knowledge',
        source TEXT DEFAULT 'agent',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""",
    "CREATE INDEX IF NOT EXISTS idx_episodes_start ON episodes(start_ts)",
    "CREATE INDEX IF NOT EXISTS idx_episodes_domain ON episodes(domain)",
    "CREATE INDEX IF NOT EXISTS idx_episodes_created ON episodes(created_at DESC)",
    """CREATE VIRTUAL TABLE IF NOT EXISTS episodes_fts USING fts5(
        title,
        summary,
        tokenize='porter unicode61',
        content_rowid='rowid'
    )""",
    # v2.2.0 G2: knowledge triples
    """CREATE TABLE IF NOT EXISTS triples (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        subject TEXT NOT NULL,
        predicate TEXT NOT NULL,
        object TEXT NOT NULL,
        valid_from TEXT,
        valid_until TEXT,
        source TEXT DEFAULT 'extracted',
        confidence REAL DEFAULT 1.0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(subject, predicate, object)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_triples_subject ON triples(subject)",
    "CREATE INDEX IF NOT EXISTS idx_triples_object ON triples(object)",
    "CREATE INDEX IF NOT EXISTS idx_triples_predicate ON triples(predicate)",
    # Phase 7: embeddings (v2 gated this on optional deps; see module docstring)
    """CREATE TABLE IF NOT EXISTS embeddings (
        fact_id TEXT PRIMARY KEY,
        vector BLOB NOT NULL,
        model TEXT DEFAULT 'all-MiniLM-L6-v2',
        dim INTEGER DEFAULT 384,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (fact_id) REFERENCES facts(id) ON DELETE CASCADE
    )""",
    "CREATE INDEX IF NOT EXISTS idx_embeddings_model ON embeddings(model)",
    # Phase 11.3: fact versioning
    """CREATE TABLE IF NOT EXISTS fact_versions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fact_id TEXT NOT NULL,
        content TEXT NOT NULL,
        importance REAL DEFAULT 0.5,
        domain TEXT DEFAULT 'Knowledge',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        source TEXT DEFAULT 'version_snapshot'
    )""",
    "CREATE INDEX IF NOT EXISTS idx_versions_fact ON fact_versions(fact_id, created_at DESC)",
    # Phase 2 security: audit + pending quarantine
    """CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        action TEXT NOT NULL,
        actor TEXT DEFAULT 'agent',
        session_id TEXT DEFAULT '',
        fact_id TEXT DEFAULT '',
        detail TEXT DEFAULT '',
        ok INTEGER DEFAULT 1
    )""",
    "CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts DESC)",
    """CREATE TABLE IF NOT EXISTS pending_facts (
        id TEXT PRIMARY KEY,
        content TEXT NOT NULL,
        title TEXT DEFAULT '',
        source TEXT DEFAULT 'auto_extracted',
        importance REAL DEFAULT 0.5,
        domain TEXT DEFAULT 'Knowledge',
        tags TEXT DEFAULT '',
        session_id TEXT DEFAULT '',
        reason TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""",
)

# (table, column, full ALTER) — SQLite has no ALTER ... ADD COLUMN IF NOT
# EXISTS, so each is guarded by a PRAGMA table_info check, as v2 did.
_COLUMN_UPGRADES: tuple[tuple[str, str, str], ...] = (
    ("facts", "last_accessed", "ALTER TABLE facts ADD COLUMN last_accessed TIMESTAMP"),
    ("facts", "access_count", "ALTER TABLE facts ADD COLUMN access_count INTEGER DEFAULT 0"),
    ("facts", "sensitivity", "ALTER TABLE facts ADD COLUMN sensitivity TEXT DEFAULT 'internal'"),
    ("facts", "profile_id", "ALTER TABLE facts ADD COLUMN profile_id TEXT DEFAULT ''"),
    ("facts", "fact_timestamp", "ALTER TABLE facts ADD COLUMN fact_timestamp TEXT"),
    (
        "facts",
        "version",
        "ALTER TABLE facts ADD COLUMN version INTEGER NOT NULL DEFAULT 1",
    ),
    (
        "facts",
        "deleted",
        "ALTER TABLE facts ADD COLUMN deleted INTEGER NOT NULL DEFAULT 0",
    ),
    (
        "facts_archive",
        "profile_id",
        "ALTER TABLE facts_archive ADD COLUMN profile_id TEXT DEFAULT ''",
    ),
    (
        "facts_archive",
        "version",
        "ALTER TABLE facts_archive ADD COLUMN version INTEGER NOT NULL DEFAULT 1",
    ),
    (
        "facts_archive",
        "sensitivity",
        "ALTER TABLE facts_archive ADD COLUMN sensitivity TEXT DEFAULT 'internal'",
    ),
)

_INDEXES_AFTER_UPGRADES: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS idx_facts_last_accessed ON facts(last_accessed DESC)",
    "CREATE INDEX IF NOT EXISTS idx_facts_profile ON facts(profile_id)",
)


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        is not None
    )


def _columns(conn: sqlite3.Connection, table: str) -> set:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def up(conn: sqlite3.Connection) -> None:
    """Bring ``conn`` to the exact v2.7 shape. Idempotent; never commits."""
    for statement in _BASE_STATEMENTS:
        conn.execute(statement)

    for table, column, alter in _COLUMN_UPGRADES:
        # facts_archive only exists once consolidate() has run; upgrading a
        # table that is not there would be an error, and creating it here
        # would not be faithful to _init_schema.
        if not _table_exists(conn, table):
            continue
        if column not in _columns(conn, table):
            conn.execute(alter)

    for statement in _INDEXES_AFTER_UPGRADES:
        conn.execute(statement)
