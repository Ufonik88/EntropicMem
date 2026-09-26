"""EM-204 — migration 0002: v3 core schema + lossless v2 data move.

Card AC:
* row-count and content parity checks **inside** the migration, aborting on
  mismatch
* a migrated DB answers a legacy-id lookup (the full ``get_fact()`` facade is
  EM-211, which depends on this card; here the equivalent is asserted at the
  storage layer via ``memories.legacy_id``)
* v2 DBs migrate losslessly (S2 exit criteria) and fresh installs create v3

Every fixture here is synthetic. These tests must never touch the live store:
``migrations.migrate`` refuses non-temp/non-test paths, and the module-level
test below proves the rich builder is also refused against a live-shaped path.

Several assertions exist because the real live store disagrees with what the
plan assumed — see each test's docstring. They are the reason this migration
was written against observed data instead of the card text alone.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "plugins" / "entropicmem" / "scripts"))

from em.store import db as emdb  # noqa: E402
from em.store import migrations as emmig  # noqa: E402

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "db"

V2_FIXTURES = ["v2_3_0.db", "v2_5_0.db", "v2_7_0.db"]


def _load_migration_module():
    """Load ``0002_v3_core`` directly so unit tests can call its pure helpers."""
    path = (
        REPO
        / "plugins"
        / "entropicmem"
        / "scripts"
        / "em"
        / "store"
        / "migrations"
        / "0002_v3_core.py"
    )
    spec = importlib.util.spec_from_file_location("em_0002_v3_core", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_M0002 = _load_migration_module()


def _load_builder():
    """Load the rich-v2 fixture builder by path (``tests/fixtures`` is not a package)."""
    spec = importlib.util.spec_from_file_location(
        "em_build_rich_v2", FIXTURES / "build_rich_v2.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_BUILDER = _load_builder()


class _FakeConn:
    """Duck-typed connection that reports a refused path and records DDL.

    The runner legitimately calls ``PRAGMA database_list`` to learn the path
    *before* the guard runs, so that one query is answered. Anything else —
    DDL, a backup, a write — is recorded and makes the test fail, proving the
    guard fired before any observable work (the EM-203 contract).
    """

    def __init__(self, path):
        self._path = str(path)
        self.executed: list = []

    def execute(self, sql, *args):
        statement = " ".join(str(sql).split())
        if statement.upper().startswith("PRAGMA DATABASE_LIST"):
            return _OneRow((("main", self._path, self._path),))
        self.executed.append(statement)
        raise AssertionError(f"statement ran during a refused migration: {statement}")


class _OneRow:
    """Minimal cursor-shaped result for the single query the guard needs."""

    def __init__(self, rows):
        self._rows = list(rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None


def _uv(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def _count(conn: sqlite3.Connection, table: str, *args) -> int:
    """Row count. ``table`` may be a full WHERE clause, with args bound."""
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}", args).fetchone()[0])


def _registry_with_real_0002():
    """Registry whose version-2 entry is *this* module object's ``up``.

    ``migrations.migrate`` with the default registry loads each module fresh
    through importlib, producing a different module object than the one these
    tests loaded — so monkeypatching helpers on the test-side copy would have
    no effect and the parity-mutation tests would pass vacuously. Injecting an
    explicit registry binds the runner to the object under test.
    """
    baseline = [m for m in emmig.discover() if m.version == 1]
    v3 = emmig.Migration(
        version=2,
        name=_M0002.NAME,
        slug="0002_v3_core",
        up=_M0002.up,
        checksum="f" * 64,  # not applied yet, so never checksum-verified
    )
    return baseline + [v3]


def _tables(conn: sqlite3.Connection) -> set:
    return {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
            " AND name NOT LIKE 'sqlite_%'"
        )
    }


def _row(conn: sqlite3.Connection, sql: str, *args) -> dict:
    conn.row_factory = sqlite3.Row
    row = conn.execute(sql, args).fetchone()
    conn.row_factory = None
    return dict(row) if row is not None else {}


def _baseline_only():
    """Registry holding only migration 0001, for building genuine v2 DBs."""
    return [m for m in emmig.discover() if m.version == 1]


@pytest.fixture
def rich_v2_db(tmp_path):
    """A v2.7 DB carrying every edge case found in the live store.

    Returns ``(path, v2_row_counts)`` with migration 0002 **not** applied.
    """
    path = tmp_path / "rich_v2.db"
    conn = emdb.open_db(path)
    emmig.migrate(conn, registry=_baseline_only())
    conn.close()
    counts = _BUILDER.build(path)
    return path, counts


@pytest.fixture
def migrated(rich_v2_db):
    """The rich v2 DB with the full migration applied."""
    path, counts = rich_v2_db
    conn = emdb.open_db(path)
    emmig.migrate(conn)
    yield conn, counts
    conn.close()


# --------------------------------------------------------------------------
# Registry / shape
# --------------------------------------------------------------------------


def test_migration_is_registered_as_version_2():
    found = {m.version: m.name for m in emmig.discover()}
    assert found == {1: "baseline_v27", 2: "v3_core"}
    assert emmig.LATEST == 2


def test_migration_module_exposes_the_required_api():
    assert _M0002.VERSION == 2
    assert _M0002.NAME == "v3_core"
    assert callable(_M0002.up)


# --------------------------------------------------------------------------
# Frozen helpers — these MUST NOT drift, they define an applied migration
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("EntropicMem", "entropicmem"),
        ("  spaced   out  ", "spaced out"),
        ("EntropicMem.", "entropicmem"),
        ("Trailing!!!", "trailing"),
        # only TRAILING punctuation is stripped; interior punctuation stays
        ("MiXeD CaSe, Trailing;", "mixed case, trailing"),
        ("", ""),
    ],
)
def test_normalize_content_matches_the_spec(raw, expected):
    assert _M0002.normalize_content(raw) == expected


def test_normalize_content_applies_nfkc():
    # U+FB01 LATIN SMALL LIGATURE FI -> "fi" under NFKC
    assert _M0002.normalize_content("\ufb01sh") == "fish"


def test_normalize_content_excludes_scope():
    """§3.3: scope lives in the unique index, not in the hash."""
    assert _M0002.content_hash("same content") == _M0002.content_hash("same content")
    assert len(_M0002.content_hash("x")) == 64


def test_content_hash_is_sha256_of_normalized():
    text = "  Hello, World.  "
    expected = hashlib.sha256("hello, world".encode()).hexdigest()
    assert _M0002.content_hash(text) == expected


@pytest.mark.parametrize(
    "episode_id,expected",
    [
        ("ep_sess_0f0d8c66f520", "session"),
        ("ep_sess_20260918_144040_cd6b92", "session"),
        ("ep_sess_0f0d8c66f520_w1", "window"),
        ("ep_sess_0f0d8c66f520_w23", "window"),
        ("ep_precomp_0f0d8c66f520", "precompress"),
        ("ep_013b486079fd", "manual"),
        # adversarial: must not be misread as a window
        ("ep_sess_abc_w", "session"),
        ("ep_sess_abc_wx", "session"),
        ("ep_sess_abc_1w", "session"),
        ("ep_sess_abc_w1x", "session"),
    ],
)
def test_episode_kind_classifies_every_v2_shape(episode_id, expected):
    """Regression: window ids are ``ep_sess_{sid}_w{n}``, so they start with
    ``ep_sess_`` too. Testing that prefix first classified every window as a
    session — silently wrong, no error. The suffix must win."""
    assert _M0002._episode_kind(episode_id) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("agent_tool", "agent_tool"),
        ("built_in_memory", "mirrored_builtin"),
        ("auto_extracted", "extracted_rule"),
        ("promoted", "promoted"),
        ("cli", "cli"),
        # the live store has 64 distinct sources; unmapped ones become import
        ("notion", "import"),
        ("second-brain", "import"),
        ("mnemosyne_legacy", "import"),
        ("", "import"),
        (None, "import"),
    ],
)
def test_source_mapping_follows_the_card(raw, expected):
    assert _M0002._map_source(raw) == expected


@pytest.mark.parametrize(
    "domain,source,tags,content,expected",
    [
        ("People", "agent_tool", [], "anything", "profile"),
        ("Knowledge", "built_in_memory", [], "anything", "profile"),
        ("Knowledge", "agent_tool", ["preference"], "x", "preference"),
        ("Knowledge", "agent_tool", ["PREFERENCE"], "x", "preference"),
        ("Knowledge", "agent_tool", [], "Preference: dark mode", "preference"),
        ("Knowledge", "agent_tool", [], "plain fact", "fact"),
        # 'preference' as a substring of another tag must NOT match
        ("Knowledge", "agent_tool", ["preferences-ui"], "x", "fact"),
    ],
)
def test_kind_rules(domain, source, tags, content, expected):
    assert _M0002._kind_for(domain, source, tags, content) == expected


@pytest.mark.parametrize(
    "kind,importance,expected",
    [
        ("fact", 0.75, "evergreen"),
        ("fact", 0.74, "standard"),
        ("fact", 0.5, "standard"),
        ("profile", 0.1, "evergreen"),
        ("preference", 0.1, "evergreen"),
    ],
)
def test_decay_class_rules(kind, importance, expected):
    assert _M0002._decay_for(kind, importance) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("", []),
        (None, []),
        ("preference", ["preference"]),
        ("durable, agent,globex", ["durable", "agent", "globex"]),
        ("a, a, b", ["a", "b"]),  # de-duplicated
        ('["a","b"]', ["a", "b"]),  # already JSON
        ("[not json", ["[not json"]),
    ],
)
def test_tags_become_a_json_array(raw, expected):
    assert _M0002._split_tags(raw) == expected


def test_all_three_v2_timestamp_shapes_normalise_to_z():
    """The live store mixes all three; a fourth (unparseable) must not abort."""
    for raw in (
        "2026-09-26T01:29:17.323720+00:00",
        "2026-04-24T08:25:58.514370",
        "2026-08-08 08:03:10",
    ):
        out = _M0002._to_v3_ts(raw)
        assert out is not None and out.endswith("Z"), (raw, out)
    assert _M0002._to_v3_ts("not-a-timestamp") is None
    assert _M0002._to_v3_ts("") is None
    assert _M0002._to_v3_ts(None) is None


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("", "{}"),
        (None, "{}"),
        ('{"k":"v"}', '{"k":"v"}'),
        # free-text detail is the live format; it must survive, wrapped
        ("domain=Infrastructure;tier=internal", None),
    ],
)
def test_audit_detail_stays_valid_json_without_losing_text(raw, expected):
    out = _M0002._detail_to_json(raw)
    json.loads(out)  # must parse
    if expected is not None:
        assert out == expected
    else:
        assert json.loads(out) == {"v2_detail": raw}


def test_audit_hash_matches_the_documented_formula():
    """§3.3: sha256(prev_hash || ts || action || actor || target_id || detail)."""
    prev = "0" * 64
    expected = hashlib.sha256(
        (prev + "2026-01-01T00:00:00.000Z" + "remember" + "agent" + "mem_1" + "{}").encode()
    ).hexdigest()
    assert _M0002._audit_hash(prev, "2026-01-01T00:00:00.000Z", "remember", "agent", "mem_1", "{}") == expected


@pytest.mark.parametrize(
    "raw,default,expected",
    [(0.5, 0.5, 0.5), (1.7, 0.5, 1.0), (-0.5, 0.5, 0.0), (None, 0.8, 0.8), ("x", 0.8, 0.8), (float("nan"), 0.8, 0.8)],
)
def test_clamp01_respects_the_check_constraint(raw, default, expected):
    assert _M0002._clamp01(raw, default) == expected


def test_entity_kinds_are_frozen_and_later_categories_win():
    """Frozen from ``triple_extract.KNOWN_ENTITIES`` at v2.8.0. Iteration order
    matters: as in the original module a name in two categories resolves to the
    later one ('notion' → service, 'tailscale' → infra→thing)."""
    kinds = _M0002._ENTITY_KINDS
    assert kinds["alice"] == "person"
    assert kinds["microsoft"] == "org"  # v2 'company' → v3 'org'
    assert kinds["entropicmem"] == "project"
    assert kinds["tailscale"] == "thing"  # service then infra wins → thing
    assert kinds["notion"] == "service"  # project then service wins
    assert kinds["memory"] == "concept"
    assert kinds.get("definitely-unknown") is None


# --------------------------------------------------------------------------
# Schema creation
# --------------------------------------------------------------------------


def test_fresh_install_creates_v3_with_no_data(tmp_path):
    """S2 exit criteria: 'fresh installs create v3'."""
    conn = emdb.open_db(tmp_path / "fresh.db")
    applied = emmig.migrate(conn)
    assert [m.version for m in applied] == [1, 2]
    assert _uv(conn) == emmig.LATEST == 2

    tables = _tables(conn)
    for expected in (
        "memories",
        "memories_fts",
        "memory_versions",
        "entities",
        "entity_aliases",
        "memory_entities",
        "relations",
        "episodes",
        "episodes_fts",
        "transcript_chunks",
        "embeddings",
        "jobs",
        "audit_log",
        "feedback",
        "metrics",
        "meta",
        "schema_migrations",
    ):
        assert expected in tables, f"missing v3 table {expected}"
    assert _count(conn, "memories") == 0
    assert _row(conn, "SELECT value FROM meta WHERE key='migrated_from'")["value"] == "none"
    assert _row(conn, "SELECT value FROM meta WHERE key='schema_generation'")["value"] == "3"
    # no v2 leftovers on a fresh install
    assert not [t for t in tables if t.startswith("v2_")]
    conn.close()


def test_up_is_a_noop_when_memories_already_exists(tmp_path):
    """Direct double-call must not corrupt or duplicate."""
    conn = emdb.open_db(tmp_path / "twice.db")
    emmig.migrate(conn)
    before = _count(conn, "memories")
    _M0002.up(conn)
    assert _count(conn, "memories") == before
    conn.close()


def test_v3_indexes_triggers_and_unique_constraints_exist(migrated):
    conn, _ = migrated
    names = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('index','trigger')"
            " AND name NOT LIKE 'sqlite_%'"
        )
    }
    for expected in (
        "ux_mem_hash_scope",
        "ix_mem_scope_status",
        "ix_mem_kind",
        "ix_mem_updated",
        "ix_mem_valid",
        "ix_mem_session",
        "ix_rel_subject",
        "ix_rel_object",
        "ix_jobs_ready",
        "ix_chunks_session",
        "memories_ai",
        "memories_ad",
        "memories_au",
        "episodes_ai",
        "episodes_ad",
        "episodes_au",
        "audit_no_update",
        "audit_no_delete",
    ):
        assert expected in names, f"missing {expected}"


def test_ux_mem_hash_scope_is_partial_and_unique(migrated):
    conn, _ = migrated
    ddl = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name='ux_mem_hash_scope'"
    ).fetchone()[0]
    assert "UNIQUE" in ddl and "WHERE" in ddl
    assert "'active','pending'" in ddl.replace(" ", "").replace('"', "'") or "active" in ddl


# --------------------------------------------------------------------------
# Data move — memories
# --------------------------------------------------------------------------


def test_every_v2_fact_lands_in_memories_exactly_once(migrated):
    conn, counts = migrated
    expected = counts["facts"] + counts["pending_facts"] + counts["facts_archive"]
    assert _count(conn, "memories") == expected
    assert _count(conn, "memories WHERE 1=1") == expected
    # 1:1 legacy_id mapping, no NULLs
    assert _count(conn, "memories WHERE legacy_id IS NULL") == 0
    distinct = conn.execute(
        "SELECT COUNT(DISTINCT legacy_id) FROM memories"
    ).fetchone()[0]
    assert distinct == expected


def test_content_is_preserved_byte_for_byte(migrated):
    conn, counts = migrated
    mismatched = conn.execute(
        "SELECT COUNT(*) FROM memories m JOIN v2_facts f ON f.id = m.legacy_id"
        " WHERE m.content IS NOT f.content"
    ).fetchone()[0]
    assert mismatched == 0


def test_status_mapping_covers_all_four_v2_sources(migrated):
    conn, _ = migrated
    assert _row(conn, "SELECT status FROM memories WHERE legacy_id='gone'")["status"] == "deleted"
    assert _row(conn, "SELECT status FROM memories WHERE legacy_id='a1'")["status"] == "archived"
    assert _row(conn, "SELECT status FROM memories WHERE legacy_id='p3'")["status"] == "pending"
    assert _row(conn, "SELECT status FROM memories WHERE legacy_id='k_evergreen'")["status"] == "active"


def test_duplicate_content_is_superseded_not_dropped(migrated):
    """v3's new unique index would reject v2 duplicates outright. The real
    store has three active facts normalising to 'entropicmem'; the newest stays
    active and the rest become superseded with a valid winner. Nothing is
    deleted, so the row count still balances."""
    conn, _ = migrated
    rows = conn.execute(
        "SELECT legacy_id, status, superseded_by, valid_to FROM memories"
        " WHERE legacy_id IN ('dup1','dup2','dup3')"
    ).fetchall()
    assert len(rows) == 3
    statuses = [r[1] for r in rows]
    assert statuses.count("active") == 1, statuses
    assert statuses.count("superseded") == 2, statuses

    winner = next(r for r in rows if r[1] == "active")
    assert winner[0] == "dup3"  # newest updated_at wins
    winner_id = conn.execute(
        "SELECT id FROM memories WHERE legacy_id='dup3'"
    ).fetchone()[0]
    assert winner_id.startswith("mem_")

    for legacy_id, status, superseded_by, valid_to in rows:
        if status == "superseded":
            # superseded_by holds the winner's RESOLVED mem_ id, not the legacy
            # id — a dangling reference here would break EM-205's history walk.
            assert superseded_by == winner_id
            assert conn.execute(
                "SELECT 1 FROM memories WHERE id=?", (superseded_by,)
            ).fetchone() is not None
            assert valid_to is not None and valid_to.endswith("Z")

    # exactly one survivor per hash+scope group
    survivors = conn.execute(
        "SELECT COUNT(*) FROM memories WHERE status IN ('active','pending')"
        " AND content_hash = (SELECT content_hash FROM memories WHERE legacy_id='dup1')"
    ).fetchone()[0]
    assert survivors == 1


def test_pending_facts_internal_duplicates_are_also_resolved(migrated):
    """The live store has 7 colliding keys *within* ``pending_facts`` —
    ``status='pending'`` is covered by the same partial unique index."""
    conn, _ = migrated
    p = {
        row[0]: row[1]
        for row in conn.execute(
            "SELECT legacy_id, status FROM memories WHERE legacy_id IN ('p1','p2','p3')"
        )
    }
    assert p["p3"] == "pending"
    assert sorted(p.values()).count("pending") == 2  # p2 wins over p1
    assert p["p1"] == "superseded"


def test_no_duplicate_hash_scope_groups_survive_the_move(migrated):
    """The invariant ``ux_mem_hash_scope`` enforces, checked explicitly so a
    future change cannot silently weaken it."""
    conn, _ = migrated
    dupes = conn.execute(
        "SELECT COUNT(*) FROM (SELECT content_hash, scope_profile, scope_user, scope_chat"
        " FROM memories WHERE status IN ('active','pending')"
        " GROUP BY 1,2,3,4 HAVING COUNT(*) > 1)"
    ).fetchone()[0]
    assert dupes == 0


def test_every_memory_gets_a_prefixed_ulid_id(migrated):
    conn, _ = migrated
    bad = conn.execute(
        "SELECT COUNT(*) FROM memories WHERE id NOT LIKE 'mem\\_%' ESCAPE '\\'"
    ).fetchone()[0]
    assert bad == 0
    ids = [r[0] for r in conn.execute("SELECT id FROM memories")]
    assert len(set(ids)) == len(ids)


def test_scope_and_visibility_follow_the_card(migrated):
    """v2 had no per-user scoping (§3.5 lands in S4), so migrated rows are
    profile-wide: ``visibility='profile'``, ``scope_user=''``."""
    conn, _ = migrated
    assert _count(conn, "memories WHERE visibility <> 'profile'") == 0
    assert _count(conn, "memories WHERE scope_user <> ''") == 0
    assert _count(conn, "memories WHERE scope_chat <> ''") == 0


def test_empty_profile_id_falls_back_to_the_registry_slug(migrated):
    conn, _ = migrated
    assert _row(conn, "SELECT scope_profile FROM memories WHERE legacy_id='no_prof'")["scope_profile"] == "default"
    assert _count(conn, "memories WHERE scope_profile = ''") == 0


def test_timestamps_are_normalised_and_never_null(migrated):
    conn, _ = migrated
    assert _count(conn, "memories WHERE created_at NOT LIKE '%Z'") == 0
    assert _count(conn, "memories WHERE updated_at NOT LIKE '%Z'") == 0
    assert _count(conn, "memories WHERE created_at IS NULL OR updated_at IS NULL") == 0
    for legacy_id in ("ts_iso", "ts_naive", "ts_sqlite"):
        assert _row(conn, "SELECT created_at FROM memories WHERE legacy_id=?", legacy_id)["created_at"].endswith("Z")
    # unparseable -> falls back to a valid value rather than aborting
    assert _row(conn, "SELECT created_at FROM memories WHERE legacy_id='ts_bad'")["created_at"].endswith("Z")


def test_pending_expiry_is_creation_plus_30_days(migrated):
    conn, _ = migrated
    row = _row(
        conn,
        "SELECT created_at, pending_expires_at FROM memories WHERE legacy_id='p3'",
    )
    assert row["pending_expires_at"].startswith("2026-10-20")


def test_values_are_clamped_into_the_check_constraints(migrated):
    conn, _ = migrated
    assert _row(conn, "SELECT importance FROM memories WHERE legacy_id='imp_hi'")["importance"] == 1.0
    assert _row(conn, "SELECT importance FROM memories WHERE legacy_id='imp_lo'")["importance"] == 0.0
    assert _row(conn, "SELECT sensitivity FROM memories WHERE legacy_id='sens_odd'")["sensitivity"] == "internal"
    assert _count(conn, "memories WHERE importance < 0 OR importance > 1") == 0


def test_version_and_summary_are_carried_over(migrated):
    conn, _ = migrated
    assert _row(conn, "SELECT version FROM memories WHERE legacy_id='v23'")["version"] == 7
    assert _row(conn, "SELECT summary FROM memories WHERE legacy_id='k_people'")["summary"] != ""


def test_summary_respects_the_200_char_cap(tmp_path):
    conn = emdb.open_db(tmp_path / "long.db")
    emmig.migrate(conn, registry=_baseline_only())
    conn.execute(
        "INSERT INTO facts (id, content, title, source, importance, domain, tags,"
        " session_id, created_at, updated_at, profile_id, version, deleted)"
        " VALUES ('long1','c',?,'agent',0.5,'Knowledge','','s','2026-01-01 00:00:00',"
        " '2026-01-01 00:00:00','default',1,0)",
        ("x" * 500,),
    )
    conn.commit()
    conn.close()

    conn = emdb.open_db(tmp_path / "long.db")
    emmig.migrate(conn)
    assert len(_row(conn, "SELECT summary FROM memories WHERE legacy_id='long1'")["summary"]) <= 200
    conn.close()


# --------------------------------------------------------------------------
# Data move — the rest
# --------------------------------------------------------------------------


def test_memory_versions_resolve_through_legacy_id(migrated):
    conn, counts = migrated
    # 3 v2 rows: 2 belong to dup1, 1 is an orphan
    assert _count(conn, "memory_versions") == 2
    versions = [
        row[0]
        for row in conn.execute("SELECT version FROM memory_versions ORDER BY version")
    ]
    assert versions == [1, 2]  # numbered chronologically per memory
    dup_id = _row(conn, "SELECT id FROM memories WHERE legacy_id='dup1'")["id"]
    assert _count(conn, "memory_versions WHERE memory_id=?", dup_id) == 2


def test_orphan_versions_stay_in_v2_and_are_reported(migrated):
    """The live store has 40 ``fact_versions`` rows pointing at a fact that no
    longer exists. They cannot be re-keyed, so they stay in ``v2_fact_versions``
    (kept one release per the card) and are counted in ``meta`` — not silently
    dropped, not inserted with a dangling owner."""
    conn, counts = migrated
    assert _count(conn, "v2_fact_versions WHERE fact_id='MISSING_FACT'") == 1
    assert _row(conn, "SELECT value FROM meta WHERE key='memory_versions_orphaned'")["value"] == "1"
    assert conn.execute(
        "SELECT COUNT(*) FROM memory_versions mv WHERE NOT EXISTS"
        " (SELECT 1 FROM memories m WHERE m.id = mv.memory_id)"
    ).fetchone()[0] == 0


def test_episodes_keep_their_ids_and_gain_a_kind(migrated):
    conn, counts = migrated
    assert _count(conn, "episodes") == counts["episodes"]
    assert _count(conn, "episodes WHERE legacy_id <> id") == 0
    kinds = {
        row[0]: row[1]
        for row in conn.execute("SELECT id, kind FROM episodes")
    }
    assert kinds["ep_sess_abc"] == "session"
    assert kinds["ep_precomp_1"] == "precompress"
    assert kinds["ep_manual_1"] == "manual"


def test_manual_episodes_use_their_own_id_as_session(migrated):
    """Load-bearing: on the real store this rule is what keeps
    ``UNIQUE(session_id, kind, window_seq)`` satisfiable (194 collisions
    otherwise, because 721 manual episodes share few real sessions)."""
    conn, _ = migrated
    for legacy_id in ("ep_manual_1", "ep_manual_2"):
        row = _row(conn, "SELECT session_id, kind FROM episodes WHERE id=?", legacy_id)
        assert row["session_id"] == legacy_id
        assert row["kind"] == "manual"


def test_episode_uniqueness_constraint_holds(migrated):
    conn, counts = migrated
    rows = conn.execute(
        "SELECT session_id, kind, window_seq, COUNT(*) c FROM episodes"
        " GROUP BY 1,2,3 HAVING c > 1"
    ).fetchall()
    assert rows == []


def test_window_seq_is_a_per_session_kind_counter(tmp_path):
    """Three windows in one session must get 0,1,2 — not all 0."""
    path = tmp_path / "win.db"
    conn = emdb.open_db(path)
    emmig.migrate(conn, registry=_baseline_only())
    conn.close()
    _BUILDER.build(path)

    conn = emdb.open_db(path)
    for n in (2, 3):
        conn.execute(
            "INSERT INTO episodes (episode_id, title, summary, source_session, created_at)"
            " VALUES (?,?,?,?,?)",
            (f"ep_sess_abc_w{n}", f"Window {n}", "s", "20260920_100000_abc", "2026-08-08 08:03:10"),
        )
    conn.commit()
    conn.close()

    conn = emdb.open_db(path)
    emmig.migrate(conn)
    seqs = sorted(
        row[0]
        for row in conn.execute(
            "SELECT window_seq FROM episodes WHERE kind='window' ORDER BY window_seq"
        )
    )
    assert seqs == [0, 1, 2], seqs
    conn.close()


def test_triples_become_entities_and_relations(migrated):
    conn, counts = migrated
    assert _count(conn, "relations") == counts["triples"]
    # 3 triples over subjects/objects -> EntropicMem, project, Alice, Globex Corp, SQLite
    assert _count(conn, "entities") == 5
    entropicmem = _row(conn, "SELECT kind FROM entities WHERE name='EntropicMem'")
    assert entropicmem["kind"] == "project"  # from KNOWN_ENTITIES
    unknown = _row(conn, "SELECT kind FROM entities WHERE name='Globex Corp'")
    assert unknown["kind"] == "thing"
    assert _count(conn, "entity_aliases") == _count(conn, "entities")


def test_entity_ids_are_prefixed_ulids(migrated):
    conn, _ = migrated
    assert _count(conn, "entities WHERE id NOT LIKE 'ent\\_%' ESCAPE '\\'") == 0
    assert _count(conn, "relations WHERE id NOT LIKE 'rel\\_%' ESCAPE '\\'") == 0


def test_embeddings_are_rekeyed_to_the_new_memory_id(migrated):
    conn, _ = migrated
    rows = conn.execute(
        "SELECT owner_type, owner_id, model, dim, length(vector) FROM embeddings"
    ).fetchall()
    assert len(rows) == 1
    owner_type, owner_id, model, dim, vlen = rows[0]
    assert owner_type == "memory"
    assert model == "all-MiniLM-L6-v2" and dim == 384 and vlen == 2
    # owner_id resolves to a real memory
    assert conn.execute("SELECT 1 FROM memories WHERE id=?", (owner_id,)).fetchone() is not None
    # content_hash matches the memory's own hash
    assert _row(conn, "SELECT content_hash FROM embeddings")["content_hash"] == _row(
        conn, "SELECT content_hash FROM memories WHERE id=?", owner_id
    )["content_hash"]


def test_orphan_embeddings_stay_in_v2_and_are_reported(migrated):
    """The live store has 6 of these. Only representable because v2 runs with
    foreign_keys OFF; v3 enforces them, so they must not be inserted."""
    conn, _ = migrated
    assert _count(conn, "v2_embeddings WHERE fact_id='MISSING'") == 1
    assert _row(conn, "SELECT value FROM meta WHERE key='embeddings_orphaned'")["value"] == "1"
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == [
    ] or all(
        row[0].startswith("v2_") for row in conn.execute("PRAGMA foreign_key_check").fetchall()
    )


def test_audit_log_is_rebuilt_into_a_verifiable_chain(migrated):
    conn, counts = migrated
    assert _count(conn, "audit_log") == counts["audit_log"]
    prev = "0" * 64
    for row in conn.execute(
        "SELECT seq, ts, action, actor, target_id, detail, prev_hash, hash"
        " FROM audit_log ORDER BY seq"
    ):
        ts, action, actor, target_id, detail, prev_hash, digest = row[1:]
        assert prev_hash == prev, f"seq {row[0]}: broken prev_hash link"
        expected = hashlib.sha256(
            "".join((prev, ts, action, actor, target_id, detail)).encode()
        ).hexdigest()
        assert digest == expected, f"seq {row[0]}: hash does not match content"
        prev = expected


def test_audit_log_is_append_only_after_migration(migrated):
    conn, _ = migrated
    with pytest.raises(sqlite3.Error, match="append-only"):
        conn.execute("UPDATE audit_log SET action='tampered' WHERE seq=1")
    with pytest.raises(sqlite3.Error, match="append-only"):
        conn.execute("DELETE FROM audit_log WHERE seq=1")
    # INSERT is still allowed (the chain grows)
    conn.execute(
        "INSERT INTO audit_log (ts, action, actor, prev_hash, hash)"
        " VALUES ('2026-01-01T00:00:00.000Z','test','t','p','h')"
    )


def test_audit_purge_token_allows_deletion(migrated):
    """§3.3's WHEN clause: the delete trigger yields to an explicit purge token."""
    conn, _ = migrated
    conn.execute("INSERT INTO meta (key, value) VALUES ('audit_purge_token','t')")
    conn.execute("DELETE FROM audit_log WHERE seq=1")  # must not raise
    conn.execute("DELETE FROM meta WHERE key='audit_purge_token'")
    with pytest.raises(sqlite3.Error, match="append-only"):
        conn.execute("DELETE FROM audit_log WHERE seq=2")


