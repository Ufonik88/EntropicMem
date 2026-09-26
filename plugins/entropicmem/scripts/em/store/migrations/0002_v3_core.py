"""0002 — v3 core schema + lossless data move from v2 (EM-204).

Plan card EM-204 / §3.3. Creates the v3 tables, indexes, external-content FTS
and append-only audit triggers, moves every v2 row into them, then runs
row-count and content parity checks that abort the migration on any mismatch.

**Self-containment is a correctness requirement here, not a style choice.**
The runner records ``sha256`` of *this module's source* and refuses to re-run a
migration whose checksum changed. If this file imported a helper (say a future
``em.store.hashing.normalize``), that helper could change later and silently
alter what an "already applied" migration means while its checksum stayed the
same. So ``normalize_content``/``content_hash`` are inlined and frozen.
:mod:`em.clock` is the one import: it is EM-201's stable public API and §3.3
requires that v3 timestamps and ids come from it.

**Deliberate decisions (each verified against a real 1570-fact v2.8 store):**

* *Duplicate content.* v3 adds ``ux_mem_hash_scope``, a UNIQUE index over
  ``(content_hash, scope_profile, scope_user, scope_chat) WHERE status IN
  ('active','pending')``. v2 had no such constraint, so real stores contain
  collisions (three active facts whose content normalises to ``entropicmem``).
  Inserting them all would abort, so within each collision group the
  most-recently-updated row stays ``active``/``pending`` and the others become
  ``superseded`` with ``superseded_by`` pointing at the winner and ``valid_to``
  set to the winner's ``created_at``. Nothing is deleted and the row count is
  preserved, which is what §3.4's status machine is for.
* *Orphans.* 6 ``embeddings`` and 40 ``fact_versions`` rows in the real store
  reference a ``fact_id`` that no longer exists. They cannot be re-keyed, so
  they are left in the renamed ``v2_*`` tables (kept for one release per the
  card) and their counts are recorded in ``meta`` and reported by the parity
  check rather than being silently dropped or inserted with a dangling owner.
* *Tables v3 does not model.* A live ``memory.db`` also holds ``graph_edges``,
  ``notes_meta`` and ``notes_fts`` (written by ``index.py``/``graph_query.py``,
  never by ``_init_schema``). They are preserved untouched — not renamed, not
  dropped. ``schema_info``, ``profile_registry`` and the sync tables
  (``sync_outbox``, ``sync_offsets``, ``shared_facts``) are likewise left alone:
  the card keeps sync ``fact_id`` references as legacy ids until EM-309.
* *Episode ids.* v2 ``episode_id`` values are already unique text ids, so they
  are kept as the v3 ``id`` **and** copied to ``legacy_id`` instead of minting
  new ULIDs. Nothing referencing an episode id churns. ``window_seq`` is
  assigned as a per-``(session_id, kind)`` counter so the v3
  ``UNIQUE(session_id, kind, window_seq)`` holds for any input, and manual
  episodes use their own id as ``session_id`` (the card's rule; on the real
  store it avoids 194 collisions).
* *Version snapshots.* v2 ``fact_versions`` records no version number per
  snapshot, so snapshots are numbered 1..n per memory in chronological order.
  The live row keeps ``facts.version``. The two need not agree; the original
  rows survive in ``v2_fact_versions``.
* *Audit ``detail``.* v2 stored free text (``domain=Infrastructure;tier=internal``),
  v3 wants JSON. Values that are already JSON pass through; anything else is
  wrapped as ``{"v2_detail": "<original>"}`` so no information is lost and the
  column stays valid JSON. Empty becomes ``{}``. The hash chain is rebuilt in
  ``seq`` order with genesis ``prev_hash = '0' * 64``.
* ``user_version`` ends at **2** (the migration number), not the "3" in §3.3's
  heading: EM-203 defines ``user_version`` as the highest applied migration
  version and requires contiguous numbering from 1. The schema *generation* is
  recorded separately as ``meta.schema_generation = '3'``. See the card note.

Never commits: the runner owns the transaction.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
from datetime import timedelta
from typing import Dict, List, Optional, Sequence, Tuple

from em import clock

VERSION = 2
NAME = "v3_core"

__all__ = ["NAME", "VERSION", "content_hash", "normalize_content", "up"]

# --------------------------------------------------------------------------
# Frozen helpers (see module docstring: these MUST stay inline)
# --------------------------------------------------------------------------

#: Trailing punctuation stripped by :func:`normalize_content` (§3.3).
_TRAILING_PUNCT = ".,;:!?\u2026\"'\u00bb\u201d\u2019"

_WHITESPACE_RE = re.compile(r"\s+")

#: v3 ``memories.source`` vocabulary (§3.3).
_VALID_SOURCES = frozenset(
    {
        "user_stated",
        "agent_tool",
        "mirrored_builtin",
        "extracted_llm",
        "extracted_rule",
        "promoted",
        "reflection",
        "import",
        "cli",
    }
)

#: v2 ``facts.source`` → v3 ``memories.source`` (card's explicit mappings).
#: Everything else becomes ``import``; the original string survives in
#: ``v2_facts.source``.
_SOURCE_MAP = {
    "agent_tool": "agent_tool",
    "built_in_memory": "mirrored_builtin",
    "auto_extracted": "extracted_rule",
    "promoted": "promoted",
    "cli": "cli",
    "user_stated": "user_stated",
    "extracted_llm": "extracted_llm",
    "extracted_rule": "extracted_rule",
    "reflection": "reflection",
    "import": "import",
}

#: v3 ``memories.sensitivity`` vocabulary.
_VALID_SENSITIVITY = frozenset({"public", "internal", "sensitive", "secret"})

#: Pending facts expire 30 days after creation (card).
_PENDING_TTL_DAYS = 30

#: v2 window-episode ids are ``ep_sess_{sid}_w{n}`` (``session_digest``) and
#: ``memory_engine`` matches them with ``episode_base + "_w%"``. Anchored so a
#: window inside a *session* id is recognised: every window id also starts with
#: ``ep_sess_``, so the suffix has to be tested first.
_WINDOW_SUFFIX_RE = re.compile(r"_w\d+$")

#: ``summary`` is documented as "<= 200 chars" in §3.3.
_SUMMARY_MAX = 200

#: Frozen copy of ``triple_extract.KNOWN_ENTITIES`` (v2.8.0). Iteration order
#: matters: as in the original module, a name in two categories resolves to the
#: *later* category ("notion" → service, "tailscale" → infra).
_KNOWN_ENTITIES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("person", ("alice", "bob")),
    (
        "company",
        ("nous research", "microsoft", "google", "openai", "meta"),
    ),
    (
        "project",
        (
            "entropicmem",
            "mnemosyne",
            "hermes",
            "hermes agent",
            "mem0",
            "vaultknox",
            "tencentdb",
            "notion",
            "obsidian",
            "logseq",
        ),
    ),
    (
        "service",
        (
            "google drive",
            "gdrive",
            "tailscale",
            "cloudflare",
            "signal",
            "telegram",
            "discord",
            "notion",
            "obsidian",
            "logseq",
            "openrouter",
            "deepseek",
            "backblaze",
            "rclone",
            "gmail",
            "google calendar",
            "github",
        ),
    ),
    (
        "infra",
        (
            "linux",
            "ubuntu",
            "docker",
            "nginx",
            "systemd",
            "sqlite",
            "postgresql",
            "redis",
            "fastapi",
            "uvicorn",
            "python",
            "node",
            "typescript",
            "flutter",
            "tailscale",
            "cloudflare tunnel",
            "hermes gateway",
            "gateway",
            "graph server",
            "memory.db",
            "index.db",
        ),
    ),
    (
        "concept",
        (
            "memory",
            "recall",
            "prefetch",
            "embedding",
            "fts5",
            "hybrid search",
            "episodic memory",
            "knowledge graph",
            "triple store",
            "backup",
            "stability gate",
            "health check",
            "sole provider",
            "cutover",
            "migration",
            "dual-write",
            "cron",
            "plugin",
            "skill",
            "vault",
        ),
    ),
)

#: ``KNOWN_ENTITIES`` category → v3 ``entities.kind`` (§3.3 vocabulary is
#: person|org|project|place|product|service|concept|thing; v2's "company" and
#: "infra" have no v3 equivalent so they map to org/thing).
_ENTITY_KIND_MAP = {
    "person": "person",
    "company": "org",
    "project": "project",
    "service": "service",
    "infra": "thing",
    "concept": "concept",
}


def _entity_kinds() -> Dict[str, str]:
    """Lowercase entity name → v3 kind, later categories winning."""
    kinds: Dict[str, str] = {}
    for category, names in _KNOWN_ENTITIES:
        kind = _ENTITY_KIND_MAP.get(category, "thing")
        for name in names:
            kinds[name] = kind
    return kinds


_ENTITY_KINDS = _entity_kinds()


def normalize_content(text: str) -> str:
    """§3.3 ``normalize``: NFKC → casefold → collapse whitespace → strip
    trailing punctuation. Scope is deliberately NOT included (it lives in the
    unique index)."""
    folded = unicodedata.normalize("NFKC", text or "").casefold()
    return _WHITESPACE_RE.sub(" ", folded).strip().rstrip(_TRAILING_PUNCT)


def content_hash(text: str) -> str:
    """``sha256(normalize(content))`` hex, per §3.3."""
    return hashlib.sha256(normalize_content(text).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# Small SQL helpers
# --------------------------------------------------------------------------


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        is not None
    )


def _columns(conn: sqlite3.Connection, table: str) -> set:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


class ParityError(RuntimeError):
    """A post-move parity check failed; the runner rolls the migration back."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ParityError(message)


