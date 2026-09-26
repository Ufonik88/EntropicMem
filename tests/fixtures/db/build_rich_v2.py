"""Build a rich synthetic v2.7 database exercising every EM-204 edge case.

Used by ``tests/unit/test_em_migration_v3_core.py``. Deliberately opens the
builder connection with ``foreign_keys=OFF`` because that is what the v2 engine
does (it never sets the pragma, and SQLite's default is off). Real v2 stores
therefore accumulate orphans that would be impossible under v3's enforced
foreign keys -- e.g. ``embeddings``/``fact_versions`` rows whose ``fact_id`` no
longer resolves. EM-204 has to tolerate exactly that, so the fixture has to
produce it honestly rather than being unable to represent it.

Shapes covered (each one observed in a live 1570-fact v2.8.0 store):

* duplicate normalised content among ACTIVE facts (would violate v3's
  ``ux_mem_hash_scope``) and within ``pending_facts``
* every ``kind`` rule input: domain People, source built_in_memory, a
  ``preference`` tag, a ``Preference:`` prefix, importance >= 0.75
* ``deleted=1`` rows
* all three v2 timestamp shapes plus an unparseable one
* empty ``profile_id`` (resolved-profile fallback)
* comma-string, already-JSON and empty ``tags``
* out-of-range ``importance`` and an invalid ``sensitivity``
* ``facts_archive`` (only exists after ``consolidate()`` in v2)
* orphan ``fact_versions`` and orphan ``embeddings``
* all four episode kinds, including manual episodes sharing one session
* triples naming a ``KNOWN_ENTITIES`` entry (entity kind mapping)
* ``audit_log`` details in free-text, JSON and NULL forms
* tables v3 does not model (``graph_edges``, ``notes_meta``) that must survive
* a sync table whose ``fact_id`` must stay a legacy id
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

NOW_ISO = "2026-09-20T10:00:00.000000+00:00"
NAIVE = "2026-04-24T08:25:58.514370"
SQLITE_TS = "2026-08-08 08:03:10"

#: legacy ids the tests assert against
DUP_IDS = ("dup1", "dup2", "dup3")
ORPHAN_FACT = "MISSING_FACT"


def build(path: Path) -> dict:
    """Create a v2.7-shaped DB at ``path`` and return its per-table row counts.

    ``path`` must already have the v2.7 schema (apply migration ``0001`` with a
    baseline-only registry first).
    """
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    # v2 does not enable FK enforcement; reproduce that faithfully.
    conn.execute("PRAGMA foreign_keys=OFF")

    def fact(
        fid,
        content,
        *,
        title="t",
        source="agent_tool",
        importance=0.5,
        domain="Knowledge",
        tags="",
        session="s1",
        created=NOW_ISO,
        profile="default",
        deleted=0,
        version=1,
        sens="internal",
        ts=None,
    ):
        conn.execute(
            "INSERT INTO facts (id, content, title, source, importance, domain,"
            " tags, session_id, created_at, updated_at, last_accessed,"
            " access_count, profile_id, fact_timestamp, version, deleted,"
            " sensitivity) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                fid,
                content,
                title,
                source,
                importance,
                domain,
                tags,
                session,
                created,
                created,
                created,
                3,
                profile,
                ts if ts is not None else created,
                version,
                deleted,
                sens,
            ),
        )

    # 1) duplicate normalised content among ACTIVE facts
    fact("dup1", "entropicmem", source="auto_extracted", created="2026-07-22T17:53:52.772550+00:00")
    fact("dup2", "ENTROPICMEM", source="auto_extracted", created="2026-07-23T10:05:11.026611+00:00")
    fact("dup3", "  EntropicMem.  ", source="auto_extracted", created="2026-07-23T10:31:58.610496+00:00")
    # 2) every kind rule input
    fact("k_people", "Alice works at Globex", domain="People")
    fact("k_builtin", "mirrored builtin memory", source="built_in_memory")
    fact("k_tagpref", "prefers concise replies", tags="preference, style")
    fact("k_prefix", "Preference: dark mode")
    fact("k_evergreen", "high importance fact", importance=0.9)
    # 3) soft-deleted
    fact("gone", "soft deleted fact", deleted=1)
    # 4) the three v2 timestamp shapes + one unparseable
    fact("ts_iso", "iso offset ts", created=NOW_ISO, ts=NOW_ISO)
    fact("ts_naive", "naive ts", created=NAIVE, ts=NAIVE)
    fact("ts_sqlite", "sqlite CURRENT_TIMESTAMP ts", created=SQLITE_TS, ts=SQLITE_TS)
    fact("ts_bad", "unparseable ts", created="not-a-timestamp")
    # 5) empty profile_id -> resolved profile
    fact("no_prof", "no profile id", profile="")
    # 6) tag formats
    fact("tags_multi", "multi tag", tags="durable, agent,globex")
    fact("tags_json", "json tag", tags='["a","b"]')
    fact("tags_empty", "no tags", tags="")
    # 7) out-of-range / invalid enum values
    fact("imp_hi", "importance too high", importance=1.7)
    fact("imp_lo", "importance negative", importance=-0.5)
    fact("sens_odd", "odd sensitivity", sens="weird")
    # 8) a high version number
    fact("v23", "fact with high version", version=7)

    # pending_facts, including an internal duplicate pair
    for pid, content in (("p1", "hermes setup"), ("p2", "HERMES SETUP"), ("p3", "unique pending")):
        conn.execute(
            "INSERT INTO pending_facts (id, content, title, source, importance,"
            " domain, tags, session_id, reason, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (pid, content, "t", "auto_extracted", 0.5, "Knowledge", "", "s1", "low_confidence", NOW_ISO),
        )

    # facts_archive (only exists after consolidate() in v2)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS facts_archive (
            id TEXT PRIMARY KEY, content TEXT NOT NULL, title TEXT DEFAULT '',
            source TEXT DEFAULT 'agent', importance REAL DEFAULT 0.5,
            domain TEXT DEFAULT 'Knowledge', tags TEXT DEFAULT '',
            session_id TEXT DEFAULT '', created_at TIMESTAMP, updated_at TIMESTAMP,
            last_accessed TIMESTAMP, access_count INTEGER DEFAULT 0,
            profile_id TEXT DEFAULT '', version INTEGER NOT NULL DEFAULT 1,
            sensitivity TEXT DEFAULT 'internal',
            archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"""
    )
    conn.execute(
        "INSERT INTO facts_archive (id, content, title, source, importance, domain,"
        " tags, session_id, created_at, updated_at, profile_id, version,"
        " sensitivity, archived_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("a1", "archived fact", "t", "agent", 0.3, "Knowledge", "", "s1", NOW_ISO, NOW_ISO, "default", 1, "internal", NOW_ISO),
    )

    # fact_versions: two real + one ORPHAN
    for vid, fid, content in ((1, "dup1", "v1 content"), (2, "dup1", "v2 content"), (3, ORPHAN_FACT, "orphan version")):
        conn.execute(
            "INSERT INTO fact_versions (id, fact_id, content, importance, domain, created_at, source)"
            " VALUES (?,?,?,?,?,?,?)",
            (vid, fid, content, 0.5, "Knowledge", NOW_ISO, "version_snapshot"),
        )

    # episodes: all four kinds; the two manual ones share a session
    episodes = [
        ("ep_sess_abc", "Session episode", "sum", "20260920_100000_abc"),
        ("ep_precomp_1", "Precompress", "sum", "20260920_100000_abc"),
        ("ep_sess_abc_w1", "Window 1", "sum", "20260920_100000_abc"),
        ("ep_manual_1", "Manual one", "sum", "shared_session"),
        ("ep_manual_2", "Manual two", "sum", "shared_session"),
    ]
    for eid, title, summary, session in episodes:
        conn.execute(
            "INSERT INTO episodes (episode_id, title, summary, start_ts, end_ts,"
            " source_session, linked_fact_ids, importance, domain, source, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (eid, title, summary, NAIVE, NAIVE, session, "[]", 0.6, "Knowledge", "agent", SQLITE_TS),
        )

    # triples, one subject being a KNOWN_ENTITIES name
    for subject, predicate, obj in (
        ("EntropicMem", "is_a", "project"),
        ("Alice", "works_at", "Globex Corp"),
        ("EntropicMem", "uses", "SQLite"),
    ):
        conn.execute(
            "INSERT INTO triples (subject, predicate, object, valid_from,"
            " valid_until, source, confidence, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (subject, predicate, obj, None, None, "extracted", 0.9, NOW_ISO),
        )

    # embeddings: one real + one ORPHAN (only representable with FK off)
    conn.execute(
        "INSERT INTO embeddings (fact_id, vector, model, dim, created_at) VALUES (?,?,?,?,?)",
        ("dup1", b"\x01\x02", "all-MiniLM-L6-v2", 384, NOW_ISO),
    )
    conn.execute(
        "INSERT INTO embeddings (fact_id, vector, model, dim, created_at) VALUES (?,?,?,?,?)",
        ("MISSING", b"\x03", "all-MiniLM-L6-v2", 384, NOW_ISO),
    )

    # audit_log: free-text, JSON and NULL details
    conn.execute(
        "INSERT INTO audit_log (id, ts, action, actor, session_id, fact_id, detail, ok)"
        " VALUES (1,?,?,?,?,?,?,?)",
        (SQLITE_TS, "remember", "agent", "s1", "dup1", "domain=Infrastructure;tier=internal", 1),
    )
    conn.execute(
        "INSERT INTO audit_log (id, ts, action, actor, session_id, fact_id, detail, ok)"
        " VALUES (2,?,?,?,?,?,?,?)",
        (NOW_ISO, "remember", "agent", "s1", "dup2", '{"k":"v"}', 1),
    )
    conn.execute(
        "INSERT INTO audit_log (id, ts, action, actor, session_id, fact_id, detail, ok)"
        " VALUES (3,?,?,?,?,?,?,?)",
        (NOW_ISO, "forget", "agent", "", "", "", None),
    )

    # Tables v3 does not model: must survive untouched.
    conn.execute("CREATE TABLE graph_edges (id INTEGER PRIMARY KEY, source TEXT, target TEXT)")
    conn.execute("INSERT INTO graph_edges (source, target) VALUES ('a','b')")
    conn.execute("CREATE TABLE notes_meta (note_id TEXT PRIMARY KEY, title TEXT)")
    conn.execute("INSERT INTO notes_meta VALUES ('n1','note one')")

    conn.execute(
        "INSERT INTO profile_registry (slug, created_at, renamed_to) VALUES ('default',?,'')",
        (NOW_ISO,),
    )
    conn.execute(
        "INSERT INTO sync_outbox (fact_id, op, version, written_at, payload, emitted)"
        " VALUES ('dup1','add',1,?,'{}',0)",
        (NOW_ISO,),
    )
    conn.commit()

    tables = (
        "facts",
        "pending_facts",
        "facts_archive",
        "fact_versions",
        "episodes",
        "triples",
        "embeddings",
        "audit_log",
        "graph_edges",
        "notes_meta",
        "sync_outbox",
    )
    counts = {
        table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        for table in tables
    }
    conn.close()
    return counts