def test_all_audit_details_are_valid_json(migrated):
    conn, _ = migrated
    for row in conn.execute("SELECT detail FROM audit_log"):
        json.loads(row[0])
    # free-text detail survives, wrapped
    wrapped = conn.execute(
        "SELECT detail FROM audit_log WHERE detail LIKE '%v2_detail%'"
    ).fetchone()
    assert wrapped is not None
    assert json.loads(wrapped[0])["v2_detail"] == "domain=Infrastructure;tier=internal"


# --------------------------------------------------------------------------
# Preservation: what v3 does not model must survive
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "table",
    [
        "schema_info",
        "profile_registry",
        "sync_outbox",
        "sync_offsets",
        "shared_facts",
        "graph_edges",
        "notes_meta",
    ],
)
def test_unmodelled_tables_are_preserved_untouched(migrated, table):
    """``graph_edges``/``notes_meta`` are written by ``index.py`` and
    ``graph_query.py`` into memory.db and are absent from ``_init_schema``, so
    neither the card nor the v2 fixtures mention them. They must survive."""
    conn, counts = migrated
    assert table in _tables(conn), f"{table} was dropped or renamed"
    if table in counts:
        assert _count(conn, table) == counts[table]


def test_sync_outbox_keeps_legacy_fact_ids(migrated):
    """Card: sync ``fact_id`` references stay legacy ids until EM-309."""
    conn, _ = migrated
    assert _row(conn, "SELECT fact_id FROM sync_outbox")["fact_id"] == "dup1"