# --------------------------------------------------------------------------
# Value normalisation
# --------------------------------------------------------------------------


def _to_v3_ts(raw: object) -> Optional[str]:
    """Normalise any v2 timestamp to §3.3's ``...Z`` form.

    Real v2 stores mix three shapes (verified on a live 2.8.0 database):
    ``2026-09-26T01:29:17.323720+00:00``, naive ``2026-04-24T08:25:58.514370``
    and SQLite's ``CURRENT_TIMESTAMP`` form ``2026-08-08 08:03:10``.
    :func:`em.clock.parse_iso` accepts all three. Unparseable or empty values
    become ``None`` rather than aborting a migration over one bad cell.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        return clock.to_iso(clock.parse_iso(text))
    except ValueError:
        return None


def _to_v3_ts_or(raw: object, fallback: Optional[str]) -> str:
    """Like :func:`_to_v3_ts` but never returns ``None`` (for NOT NULL cols)."""
    return _to_v3_ts(raw) or fallback or clock.to_iso(clock.utc_now())


def _split_tags(raw: object) -> List[str]:
    """v2 stored tags as a comma-separated string; v3 wants a JSON array."""
    text = "" if raw is None else str(raw).strip()
    if not text:
        return []
    if text.startswith("["):  # already JSON in some hand-written rows
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None
        if isinstance(parsed, list):
            return [str(t).strip() for t in parsed if str(t).strip()]
    seen: List[str] = []
    for part in text.split(","):
        tag = part.strip()
        if tag and tag not in seen:
            seen.append(tag)
    return seen


def _clamp01(value: object, default: float) -> float:
    """Coerce into v3's ``CHECK (x BETWEEN 0 AND 1)`` range."""
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    if number != number:  # NaN
        return default
    return min(1.0, max(0.0, number))


def _map_source(raw: object) -> str:
    text = "" if raw is None else str(raw).strip()
    mapped = _SOURCE_MAP.get(text)
    if mapped is not None:
        return mapped
    return text if text in _VALID_SOURCES else "import"


def _map_sensitivity(raw: object) -> str:
    text = "" if raw is None else str(raw).strip()
    return text if text in _VALID_SENSITIVITY else "internal"


def _kind_for(domain: object, source: object, tags: Sequence[str], content: str) -> str:
    """Card's rule: ``domain == 'People'`` or ``source == 'built_in_memory'`` →
    ``profile``; a ``preference`` tag or ``Preference:`` prefix →
    ``preference``; else ``fact``."""
    if str(domain or "") == "People" or str(source or "") == "built_in_memory":
        return "profile"
    if any(t.casefold() == "preference" for t in tags):
        return "preference"
    if content.startswith("Preference:"):
        return "preference"
    return "fact"


def _decay_for(kind: str, importance: float) -> str:
    """Card's rule: importance ≥ 0.75 or kind ∈ {profile, preference} →
    ``evergreen``, else ``standard``."""
    if importance >= 0.75 or kind in ("profile", "preference"):
        return "evergreen"
    return "standard"


def _episode_kind(episode_id: str) -> str:
    """Card's rule for v3 ``episodes.kind``.

    Order matters: the window suffix must be tested **before** the ``ep_sess_``
    prefix, because a real window id looks like ``ep_sess_<id>_w3`` — it starts
    with ``ep_sess_`` *and* carries ``_w{n}``. Testing the prefix first would
    silently classify every window as a session.
    """
    if _WINDOW_SUFFIX_RE.search(episode_id):
        return "window"
    if episode_id.startswith("ep_precomp"):
        return "precompress"
    if episode_id.startswith("ep_sess_"):
        return "session"
    return "manual"


def _detail_to_json(raw: object) -> str:
    """v3 ``audit_log.detail`` is ``NOT NULL DEFAULT '{}'`` and holds JSON."""
    text = "" if raw is None else str(raw).strip()
    if not text:
        return "{}"
    try:
        json.loads(text)
    except ValueError:
        return json.dumps({"v2_detail": text}, ensure_ascii=False)
    return text


def _audit_hash(prev_hash: str, ts: str, action: str, actor: str, target_id: str, detail: str) -> str:
    """§3.3: ``sha256(prev_hash || ts || action || actor || target_id || detail)``."""
    payload = "".join((prev_hash, ts, action, actor, target_id, detail))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# v3 DDL (§3.3, verbatim except for IF NOT EXISTS where re-creation is safe)
# --------------------------------------------------------------------------