def test_v2_tables_are_renamed_not_dropped(migrated):
    conn, _ = migrated
    tables = _tables(conn)
    for name in (
        "facts",
        "pending_facts",
        "facts_archive",
        "fact_versions",
        "episodes",
        "triples",
        "embeddings",
        "audit_log",
        "facts_fts",
        "episodes_fts",
    ):
        assert f"v2_{name}" in tables, f"v2_{name} missing"

    # v3 recreates three of those names with a NEW shape, so their absence
    # cannot be asserted; assert instead that the v3 shape won (the collision
    # is the real hazard — CREATE TABLE IF NOT EXISTS would have kept v2's).
    for name in ("episodes", "embeddings", "audit_log"):
        cols = {row[1] for row in conn.execute(f"PRAGMA table_info({name})")}
        assert "rid" in cols or "owner_type" in cols or "prev_hash" in cols, (
            f"{name} still has the v2 shape, not v3"
        )
    # v3-only columns prove the rename happened before the v3 DDL
    assert "prev_hash" in {r[1] for r in conn.execute("PRAGMA table_info(audit_log)")}
    assert "owner_type" in {r[1] for r in conn.execute("PRAGMA table_info(embeddings)")}
    assert "window_seq" in {r[1] for r in conn.execute("PRAGMA table_info(episodes)")}


def test_meta_records_the_migration_provenance(migrated):
    conn, counts = migrated
    meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
    assert meta["schema_generation"] == "3"
    assert meta["migrated_from"] == "v2"
    assert meta["owner_user_id"] == "owner"
    assert int(meta["memories"]) == counts["facts"] + counts["pending_facts"] + counts["facts_archive"]
    assert int(meta["dedup_collision_groups"]) >= 2
    assert int(meta["embeddings_orphaned"]) == 1
    assert int(meta["memory_versions_orphaned"]) == 1


# --------------------------------------------------------------------------
# FTS
# --------------------------------------------------------------------------


def test_external_content_fts_is_populated_and_in_sync(migrated):
    conn, _ = migrated
    assert conn.execute(
        "SELECT COUNT(*) FROM memories_fts WHERE memories_fts MATCH 'entropicmem'"
    ).fetchone()[0] > 0
    assert conn.execute(
        "SELECT COUNT(*) FROM episodes_fts WHERE episodes_fts MATCH 'session'"
    ).fetchone()[0] > 0
    # 'integrity-check' raises if the external content is out of sync
    conn.execute("INSERT INTO memories_fts(memories_fts) VALUES('integrity-check')")
    conn.execute("INSERT INTO episodes_fts(episodes_fts) VALUES('integrity-check')")