_V3_DDL: Tuple[str, ...] = (
    """CREATE TABLE IF NOT EXISTS memories (
      rid              INTEGER PRIMARY KEY AUTOINCREMENT,
      id               TEXT NOT NULL UNIQUE,
      legacy_id        TEXT UNIQUE,
      scope_profile    TEXT NOT NULL,
      scope_user       TEXT NOT NULL DEFAULT '',
      scope_chat       TEXT NOT NULL DEFAULT '',
      visibility       TEXT NOT NULL DEFAULT 'user'
                       CHECK (visibility IN ('user','chat','profile','shared')),
      kind             TEXT NOT NULL DEFAULT 'fact'
                       CHECK (kind IN ('fact','preference','profile','procedure','event','constraint','insight','note')),
      content          TEXT NOT NULL,
      summary          TEXT NOT NULL DEFAULT '',
      content_hash     TEXT NOT NULL,
      domain           TEXT NOT NULL DEFAULT 'Knowledge',
      tags             TEXT NOT NULL DEFAULT '[]',
      status           TEXT NOT NULL DEFAULT 'active'
                       CHECK (status IN ('pending','active','superseded','archived','deleted')),
      importance       REAL NOT NULL DEFAULT 0.5 CHECK (importance BETWEEN 0 AND 1),
      confidence       REAL NOT NULL DEFAULT 0.8 CHECK (confidence BETWEEN 0 AND 1),
      sensitivity      TEXT NOT NULL DEFAULT 'internal'
                       CHECK (sensitivity IN ('public','internal','sensitive','secret')),
      source           TEXT NOT NULL,
      source_session   TEXT NOT NULL DEFAULT '',
      source_turn      INTEGER,
      author_id        TEXT NOT NULL DEFAULT '',
      evidence         TEXT NOT NULL DEFAULT '',
      pinned           INTEGER NOT NULL DEFAULT 0,
      decay_class      TEXT NOT NULL DEFAULT 'standard'
                       CHECK (decay_class IN ('evergreen','standard','volatile')),
      valid_from       TEXT,
      valid_to         TEXT,
      created_at       TEXT NOT NULL,
      updated_at       TEXT NOT NULL,
      last_accessed_at TEXT,
      last_injected_at TEXT,
      access_count     INTEGER NOT NULL DEFAULT 0,
      inject_count     INTEGER NOT NULL DEFAULT 0,
      helpful_count    INTEGER NOT NULL DEFAULT 0,
      unhelpful_count  INTEGER NOT NULL DEFAULT 0,
      superseded_by    TEXT REFERENCES memories(id),
      pending_reason   TEXT NOT NULL DEFAULT '',
      pending_expires_at TEXT,
      trust_flags      TEXT NOT NULL DEFAULT '[]',
      token_estimate   INTEGER NOT NULL DEFAULT 0,
      version          INTEGER NOT NULL DEFAULT 1
    )""",
    """CREATE UNIQUE INDEX IF NOT EXISTS ux_mem_hash_scope
       ON memories(content_hash, scope_profile, scope_user, scope_chat)
       WHERE status IN ('active','pending')""",
    "CREATE INDEX IF NOT EXISTS ix_mem_scope_status ON memories(scope_profile, scope_user, status)",
    "CREATE INDEX IF NOT EXISTS ix_mem_kind ON memories(kind, status)",
    "CREATE INDEX IF NOT EXISTS ix_mem_updated ON memories(updated_at DESC)",
    "CREATE INDEX IF NOT EXISTS ix_mem_valid ON memories(valid_from, valid_to)",
    "CREATE INDEX IF NOT EXISTS ix_mem_session ON memories(source_session, source_turn)",
    # External-content FTS kept in sync by triggers (§3.3).
    """CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
      content, summary, tags, domain, content='memories', content_rowid='rid',
      tokenize='porter unicode61 remove_diacritics 2'
    )""",
    """CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
      INSERT INTO memories_fts(rowid, content, summary, tags, domain)
      VALUES (new.rid, new.content, new.summary, new.tags, new.domain);
    END""",
    """CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
      INSERT INTO memories_fts(memories_fts, rowid, content, summary, tags, domain)
      VALUES ('delete', old.rid, old.content, old.summary, old.tags, old.domain);
    END""",
    """CREATE TRIGGER IF NOT EXISTS memories_au
       AFTER UPDATE OF content, summary, tags, domain ON memories BEGIN
      INSERT INTO memories_fts(memories_fts, rowid, content, summary, tags, domain)
      VALUES ('delete', old.rid, old.content, old.summary, old.tags, old.domain);
      INSERT INTO memories_fts(rowid, content, summary, tags, domain)
      VALUES (new.rid, new.content, new.summary, new.tags, new.domain);
    END""",
    """CREATE TABLE IF NOT EXISTS memory_versions (
      id INTEGER PRIMARY KEY AUTOINCREMENT, memory_id TEXT NOT NULL, version INTEGER NOT NULL,
      content TEXT NOT NULL, importance REAL, confidence REAL, status TEXT,
      valid_from TEXT, valid_to TEXT,
      changed_at TEXT NOT NULL, change_reason TEXT NOT NULL, actor TEXT NOT NULL,
      UNIQUE(memory_id, version)
    )""",
    """CREATE TABLE IF NOT EXISTS entities (
      id TEXT PRIMARY KEY, scope_profile TEXT NOT NULL, name TEXT NOT NULL,
      kind TEXT NOT NULL DEFAULT 'thing',
      description TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
      UNIQUE(scope_profile, name)
    )""",
    """CREATE TABLE IF NOT EXISTS entity_aliases (
      alias_norm TEXT NOT NULL, entity_id TEXT NOT NULL REFERENCES entities(id),
      PRIMARY KEY(alias_norm, entity_id)
    )""",
    """CREATE TABLE IF NOT EXISTS memory_entities (
      memory_id TEXT NOT NULL REFERENCES memories(id),
      entity_id TEXT NOT NULL REFERENCES entities(id),
      role TEXT NOT NULL DEFAULT 'mention', PRIMARY KEY(memory_id, entity_id)
    )""",
    """CREATE TABLE IF NOT EXISTS relations (
      id TEXT PRIMARY KEY, scope_profile TEXT NOT NULL, subject_id TEXT NOT NULL,
      predicate TEXT NOT NULL, object_id TEXT,
      object_literal TEXT, memory_id TEXT REFERENCES memories(id),
      confidence REAL NOT NULL DEFAULT 0.7,
      valid_from TEXT, valid_to TEXT, created_at TEXT NOT NULL, source TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS ix_rel_subject ON relations(subject_id, predicate)",
    "CREATE INDEX IF NOT EXISTS ix_rel_object ON relations(object_id)",
    """CREATE TABLE IF NOT EXISTS episodes (
      rid INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
      scope_profile TEXT NOT NULL, scope_user TEXT NOT NULL DEFAULT '',
      scope_chat TEXT NOT NULL DEFAULT '',
      kind TEXT NOT NULL CHECK (kind IN ('session','window','precompress','delegation','manual')),
      session_id TEXT NOT NULL DEFAULT '', window_seq INTEGER NOT NULL DEFAULT 0,
      title TEXT NOT NULL, summary TEXT NOT NULL,
      decisions TEXT NOT NULL DEFAULT '[]', open_loops TEXT NOT NULL DEFAULT '[]',
      entities TEXT NOT NULL DEFAULT '[]', start_at TEXT, end_at TEXT,
      importance REAL NOT NULL DEFAULT 0.5,
      summarizer TEXT NOT NULL DEFAULT 'extractive',
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL, legacy_id TEXT UNIQUE,
      UNIQUE(session_id, kind, window_seq)
    )""",
    """CREATE VIRTUAL TABLE IF NOT EXISTS episodes_fts USING fts5(
      title, summary, decisions, open_loops, content='episodes', content_rowid='rid',
      tokenize='porter unicode61 remove_diacritics 2'
    )""",
    """CREATE TRIGGER IF NOT EXISTS episodes_ai AFTER INSERT ON episodes BEGIN
      INSERT INTO episodes_fts(rowid, title, summary, decisions, open_loops)
      VALUES (new.rid, new.title, new.summary, new.decisions, new.open_loops);
    END""",
    """CREATE TRIGGER IF NOT EXISTS episodes_ad AFTER DELETE ON episodes BEGIN
      INSERT INTO episodes_fts(episodes_fts, rowid, title, summary, decisions, open_loops)
      VALUES ('delete', old.rid, old.title, old.summary, old.decisions, old.open_loops);
    END""",
    """CREATE TRIGGER IF NOT EXISTS episodes_au
       AFTER UPDATE OF title, summary, decisions, open_loops ON episodes BEGIN
      INSERT INTO episodes_fts(episodes_fts, rowid, title, summary, decisions, open_loops)
      VALUES ('delete', old.rid, old.title, old.summary, old.decisions, old.open_loops);
      INSERT INTO episodes_fts(rowid, title, summary, decisions, open_loops)
      VALUES (new.rid, new.title, new.summary, new.decisions, new.open_loops);
    END""",
    """CREATE TABLE IF NOT EXISTS transcript_chunks (
      digest TEXT PRIMARY KEY,
      session_id TEXT NOT NULL, seq INTEGER NOT NULL, role TEXT NOT NULL,
      author_id TEXT NOT NULL DEFAULT '',
      text TEXT NOT NULL, ts TEXT, captured_at TEXT NOT NULL, source TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS ix_chunks_session ON transcript_chunks(session_id, seq)",
    """CREATE TABLE IF NOT EXISTS embeddings (
      owner_type TEXT NOT NULL CHECK (owner_type IN ('memory','episode','note_chunk')),
      owner_id TEXT NOT NULL,
      model TEXT NOT NULL, dim INTEGER NOT NULL, vector BLOB NOT NULL,
      content_hash TEXT NOT NULL, created_at TEXT NOT NULL,
      PRIMARY KEY(owner_type, owner_id, model)
    )""",
    """CREATE TABLE IF NOT EXISTS jobs (
      id TEXT PRIMARY KEY, type TEXT NOT NULL, payload TEXT NOT NULL DEFAULT '{}',
      dedupe_key TEXT UNIQUE,
      status TEXT NOT NULL DEFAULT 'queued'
             CHECK (status IN ('queued','running','done','failed','dead')),
      priority INTEGER NOT NULL DEFAULT 5, attempts INTEGER NOT NULL DEFAULT 0,
      max_attempts INTEGER NOT NULL DEFAULT 5,
      run_after TEXT NOT NULL, locked_by TEXT, locked_until TEXT, last_error TEXT,
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS ix_jobs_ready ON jobs(status, run_after, priority)",
    """CREATE TABLE IF NOT EXISTS audit_log (
      seq INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, action TEXT NOT NULL,
      actor TEXT NOT NULL,
      session_id TEXT NOT NULL DEFAULT '', target_id TEXT NOT NULL DEFAULT '',
      detail TEXT NOT NULL DEFAULT '{}',
      ok INTEGER NOT NULL DEFAULT 1, prev_hash TEXT NOT NULL, hash TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS feedback (
      id INTEGER PRIMARY KEY AUTOINCREMENT, memory_id TEXT NOT NULL,
      session_id TEXT NOT NULL,
      signal TEXT NOT NULL CHECK (signal IN ('helpful','unhelpful','wrong','outdated')),
      note TEXT NOT NULL DEFAULT '', ts TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS metrics (
      id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, name TEXT NOT NULL,
      value REAL NOT NULL, labels TEXT NOT NULL DEFAULT '{}'
    )""",
    "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)",
)

#: Append-only audit triggers, created only after the rebuilt chain is in
#: place (they block UPDATE/DELETE, so adding them first would make the
#: rebuild impossible to correct).
_AUDIT_TRIGGERS: Tuple[str, ...] = (
    """CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_log
       BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END""",
    """CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_log
       WHEN (SELECT value FROM meta WHERE key='audit_purge_token') IS NULL
       BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END""",
)

#: v2 tables that hold data the migration reads. Used both to decide whether a
#: database really is a v2 store (any non-empty one) and to drop the empty
#: shells on a fresh install. ``facts_fts``/``episodes_fts`` are excluded: they
#: are rebuilt as external-content FTS, never read.
_V2_SOURCE_TABLES: Tuple[str, ...] = (
    "facts",
    "pending_facts",
    "facts_archive",
    "fact_versions",
    "episodes",
    "triples",
    "embeddings",
    "audit_log",
)

#: v2 tables renamed to ``v2_<name>`` and kept for one release (card).
#: ``episodes_fts``/``facts_fts`` are plain (non-external-content) fts5 tables
#: and rename cleanly along with their shadow tables.
_RENAMED_V2_TABLES: Tuple[str, ...] = _V2_SOURCE_TABLES + ("facts_fts", "episodes_fts")

# Tables v3 does not model (``schema_info``, ``profile_registry``, the sync
# tables, and ``graph_edges``/``notes_meta``/``notes_fts``) are deliberately
# NOT in ``_RENAMED_V2_TABLES`` and not dropped: they survive untouched.
# Preservation is asserted by
# ``test_unmodelled_tables_are_preserved_untouched``.


def _v2_row_counts(conn: sqlite3.Connection) -> Dict[str, int]:
    """Row counts of the v2 source tables, read from their ORIGINAL names.

    Returns ``{}`` when no v2 table holds a single row, which is how a fresh
    install is told apart from a real v2 database (``0001`` leaves the empty v2
    shape behind on every database, so table *presence* proves nothing).
    """
    counts: Dict[str, int] = {}
    for table in _V2_SOURCE_TABLES:
        if _table_exists(conn, table):
            n = _count(conn, table)
            if n:
                counts[table] = n
    return counts


def _drop_empty_v2_tables(conn: sqlite3.Connection) -> None:
    """Drop the empty v2 shells ``0001`` leaves on a fresh database.

    Only called when :func:`_v2_row_counts` found zero rows in every v2 source
    table, so nothing can be lost. Needed because v2 and v3 share the table
    names ``episodes``, ``embeddings`` and ``audit_log``: leaving the shells in
    place would make ``CREATE TABLE IF NOT EXISTS`` keep the **v2** shape under
    the v3 name.
    """
    for table in _V2_SOURCE_TABLES + _RENAMED_V2_TABLES:
        if _table_exists(conn, table):
            conn.execute(f"DROP TABLE IF EXISTS {table}")


def _rename_v2_tables(conn: sqlite3.Connection) -> None:
    """Rename every v2 table to ``v2_<name>``.

    Must run BEFORE the v3 DDL, for the same name-collision reason as
    :func:`_drop_empty_v2_tables`. ``facts_fts``/``episodes_fts`` are plain
    (non-external-content) fts5 tables and rename cleanly along with their
    shadow tables.
    """
    for table in _RENAMED_V2_TABLES:
        if _table_exists(conn, table):
            conn.execute(f"ALTER TABLE {table} RENAME TO v2_{table}")


def _create_v3_schema(conn: sqlite3.Connection) -> None:
    for statement in _V3_DDL:
        conn.execute(statement)


def _resolved_profile(conn: sqlite3.Connection) -> str:
    """``scope_profile`` fallback for rows with no ``profile_id``.

    v2 keeps registered profiles in ``profile_registry``; a single-row registry
    is the normal case. With several (or none) registered the migration cannot
    guess, so it uses ``default`` — the same value ``meta.owner_user_id``
    scoping falls back to in §3.5.
    """
    if _table_exists(conn, "v2_profile_registry") or _table_exists(conn, "profile_registry"):
        table = (
            "v2_profile_registry"
            if _table_exists(conn, "v2_profile_registry")
            else "profile_registry"
        )
        rows = [r[0] for r in conn.execute(f"SELECT slug FROM {table} ORDER BY slug")]
        if len(rows) == 1:
            return str(rows[0])
    return "default"


# --------------------------------------------------------------------------
# Data move: facts / pending_facts / facts_archive -> memories
# --------------------------------------------------------------------------

_MEMORY_COLUMNS = (
    "id, legacy_id, scope_profile, scope_user, scope_chat, visibility, kind, "
    "content, summary, content_hash, domain, tags, status, importance, "
    "confidence, sensitivity, source, source_session, source_turn, author_id, "
    "evidence, pinned, decay_class, valid_from, valid_to, created_at, "
    "updated_at, last_accessed_at, last_injected_at, access_count, "
    "inject_count, helpful_count, unhelpful_count, superseded_by, "
    "pending_reason, pending_expires_at, trust_flags, token_estimate, version"
)


class _MemoryRow:
    """One v2 row prepared as a v3 ``memories`` row (mutable: dedup edits it)."""

    __slots__ = (
        "legacy_id",
        "content",
        "summary",
        "hash",
        "domain",
        "tags",
        "status",
        "importance",
        "sensitivity",
        "source",
        "session",
        "kind",
        "decay",
        "valid_from",
        "created_at",
        "updated_at",
        "last_accessed",
        "access_count",
        "version",
        "scope_profile",
        "pending_reason",
        "pending_expires_at",
        "memory_id",
        "superseded_by",
        "valid_to",
        "sort_key",
    )

    def __init__(self, **kwargs: object) -> None:
        for name in self.__slots__:
            setattr(self, name, kwargs.get(name))


def _prepare(
    row: sqlite3.Row,
    *,
    status: str,
    profile: str,
    pending_reason: str = "",
    pending_expires_at: Optional[str] = None,
    updated_override: Optional[str] = None,
) -> _MemoryRow:
    """Turn one v2 row (facts / pending_facts / facts_archive) into a
    :class:`_MemoryRow`."""
    content = "" if row["content"] is None else str(row["content"])
    tags = _split_tags(row["tags"] if "tags" in row.keys() else "")
    source_raw = row["source"] if "source" in row.keys() else ""
    domain = str(row["domain"] or "Knowledge") if "domain" in row.keys() else "Knowledge"
    importance = _clamp01(row["importance"] if "importance" in row.keys() else 0.5, 0.5)
    kind = _kind_for(domain, source_raw, tags, content)

    created = _to_v3_ts(row["created_at"] if "created_at" in row.keys() else None)
    updated_raw = (
        updated_override
        if updated_override is not None
        else (row["updated_at"] if "updated_at" in row.keys() else None)
    )
    updated = _to_v3_ts(updated_raw) or created

    raw_profile = row["profile_id"] if "profile_id" in row.keys() else ""
    scope_profile = str(raw_profile).strip() if raw_profile else profile

    title = row["title"] if "title" in row.keys() else ""
    summary = "" if title is None else str(title).strip()[:_SUMMARY_MAX]

    return _MemoryRow(
        legacy_id=str(row["legacy_id"]),
        content=content,
        summary=summary,
        hash=content_hash(content),
        domain=domain,
        tags=json.dumps(tags, ensure_ascii=False),
        status=status,
        importance=importance,
        sensitivity=_map_sensitivity(row["sensitivity"] if "sensitivity" in row.keys() else None),
        source=_map_source(source_raw),
        session=str(row["session_id"] or "") if "session_id" in row.keys() else "",
        kind=kind,
        decay=_decay_for(kind, importance),
        valid_from=_to_v3_ts(row["fact_timestamp"] if "fact_timestamp" in row.keys() else None),
        created_at=created or clock.to_iso(clock.utc_now()),
        updated_at=updated or created or clock.to_iso(clock.utc_now()),
        last_accessed=_to_v3_ts(row["last_accessed"] if "last_accessed" in row.keys() else None),
        access_count=int(row["access_count"] or 0) if "access_count" in row.keys() else 0,
        version=int(row["version"] or 1) if "version" in row.keys() else 1,
        scope_profile=scope_profile,
        pending_reason=pending_reason,
        pending_expires_at=pending_expires_at,
        memory_id=None,
        superseded_by=None,
        valid_to=None,
        # Deterministic winner selection: newest update wins, legacy id breaks ties.
        sort_key=(updated or created or "", str(row["legacy_id"])),
    )


def _collect_memories(conn: sqlite3.Connection, profile: str) -> List[_MemoryRow]:
    """Read every v2 fact-like row into :class:`_MemoryRow` objects."""
    prepared: List[_MemoryRow] = []

    if _table_exists(conn, "v2_facts"):
        query = "SELECT id AS legacy_id, * FROM v2_facts ORDER BY id"
        for row in conn.execute(query):
            status = "deleted" if int(row["deleted"] or 0) == 1 else "active"
            prepared.append(_prepare(row, status=status, profile=profile))

    if _table_exists(conn, "v2_pending_facts"):
        query = "SELECT id AS legacy_id, * FROM v2_pending_facts ORDER BY id"
        for row in conn.execute(query):
            created = _to_v3_ts(row["created_at"])
            expires: Optional[str] = None
            if created:
                try:
                    expires = clock.to_iso(
                        clock.parse_iso(created) + timedelta(days=_PENDING_TTL_DAYS)
                    )
                except ValueError:
                    expires = None
            prepared.append(
                _prepare(
                    row,
                    status="pending",
                    profile=profile,
                    pending_reason=str(row["reason"] or "") if "reason" in row.keys() else "",
                    pending_expires_at=expires,
                )
            )

    if _table_exists(conn, "v2_facts_archive"):
        query = "SELECT id AS legacy_id, * FROM v2_facts_archive ORDER BY id"
        for row in conn.execute(query):
            archived = _to_v3_ts(row["archived_at"] if "archived_at" in row.keys() else None)
            prepared.append(
                _prepare(
                    row,
                    status="archived",
                    profile=profile,
                    updated_override=archived,
                )
            )

    return prepared


def _resolve_duplicates(rows: List[_MemoryRow]) -> Tuple[int, int]:
    """Apply the card's status machine to v3's new uniqueness constraint.

    Within each ``(content_hash, scope_profile, scope_user, scope_chat)`` group
    that the partial unique index covers (``active``/``pending``), the newest
    row keeps its status and the rest become ``superseded``. Returns
    ``(groups_with_collisions, rows_superseded)``.
    """
    groups: Dict[Tuple[str, str, str, str], List[_MemoryRow]] = {}
    for row in rows:
        if row.status not in ("active", "pending"):
            continue
        key = (row.hash, row.scope_profile, "", "")
        groups.setdefault(key, []).append(row)

    collisions = 0
    superseded = 0
    for members in groups.values():
        if len(members) < 2:
            continue
        collisions += 1
        members.sort(key=lambda r: r.sort_key, reverse=True)
        winner = members[0]
        for loser in members[1:]:
            loser.status = "superseded"
            loser.superseded_by = winner.legacy_id  # resolved to a mem_ id below
            loser.valid_to = winner.created_at
            superseded += 1
    return collisions, superseded


def _insert_memories(conn: sqlite3.Connection, rows: List[_MemoryRow]) -> Dict[str, str]:
    """Insert every row; returns ``legacy_id -> mem_ id``.

    ``superseded_by`` is filled in by a second pass because it is a
    self-referencing foreign key and ``foreign_keys`` is ON.
    """
    legacy_to_new: Dict[str, str] = {}
    insert_sql = f"INSERT INTO memories ({_MEMORY_COLUMNS}) VALUES ({','.join('?' * 39)})"

    for row in rows:
        new_id = clock.new_id("mem")
        row.memory_id = new_id
        legacy_to_new[row.legacy_id] = new_id
        conn.execute(
            insert_sql,
            (
                new_id,
                row.legacy_id,
                row.scope_profile,
                "",  # scope_user: v2 had no per-user scoping (§3.5, S4)
                "",  # scope_chat
                "profile",  # visibility: v2 facts were profile-wide (card)
                row.kind,
                row.content,
                row.summary,
                row.hash,
                row.domain,
                row.tags,
                row.status,
                row.importance,
                0.8,  # confidence: v2 recorded none
                row.sensitivity,
                row.source,
                row.session,
                None,  # source_turn
                "",  # author_id
                "",  # evidence
                0,  # pinned
                row.decay,
                row.valid_from,
                row.valid_to,
                row.created_at,
                row.updated_at,
                row.last_accessed,
                None,  # last_injected_at
                row.access_count,
                0,  # inject_count
                0,  # helpful_count
                0,  # unhelpful_count
                None,  # superseded_by (second pass)
                row.pending_reason or "",
                row.pending_expires_at,
                "[]",  # trust_flags
                0,  # token_estimate
                row.version,
            ),
        )

    # Second pass: superseded_by (not in the trigger's UPDATE OF list, so no
    # FTS churn).
    for row in rows:
        if row.superseded_by:
            winner = legacy_to_new.get(row.superseded_by)
            if winner is not None:
                conn.execute(
                    "UPDATE memories SET superseded_by=? WHERE id=?",
                    (winner, row.memory_id),
                )
    return legacy_to_new


# --------------------------------------------------------------------------
# Data move: remaining tables
# --------------------------------------------------------------------------


def _move_memory_versions(conn: sqlite3.Connection, legacy_to_new: Dict[str, str]) -> Tuple[int, int]:
    """``fact_versions`` → ``memory_versions``. Returns (moved, orphaned)."""
    if not _table_exists(conn, "v2_fact_versions"):
        return 0, 0
    rows = conn.execute(
        "SELECT fact_id, content, importance, created_at, source"
        " FROM v2_fact_versions ORDER BY fact_id, created_at, id"
    ).fetchall()

    per_memory: Dict[str, int] = {}
    moved = 0
    orphaned = 0
    for row in rows:
        memory_id = legacy_to_new.get(str(row["fact_id"]))
        if memory_id is None:
            orphaned += 1  # kept in v2_fact_versions; see module docstring
            continue
        version = per_memory.get(memory_id, 0) + 1
        per_memory[memory_id] = version
        conn.execute(
            "INSERT INTO memory_versions (memory_id, version, content, importance,"
            " confidence, status, valid_from, valid_to, changed_at, change_reason, actor)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                memory_id,
                version,
                str(row["content"]),
                _clamp01(row["importance"], 0.5) if row["importance"] is not None else None,
                None,
                None,
                None,
                None,
                _to_v3_ts_or(row["created_at"], None),
                str(row["source"] or "version_snapshot"),
                "",  # v2 recorded no actor
            ),
        )
        moved += 1
    return moved, orphaned


def _move_episodes(conn: sqlite3.Connection, profile: str) -> int:
    if not _table_exists(conn, "v2_episodes"):
        return 0
    rows = conn.execute(
        "SELECT episode_id, title, summary, start_ts, end_ts, source_session,"
        " importance, created_at FROM v2_episodes ORDER BY created_at, episode_id"
    ).fetchall()

    counters: Dict[Tuple[str, str], int] = {}
    moved = 0
    for row in rows:
        episode_id = str(row["episode_id"])
        kind = _episode_kind(episode_id)
        # Card: manual episodes use their own id as session_id (load-bearing —
        # it is what keeps UNIQUE(session_id, kind, window_seq) satisfiable).
        session_id = episode_id if kind == "manual" else str(row["source_session"] or "")
        seq = counters.get((session_id, kind), 0)
        counters[(session_id, kind)] = seq + 1
        created = _to_v3_ts_or(row["created_at"], None)
        conn.execute(
            "INSERT INTO episodes (id, scope_profile, scope_user, scope_chat, kind,"
            " session_id, window_seq, title, summary, decisions, open_loops, entities,"
            " start_at, end_at, importance, summarizer, created_at, updated_at, legacy_id)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                episode_id,  # kept, see module docstring
                profile,
                "",
                "",
                kind,
                session_id,
                seq,
                str(row["title"] or ""),
                str(row["summary"] or ""),
                "[]",
                "[]",
                "[]",
                _to_v3_ts(row["start_ts"]),
                _to_v3_ts(row["end_ts"]),
                _clamp01(row["importance"], 0.5),
                "extractive",
                created,
                created,  # v2 episodes had no updated_at
                episode_id,
            ),
        )
        moved += 1
    return moved


def _move_triples(conn: sqlite3.Connection, profile: str) -> Tuple[int, int]:
    """``triples`` → ``entities`` + ``entity_aliases`` + ``relations``."""
    if not _table_exists(conn, "v2_triples"):
        return 0, 0
    rows = conn.execute(
        "SELECT subject, predicate, object, valid_from, valid_until, source,"
        " confidence, created_at FROM v2_triples ORDER BY id"
    ).fetchall()

    now = clock.to_iso(clock.utc_now())
    name_to_entity: Dict[str, str] = {}

    def entity_id_for(name: str) -> str:
        existing = name_to_entity.get(name)
        if existing is not None:
            return existing
        new_id = clock.new_id("ent")
        name_to_entity[name] = new_id
        conn.execute(
            "INSERT INTO entities (id, scope_profile, name, kind, description,"
            " created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
            (
                new_id,
                profile,
                name,
                _ENTITY_KINDS.get(normalize_content(name), "thing"),
                "",
                now,
                now,
            ),
        )
        conn.execute(
            "INSERT OR IGNORE INTO entity_aliases (alias_norm, entity_id) VALUES (?,?)",
            (normalize_content(name), new_id),
        )
        return new_id

    moved = 0
    for row in rows:
        subject = str(row["subject"])
        obj = str(row["object"])
        conn.execute(
            "INSERT INTO relations (id, scope_profile, subject_id, predicate,"
            " object_id, object_literal, memory_id, confidence, valid_from,"
            " valid_to, created_at, source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                clock.new_id("rel"),
                profile,
                entity_id_for(subject),
                str(row["predicate"]),
                entity_id_for(obj),
                None,
                None,  # v2 triples carried no originating fact
                _clamp01(row["confidence"], 0.7),
                _to_v3_ts(row["valid_from"]),
                _to_v3_ts(row["valid_until"]),
                _to_v3_ts_or(row["created_at"], now),
                str(row["source"] or "extracted"),
            ),
        )
        moved += 1
    return moved, len(name_to_entity)


def _move_embeddings(
    conn: sqlite3.Connection, legacy_to_new: Dict[str, str]
) -> Tuple[int, int]:
    """``embeddings`` → ``embeddings(owner_type='memory')``. Returns (moved, orphaned)."""
    if not _table_exists(conn, "v2_embeddings"):
        return 0, 0
    rows = conn.execute(
        "SELECT fact_id, vector, model, dim, created_at FROM v2_embeddings ORDER BY fact_id"
    ).fetchall()

    hashes = {
        row["id"]: (row["content_hash"], row["content"])
        for row in conn.execute("SELECT id, content_hash, content FROM memories")
    }
    moved = 0
    orphaned = 0
    for row in rows:
        memory_id = legacy_to_new.get(str(row["fact_id"]))
        if memory_id is None:
            orphaned += 1  # kept in v2_embeddings
            continue
        entry = hashes.get(memory_id)
        digest = entry[0] if entry else content_hash(str(entry[1]) if entry else "")
        conn.execute(
            "INSERT OR REPLACE INTO embeddings (owner_type, owner_id, model, dim,"
            " vector, content_hash, created_at) VALUES ('memory',?,?,?,?,?,?)",
            (
                memory_id,
                str(row["model"] or "all-MiniLM-L6-v2"),
                int(row["dim"] or 0),
                row["vector"],
                digest,
                _to_v3_ts_or(row["created_at"], None),
            ),
        )
        moved += 1
    return moved, orphaned


def _rebuild_audit_log(conn: sqlite3.Connection) -> int:
    """``audit_log`` → hash-chained ``audit_log``, rebuilt in ``seq`` order."""
    if not _table_exists(conn, "v2_audit_log"):
        return 0
    rows = conn.execute(
        "SELECT id, ts, action, actor, session_id, fact_id, detail, ok"
        " FROM v2_audit_log ORDER BY id"
    ).fetchall()

    genesis = "0" * 64
    prev_hash = genesis
    moved = 0
    for row in rows:
        ts = _to_v3_ts_or(row["ts"], None)
        action = str(row["action"] or "")
        actor = str(row["actor"] or "")
        target_id = str(row["fact_id"] or "")
        detail = _detail_to_json(row["detail"])
        digest = _audit_hash(prev_hash, ts, action, actor, target_id, detail)
        conn.execute(
            "INSERT INTO audit_log (seq, ts, action, actor, session_id, target_id,"
            " detail, ok, prev_hash, hash) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                int(row["id"]),  # preserve the original sequence
                ts,
                action,
                actor,
                str(row["session_id"] or ""),
                target_id,
                detail,
                1 if row["ok"] is None else int(row["ok"]),
                prev_hash,
                digest,
            ),
        )
        prev_hash = digest
        moved += 1
    return moved


def _seed_meta(conn: sqlite3.Connection, stats: Dict[str, object]) -> None:
    """Record migration provenance and the §3.5 owner default."""
    defaults = {
        "schema_generation": "3",
        "owner_user_id": "owner",
        "migrated_from": "v2",
    }
    defaults.update({k: str(v) for k, v in stats.items()})
    for key, value in sorted(defaults.items()):
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?,?)", (key, value)
        )


# --------------------------------------------------------------------------
# Parity checks (card AC: abort on mismatch)
# --------------------------------------------------------------------------


def _fts_indexed_rows(conn: sqlite3.Connection, fts: str) -> int:
    """Number of documents actually present in an external-content FTS index.

    Reads the ``<fts>_docsize`` shadow table, which holds exactly one row per
    indexed document. This is the only cheap probe that detects a
    *missing-row* desync (a dropped trigger, an index never populated):

    * ``INSERT INTO <fts>(<fts>) VALUES('integrity-check')`` compares the index
      against the **content table**, so it passes even when the index is empty
      while rows exist — verified empirically.
    * ``SELECT count(*) FROM <fts>`` on an external-content table reads
      *through* to the content table, so it always agrees with the base table
      and detects nothing.
    * ``MATCH`` detects it but needs a token to search for.

    Shadow-table naming is part of fts5's stable layout; if a future SQLite
    renames it this raises rather than silently reporting a healthy index.
    """
    try:
        return int(conn.execute(f"SELECT COUNT(*) FROM {fts}_docsize").fetchone()[0])
    except sqlite3.OperationalError as exc:  # pragma: no cover - schema drift
        raise ParityError(f"cannot probe {fts} index ({exc})") from exc


def _verify_fts_sync(conn: sqlite3.Connection) -> None:
    """Assert both external-content FTS indexes actually hold their rows."""
    for fts, base in (("memories_fts", "memories"), ("episodes_fts", "episodes")):
        expected = _count(conn, base)
        indexed = _fts_indexed_rows(conn, fts)
        _require(
            indexed == expected,
            f"{fts} holds {indexed} documents but {base} has {expected} rows"
            " — external-content FTS is out of sync",
        )
        # Belt and braces: the index must also be internally consistent.
        conn.execute(f"INSERT INTO {fts}({fts}) VALUES('integrity-check')")


def _verify_parity(
    conn: sqlite3.Connection,
    *,
    source_counts: Dict[str, int],
    moved: Dict[str, int],
) -> None:
    """Row-count and content parity. Any mismatch raises :class:`ParityError`,
    which rolls the whole migration back."""
    expected_memories = (
        source_counts.get("v2_facts", 0)
        + source_counts.get("v2_pending_facts", 0)
        + source_counts.get("v2_facts_archive", 0)
    )
    actual_memories = _count(conn, "memories")
    _require(
        actual_memories == expected_memories,
        f"memories row count {actual_memories} != v2 sources {expected_memories}",
    )

    # Every v2 id must resolve exactly once.
    distinct_legacy = conn.execute(
        "SELECT COUNT(DISTINCT legacy_id) FROM memories WHERE legacy_id IS NOT NULL"
    ).fetchone()[0]
    _require(
        int(distinct_legacy) == actual_memories,
        f"legacy_id not 1:1 ({distinct_legacy} distinct for {actual_memories} rows)",
    )
    missing = conn.execute("SELECT COUNT(*) FROM memories WHERE legacy_id IS NULL").fetchone()[0]
    _require(int(missing) == 0, f"{missing} memories have no legacy_id")

    # Content parity, per source table.
    for v2_table in ("v2_facts", "v2_pending_facts", "v2_facts_archive"):
        if not source_counts.get(v2_table):
            continue
        mismatched = conn.execute(
            f"SELECT COUNT(*) FROM memories m JOIN {v2_table} f ON f.id = m.legacy_id"
            " WHERE m.content IS NOT f.content"
        ).fetchone()[0]
        _require(
            int(mismatched) == 0,
            f"{mismatched} memories differ in content from {v2_table}",
        )
        unmigrated = conn.execute(
            f"SELECT COUNT(*) FROM {v2_table} f WHERE NOT EXISTS"
            " (SELECT 1 FROM memories m WHERE m.legacy_id = f.id)"
        ).fetchone()[0]
        _require(
            int(unmigrated) == 0,
            f"{unmigrated} rows of {v2_table} did not reach memories",
        )

    # Status accounting: superseded rows must point at a real winner.
    dangling = conn.execute(
        "SELECT COUNT(*) FROM memories WHERE status='superseded' AND ("
        " superseded_by IS NULL OR superseded_by NOT IN (SELECT id FROM memories))"
    ).fetchone()[0]
    _require(int(dangling) == 0, f"{dangling} superseded memories lack a valid superseded_by")

    # The new unique index must actually hold.
    dupe = conn.execute(
        "SELECT COUNT(*) FROM (SELECT content_hash, scope_profile, scope_user, scope_chat"
        " FROM memories WHERE status IN ('active','pending')"
        " GROUP BY 1,2,3,4 HAVING COUNT(*) > 1)"
    ).fetchone()[0]
    _require(int(dupe) == 0, f"{dupe} duplicate (hash, scope) groups among active/pending")

    # Episodes / triples / audit.
    if source_counts.get("v2_episodes"):
        _require(
            _count(conn, "episodes") == source_counts["v2_episodes"],
            f"episodes {_count(conn, 'episodes')} != v2 {source_counts['v2_episodes']}",
        )
    if source_counts.get("v2_triples"):
        _require(
            _count(conn, "relations") == source_counts["v2_triples"],
            f"relations {_count(conn, 'relations')} != v2 triples {source_counts['v2_triples']}",
        )
    if source_counts.get("v2_audit_log"):
        _require(
            _count(conn, "audit_log") == source_counts["v2_audit_log"],
            f"audit_log {_count(conn, 'audit_log')} != v2 {source_counts['v2_audit_log']}",
        )
        _verify_audit_chain(conn)

    # Embeddings and versions: moved + orphaned must equal the v2 total.
    for label, v2_table in (("embeddings", "v2_embeddings"), ("memory_versions", "v2_fact_versions")):
        if not source_counts.get(v2_table):
            continue
        accounted = int(moved.get(f"{label}_moved", 0)) + int(moved.get(f"{label}_orphaned", 0))
        _require(
            accounted == source_counts[v2_table],
            f"{label}: moved+orphaned {accounted} != v2 rows {source_counts[v2_table]}",
        )

    # External-content FTS must actually hold every row (see _fts_indexed_rows:
    # 'integrity-check' alone cannot detect a missing-row desync).
    _verify_fts_sync(conn)


def _verify_audit_chain(conn: sqlite3.Connection) -> None:
    """Recompute every audit hash; the chain must verify from genesis."""
    prev = "0" * 64
    for row in conn.execute(
        "SELECT seq, ts, action, actor, target_id, detail, prev_hash, hash"
        " FROM audit_log ORDER BY seq"
    ):
        expected_prev = str(row["prev_hash"])
        _require(
            expected_prev == prev,
            f"audit seq {row['seq']}: prev_hash {expected_prev[:12]}… != expected {prev[:12]}…",
        )
        expected = _audit_hash(
            prev,
            str(row["ts"]),
            str(row["action"]),
            str(row["actor"]),
            str(row["target_id"]),
            str(row["detail"]),
        )
        _require(
            str(row["hash"]) == expected,
            f"audit seq {row['seq']}: hash does not match its contents",
        )
        prev = expected


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def up(conn: sqlite3.Connection) -> None:
    """Create the v3 core schema and move all v2 data into it. Never commits."""
    if _table_exists(conn, "memories"):
        # Already applied. The runner never re-invokes an applied migration
        # (user_version + checksum guard), so this only fires if up() is called
        # directly twice; treat it as a no-op rather than corrupting data.
        return

    has_v2_data = _v2_row_counts(conn)
    if not has_v2_data:
        # Fresh install. Note that ``0001`` runs first and always leaves the
        # *empty* v2 shape behind, so "a facts table exists" does NOT mean
        # "this is a v2 database" — only non-empty source tables do. Dropping
        # the empty shells keeps a new store a clean v3 schema instead of a v3
        # schema littered with empty ``v2_*`` tables and a bogus
        # ``migrated_from='v2'`` marker. Safe: the runner already backed the
        # database up, and nothing here has a single row.
        _drop_empty_v2_tables(conn)
        _create_v3_schema(conn)
        _seed_meta(conn, {"migrated_from": "none", "memories": 0})
        return

    # Rename BEFORE creating the v3 schema: v2 and v3 share the names
    # ``episodes``, ``embeddings`` and ``audit_log``, and the v3 DDL uses
    # ``IF NOT EXISTS`` — creating it first would silently keep the v2 shape.
    _rename_v2_tables(conn)
    source_counts = {f"v2_{table}": n for table, n in has_v2_data.items()}

    _create_v3_schema(conn)

    profile = _resolved_profile(conn)
    rows = _collect_memories(conn, profile)
    collisions, superseded = _resolve_duplicates(rows)
    legacy_to_new = _insert_memories(conn, rows)

    versions_moved, versions_orphaned = _move_memory_versions(conn, legacy_to_new)
    episodes_moved = _move_episodes(conn, profile)
    relations_moved, entities_created = _move_triples(conn, profile)
    embeddings_moved, embeddings_orphaned = _move_embeddings(conn, legacy_to_new)
    audit_moved = _rebuild_audit_log(conn)

    moved: Dict[str, int] = {
        "memories": len(rows),
        "memories_superseded_by_dedup": superseded,
        "dedup_collision_groups": collisions,
        "memory_versions_moved": versions_moved,
        "memory_versions_orphaned": versions_orphaned,
        "episodes_moved": episodes_moved,
        "relations_moved": relations_moved,
        "entities_created": entities_created,
        "embeddings_moved": embeddings_moved,
        "embeddings_orphaned": embeddings_orphaned,
        "audit_rows_rebuilt": audit_moved,
    }

    _verify_parity(conn, source_counts=source_counts, moved=moved)

    # Append-only triggers only after the rebuilt chain is final.
    for statement in _AUDIT_TRIGGERS:
        conn.execute(statement)

    _seed_meta(conn, dict(moved))