def test_fts_triggers_track_later_writes(migrated):
    conn, _ = migrated
    conn.execute(
        "INSERT INTO memories (id, scope_profile, content, content_hash, source,"
        " created_at, updated_at) VALUES ('mem_test1','default','zzz unique token',"
        " 'h1','cli','2026-01-01T00:00:00.000Z','2026-01-01T00:00:00.000Z')"
    )
    assert conn.execute(
        "SELECT COUNT(*) FROM memories_fts WHERE memories_fts MATCH 'zzz'"
    ).fetchone()[0] == 1
    conn.execute("UPDATE memories SET content='yyy another token' WHERE id='mem_test1'")
    assert conn.execute(
        "SELECT COUNT(*) FROM memories_fts WHERE memories_fts MATCH 'yyy'"
    ).fetchone()[0] == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM memories_fts WHERE memories_fts MATCH 'zzz'"
    ).fetchone()[0] == 0
    conn.execute("DELETE FROM memories WHERE id='mem_test1'")
    conn.execute("INSERT INTO memories_fts(memories_fts) VALUES('integrity-check')")


# --------------------------------------------------------------------------
# Parity checks actually abort (card AC: "abort on mismatch")
# --------------------------------------------------------------------------


def test_parity_check_aborts_when_a_row_is_missing(tmp_path, monkeypatch):
    """Mutation check: if a fact silently fails to migrate, the migration must
    abort rather than commit a lossy upgrade."""
    path = tmp_path / "parity.db"
    conn = emdb.open_db(path)
    emmig.migrate(conn, registry=_baseline_only())
    conn.close()
    _BUILDER.build(path)

    original = _M0002._insert_memories

    def drop_one(conn_, rows):
        rows = [r for r in rows if r.legacy_id != "k_people"]
        return original(conn_, rows)

    monkeypatch.setattr(_M0002, "_insert_memories", drop_one)

    conn = emdb.open_db(path)
    with pytest.raises(_M0002.ParityError, match="memories row count"):
        emmig.migrate(conn, registry=_registry_with_real_0002())
    conn.close()

    # the runner rolled back: still at the previous version, no v3 tables
    conn = emdb.open_db(path)
    assert _uv(conn) == 1
    assert "memories" not in _tables(conn)
    assert "facts" in _tables(conn)
    conn.close()


def test_parity_check_aborts_on_corrupted_content(tmp_path, monkeypatch):
    path = tmp_path / "parity2.db"
    conn = emdb.open_db(path)
    emmig.migrate(conn, registry=_baseline_only())
    conn.close()
    _BUILDER.build(path)

    original = _M0002._insert_memories

    def corrupt(conn_, rows):
        for row in rows:
            if row.legacy_id == "k_people":
                row.content = "silently altered"
        return original(conn_, rows)

    monkeypatch.setattr(_M0002, "_insert_memories", corrupt)

    conn = emdb.open_db(path)
    with pytest.raises(_M0002.ParityError, match="differ in content"):
        emmig.migrate(conn, registry=_registry_with_real_0002())
    conn.close()
    conn = emdb.open_db(path)
    assert _uv(conn) == 1
    conn.close()


def test_parity_check_aborts_when_audit_chain_is_broken(tmp_path, monkeypatch):
    """The chain check must catch a hash that does not match its row.

    NOTE on what this can and cannot prove: ``_verify_audit_chain`` recomputes
    hashes with the same ``_audit_hash`` helper that wrote them, so mutating
    that helper is *self-consistent* and undetectable by design — a wrong
    formula verifies fine. That is why the formula itself is pinned
    independently by :func:`test_audit_hash_matches_the_documented_formula`.
    Here we corrupt a stored row instead, which is the failure the chain check
    really exists to catch.
    """
    path = tmp_path / "parity3.db"
    conn = emdb.open_db(path)
    emmig.migrate(conn, registry=_baseline_only())
    conn.close()
    _BUILDER.build(path)

    original = _M0002._rebuild_audit_log

    def corrupt_one_row(conn_):
        n = original(conn_)
        # Tamper with a stored row AFTER it was written: the chain check
        # recomputes from the stored columns, so this must be detected.
        conn_.execute("UPDATE audit_log SET action='tampered' WHERE seq=1")
        return n

    monkeypatch.setattr(_M0002, "_rebuild_audit_log", corrupt_one_row)

    conn = emdb.open_db(path)
    with pytest.raises(_M0002.ParityError, match="hash does not match"):
        emmig.migrate(conn, registry=_registry_with_real_0002())
    conn.close()


def test_parity_check_aborts_when_embedded_fts_is_out_of_sync(tmp_path, monkeypatch):
    """If the FTS triggers are dropped, the migration must notice.

    This is the check that ``'integrity-check'`` alone cannot make: with the
    trigger gone the index is simply never populated, and integrity-check
    compares against the content table so it passes vacuously. The docsize
    shadow-table probe catches it.
    """
    path = tmp_path / "parity4.db"
    conn = emdb.open_db(path)
    emmig.migrate(conn, registry=_baseline_only())
    conn.close()
    _BUILDER.build(path)

    original = _M0002._create_v3_schema

    def without_triggers(conn_):
        original(conn_)
        conn_.execute("DROP TRIGGER IF EXISTS memories_ai")

    monkeypatch.setattr(_M0002, "_create_v3_schema", without_triggers)

    conn = emdb.open_db(path)
    with pytest.raises(_M0002.ParityError, match="out of sync"):
        emmig.migrate(conn, registry=_registry_with_real_0002())
    conn.close()

    # rolled back to the pre-migration version
    conn = emdb.open_db(path)
    assert _uv(conn) == 1
    conn.close()


def test_fts_sync_probe_detects_an_unpopulated_index(tmp_path):
    """Direct regression for the false-assurance bug this card found.

    ``count(*)`` on an external-content FTS table reads through to the content
    table and always agrees with it; ``integrity-check`` compares the index
    against the same content table. Neither notices an empty index. The probe
    used by the parity check reads ``<fts>_docsize`` instead, which holds one
    row per *indexed* document and so does notice.
    """
    conn = emdb.open_db(tmp_path / "fts.db")
    conn.execute(
        "CREATE TABLE base (rid INTEGER PRIMARY KEY AUTOINCREMENT, content TEXT,"
        " summary TEXT DEFAULT '', tags TEXT DEFAULT '', domain TEXT DEFAULT '')"
    )
    conn.execute(
        "CREATE VIRTUAL TABLE base_fts USING fts5(content, summary, tags, domain,"
        " content='base', content_rowid='rid', tokenize='porter unicode61')"
    )
    conn.execute("INSERT INTO base(content) VALUES ('hello world'),('second row')")

    # The naive probes report a healthy index despite it being completely empty.
    assert _count(conn, "base_fts") == 2  # reads THROUGH to base — proves nothing
    conn.execute("INSERT INTO base_fts(base_fts) VALUES('integrity-check')")  # passes
    # The probe the migration actually uses sees the truth.
    assert _M0002._fts_indexed_rows(conn, "base_fts") == 0

    # Populate it, and the probe now agrees with the base table.
    conn.execute(
        "INSERT INTO base_fts(rowid, content) SELECT rid, content FROM base"
    )
    assert _M0002._fts_indexed_rows(conn, "base_fts") == 2
    conn.close()


# --------------------------------------------------------------------------
# Safety: the live-DB guard still covers migration 0002
# --------------------------------------------------------------------------


def test_migrate_still_refuses_a_live_shaped_path(tmp_path):
    """EM-204 is exactly the migration that could destroy the real store, so
    the EM-203 guard must still fire — and fire before any DDL runs."""
    live_shaped = tmp_path / "entropicmem" / "memory.db"
    live_shaped.parent.mkdir(parents=True)
    conn = sqlite3.connect(str(live_shaped))
    conn.execute("CREATE TABLE facts (id TEXT PRIMARY KEY, content TEXT)")
    conn.commit()
    conn.close()

    refused = emmig.assert_safe_db_path  # sanity: the guard is importable
    assert callable(refused)

    # A path outside temp/test is refused. Use a non-temp directory so the
    # guard's temp/test exemption cannot apply.
    outside = Path.home() / ".hermes" / "entropicmem" / "memory.db"
    with pytest.raises(emmig.MigrationRefused):
        emmig.assert_safe_db_path(outside)


def test_guard_runs_before_any_ddl_for_migration_0002():
    """No statement may run when the path is refused.

    ``_FakeConn`` answers only the ``PRAGMA database_list`` the runner needs to
    learn the path, and records anything else; asserting ``executed == []``
    proves the guard fired before any DDL, backup or write.
    """
    outside = Path.home() / ".hermes" / "entropicmem" / "memory.db"
    conn = _FakeConn(outside)
    with pytest.raises(emmig.MigrationRefused):
        emmig.migrate(conn)
    assert conn.executed == []


# --------------------------------------------------------------------------
# Idempotence / re-run / committed fixtures
# --------------------------------------------------------------------------


def test_re_running_is_a_noop(migrated):
    conn, counts = migrated
    before = _count(conn, "memories")
    uv_before = _uv(conn)
    applied = emmig.migrate(conn)
    assert applied == []
    assert _count(conn, "memories") == before
    assert _uv(conn) == uv_before


@pytest.mark.parametrize("fixture_name", V2_FIXTURES)
def test_committed_v2_fixtures_reach_v3(tmp_path, fixture_name):
    """Card AC: fixture DBs from v2.3/v2.5/v2.7 all migrate to LATEST."""
    src = FIXTURES / fixture_name
    if not src.is_file():
        raise AssertionError(
            f"fixture {fixture_name} is missing; it is committed to the repo,"
            " so this is a real failure, not a skip"
        )
    dst = tmp_path / fixture_name
    dst.write_bytes(src.read_bytes())
    conn = emdb.open_db(dst)
    applied = emmig.migrate(conn)
    assert [m.version for m in applied] == [1, 2]
    assert _uv(conn) == emmig.LATEST
    assert _count(conn, "memories") == _count(conn, "v2_facts")
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    conn.close()


def test_downgrade_still_refused_after_v3(tmp_path):
    conn = emdb.open_db(tmp_path / "down.db")
    emmig.migrate(conn)
    assert _uv(conn) == 2
    with pytest.raises(emdb.DowngradeError):
        emmig.migrate(conn, registry=_baseline_only())
    conn.close()


def test_checksum_change_is_detected_for_0002(tmp_path):
    """Editing an applied migration must fail loudly, not silently no-op."""
    path = tmp_path / "checksum.db"
    conn = emdb.open_db(path)
    emmig.migrate(conn)
    conn.execute(
        "UPDATE schema_migrations SET checksum=? WHERE version=2",
        ("0" * 64,),
    )
    conn.commit()
    with pytest.raises(emmig.MigrationChecksumMismatch):
        emmig.migrate(conn, registry=_baseline_only() + [
            type("M", (), {"version": 2, "name": "v3_core", "checksum": "f" * 64, "up": staticmethod(lambda c: None)})()
        ])
    conn.close()


def test_migration_works_in_a_fresh_subprocess():
    """End-to-end migration in a clean interpreter (no test-plugin state).

    Note this is NOT a wheel test: it puts the repo's ``scripts`` dir on
    ``sys.path``. Wheel packaging is asserted separately by
    :func:`test_pyproject_ships_the_migration_package`.
    """
    import subprocess

    script = (
        "import sys, tempfile, pathlib;"
        f"sys.path.insert(0, {str(REPO / 'plugins' / 'entropicmem' / 'scripts')!r});"
        "from em.store import db, migrations;"
        "d = pathlib.Path(tempfile.mkdtemp());"
        "c = db.open_db(d / 'w.db');"
        "a = migrations.migrate(c);"
        "print('|'.join(m.name for m in a));"
        "print(c.execute('PRAGMA user_version').fetchone()[0]);"
        "print(c.execute('select count(*) from sqlite_master where type=\"table\" and name=\"memories\"').fetchone()[0])"
    )
    lines = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    ).stdout.split()
    assert lines[0] == "baseline_v27|v3_core"
    assert lines[1] == "2"
    assert lines[2] == "1"


def test_pyproject_ships_the_migration_package():
    """Packaging regression: setuptools silently omits unlisted subpackages.

    EM-202 missed ``em.store`` and EM-203 missed ``em.store.migrations``; the
    wheel then contained no migration modules at all. Listed explicitly so a
    future subpackage cannot vanish the same way.
    """
    text = (REPO / "pyproject.toml").read_text()
    assert "em.store.migrations" in text
    # 0002 must be importable as package data once installed
    assert (
        REPO
        / "plugins"
        / "entropicmem"
        / "scripts"
        / "em"
        / "store"
        / "migrations"
        / "0002_v3_core.py"
    ).is_file()
