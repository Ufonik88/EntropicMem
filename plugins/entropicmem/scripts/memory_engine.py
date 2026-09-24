"""
memory_engine.py — Standalone SQLite memory engine for EntropicMem.

Provides:
  - Durable fact storage with FTS5 search
  - Unsupervised regex-based auto-extraction from conversation text
  - Temporal decay & reinforcement scoring
  - Graph edges (wikilink relationships)
  - entropic_id-based deduplication and round-trip identity
  - Export to vault as Markdown projection (optional)

Stdlib-only. No external memory dependencies.
"""

import fcntl
import hashlib
import json
import logging
import math
import os
import re
import sqlite3
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from stopwords import STOPWORDS  # English stopword set for the FTS builder
from vault import derive_title  # naming convention helper (stdlib-only, acyclic)

logger = logging.getLogger(__name__)

# ── shared FTS5 query building (memory_engine + index + retrieval) ───────────
#
# Exactly one MATCH-expression builder for the whole codebase. Every caller
# (facts prefetch/recall, vault search) goes through build_fts_query() so the
# same user query means the same thing everywhere, punctuation can never raise
# sqlite3.OperationalError, and hot-path queries stay bounded. index.py and
# retrieval.py import these from here — this module stays self-contained so a
# standalone copy of memory_engine.py keeps working.
#
# tokenizer='porter unicode61' on every FTS table: unicode61 keeps \w-ish
# tokens whole (underscores included, no '#'/'@' splitting).

MAX_FTS_TERMS = 10  # cap OR-of-prefix terms at the most discriminative words

FTS_REASON_OK = "fts"
FTS_REASON_MATCH_ERROR = "match_error"

_FTS_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_FTS_PHRASE_RE = re.compile(r"\S+", re.UNICODE)


def _fts_quote(token: str, star: bool = True) -> str:
    """Quote one token as a literal FTS5 phrase (metacharacter-safe).

    The surrounding double quotes make the token a plain string (so barewords
    like NEAR/AND/OR and leftover punctuation are literal) and internal
    quotes are doubled. ``star`` appends the trailing prefix ``*`` — terms
    of 3+ characters prefix-match their derivational family (``use`` →
    ``used``/``uses``); 1-2 character terms are exact (a prefix there would
    match nearly every document).
    """
    quoted = f'"{token.replace(chr(34), chr(34) * 2)}"'
    return quoted + ("*" if star else "")


def build_fts_query(
    query: str,
    max_terms: int = MAX_FTS_TERMS,
    fields: Sequence[str] = ("title", "tags", "body"),
) -> str:
    """Build one shared FTS5 MATCH expression for a free-text query.

    Tokenizes the query into ``\\w+`` runs (dropping FTS5 metacharacters such
    as quotes, colons, parentheses, ^ and * so punctuation can never produce a
    syntax error) and applies the term-quality rules (R2):

    - stopword tokens and tokens shorter than 2 characters are dropped —
      they appear in almost every document, so as terms they match
      everything and drown the discriminative words;
    - the prefix ``*`` goes only on tokens of 4+ characters; shorter tokens
      are exact terms (a 1-2 character prefix matches almost everything);
    - when every token was dropped (e.g. "who am I") the raw tokens come
      back, with the length rules applied as far as possible without
      emptying the query, so identity-style questions still match;
    - the surviving terms are capped at ``max_terms`` — non-stopwords first,
      then longest (most discriminative) first.

    Every term is quoted as a literal FTS5 phrase (embedded quotes doubled).
    ``fields`` are grouped per term with the FTS5 ``{col ...}`` filter so
    every caller matches the same columns.

    Returns '' when the query has no usable tokens — callers must treat ''
    as 'no matches' (skip MATCH and the fallback sweep; never match
    everything).
    """
    tokens: List[str] = []
    seen: Set[str] = set()
    for raw in _FTS_TOKEN_RE.findall(query):
        key = raw.lower()
        if key in seen:
            continue
        seen.add(key)
        tokens.append(raw)
    if not tokens:
        return ""
    kept = [t for t in tokens if len(t) >= 2 and t.lower() not in STOPWORDS]
    if not kept:
        # All tokens were dropped (every one a stopword and/or too short) —
        # fall back to the raw tokens and re-apply the length rules only as
        # far as possible without emptying the query.
        kept = [t for t in tokens if len(t) >= 2] or list(tokens)
    # Selection order for the cap: non-stopwords first, then longest first.
    kept.sort(key=lambda t: (t.lower() in STOPWORDS, -len(t)))
    kept = kept[:max_terms]
    cols = "{" + " ".join(fields) + "}" if len(fields) > 1 else (fields[0] if fields else "")
    prefix = f"{cols}: " if cols else ""
    return " OR ".join(prefix + _fts_quote(t, star=len(t) >= 3) for t in kept)


def phrase_query(text: str) -> str:
    """Metacharacter-safe single FTS5 phrase (no prefix) built from ``text``.

    Used where whole-phrase matching matters (e.g. wikilink title candidacy).
    Returns '' when the text has no usable tokens.
    """
    words = [w for w in _FTS_PHRASE_RE.findall(text)]
    if not words:
        return ""
    phrase = " ".join(words).replace('"', '""')
    return f'"{phrase}"'


def escape_like(text: str) -> str:
    """Escape LIKE wildcards (\\, %, _) in user input.

    Pair the result with ``LIKE ? ESCAPE '\\'`` so user-supplied percent and
    underscore are matched literally instead of acting as wildcards.
    """
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


_WORD_RE = re.compile(r"[A-Za-z]")


def _parse_ts(stamp: Optional[str]) -> Optional[datetime]:
    """Parse an ISO timestamp; naive values are read as UTC. None-safe."""
    if not stamp:
        return None
    try:
        dt = datetime.fromisoformat(stamp)
    except (ValueError, TypeError):
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _like_fallback_ok(query: str, match_failed: bool) -> bool:
    """Escaped literal LIKE fallback only for symbol/number queries (``%``,
    ``_``, ``8080``) or when the FTS MATCH itself errored. Word queries never
    substring-sweep: no FTS hits means no matches (R2 noise)."""
    return match_failed or _WORD_RE.search(query) is None


_STEM_SUFFIXES = ("ing", "ed", "es", "s", "ly")


def _stem(token: str) -> str:
    """Conservative suffix strip for coverage matching.
    # ponytail: crude suffix-list stemmer — covers plurals/verb forms; switch
    to a real stemmer only if recall quality demonstrably needs it."""
    for suf in _STEM_SUFFIXES:
        if token.endswith(suf) and len(token) - len(suf) >= 3:
            return token[: -len(suf)]
    return token


def coverage(query_terms: Sequence[str], text: str) -> float:
    """Lexical coverage (EM-105): stemmed query terms present in text / total.

    Absolute 0..1 per result — never normalised against the result set, so a
    weak hit can no longer inflate to relevance 1.0 (R1).
    """
    terms = [t for t in (_stem(str(q).lower()) for q in query_terms) if t]
    if not terms:
        return 0.0
    text_stems = {_stem(t) for t in _FTS_TOKEN_RE.findall(text.lower())}
    return sum(1 for t in terms if t in text_stems) / len(terms)


def coverage_terms(query: str) -> List[str]:
    """Coverage-side query terms: lowercase tokens minus stopwords/1-char."""
    return [
        t for t in _FTS_TOKEN_RE.findall(query.lower())
        if len(t) >= 2 and t not in STOPWORDS
    ]


def run_fts_match(db: sqlite3.Connection, sql: str, params: Tuple) -> Tuple[List, str]:
    """Run an FTS5 MATCH query without ever raising on the MATCH expression.

    Returns ``(rows, reason)`` where reason is ``FTS_REASON_OK`` ('fts') on
    success or ``FTS_REASON_MATCH_ERROR`` ('match_error') when SQLite rejects
    the MATCH expression — in which case the result is an empty list plus the
    reason token instead of an exception, and the failure is logged.
    """
    if not params or not params[0]:
        return [], FTS_REASON_MATCH_ERROR
    try:
        return db.execute(sql, params).fetchall(), FTS_REASON_OK
    except sqlite3.OperationalError as exc:
        logger.warning("FTS5 MATCH failed for %r: %s", params[0], exc)
        return [], FTS_REASON_MATCH_ERROR

try:
    from policy import (  # noqa: F401 (availability probe)
        evaluate_write,
        normalize_sensitivity,
        redact_for_prefetch,
    )
    POLICY_AVAILABLE = True
except ImportError:
    POLICY_AVAILABLE = False

# ── optional embedding support (Phase 7: semantic search) ──────────────────

try:
    from embeddings import (
        EMBEDDER_AVAILABLE as _EMB_AVAIL,
    )
    from embeddings import (
        NUMPY_AVAILABLE as _NP_AVAIL,
    )
    from embeddings import (
        cosine_similarity,  # noqa: F401 (availability probe)
        embed_text,
        embedding_coverage,
        hybrid_rank,
        init_embeddings_schema,
        invalidate_vector_cache,
        store_embedding,
        vector_search,
    )
    EMBEDDINGS_IMPORTABLE = True
    EMBEDDINGS_AVAILABLE = _EMB_AVAIL and _NP_AVAIL
except ImportError:
    EMBEDDINGS_IMPORTABLE = False
    EMBEDDINGS_AVAILABLE = False

# ── temporal query parsing (Phase 8) ────────────────────────────────────────

try:
    from temporal import extract_temporal_filter
    TEMPORAL_AVAILABLE = True
except ImportError:
    TEMPORAL_AVAILABLE = False

# ── PII detection (Phase 9) ─────────────────────────────────────────────────

try:
    from pii import check_pii, redact_pii, scan_pii  # noqa: F401 (availability probe)
    PII_AVAILABLE = True
except ImportError:
    PII_AVAILABLE = False

# ── schema ──────────────────────────────────────────────────────────────────

MEMORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
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
);

CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(
    content,
    title,
    tags,
    domain,
    tokenize='porter unicode61',
    content_rowid='rowid'
);

CREATE INDEX IF NOT EXISTS idx_facts_domain ON facts(domain);
CREATE INDEX IF NOT EXISTS idx_facts_importance ON facts(importance DESC);
CREATE INDEX IF NOT EXISTS idx_facts_created ON facts(created_at DESC);

-- P1 multi-profile provenance (2026-08-18): schema marker + profile slug registry
CREATE TABLE IF NOT EXISTS schema_info (
    schema_version INTEGER NOT NULL DEFAULT 1,
    phase INTEGER NOT NULL DEFAULT 1,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS profile_registry (
    slug TEXT PRIMARY KEY,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    renamed_to TEXT DEFAULT ''
);

-- P2 controlled sync (2026-08-18): local outbox + shared-facts projection
CREATE TABLE IF NOT EXISTS sync_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fact_id TEXT NOT NULL,
    op TEXT NOT NULL,
    version INTEGER NOT NULL,
    written_at TEXT NOT NULL,
    fact_timestamp TEXT DEFAULT '',
    payload TEXT NOT NULL,
    emitted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_sync_outbox_emitted ON sync_outbox(emitted);
CREATE TABLE IF NOT EXISTS sync_offsets (
    store_id TEXT PRIMARY KEY,
    last_event_seq INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS shared_facts (
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
);

-- v2.2.0 G1: episodic memory (session summaries / "what happened when")
CREATE TABLE IF NOT EXISTS episodes (
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
);
CREATE INDEX IF NOT EXISTS idx_episodes_start ON episodes(start_ts);
CREATE INDEX IF NOT EXISTS idx_episodes_domain ON episodes(domain);
CREATE INDEX IF NOT EXISTS idx_episodes_created ON episodes(created_at DESC);

CREATE VIRTUAL TABLE IF NOT EXISTS episodes_fts USING fts5(
    title,
    summary,
    tokenize='porter unicode61',
    content_rowid='rowid'
);

-- v2.2.0 G2: knowledge triples (subject --predicate--> object)
CREATE TABLE IF NOT EXISTS triples (
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
);
CREATE INDEX IF NOT EXISTS idx_triples_subject ON triples(subject);
CREATE INDEX IF NOT EXISTS idx_triples_object ON triples(object);
CREATE INDEX IF NOT EXISTS idx_triples_predicate ON triples(predicate);
"""

# ── P2 controlled sync: shared-store log schema (2026-08-18) ────────────────
# The shared store is a write-once append-only origin log + registry only.
# The UNIQUE(origin_store, fact_id, version) index is what makes `publish`
# idempotent even across a partial failure (event inserted, outbox not yet
# flagged): a re-run re-inserts nothing.
SHARED_SCHEMA = """
CREATE TABLE IF NOT EXISTS sync_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    origin_store TEXT NOT NULL,
    fact_id TEXT NOT NULL,
    op TEXT NOT NULL CHECK (op IN ('create','update','delete')),
    version INTEGER NOT NULL,
    written_at TEXT NOT NULL,
    fact_timestamp TEXT DEFAULT '',
    payload TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_sync_events_uniq
    ON sync_events(origin_store, fact_id, version);
CREATE INDEX IF NOT EXISTS idx_sync_events_origin
    ON sync_events(origin_store, event_id);
CREATE TABLE IF NOT EXISTS sync_offsets (
    store_id TEXT PRIMARY KEY,
    last_event_seq INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS shared_facts (
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
);
"""

# ── auto-extraction patterns ────────────────────────────────────────────────

# Heuristic patterns for extracting facts from conversation text without an LLM.
# Each pattern produces (content, domain, importance) tuples.

_EXTRACTION_PATTERNS: List[Tuple[str, str, float, str]] = [
    # EM-111 (G1): generic first-person patterns ONLY. The old
    # domain-specific keyword lists (finance/alarm/hermes/obsidian/social/
    # events) encoded one employer's world into a generic engine, missed
    # everything outside it, and leaked employer/campaign/product strings
    # into the shipped scripts.
    (r"\b(?:i|we)\s+(?:always |usually |often |also |still |really |generally "
     r"|typically |prefer to |tend to )?(?:prefer|like|love|want|need|hate|dislike"
     r"|use|using|keep|choose|avoid|work with|work on|live in|run|manage|maintain"
     r"|build|drive|own)\b[^.!?\n]{3,120}",
     "Preferences", 0.5, "first-person"),
    (r"\bmy\s+[a-z][\w\- ]{2,40}?\s+(?:is|are|was|has|have|runs|uses|stays|needs"
     r"|works)\b[^.!?\n]{2,120}",
     "Preferences", 0.5, "first-person"),
    (r"\b(?:i|we)\s+(?:always |never |must |should |have to |need to )\w+[^.!?\n]{3,120}",
     "Preferences", 0.5, "constraint"),
]

# ── data types ──────────────────────────────────────────────────────────────


@dataclass
class StoredFact:
    id: str
    content: str
    title: str = ""
    source: str = "agent"
    importance: float = 0.5
    domain: str = "Knowledge"
    tags: List[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    last_accessed: str = ""
    access_count: int = 0
    sensitivity: str = "internal"
    relevance_score: float = 0.0  # FTS5 rank-based relevance (0-1)
    decay_score: float = 1.0      # temporal decay factor (1.0 = no decay)
    why_retrieved: List[Any] = field(default_factory=list)  # P1 D1: explainable recall reason tokens

    @staticmethod
    def make_id(content: str) -> str:
        """Deterministic entropic_id from content."""
        return hashlib.sha256(content.encode()).hexdigest()[:16]


# ── engine ──────────────────────────────────────────────────────────────────


class MemoryEngine:
    """Standalone memory engine. One SQLite database, no external deps."""

    def __init__(self, db_path: Path, profile_id: Optional[str] = None, publish_scope: Optional[str] = None, hermes_home: Optional[Path] = None):
        self.db_path = Path(db_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._profile_id = profile_id
        self._hermes_home = Path(hermes_home).expanduser() if hermes_home else None
        self.publish_scope = (
            publish_scope or os.environ.get("ENTROPICMEM_PUBLISH_SCOPE") or "shared"
        ).lower()
        self.db = sqlite3.connect(str(self.db_path), timeout=30)
        # Restrictive modes: memory may hold finance/PII
        try:
            os.chmod(self.db_path.parent, 0o700)
            if self.db_path.exists():
                os.chmod(self.db_path, 0o600)
        except OSError:
            pass
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")

        # Concurrency guard: file lock for write serialization.
        # The lock is REENTRANT per engine instance (counter-based): nested
        # helpers (_backup inside forget()/consolidate(), _init_schema inside
        # migrate()) must not release the flock mid-operation.
        lock_path = self.db_path.parent / f"{self.db_path.name}.lock"
        self._lock_fd = open(lock_path, "w")
        self._write_locked = False
        self._lock_depth = 0

        self._init_schema()

    def _acquire_write_lock(self) -> None:
        """Acquire exclusive file lock for write operations (reentrant)."""
        if self._lock_depth > 0:
            self._lock_depth += 1
            return
        try:
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            # Lock held by another process — wait briefly
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX)
        self._write_locked = True
        self._lock_depth = 1

    def _release_write_lock(self) -> None:
        """Release file lock after write operations (outermost call wins)."""
        if self._lock_depth == 0:
            return
        self._lock_depth -= 1
        if self._lock_depth == 0 and self._write_locked:
            fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
            self._write_locked = False

    # ── P1 multi-profile provenance (2026-08-18) ────────────────────────────

    MIGRATION_LOCK_FILENAME = "migration.lock"
    EM_MIGRATION_IN_PROGRESS = (
        "EM_MIGRATION_IN_PROGRESS: writes rejected while migration.lock is present "
        "(entropicmem migrate running)"
    )

    def profile_id(self) -> str:
        """Resolve the owning profile slug: explicit > hermes_home basename > 'default'.

        H3/EM-102: the HERMES_HOME env var is never read — in a multiplexed
        gateway it can be poisoned by another profile after initialize,
        which stamped every write with the wrong slug.
        """
        if self._profile_id:
            return self._profile_id
        if self._hermes_home:
            name = self._hermes_home.resolve().name
            if name and name != ".hermes":
                return name
        return "default"

    def _check_migration_lock(self) -> None:
        """Fail-closed guard: durable writes are rejected while migration.lock exists."""
        if (self.db_path.parent / self.MIGRATION_LOCK_FILENAME).exists():
            self.audit(
                "write_rejected",
                actor=self.profile_id(),
                detail="migration.lock present",
                ok=False,
            )
            raise RuntimeError(self.EM_MIGRATION_IN_PROGRESS)

    # ── P2 controlled sync helpers ──────────────────────────────────────────

    def _publish_allowed(self, sensitivity: Optional[str]) -> bool:
        """Publish-side filter, enforced at write time inside the transaction.

        scope 'none' emits nothing; 'secret'/'sensitive' tier facts never leave
        the store regardless of scope. Public + internal emit under
        'shared'/'all'. (Finance/People/'sensitive' facts stay local.)
        """
        if self.publish_scope == "none":
            return False
        if (sensitivity or "internal").lower() in ("secret", "sensitive"):
            return False
        return True

    def _enqueue_outbox(
        self, *, fact_id: str, op: str, version: int, written_at: str,
        fact_timestamp: str, payload: str, sensitivity: Optional[str],
    ) -> None:
        """Append a sync_outbox row in the SAME transaction as the facts write.

        Called before the caller's commit; the outbox insert is durable by
        construction with the fact itself. Rows stay local and unemitted;
        `publish()` drains them to the shared log idempotently.
        """
        if not self._publish_allowed(sensitivity):
            return
        self.db.execute(
            "INSERT INTO sync_outbox (fact_id, op, version, written_at, fact_timestamp, payload, emitted) "
            "VALUES (?, ?, ?, ?, ?, ?, 0)",
            (fact_id, op, version, written_at, fact_timestamp, payload),
        )

    def _has_embeddings_table(self) -> bool:
        """True when the embeddings table exists on this DB (schema probe)."""
        row = self.db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='embeddings'"
        ).fetchone()
        return row is not None

    def _init_schema(self) -> None:
        self._acquire_write_lock()
        try:
            self.db.executescript(MEMORY_SCHEMA)
            # Migrate: add temporal columns and index if they don't exist
            existing_cols = {r[1] for r in self.db.execute("PRAGMA table_info(facts)").fetchall()}
            if "last_accessed" not in existing_cols:
                self.db.execute("ALTER TABLE facts ADD COLUMN last_accessed TIMESTAMP")
            if "access_count" not in existing_cols:
                self.db.execute("ALTER TABLE facts ADD COLUMN access_count INTEGER DEFAULT 0")
            self.db.execute("CREATE INDEX IF NOT EXISTS idx_facts_last_accessed ON facts(last_accessed DESC)")
            # Phase 7: embeddings table (no-op if deps missing)
            if EMBEDDINGS_AVAILABLE:
                init_embeddings_schema(self.db)
            # Phase 11.3: fact versioning table
            self.db.execute("""
                CREATE TABLE IF NOT EXISTS fact_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fact_id TEXT NOT NULL,
                    content TEXT NOT NULL,
                    importance REAL DEFAULT 0.5,
                    domain TEXT DEFAULT 'Knowledge',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    source TEXT DEFAULT 'version_snapshot'
                )
            """)
            self.db.execute("CREATE INDEX IF NOT EXISTS idx_versions_fact ON fact_versions(fact_id, created_at DESC)")
            # Phase 2 security: sensitivity + audit + pending quarantine
            existing_cols = {r[1] for r in self.db.execute("PRAGMA table_info(facts)").fetchall()}
            if "sensitivity" not in existing_cols:
                self.db.execute("ALTER TABLE facts ADD COLUMN sensitivity TEXT DEFAULT 'internal'")
            # P1 multi-profile provenance: profile stamping columns (idempotent)
            if "profile_id" not in existing_cols:
                self.db.execute("ALTER TABLE facts ADD COLUMN profile_id TEXT DEFAULT ''")
            if "fact_timestamp" not in existing_cols:
                self.db.execute("ALTER TABLE facts ADD COLUMN fact_timestamp TEXT")
            if "version" not in existing_cols:
                self.db.execute("ALTER TABLE facts ADD COLUMN version INTEGER NOT NULL DEFAULT 1")
            if "deleted" not in existing_cols:
                self.db.execute("ALTER TABLE facts ADD COLUMN deleted INTEGER NOT NULL DEFAULT 0")
            self.db.execute("CREATE INDEX IF NOT EXISTS idx_facts_profile ON facts(profile_id)")
            # facts_archive is created lazily by consolidate(); upgrade it if present
            has_archive = self.db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='facts_archive'"
            ).fetchone()
            if has_archive:
                arch_cols = {r[1] for r in self.db.execute("PRAGMA table_info(facts_archive)").fetchall()}
                if "profile_id" not in arch_cols:
                    self.db.execute("ALTER TABLE facts_archive ADD COLUMN profile_id TEXT DEFAULT ''")
                if "version" not in arch_cols:
                    self.db.execute("ALTER TABLE facts_archive ADD COLUMN version INTEGER NOT NULL DEFAULT 1")
                if "sensitivity" not in arch_cols:
                    self.db.execute("ALTER TABLE facts_archive ADD COLUMN sensitivity TEXT DEFAULT 'internal'")
            self.db.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    action TEXT NOT NULL,
                    actor TEXT DEFAULT 'agent',
                    session_id TEXT DEFAULT '',
                    fact_id TEXT DEFAULT '',
                    detail TEXT DEFAULT '',
                    ok INTEGER DEFAULT 1
                )
            """)
            self.db.execute("CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts DESC)")
            self.db.execute("""
                CREATE TABLE IF NOT EXISTS pending_facts (
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
                )
            """)
            self.db.commit()
        finally:
            self._release_write_lock()

    def _rebuild_fts(self) -> None:
        """Rebuild the FTS5 index from the facts table (I2: DB error recovery)."""
        self._acquire_write_lock()
        try:
            self.db.execute("DELETE FROM facts_fts")
            self.db.execute(
                """INSERT INTO facts_fts (rowid, content, title, tags, domain)
                   SELECT rowid, content, title, tags, domain FROM facts"""
            )
            self.db.commit()
        finally:
            self._release_write_lock()

    def rebuild_fts(self) -> dict:
        """Public FTS5 repair (v2.1.8): drop and rebuild facts_fts from facts.

        Repairs orphan FTS rows left behind when a delete path skipped its
        FTS cleanup (recall can then surface ghost hits). Safe to call at
        any time; the health check's fts_orphans counter tells you when it
        is needed. Returns before/after counts for verification.
        """
        before = self.db.execute("SELECT COUNT(*) FROM facts_fts").fetchone()[0]
        fact_count = self.db.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
        self._rebuild_fts()
        after = self.db.execute("SELECT COUNT(*) FROM facts_fts").fetchone()[0]
        self.audit("fts_rebuild", detail=f"before={before};after={after};facts={fact_count}")
        return {"fts_before": before, "fts_after": after, "facts": fact_count}

    def _execute_with_retry(self, sql: str, params: tuple = (), max_retries: int = 2):
        """Execute SQL with automatic FTS rebuild on corruption (I2: DB error recovery)."""
        for attempt in range(max_retries + 1):
            try:
                return self.db.execute(sql, params)
            except sqlite3.DatabaseError:
                if attempt < max_retries:
                    self._rebuild_fts()
                else:
                    raise

    def close(self) -> None:
        try:
            # Force a full release even if a caller leaked a nested acquire.
            self._lock_depth = 1 if self._write_locked else 0
            self._release_write_lock()
        except (OSError, ValueError):
            pass  # lock already released or fd closed
        self._lock_depth = 0
        try:
            self._lock_fd.close()
        except (OSError, ValueError):
            pass
        self.db.close()

    def __enter__(self) -> "MemoryEngine":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    # ── CRUD ────────────────────────────────────────────────────────────


    @staticmethod
    def _sanitize_fact_text(content: str) -> str:
        """Strip prompt-injection markers and fence tags before durable storage."""
        if not content:
            return content
        # Remove memory-context fence tags and common instruction hijacks
        patterns = [
            r"</?\s*memory-context\s*>",
            r"(?im)^\s*ignore (all |any )?(previous|prior|above) instructions\s*:?\s*",
            r"(?im)^\s*system\s*:\s*",
            r"(?im)^\s*developer\s*:\s*",
        ]
        out = content
        for pat in patterns:
            out = re.sub(pat, "", out)
        # Collapse excessive whitespace from stripping
        out = re.sub(r"\n{3,}", "\n\n", out).strip()
        return out


    def audit(
        self,
        action: str,
        *,
        actor: Optional[str] = None,
        session_id: str = "",
        fact_id: str = "",
        detail: str = "",
        ok: bool = True,
    ) -> None:
        """Append-only audit event (best-effort). Actor defaults to the owning profile slug."""
        try:
            self.db.execute(
                """INSERT INTO audit_log (action, actor, session_id, fact_id, detail, ok)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (action, actor or self.profile_id(), session_id, fact_id, detail[:2000], 1 if ok else 0),
            )
            self.db.commit()
        except (sqlite3.Error, OSError) as exc:
            logger.warning("audit write failed for action=%s: %s", action, exc)

    def list_audit(self, limit: int = 50) -> List[dict]:
        rows = self.db.execute(
            """SELECT id, ts, action, actor, session_id, fact_id, detail, ok
               FROM audit_log ORDER BY id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def quarantine_fact(
        self,
        content: str,
        *,
        title: str = "",
        source: str = "auto_extracted",
        importance: float = 0.5,
        domain: str = "Knowledge",
        tags: Optional[List[str]] = None,
        session_id: str = "",
        reason: str = "",
    ) -> str:
        """Store a candidate fact in pending_facts (not durable recall)."""
        # EM-111: quarantine hygiene — sanitize injection markers and redact
        # PII before the candidate is stored anywhere.
        content = self._sanitize_fact_text(content)
        if PII_AVAILABLE:
            pii_result = check_pii(content, mode="redact")
            if pii_result["has_pii"]:
                content = pii_result["text"]
        eid = StoredFact.make_id(content)
        tags_str = ", ".join(tags) if tags else ""
        self._acquire_write_lock()
        try:
            self.db.execute(
                """INSERT OR REPLACE INTO pending_facts
                   (id, content, title, source, importance, domain, tags, session_id, reason)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (eid, content, title or content[:60], source, importance, domain, tags_str, session_id, reason),
            )
            self.db.commit()
            self.audit("quarantine", session_id=session_id, fact_id=eid, detail=reason)
        finally:
            self._release_write_lock()
        return eid

    def list_pending(self, limit: int = 50) -> List[dict]:
        rows = self.db.execute(
            """SELECT id, content, domain, source, importance, reason, created_at
               FROM pending_facts ORDER BY created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def promote_pending(self, pending_id: str, *, actor: Optional[str] = None) -> Optional[str]:
        """Promote a pending fact into durable memory via remember()."""
        row = self.db.execute(
            "SELECT * FROM pending_facts WHERE id = ?", (pending_id,)
        ).fetchone()
        if not row:
            return None
        tags = [t.strip() for t in (row["tags"] or "").split(",") if t.strip()]
        eid = self.remember(
            content=row["content"],
            title=row["title"] or "",
            source="promoted",
            importance=row["importance"] or 0.5,
            domain=row["domain"] or "Knowledge",
            tags=tags + ["promoted"],
            session_id=row["session_id"] or "",
            # EM-111: keep the pending row's domain-derived sensitivity
            sensitivity=None,
            actor=actor,
        )
        self._acquire_write_lock()
        try:
            self.db.execute("DELETE FROM pending_facts WHERE id = ?", (pending_id,))
            self.db.commit()
            self.audit("promote_pending", actor=actor, fact_id=eid, detail=pending_id)
        finally:
            self._release_write_lock()
        return eid

    def discard_pending(self, pending_id: str) -> bool:
        cur = self.db.execute("DELETE FROM pending_facts WHERE id = ?", (pending_id,))
        self.db.commit()
        self.audit("discard_pending", fact_id=pending_id, ok=cur.rowcount > 0)
        return cur.rowcount > 0

    def prune_pending(self, older_than_days: int = 30) -> int:
        """TTL purge of the pending quarantine (EM-111).

        Deletes pending rows older than ``older_than_days`` and returns the
        count. Runs on demand (CLI `pending prune --older-than 30d`) and
        automatically at session end.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(days=older_than_days)).isoformat()
        self._acquire_write_lock()
        try:
            cur = self.db.execute(
                "DELETE FROM pending_facts WHERE created_at < ?", (cutoff,)
            )
            self.db.commit()
            n = cur.rowcount
        finally:
            self._release_write_lock()
        if n:
            self.audit("pending_prune", detail=f"pruned {n} older than {older_than_days}d")
        return n

    def remember(
        self,
        content: str,
        title: str = "",
        source: str = "agent",
        importance: float = 0.5,
        domain: str = "Knowledge",
        tags: Optional[List[str]] = None,
        session_id: str = "",
        sensitivity: Optional[str] = None,
        actor: Optional[str] = None,
        profile_id: Optional[str] = None,
        fact_timestamp: Optional[str] = None,
    ) -> str:
        """
        Store a durable fact. Returns the entropic_id.
        Deduplicates: if a fact with the same content hash exists, updates it.

        Phase 9: PII detection/redaction applied before storage.
        Phase 2: sensitivity tiers + write policy (block secrets, quarantine auto).
        P1: stamps profile_id (owner slug) and fact_timestamp; bumps version on update.
        """
        content = self._sanitize_fact_text(content)
        if not content:
            raise ValueError("empty content after sanitize")
        pid = profile_id or self.profile_id()

        # Phase 2 write policy
        tier = "internal"
        if POLICY_AVAILABLE:
            tier = normalize_sensitivity(sensitivity, domain)
            action, reason = evaluate_write(
                content, domain=domain, sensitivity=tier, source=source
            )
            if action == "block":
                self.audit("remember_blocked", actor=pid, session_id=session_id, detail=reason or "", ok=False)
                raise ValueError(reason or "write blocked by policy")
            if action == "quarantine":
                return self.quarantine_fact(
                    content,
                    title=title,
                    source=source,
                    importance=importance,
                    domain=domain,
                    tags=tags,
                    session_id=session_id,
                    reason=reason or "quarantine",
                )
        else:
            tier = (sensitivity or "internal").lower()

        # Phase 9: PII check
        if PII_AVAILABLE:
            pii_result = check_pii(content, mode="redact")
            if pii_result["has_pii"]:
                content = pii_result["text"]  # use redacted version

        # P1 fail-closed migration guard (no durable writes mid-migration)
        self._check_migration_lock()

        self._acquire_write_lock()
        try:
            eid = StoredFact.make_id(content)
            tags_str = ", ".join(tags) if tags else ""
            now = datetime.now(timezone.utc).isoformat()
            ft = fact_timestamp or now
            is_create = False

            existing = self.db.execute(
                "SELECT id FROM facts WHERE id = ?", (eid,)
            ).fetchone()

            if existing:
                # Phase 11.3: snapshot before update
                self.snapshot_version(eid, source="dedup_update")
                self.db.execute(
                    """UPDATE facts SET content=?, title=?, importance=?, domain=?,
                       tags=?, session_id=?, updated_at=?, sensitivity=?, profile_id=?,
                       fact_timestamp=COALESCE(?, fact_timestamp), version=version+1
                       WHERE id=?""",
                    (content, title or self._make_title(content), importance,
                     domain, tags_str, session_id, now, tier, pid, fact_timestamp, eid),
                )
            else:
                # I1: Fuzzy deduplication — check for near-duplicate content.
                # EM-109 (L1): a fuzzy UPDATE in place is allowed only when the
                # pair passes _safe_fuzzy_update (Jaccard >= 0.95 AND identical
                # numbers/versions/IPs/dates AND identical negation tokens).
                # Otherwise the write inserts as a NEW fact and the pair is
                # audited as possible_duplicate — no more silent overwrites.
                fuzzy_id = self._find_fuzzy_duplicate(content)
                old_content = ""
                if fuzzy_id and fuzzy_id != eid:
                    row = self.db.execute(
                        "SELECT content FROM facts WHERE id = ?", (fuzzy_id,)
                    ).fetchone()
                    old_content = row[0] if row else ""
                if fuzzy_id and fuzzy_id != eid and self._safe_fuzzy_update(content, old_content):
                    # Phase 11.3: snapshot before fuzzy update
                    self.snapshot_version(fuzzy_id, source="fuzzy_dedup_update")
                    before_hash = hashlib.sha256(old_content.encode("utf-8")).hexdigest()
                    # Update the existing near-duplicate instead of creating a new fact
                    self.db.execute(
                        """UPDATE facts SET content=?, title=?, importance=?, domain=?,
                           tags=?, session_id=?, updated_at=?, sensitivity=?, profile_id=?,
                           fact_timestamp=COALESCE(?, fact_timestamp), version=version+1
                           WHERE id=?""",
                        (content, title or self._make_title(content), importance,
                         domain, tags_str, session_id, now, tier, pid, fact_timestamp, fuzzy_id),
                    )
                    # EM-109: allowed fuzzy updates are audited with the
                    # before-content hash
                    self.audit(
                        "fuzzy_update",
                        fact_id=fuzzy_id,
                        detail=json.dumps({"before_sha256": before_hash}),
                    )
                    eid = fuzzy_id  # Return the existing fact's ID
                else:
                    self.db.execute(
                        """INSERT INTO facts (id, content, title, source, importance, domain,
                           tags, session_id, created_at, updated_at, last_accessed, sensitivity,
                           profile_id, fact_timestamp)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (eid, content, title or self._make_title(content),
                         source, importance, domain, tags_str, session_id, now, now, now, tier,
                         pid, ft),
                    )
                    is_create = True
                    if fuzzy_id and fuzzy_id != eid:
                        # EM-109: near-duplicate that failed the safe rule —
                        # both facts stay, and the pair is audited
                        self.audit(
                            "possible_duplicate",
                            fact_id=eid,
                            detail=json.dumps({"new": eid, "duplicate_of": fuzzy_id}),
                        )

            # Upsert FTS — must use the same rowid as the facts table
            # Get the rowid of the fact we just inserted/updated
            fact_rowid = self.db.execute(
                "SELECT rowid FROM facts WHERE id = ?", (eid,)
            ).fetchone()
            if fact_rowid:
                # Delete old FTS entry for this rowid (if any)
                self.db.execute("DELETE FROM facts_fts WHERE rowid = ?", (fact_rowid[0],))
                # Insert with matching rowid
                self.db.execute(
                    "INSERT INTO facts_fts (rowid, content, title, tags, domain) VALUES (?, ?, ?, ?, ?)",
                    (fact_rowid[0], content, title or "", tags_str, domain),
                )

            # P2 transactional outbox: append an event row in this same transaction.
            row = self.db.execute(
                "SELECT version, fact_timestamp FROM facts WHERE id = ?", (eid,)
            ).fetchone()
            if row:
                payload = {
                    "content": content,
                    "title": title or "",
                    "source": source,
                    "importance": importance,
                    "domain": domain,
                    "tags": tags_str,
                    "sensitivity": tier,
                    "profile_id": pid,
                }
                self._enqueue_outbox(
                    fact_id=eid,
                    op="create" if is_create else "update",
                    version=row["version"],
                    written_at=now,
                    fact_timestamp=row["fact_timestamp"] or "",
                    payload=json.dumps(payload),
                    sensitivity=tier,
                )
            self.db.commit()
            # Phase 7: generate and store embedding (best-effort, non-blocking)
            if EMBEDDINGS_AVAILABLE:
                try:
                    vec = embed_text(content)
                    if vec:
                        store_embedding(self.db, eid, vec)
                except Exception as exc:  # noqa: BLE001 - third-party embedder
                    logger.warning("embedding generation failed for %s: %s", eid, exc)
        finally:
            self._release_write_lock()
        self.audit("remember", actor=actor, session_id=session_id, fact_id=eid, detail=f"domain={domain};tier={tier}")
        return eid

    def _backup(self) -> Path:
        """Create a timestamped backup of the memory DB (I4: auto-backup before destructive ops)."""
        self._acquire_write_lock()
        try:
            backup_dir = self.db_path.parent / "backups"
            backup_dir.mkdir(exist_ok=True)
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            backup_path = backup_dir / f"memory_{timestamp}.db"
            # Use SQLite backup API for consistency
            with sqlite3.connect(str(self.db_path)) as src, sqlite3.connect(str(backup_path)) as dst:
                src.backup(dst)
            return backup_path
        finally:
            self._release_write_lock()

    def forget(self, entropic_id: str, *, confirm: bool = False) -> bool:
        """Delete a fact by entropic_id. Requires confirm=True."""
        if not confirm:
            self.audit("forget_denied", fact_id=entropic_id, detail="confirm=false", ok=False)
            raise ValueError("forget requires confirm=True")
        self._check_migration_lock()
        self._acquire_write_lock()
        try:
            # I4: Auto-backup before destructive operation
            self._backup()
            # Fetch provenance before deleting (for the P2 delete outbox event)
            before = self.db.execute(
                "SELECT version, sensitivity, fact_timestamp, content, domain, tags, importance FROM facts WHERE id = ?",
                (entropic_id,),
            ).fetchone()
            # Get rowid before deleting from facts
            row = self.db.execute("SELECT rowid FROM facts WHERE id = ?", (entropic_id,)).fetchone()
            self.db.execute("DELETE FROM facts WHERE id = ?", (entropic_id,))
            if row:
                self.db.execute("DELETE FROM facts_fts WHERE rowid = ?", (row[0],))
            # Remove embedding if present. Plain SQL — must NOT be gated on
            # EMBEDDINGS_AVAILABLE, or runs without sentence-transformers
            # (e.g. system python) leave orphan rows that trip the health check.
            if self._has_embeddings_table():
                self.db.execute("DELETE FROM embeddings WHERE fact_id = ?", (entropic_id,))
                if EMBEDDINGS_IMPORTABLE:
                    invalidate_vector_cache()
            if before:
                now = datetime.now(timezone.utc).isoformat()
                payload = {
                    "content": before["content"],
                    "title": "",
                    "source": "deleted",
                    "importance": before["importance"],
                    "domain": before["domain"],
                    "tags": before["tags"] or "",
                    "sensitivity": before["sensitivity"] or "internal",
                    "profile_id": self.profile_id(),
                    "deleted": True,
                }
                self._enqueue_outbox(
                    fact_id=entropic_id,
                    op="delete",
                    # Tombstone uses a NEW version: the shared log's
                    # UNIQUE(origin_store, fact_id, version) index already holds
                    # an event at the current version, so a delete at that same
                    # version would be IGNORED and the tombstone never propagate.
                    version=int(before["version"] or 1) + 1,
                    written_at=now,
                    fact_timestamp=before["fact_timestamp"] or "",
                    payload=json.dumps(payload),
                    sensitivity=before["sensitivity"],
                )
            self.db.commit()
            self.audit("forget", fact_id=entropic_id, ok=row is not None)
            return row is not None
        finally:
            self._release_write_lock()

    def consolidate(
        self,
        max_age_days: int = 90,
        min_access_count: int = 0,
        dry_run: bool = True,
        confirm: bool = False,
        evergreen_domains: Optional[Sequence[str]] = None,
    ) -> dict:
        """Archive old, low-value facts (I3; safe selection per EM-108/L2).

        A fact is a candidate only when ALL hold:
        - importance < 0.6 (durable memory is never archived)
        - domain not in ``evergreen_domains`` (default ["People"])
        - source not in ("built_in_memory", "promoted")
        - no "pinned" tag
        - age from ``max(updated_at, last_accessed)`` >= ``max_age_days``
        - access_count <= ``min_access_count``

        Candidates archive lowest-importance first (oldest first within a
        tier); archive rows keep the fact's sensitivity.

        If dry_run=True, reports what would be archived without modifying anything.
        """
        evergreen: Set[str] = set(evergreen_domains) if evergreen_domains is not None else {"People"}
        now = datetime.now(timezone.utc)

        # Find candidates (EM-108: durable facts are never candidates)
        candidates = []
        for row in self.db.execute(
            """SELECT id, title, source, importance, domain, tags, created_at,
                      updated_at, last_accessed
               FROM facts WHERE access_count <= ?""",
            (min_access_count,),
        ).fetchall():
            fid, title, source, importance, domain, tags, created_at, updated_at, last_accessed = row
            if (importance or 0.0) >= 0.6:
                continue
            if (domain or "Knowledge") in evergreen:
                continue
            if (source or "agent") in ("built_in_memory", "promoted"):
                continue
            tag_list = [t.strip() for t in (tags or "").split(",") if t.strip()]
            if "pinned" in tag_list:
                continue
            stamps = [s for s in (_parse_ts(updated_at), _parse_ts(last_accessed)) if s]
            newest = max(stamps) if stamps else _parse_ts(created_at)
            if newest is None:
                continue
            age_days = (now - newest).total_seconds() / 86400.0
            if age_days < max_age_days:
                continue
            candidates.append((importance or 0.0, newest, fid, title or "", age_days))

        # Lowest importance first, oldest first within a tier
        candidates.sort(key=lambda c: (c[0], c[1]))
        candidate_ids = [fid for _, _, fid, _, _ in candidates]

        if dry_run or not confirm:
            return {
                "archived": 0,
                "would_archive": len(candidate_ids),
                # EM-108: dry-run reports the candidate list, not just a count
                "candidates": [
                    {
                        "id": fid,
                        "title": title,
                        "age": round(age_days, 1),
                        "importance": importance,
                    }
                    for importance, _, fid, title, age_days in candidates
                ],
                "cutoff_days": max_age_days,
                "dry_run": True,
                "confirm_required": not confirm,
            }

        # Mutation phase runs under the (reentrant) write lock; the nested
        # _backup() call keeps the lock held instead of unlocking mid-operation.
        self._acquire_write_lock()
        try:
            # I4: Auto-backup before destructive operation
            self._backup()

            # Create archive table if needed
            self.db.execute("""
                CREATE TABLE IF NOT EXISTS facts_archive (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    title TEXT DEFAULT '',
                    source TEXT DEFAULT 'agent',
                    importance REAL DEFAULT 0.5,
                    domain TEXT DEFAULT 'Knowledge',
                    tags TEXT DEFAULT '',
                    session_id TEXT DEFAULT '',
                    created_at TIMESTAMP,
                    updated_at TIMESTAMP,
                    last_accessed TIMESTAMP,
                    access_count INTEGER DEFAULT 0,
                    profile_id TEXT DEFAULT '',
                    version INTEGER NOT NULL DEFAULT 1,
                    sensitivity TEXT DEFAULT 'internal',
                    archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            archived = 0
            has_embeddings = self._has_embeddings_table()
            for fid in candidate_ids:
                # Copy to archive (sensitivity preserved — EM-108)
                self.db.execute(
                    """INSERT OR REPLACE INTO facts_archive
                       (id, content, title, source, importance, domain, tags,
                        session_id, created_at, updated_at, last_accessed, access_count,
                        sensitivity)
                       SELECT id, content, title, source, importance, domain, tags,
                              session_id, created_at, updated_at, last_accessed, access_count,
                              sensitivity
                       FROM facts WHERE id = ?""",
                    (fid,),
                )
                # Delete from facts + FTS
                row = self.db.execute("SELECT rowid FROM facts WHERE id = ?", (fid,)).fetchone()
                self.db.execute("DELETE FROM facts WHERE id = ?", (fid,))
                if row:
                    self.db.execute("DELETE FROM facts_fts WHERE rowid = ?", (row[0],))
                # Same orphan-embedding guard as forget(): plain SQL, not gated
                # on EMBEDDINGS_AVAILABLE.
                if has_embeddings:
                    self.db.execute("DELETE FROM embeddings WHERE fact_id = ?", (fid,))
                archived += 1

            self.db.commit()
        finally:
            self._release_write_lock()
        if has_embeddings and EMBEDDINGS_IMPORTABLE:
            invalidate_vector_cache()
        self.audit("consolidate", detail=f"archived={archived};days={max_age_days}")
        return {"archived": archived, "cutoff_days": max_age_days, "dry_run": False}

    def migrate(self, *, schema_version: int = 1, phase: int = 1) -> dict:
        """P1 provenance migration: register the owning profile slug, backfill
        legacy rows, stamp schema_info. Idempotent and safe to re-run.

        The CLI holds migration.lock while this runs; engine writes fail
        closed (EM_MIGRATION_IN_PROGRESS) while the lock exists.
        """
        self._acquire_write_lock()
        try:
            self._init_schema()
            pid = self.profile_id()
            now = datetime.now(timezone.utc).isoformat()
            self.db.execute(
                "INSERT OR IGNORE INTO profile_registry (slug, created_at) VALUES (?, ?)",
                (pid, now),
            )
            # Backfill legacy rows: empty profile_id → owning store's slug
            cur = self.db.execute(
                """UPDATE facts SET profile_id=?, fact_timestamp=COALESCE(fact_timestamp, created_at)
                   WHERE profile_id IS NULL OR profile_id=''""",
                (pid,),
            )
            facts_backfilled = cur.rowcount
            arch_backfilled = 0
            if self.db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='facts_archive'"
            ).fetchone():
                cur = self.db.execute(
                    """UPDATE facts_archive SET profile_id=?, version=COALESCE(version, 1)
                       WHERE profile_id IS NULL OR profile_id=''""",
                    (pid,),
                )
                arch_backfilled = cur.rowcount
            # Single-row current state (re-run safe)
            self.db.execute("DELETE FROM schema_info")
            self.db.execute(
                "INSERT INTO schema_info (schema_version, phase, applied_at) VALUES (?, ?, ?)",
                (schema_version, phase, now),
            )
            self.db.commit()
            return {
                "profile": pid,
                "facts_backfilled": facts_backfilled,
                "archive_backfilled": arch_backfilled,
                "schema_version": schema_version,
                "phase": phase,
            }
        finally:
            self._release_write_lock()

    # ── P2 controlled sync (shared store) ───────────────────────────────────

    @staticmethod
    def shared_path(hermes_home: Optional[Path] = None) -> Path:
        """Resolve the shared sync store path (env override or default).

        The shared log is anchored at the ROOT hermes home, not the active
        profile home: profile mode uses <root>/profiles/<name>, and the
        shared store must stay at <root>/entropicmem-shared/ so all
        profiles converge on one log.

        H3/EM-102: HERMES_HOME is never read — callers pass ``hermes_home``
        explicitly (the engine forwards its own); without it the default is
        ~/.hermes.
        """
        env = os.environ.get("ENTROPICMEM_SHARED_DB")
        if env:
            return Path(env).expanduser().resolve()
        base = Path(hermes_home).expanduser() if hermes_home else Path.home() / ".hermes"
        if base.parent.name == "profiles":
            base = base.parent.parent  # profile mode: climb back to <root>
        return (base / "entropicmem-shared" / "memory.db").resolve()

    @staticmethod
    def shared_init(shared_db: Optional[Path] = None) -> dict:
        """Bootstrap the shared sync store (append-only origin log). Idempotent."""
        path = Path(shared_db) if shared_db else MemoryEngine.shared_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), timeout=30)
        try:
            conn.executescript(SHARED_SCHEMA)
            conn.commit()
        finally:
            conn.close()
        return {"shared_db": str(path)}

    def publish(self, shared_db: Optional[Path] = None) -> dict:
        """Drain unemitted local outbox rows into the shared sync_events log.

        Idempotent by construction: rows are marked emitted only after the
        shared insert commits, and the UNIQUE(origin_store, fact_id, version)
        index makes a partial-failure re-run insert nothing new.
        """
        self._check_migration_lock()
        self._acquire_write_lock()
        try:
            rows = self.db.execute(
                "SELECT * FROM sync_outbox WHERE emitted=0 ORDER BY id"
            ).fetchall()
            if not rows:
                return {"published": 0, "profile": self.profile_id()}
            shared = sqlite3.connect(str(shared_db or self.shared_path(self._hermes_home)), timeout=30)
            shared.row_factory = sqlite3.Row
            try:
                new_events = 0
                attempted: List[int] = []
                for r in rows:
                    cur = shared.execute(
                        "INSERT OR IGNORE INTO sync_events "
                        "(origin_store, fact_id, op, version, written_at, fact_timestamp, payload) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (self.profile_id(), r["fact_id"], r["op"], r["version"],
                         r["written_at"], r["fact_timestamp"] or "", r["payload"]),
                    )
                    new_events += cur.rowcount
                    attempted.append(r["id"])
                shared.commit()
            finally:
                shared.close()
            for rid in attempted:
                self.db.execute("UPDATE sync_outbox SET emitted=1 WHERE id=?", (rid,))
            self.db.commit()
            return {"published": new_events, "profile": self.profile_id()}
        finally:
            self._release_write_lock()

    def pull(self, shared_db: Optional[Path] = None) -> dict:
        """Apply new shared sync_events into the local shared_facts projection.

        Echo prevention: events whose origin_store is this store are skipped.
        LWW: an event is applied only when its (version, written_at) is newer
        than the existing projection row; older events are no-ops. Deletions
        set shared_facts.deleted=1 but keep the row (append-only log).
        """
        self._check_migration_lock()
        self._acquire_write_lock()
        try:
            shared = sqlite3.connect(str(shared_db or self.shared_path(self._hermes_home)), timeout=30)
            shared.row_factory = sqlite3.Row
            try:
                last = self.db.execute(
                    "SELECT last_event_seq FROM sync_offsets WHERE store_id=?", (self.profile_id(),)
                ).fetchone()
                last_seq = last["last_event_seq"] if last else 0
                events = shared.execute(
                    "SELECT * FROM sync_events WHERE event_id>? ORDER BY event_id", (last_seq,)
                ).fetchall()
                applied = 0
                max_seq = last_seq
                for ev in events:
                    max_seq = ev["event_id"]
                    if ev["origin_store"] == self.profile_id():
                        continue  # echo prevention: never re-import own writes
                    existing = self.db.execute(
                        "SELECT version, written_at FROM shared_facts WHERE fact_id=? AND origin_store=?",
                        (ev["fact_id"], ev["origin_store"]),
                    ).fetchone()
                    if existing and (ev["version"], ev["written_at"]) <= (
                        existing["version"], existing["written_at"]
                    ):
                        continue  # LWW: stale event is a no-op
                    payload = json.loads(ev["payload"] or "{}")
                    self.db.execute(
                        """INSERT INTO shared_facts
                           (fact_id, origin_store, version, written_at, fact_timestamp,
                            content, domain, tags, importance, sensitivity, deleted)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                           ON CONFLICT(fact_id, origin_store) DO UPDATE SET
                            version=excluded.version, written_at=excluded.written_at,
                            fact_timestamp=excluded.fact_timestamp, content=excluded.content,
                            domain=excluded.domain, tags=excluded.tags,
                            importance=excluded.importance, sensitivity=excluded.sensitivity,
                            deleted=excluded.deleted""",
                        (ev["fact_id"], ev["origin_store"], ev["version"], ev["written_at"],
                         ev["fact_timestamp"] or "", str(payload.get("content", "")),
                         payload.get("domain", "Knowledge"),
                         str(payload.get("tags", "") or ""),
                         float(payload.get("importance", 0.5)),
                         payload.get("sensitivity", "internal"),
                         1 if ev["op"] == "delete" else 0),
                    )
                    applied += 1
                self.db.execute(
                    """INSERT INTO sync_offsets (store_id, last_event_seq, updated_at)
                       VALUES (?, ?, CURRENT_TIMESTAMP)
                       ON CONFLICT(store_id) DO UPDATE SET
                        last_event_seq=excluded.last_event_seq,
                        updated_at=CURRENT_TIMESTAMP""",
                    (self.profile_id(), max_seq),
                )
                self.db.commit()
                return {"pulled": len(events), "applied": applied, "profile": self.profile_id()}
            finally:
                shared.close()
        finally:
            self._release_write_lock()

    def backfill(self, shared_db: Optional[Path] = None) -> dict:
        """Emit every local non-published fact into the shared log once.

        Implements LOCKED decision 1 (explicit opt-in for legacy facts):
        nothing auto-publishes; this is the one-shot `publish --backfill`.
        Idempotent via the UNIQUE(origin_store, fact_id, version) index.
        """
        self._acquire_write_lock()
        try:
            rows = self.db.execute(
                "SELECT id, content, title, domain, tags, importance, sensitivity, "
                "fact_timestamp, version FROM facts WHERE deleted=0"
            ).fetchall()
            shared = sqlite3.connect(str(shared_db or self.shared_path(self._hermes_home)), timeout=30)
            shared.row_factory = sqlite3.Row
            try:
                emitted = 0
                for r in rows:
                    if not self._publish_allowed(r["sensitivity"]):
                        continue
                    payload = {
                        "content": r["content"], "title": r["title"] or "",
                        "source": "backfill", "importance": r["importance"],
                        "domain": r["domain"], "tags": r["tags"] or "",
                        "sensitivity": r["sensitivity"] or "internal",
                        "profile_id": self.profile_id(),
                    }
                    cur = shared.execute(
                        "INSERT OR IGNORE INTO sync_events "
                        "(origin_store, fact_id, op, version, written_at, fact_timestamp, payload) "
                        "VALUES (?, ?, 'create', ?, ?, ?, ?)",
                        (self.profile_id(), r["id"], int(r["version"] or 1),
                         datetime.now(timezone.utc).isoformat(),
                         r["fact_timestamp"] or "", json.dumps(payload)),
                    )
                    emitted += cur.rowcount
                shared.commit()
            finally:
                shared.close()
            return {"emitted": emitted, "profile": self.profile_id()}
        finally:
            self._release_write_lock()

    def recall(
        self,
        query: str,
        top_k: int = 10,
        domain: Optional[str] = None,
        scope: str = "own",
    ) -> List[StoredFact]:
        """Full-text search over stored facts.

        Returns facts ranked by relevance. An EXACT content/id match is
        always surfaced first (so a fact is always self-retrievable),
        followed by FTS5 prefix matches and a LIKE fallback.

        P2 scope: 'own' (default) = local facts; 'shared' = peer-shared
        facts only; 'all' = local facts merged with peer-shared facts
        (local wins on id collision).

        Phase 8: supports NL temporal queries ("last Tuesday", "2 weeks ago").
        """
        # Phase 8: extract temporal filter from query
        temporal_range = None
        if TEMPORAL_AVAILABLE:
            query, temporal_range = extract_temporal_filter(query)

        if scope not in ("own", "shared", "all"):
            scope = "own"

        # Shared FTS5 query builder — same fields and semantics as
        # recall_with_relevance() so prefetch and recall agree on meaning.
        fts_query = build_fts_query(query, fields=("content", "title", "tags"))

        where = ""
        params: tuple = ()
        if domain:
            where = "AND facts_fts.domain = ?"
            params = (domain,)

        # Phase 8: temporal date range filter
        date_where = ""
        date_params: tuple = ()
        if temporal_range:
            date_where = "AND f.created_at >= ? AND f.created_at <= ?"
            date_params = (temporal_range[0], temporal_range[1] + "T23:59:59")

        # Exact-match boost
        exact_params = (query, StoredFact.make_id(query))
        exact_date_where = ""
        if domain:
            exact_params = (*exact_params, domain)
        if temporal_range:
            exact_date_where = "AND created_at >= ? AND created_at <= ?"
            exact_params = (*exact_params, temporal_range[0], temporal_range[1] + "T23:59:59")
        exact_rows = self.db.execute(
            f"""
            SELECT * FROM facts
            WHERE (content = ? OR id = ?) {("AND domain = ?" if domain else "")} {exact_date_where}
            ORDER BY importance DESC
            """,
            exact_params,
        ).fetchall()
        exact = [self._row_to_fact(r) for r in exact_rows]
        for f in exact:
            f.why_retrieved = self._build_reasons(
                exact_match=True, fts_match=False, domain_filtered=bool(domain),
            )

        # FTS5 MATCH (never raises: bad MATCH expressions → empty + reason)
        rows: list = []
        match_failed = False
        if not query.strip():
            # empty query: 'no matches', never a LIKE '%%' sweep. Exact hits
            # above still make a fact self-recallable.
            return self._served(exact[:top_k])
        if fts_query:
            rows, fts_reason = run_fts_match(
                self.db,
                f"""
                SELECT f.* FROM facts_fts
                JOIN facts f ON facts_fts.rowid = f.rowid
                WHERE facts_fts MATCH ? {where} {date_where}
                ORDER BY rank ASC, f.importance DESC
                LIMIT ?
                """,
                (fts_query, *params, *date_params, top_k),
            )
            match_failed = fts_reason == FTS_REASON_MATCH_ERROR
        fts_hits = [self._row_to_fact(r) for r in rows]
        for f in fts_hits:
            f.why_retrieved = self._build_reasons(
                fts_match=True, domain_filtered=bool(domain),
            )
        local = exact
        if fts_hits:
            seen = {f.id for f in exact}
            local = exact + [f for f in fts_hits if f.id not in seen]
        elif _like_fallback_ok(query, match_failed):
            # LIKE fallback (wildcards in user input are matched literally;
            # symbol/number queries only — word queries never substring-sweep)
            like = f"%{escape_like(query)}%"
            like_params = (like, like, like)
            if domain:
                like_params = (*like_params, domain)
                like_where = ("WHERE (f.content LIKE ? ESCAPE '\\' OR f.title LIKE ? ESCAPE '\\' "
                              "OR f.tags LIKE ? ESCAPE '\\') AND f.domain = ?")
            else:
                like_where = ("WHERE f.content LIKE ? ESCAPE '\\' OR f.title LIKE ? ESCAPE '\\' "
                              "OR f.tags LIKE ? ESCAPE '\\'")
            rows = self.db.execute(
                f"""
                SELECT f.* FROM facts f
                {like_where}
                ORDER BY f.importance DESC
                LIMIT ?
                """,
                (*like_params, top_k),
            ).fetchall()
            like_hits = [self._row_to_fact(r) for r in rows]
            for f in like_hits:
                f.why_retrieved = self._build_reasons(
                    like_fallback=True, domain_filtered=bool(domain),
                    match_error=match_failed,
                )
            seen = {f.id for f in exact}
            local = exact + [f for f in like_hits if f.id not in seen]

        # P2 scope: merge the peer-shared projection for 'shared'/'all'.
        if scope == "own":
            return self._served(local[:top_k])
        shared = self._recall_shared(query, domain, top_k)
        if scope == "shared":
            return self._served(shared[:top_k])
        seen = {f.id for f in local}
        return self._served((local + [f for f in shared if f.id not in seen])[:top_k])

    def _recall_shared(self, query: str, domain: Optional[str], top_k: int) -> List[StoredFact]:
        """Search the local shared_facts projection (peer-published facts)."""
        like = f"%{escape_like(query)}%"
        if domain:
            rows = self.db.execute(
                """SELECT * FROM shared_facts
                   WHERE (content LIKE ? ESCAPE '\\' OR tags LIKE ? ESCAPE '\\')
                     AND domain = ? AND deleted = 0
                   ORDER BY importance DESC, written_at DESC LIMIT ?""",
                (like, like, domain, top_k),
            ).fetchall()
        else:
            rows = self.db.execute(
                """SELECT * FROM shared_facts
                   WHERE (content LIKE ? ESCAPE '\\' OR tags LIKE ? ESCAPE '\\')
                     AND deleted = 0
                   ORDER BY importance DESC, written_at DESC LIMIT ?""",
                (like, like, top_k),
            ).fetchall()
        out = []
        for r in rows:
            tags = [t for t in (r["tags"] or "").split(", ") if t]
            out.append(StoredFact(
                id=r["fact_id"],
                content=r["content"],
                title=r["content"][:60],
                source=f"shared:{r['origin_store']}",
                importance=r["importance"],
                domain=domain or r["domain"],
                tags=[t for t in tags if t],
                created_at=r["written_at"],
                updated_at=r["written_at"],
                sensitivity=r["sensitivity"],
                why_retrieved=MemoryEngine._build_reasons(fts_match=True, domain_filtered=bool(domain)),
            ))
        return out

    def get_fact(self, entropic_id: str) -> Optional[StoredFact]:
        row = self.db.execute("SELECT * FROM facts WHERE id = ?", (entropic_id,)).fetchone()
        return self._row_to_fact(row) if row else None

    def list_facts(
        self,
        domain: Optional[str] = None,
        limit: int = 100,
    ) -> List[StoredFact]:
        if domain:
            rows = self.db.execute(
                "SELECT * FROM facts WHERE domain = ? ORDER BY importance DESC, created_at DESC LIMIT ?",
                (domain, limit),
            ).fetchall()
        else:
            rows = self.db.execute(
                "SELECT * FROM facts ORDER BY importance DESC, created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_fact(r) for r in rows]

    def stats(self) -> dict:
        count = self.db.execute("SELECT COUNT(*) as cnt FROM facts").fetchone()["cnt"]
        domains = self.db.execute(
            "SELECT domain, COUNT(*) as cnt FROM facts GROUP BY domain ORDER BY cnt DESC"
        ).fetchall()
        return {
            "fact_count": count,
            "db_path": str(self.db_path),
            "domains": {r["domain"]: r["cnt"] for r in domains},
        }

    # ── auto-extraction ─────────────────────────────────────────────────

    def extract_and_store(
        self,
        user_text: str,
        assistant_text: str = "",
        session_id: str = "",
        source: str = "auto_extracted",
        min_confidence: float = 0.4,
        promote: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Extract candidate facts from conversation text using heuristic patterns.

        QUARANTINE SEMANTICS: every extracted candidate is recorded in the
        pending_facts quarantine via quarantine_fact(). When the write policy
        allows the candidate, it is ALSO promoted to durable facts (EM-111 —
        extraction now has a promotion path); the pending row remains as the
        extraction record until the TTL purge (prune_pending). Promote or drop
        a candidate explicitly with promote_pending() (CLI: `entropicmem
        pending promote <id>`) or discard_pending(). Returns the list of
        quarantined candidates ({id, content, domain, importance, tag,
        pending: True}).

        This is a regex-based extraction — no LLM required.
        Designed for zero-cost, zero-latency background extraction.
        """
        combined = f"{user_text}\n{assistant_text}"
        extracted: List[Dict[str, Any]] = []

        # Pattern-based extraction
        for pattern, domain, importance, tag in _EXTRACTION_PATTERNS:
            for m in re.finditer(pattern, combined, re.IGNORECASE):
                # Use full match text (group(0)) — avoids tuple reconstruction
                # garbage from multi-group patterns
                content = m.group(0).strip()

                # Minimum quality filter
                if len(content) < 10 or len(content) > 500:
                    continue
                if importance < min_confidence:
                    continue
                self._quarantine_candidate(
                    extracted, content, source, session_id,
                    importance, domain, tag, "auto_extract", promote,
                )

        # Preference detection via common patterns
        preference_patterns = [
            (r"(?:i|we)\s+(?:prefer|want|like|use|using|need)\s+(.+?)(?:\.\s|$)", "People", 0.5),
            (r"(?:don't|do not|never)\s+(?:want|like|need|use)\s+(.+?)(?:\.\s|$)", "People", 0.5),
        ]

        for pattern, domain, importance in preference_patterns:
            for m in re.finditer(pattern, combined, re.IGNORECASE):
                content = f"Preference: {m.group(1).strip().capitalize().rstrip('.')}."
                if len(content) < 15 or len(content) > 300:
                    continue
                self._quarantine_candidate(
                    extracted, content, source, session_id,
                    importance, domain, "preference", "auto_extract_preference", promote,
                )

        return extracted

    def _quarantine_candidate(
        self,
        extracted: List[Dict[str, Any]],
        content: str,
        source: str,
        session_id: str,
        importance: float,
        domain: str,
        tag: str,
        reason: str,
        promote: bool = True,
    ) -> None:
        """Dedup + quarantine one candidate; append to ``extracted`` if stored."""
        eid = StoredFact.make_id(content)
        if self.get_fact(eid):
            return
        if self.db.execute("SELECT 1 FROM pending_facts WHERE id = ?", (eid,)).fetchone():
            return

        # Quarantine — every extraction is recorded in pending_facts
        stored_id = self.quarantine_fact(
            content=content,
            source=source,
            importance=importance,
            domain=domain,
            tags=[tag],
            session_id=session_id,
            reason=reason,
        )
        # EM-111: extraction now has a promotion path — when the write policy
        # allows the candidate it goes to durable facts too; the pending row
        # stays as the extraction record (TTL-pruned by prune_pending).
        # Background paths (session-end capture) pass promote=False and stay
        # pending-only.
        if promote:
            try:
                self.remember(
                    content=content,
                    source="promoted",
                    importance=importance,
                    domain=domain,
                    tags=[tag],
                    session_id=session_id,
                )
            except ValueError:
                pass  # policy-blocked or empty after sanitize: stays quarantined
        extracted.append({
            "id": stored_id,
            "content": content,
            "domain": domain,
            "importance": importance,
            "tag": tag,
            "pending": True,
        })

    # ── temporal decay & reinforcement ──────────────────────────────────

    def reinforce(self, entropic_id: str) -> bool:
        """
        Boost a fact: update last_accessed to now and increment access_count.
        Returns True if the fact was found and reinforced.
        """
        self._acquire_write_lock()
        try:
            row = self.db.execute("SELECT id FROM facts WHERE id = ?", (entropic_id,)).fetchone()
            if not row:
                return False
            now = datetime.now(timezone.utc).isoformat()
            self.db.execute(
                """UPDATE facts SET last_accessed = ?, access_count = access_count + 1
                   WHERE id = ?""",
                (now, entropic_id),
            )
            self.db.commit()
            return True
        finally:
            self._release_write_lock()

    # ── Phase 11.3: fact versioning ─────────────────────────────────────────

    def snapshot_version(self, entropic_id: str, source: str = "update") -> bool:
        """Save the current state of a fact to the versions table before modifying it."""
        row = self.db.execute(
            "SELECT content, importance, domain FROM facts WHERE id = ?",
            (entropic_id,),
        ).fetchone()
        if not row:
            return False
        self.db.execute(
            """INSERT INTO fact_versions (fact_id, content, importance, domain, source)
               VALUES (?, ?, ?, ?, ?)""",
            (entropic_id, row[0], row[1], row[2], source),
        )
        return True

    def get_versions(self, entropic_id: str) -> List[dict]:
        """Get all version snapshots for a fact, newest first."""
        rows = self.db.execute(
            """SELECT content, importance, domain, created_at, source
               FROM fact_versions WHERE fact_id = ?
               ORDER BY created_at DESC, id DESC""",
            (entropic_id,),
        ).fetchall()
        return [
            {
                "content": r[0],
                "importance": r[1],
                "domain": r[2],
                "created_at": r[3],
                "source": r[4],
            }
            for r in rows
        ]

    def _served(self, facts: List[StoredFact]) -> List[StoredFact]:
        """R3/EM-106: serving a fact (``recall()`` returns it to the caller)
        bumps ``last_accessed`` so actively-used facts stop decaying (one
        batched UPDATE; f002 contract). Ranking (`recall_with_relevance`)
        deliberately does NOT touch — ranking is not serving, and touching
        there would rescue weak candidates from decay mid-pipeline. Prefetch
        injection bumps via the provider's ``touch_on_inject`` write."""
        if facts:
            ts = datetime.now(timezone.utc).isoformat()
            self.touch([f.id for f in facts])
            for f in facts:
                f.last_accessed = ts
        return facts

    def touch(self, fact_ids: Sequence[str]) -> int:
        """Batched ``last_accessed`` bump for facts just served/injected."""
        ids = [i for i in fact_ids if i]
        if not ids:
            return 0
        ts = datetime.now(timezone.utc).isoformat()
        marks = ",".join("?" * len(ids))
        cur = self.db.execute(
            f"UPDATE facts SET last_accessed = ? WHERE id IN ({marks})",
            (ts, *ids),
        )
        self.db.commit()
        return cur.rowcount

    def _decay_factor(
        self,
        fact: StoredFact,
        now_ts: datetime,
        half_life_days: float,
        decay_floor: float,
        evergreen_domains: Set[str],
    ) -> float:
        """EM-106: decay that cannot erase durable memory.

        1.0 when the fact is durable (importance ≥ 0.75, evergreen domain,
        ``built_in_memory``/``promoted`` source, or a ``pinned`` tag).
        Otherwise ``max(decay_floor, exp(-λ·age))`` with age from the most
        recent of ``updated_at``/``last_accessed`` and λ = ln2/half_life —
        floor default 0.5, half-life default 90 days.
        """
        if (
            fact.importance >= 0.75
            or fact.domain in evergreen_domains
            or fact.source in ("built_in_memory", "promoted")
            or "pinned" in (fact.tags or [])
        ):
            return 1.0
        stamps = [s for s in (_parse_ts(fact.updated_at), _parse_ts(fact.last_accessed)) if s]
        if not stamps:
            return 1.0
        age_days = max(0.0, (now_ts - max(stamps)).total_seconds() / 86400.0)
        lam = math.log(2) / half_life_days if half_life_days > 0 else 0.0
        return max(decay_floor, math.exp(-lam * age_days))

    def recall_with_relevance(
        self,
        query: str,
        top_k: int = 10,
        domain: Optional[str] = None,
        min_relevance: float = 0.0,
        decay_enabled: bool = True,
        decay_half_life_days: float = 90.0,
        decay_floor: float = 0.5,
        evergreen_domains: Optional[Sequence[str]] = None,
        reinforcement_boost: float = 0.1,
        auto_reinforce: bool = False,
    ) -> List[StoredFact]:
        """Full-text search with absolute relevance scoring and EM-106 decay.

        Scores: relevance = 0.75*coverage + 0.25*rank_bonus; combined =
        clip(relevance * decay_factor * (0.85 + 0.3*importance), 0, 1).
        Decay never erases durable memory (see ``_decay_factor``).
        Auto-reinforce is opt-in (default False) to avoid write-on-read.
        """
        if not query.strip():
            return []

        # Shared FTS5 query builder — same fields (content/title/tags) as
        # recall() so prefetch and recall agree on what a query means.
        fts_query = build_fts_query(query, fields=("content", "title", "tags"))
        # '' from the builder means no FTS terms: skip straight to the
        # escaped LIKE fallback below (literal-substring search for symbol
        # queries like "%"/"_"); only an empty query is 'no matches'.

        where = ""
        params: tuple = ()
        if domain:
            where = "AND f.domain = ?"
            params = (domain,)

        # Get FTS5 results with bm25 rank (never raises on a bad MATCH)
        match_failed = False
        rows: list = []
        if fts_query:
            rows, fts_reason = run_fts_match(
                self.db,
                f"""
                SELECT f.*, bm25(facts_fts) as rank
                FROM facts_fts
                JOIN facts f ON facts_fts.rowid = f.rowid
                WHERE facts_fts MATCH ? {where}
                ORDER BY rank
                LIMIT ?
                """,
                (fts_query, *params, top_k * 2),
            )
            match_failed = fts_reason == FTS_REASON_MATCH_ERROR

        if not rows:
            if not _like_fallback_ok(query, match_failed):
                return []
            return self._recall_like_fallback(
                query, top_k, domain, min_relevance, match_error=match_failed,
            )

        # EM-105: absolute scoring (R1/R4) — replaces min-max normalisation.
        # relevance = 0.75 * lexical coverage + 0.25 * rank_bonus where
        # rank_bonus = 1/(1 + 0.15 * bm25_rank_index) (row order is bm25).
        # combined = relevance * decay_factor * (0.85 + 0.3 * importance),
        # clipped to [0, 1]; min_relevance applies to combined.
        query_terms = coverage_terms(query)

        # EM-106 decay config (defaults per plan: People evergreen, floor 0.5)
        evergreen: Set[str] = set(evergreen_domains) if evergreen_domains is not None else {"People"}
        now_ts = datetime.now(timezone.utc)

        results = []
        for idx, row in enumerate(rows):
            fact = self._row_to_fact(row)

            text = " ".join(
                p for p in (fact.title, fact.content, " ".join(fact.tags or [])) if p
            )
            lex = coverage(query_terms, text)
            rank_bonus = 1.0 / (1.0 + 0.15 * idx)
            relevance = 0.75 * lex + 0.25 * rank_bonus

            # EM-106: decay that cannot erase durable memory
            fact.decay_score = (
                self._decay_factor(
                    fact, now_ts, decay_half_life_days, decay_floor, evergreen,
                )
                if decay_enabled
                else 1.0
            )

            combined_score = relevance * fact.decay_score * (0.85 + 0.3 * fact.importance)
            combined_score = min(1.0, max(0.0, combined_score))

            # Apply min relevance filter
            if combined_score >= min_relevance:
                fact.relevance_score = combined_score
                fact.why_retrieved = self._build_reasons(
                    fts_match=True,
                    recency_applied=decay_enabled,
                    importance_applied=True,
                    domain_filtered=bool(domain),
                ) + [{"signal": "coverage", "value": round(lex, 4)}]
                results.append(fact)

        # Sort by combined score (descending)
        results.sort(key=lambda f: f.relevance_score, reverse=True)

        # Auto-reinforce returned facts (opt-in)
        if auto_reinforce:
            for fact in results[:top_k]:
                self.reinforce(fact.id)

        return results[:top_k]

    def recall_hybrid(
        self,
        query: str,
        top_k: int = 10,
        domain: Optional[str] = None,
        fts_weight: float = 0.6,
        vec_weight: float = 0.4,
        expand_links: bool = False,
        auto_reinforce: bool = False,
    ) -> List[StoredFact]:
        """Hybrid search: FTS5 BM25 + vector similarity fusion (Phase 7).

        Falls back to FTS5-only recall if embeddings are unavailable.

        Phase 10.2: when expand_links=True, traverses the wikilink graph
        and appends connected vault notes as low-score context facts.
        """
        if not EMBEDDINGS_AVAILABLE:
            results = self.recall_with_relevance(query, top_k=top_k, domain=domain)
        else:
            # FTS5 pass (get more candidates for fusion)
            fts_hits = self.recall_with_relevance(query, top_k=top_k * 2, domain=domain)
            fts_scores = []
            if fts_hits:
                max_rel = max(f.relevance_score for f in fts_hits) or 1.0
                fts_scores = [(f.id, f.relevance_score / max_rel) for f in fts_hits]

            # Vector pass
            vec_scores = []
            query_vec = embed_text(query)
            if query_vec:
                vec_results = vector_search(self.db, query_vec, top_k=top_k * 2, domain=domain)
                if vec_results:
                    max_sim = max(s for _, s in vec_results) or 1.0
                    vec_scores = [(fid, sim / max_sim) for fid, sim in vec_results]

            # Fuse
            fused = hybrid_rank(fts_scores, vec_scores, fts_weight, vec_weight)

            # Build result list
            fact_map = {f.id: f for f in fts_hits}
            # Fetch any vector-only hits not in FTS results
            for fid, _ in fused:
                if fid not in fact_map:
                    fact = self.get_fact(fid)
                    if fact:
                        fact.why_retrieved = self._build_reasons(
                            vector_match=True,
                            domain_filtered=bool(domain),
                        )
                        fact_map[fid] = fact

            results = []
            for fid, score in fused[:top_k]:
                fact = fact_map.get(fid)
                if fact:
                    fact.relevance_score = score
                    results.append(fact)

        # Phase 10.2: graph-aware expansion
        if expand_links and results:
            results = self._expand_with_links(results, query, top_k)

        # Auto-reinforce (opt-in)
        if auto_reinforce:
            for fact in results:
                self.reinforce(fact.id)

        return results

    def _expand_with_links(
        self,
        results: List[StoredFact],
        query: str,
        top_k: int,
    ) -> List[StoredFact]:
        """Expand recall results with linked notes (Phase 10.2).

        Traverses the unified graph_edges table (the same graph the vault
        index and the triple sync maintain — never the retired `links`
        table). For each result whose title appears in the graph, fetch
        connected notes and append matching facts as context with a
        reduced relevance score. Databases without a graph_edges table
        return the results unchanged.
        """
        try:
            from graph_query import get_connected_notes
        except ImportError:
            return results

        seen_ids = {f.id for f in results}
        expanded = list(results)
        base_score = min(f.relevance_score for f in results) if results else 0.1

        for fact in results[:5]:  # expand top 5 only
            title = fact.title or fact.content[:60]
            connected = get_connected_notes(self.db, title, depth=1)
            for linked_title in list(connected["all"])[:3]:
                # Search for a fact matching the linked title
                linked_facts = self.recall(linked_title, top_k=1)
                for lf in linked_facts:
                    if lf.id not in seen_ids:
                        lf.relevance_score = base_score * 0.5  # reduced weight
                        expanded.append(lf)
                        seen_ids.add(lf.id)

        return expanded[:top_k + 5]  # allow slight overflow for context

    def rebuild_embeddings(self) -> dict:
        """Regenerate embeddings for all facts (Phase 7.3).

        Returns {total, embedded, skipped, errors}.
        """
        if not EMBEDDINGS_AVAILABLE:
            return {"total": 0, "embedded": 0, "skipped": 0, "errors": 0,
                    "message": "sentence-transformers not installed"}

        facts = self.list_facts(limit=10000)
        embedded = 0
        errors = 0
        for fact in facts:
            try:
                vec = embed_text(fact.content)
                if vec:
                    store_embedding(self.db, fact.id, vec)
                    embedded += 1
            except Exception as exc:  # noqa: BLE001 - third-party embedder
                logger.warning("embedding rebuild failed for %s: %s", fact.id, exc)
                errors += 1

        return {
            "total": len(facts),
            "embedded": embedded,
            "skipped": len(facts) - embedded - errors,
            "errors": errors,
        }

    def embedding_stats(self) -> dict:
        """Report embedding coverage and availability (Phase 7.3)."""
        if not EMBEDDINGS_AVAILABLE:
            return {"available": False, "message": "sentence-transformers not installed"}
        return embedding_coverage(self.db)

    # ── v2.2.0 G1: episodic memory ──────────────────────────────────────────────

    def add_episode(
        self,
        title: str,
        summary: str,
        *,
        start_ts: Optional[str] = None,
        end_ts: Optional[str] = None,
        source_session: str = "",
        linked_fact_ids: Optional[List[str]] = None,
        importance: float = 0.5,
        domain: str = "Knowledge",
        source: str = "agent",
        episode_id: Optional[str] = None,
    ) -> str:
        """Store a distilled episodic record (session summary / timeline entry).

        Episodes answer "when did X happen" — a timestamped timeline layer
        distinct from the semantic fact store. Returns the episode_id.
        """
        self._check_migration_lock()
        self._acquire_write_lock()
        try:
            eid = episode_id or ("ep_" + uuid.uuid4().hex[:12])
            linked = json.dumps(linked_fact_ids or [])
            self.db.execute(
                "INSERT OR REPLACE INTO episodes "
                "(episode_id, title, summary, start_ts, end_ts, source_session, "
                " linked_fact_ids, importance, domain, source) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (eid, title, summary, start_ts, end_ts, source_session,
                 linked, importance, domain, source),
            )
            row = self.db.execute(
                "SELECT rowid FROM episodes WHERE episode_id = ?", (eid,)
            ).fetchone()
            if row:
                self.db.execute(
                    "DELETE FROM episodes_fts WHERE rowid = ?", (row[0],)
                )
                self.db.execute(
                    "INSERT INTO episodes_fts (rowid, title, summary) VALUES (?, ?, ?)",
                    (row[0], title, summary),
                )
            self.db.commit()
        finally:
            self._release_write_lock()
        self.audit("episode_add", fact_id=eid, detail=f"domain={domain};source={source}")
        return eid

    def list_episodes(
        self,
        *,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        domain: Optional[str] = None,
        limit: int = 50,
    ) -> List[dict]:
        """List episodes in chronological order within an optional date window."""
        clauses: list = []
        params: list = []
        if from_date:
            clauses.append("start_ts >= ?")
            params.append(from_date)
        if to_date:
            clauses.append("COALESCE(start_ts, created_at) <= ?")
            params.append(to_date + "T23:59:59")
        if domain:
            clauses.append("domain = ?")
            params.append(domain)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self.db.execute(
            f"SELECT * FROM episodes {where} ORDER BY start_ts ASC, created_at ASC LIMIT ?",
            (*params, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def recall_episodes(
        self,
        query: str,
        *,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        limit: int = 10,
    ) -> List[dict]:
        """FTS timeline recall over episodes (title + summary), with window filter."""
        fts_query = build_fts_query(query, fields=("title", "summary"))
        if not fts_query:
            return []
        where = ""
        window_params: list = []
        if from_date or to_date:
            clauses = []
            if from_date:
                clauses.append("e.start_ts >= ?")
                window_params.append(from_date)
            if to_date:
                clauses.append("COALESCE(e.start_ts, e.created_at) <= ?")
                window_params.append(to_date + "T23:59:59")
            where = " AND " + " AND ".join(clauses)
        rows, _reason = run_fts_match(
            self.db,
            "SELECT e.* FROM episodes_fts f JOIN episodes e ON e.rowid = f.rowid "
            f"WHERE episodes_fts MATCH ?{where} "
            "ORDER BY e.start_ts ASC, e.created_at ASC LIMIT ?",
            (fts_query, *window_params, limit),
        )
        return [dict(r) for r in rows]

    def rebuild_episodes_fts(self) -> int:
        """Rebuild episodes_fts from the episodes table (orphan repair).

        Deletes are not FTS-triggered (no AFTER DELETE trigger on episodes),
        so removing episodes leaves stale rows. Returns the FTS row count.
        """
        self._acquire_write_lock()
        try:
            self.db.execute("DELETE FROM episodes_fts")
            cur = self.db.execute(
                "INSERT INTO episodes_fts (rowid, title, summary) "
                "SELECT rowid, title, summary FROM episodes"
            )
            self.db.commit()
            # rowcount = rows just inserted into FTS; matches the episodes
            # count after a rebuild, avoiding a separate COUNT(*) scan.
            # Guard for drivers that report -1 (undetermined) for
            # INSERT...SELECT and fall back to an explicit count against
            # the canonical episodes table (FTS is a mirror of it).
            if cur.rowcount >= 0:
                return cur.rowcount
            return self.db.execute(
                "SELECT COUNT(*) FROM episodes"
            ).fetchone()[0]
        finally:
            self._release_write_lock()

    def episode_stats(self) -> dict:
        """Count episodes (total + by domain)."""
        total = self.db.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
        by_domain = dict(
            self.db.execute(
                "SELECT domain, COUNT(*) FROM episodes GROUP BY domain ORDER BY 2 DESC"
            ).fetchall()
        )
        return {"total": total, "by_domain": by_domain}

    # ── v2.2.0 G2: knowledge triples ──────────────────────────────────────────

    def upsert_triple(
        self,
        subject: str,
        predicate: str,
        object_: str,
        *,
        valid_from: Optional[str] = None,
        valid_until: Optional[str] = None,
        source: str = "extracted",
        confidence: float = 1.0,
    ) -> int:
        """Insert or update a (subject, predicate, object) triple. Returns row id."""
        self._check_migration_lock()
        self._acquire_write_lock()
        try:
            self.db.execute(
                "INSERT INTO triples (subject, predicate, object, valid_from, valid_until, source, confidence) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(subject, predicate, object) DO UPDATE SET "
                "valid_from = COALESCE(excluded.valid_from, triples.valid_from), "
                "valid_until = excluded.valid_until, source = excluded.source, "
                "confidence = excluded.confidence",
                (subject, predicate, object_, valid_from, valid_until, source, confidence),
            )
            self.db.commit()
            row = self.db.execute(
                "SELECT id FROM triples WHERE subject = ? AND predicate = ? AND object = ?",
                (subject, predicate, object_),
            ).fetchone()
            return row[0] if row else 0
        finally:
            self._release_write_lock()

    def list_triples(
        self,
        *,
        subject: Optional[str] = None,
        predicate: Optional[str] = None,
        object_: Optional[str] = None,
        source: Optional[str] = None,
        active_only: bool = True,
        limit: int = 200,
    ) -> List[dict]:
        """Query triples with optional filters. active_only excludes expired rows."""
        clauses: list = []
        params: list = []
        if subject:
            clauses.append("subject = ?")
            params.append(subject)
        if predicate:
            clauses.append("predicate = ?")
            params.append(predicate)
        if object_:
            clauses.append("object = ?")
            params.append(object_)
        if source:
            clauses.append("source = ?")
            params.append(source)
        if active_only:
            clauses.append("(valid_until IS NULL OR valid_until = '')")
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self.db.execute(
            f"SELECT * FROM triples {where} ORDER BY confidence DESC, created_at DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def triple_neighbors(self, entity: str, *, limit: int = 100) -> List[dict]:
        """All relations touching an entity (as subject or object)."""
        rows = self.db.execute(
            "SELECT * FROM triples WHERE (subject = ? OR object = ?) "
            "AND (valid_until IS NULL OR valid_until = '') "
            "ORDER BY confidence DESC LIMIT ?",
            (entity, entity, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def triple_path(self, start: str, end: str, *, max_depth: int = 4) -> List[dict]:
        """BFS over the triple graph from start to end. Returns the path edges.

        Depth-bounded: neighbors whose path would exceed `max_depth` are
        never enqueued, so the search cannot expand beyond the limit.
        """
        if start == end:
            return []
        seen: set = {start}
        queue: deque = deque([(start, [])])
        while queue:
            node, path = queue.popleft()
            for t in self.triple_neighbors(node, limit=500):
                other = t["object"] if t["subject"] == node else t["subject"]
                new_path = path + [dict(t)]
                if len(new_path) > max_depth:
                    continue  # don't enqueue this neighbor
                if other == end:
                    return new_path
                if other not in seen:
                    seen.add(other)
                    queue.append((other, new_path))
        return []

    def triple_inconsistencies(self) -> List[dict]:
        """Conflicting relations: same subject+predicate with differing objects."""
        rows = self.db.execute(
            "SELECT subject, predicate, COUNT(DISTINCT object) AS n_objects, "
            "GROUP_CONCAT(DISTINCT object) AS objects "
            "FROM triples WHERE (valid_until IS NULL OR valid_until = '') "
            "GROUP BY subject, predicate HAVING n_objects > 1 "
            "ORDER BY n_objects DESC LIMIT 50"
        ).fetchall()
        return [dict(r) for r in rows]

    def triple_stats(self) -> dict:
        """Triple counts: total, distinct subjects, by source."""
        total = self.db.execute("SELECT COUNT(*) FROM triples").fetchone()[0]
        subjects = self.db.execute(
            "SELECT COUNT(DISTINCT subject) FROM triples"
        ).fetchone()[0]
        by_source = dict(
            self.db.execute(
                "SELECT source, COUNT(*) FROM triples GROUP BY source ORDER BY 2 DESC"
            ).fetchall()
        )
        return {"total": total, "distinct_subjects": subjects, "by_source": by_source}

    # ── timeline (Phase 8) ────────────────────────────────────────────────────

    def timeline(
        self,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        domain: Optional[str] = None,
        limit: int = 50,
    ) -> List[StoredFact]:
        """Return facts in chronological order within a date range (Phase 8).

        Dates are ISO strings (YYYY-MM-DD). If omitted, unbounded.
        """
        clauses = []
        params: list = []
        if from_date:
            clauses.append("created_at >= ?")
            params.append(from_date)
        if to_date:
            clauses.append("created_at <= ?")
            params.append(to_date + "T23:59:59")
        if domain:
            clauses.append("domain = ?")
            params.append(domain)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self.db.execute(
            f"SELECT * FROM facts {where} ORDER BY created_at ASC LIMIT ?",
            (*params, limit),
        ).fetchall()
        return [self._row_to_fact(r) for r in rows]

    def _recall_like_fallback(
        self,
        query: str,
        top_k: int,
        domain: Optional[str],
        min_relevance: float,
        match_error: bool = False,
    ) -> List[StoredFact]:
        """Fallback LIKE-based search when FTS5 returns no results.

        User-supplied LIKE wildcards are escaped so %/_ match literally.
        ``match_error`` records that the FTS stage failed (vs. simply had no
        hits) and surfaces as a 'match_error' reason token on each hit.
        """
        where = ""
        params: tuple = ()
        if domain:
            where = "AND domain = ?"
            params = (domain,)

        like = f"%{escape_like(query)}%"
        like_params = (like, like, like)
        rows = self.db.execute(
            f"""
            SELECT * FROM facts
            WHERE (content LIKE ? ESCAPE '\\' OR title LIKE ? ESCAPE '\\'
                   OR tags LIKE ? ESCAPE '\\') {where}
            ORDER BY importance DESC
            LIMIT ?
            """,
            (*like_params, *params, top_k),
        ).fetchall()

        results = []
        for row in rows:
            fact = self._row_to_fact(row)
            fact.relevance_score = fact.importance * 0.8
            if fact.relevance_score >= min_relevance:
                fact.why_retrieved = self._build_reasons(
                    like_fallback=True,
                    importance_applied=True,
                    domain_filtered=bool(domain),
                    match_error=match_error,
                )
                results.append(fact)

        return results

    # ── export to vault ─────────────────────────────────────────────────

    def project_to_vault(self, vault, index, limit: int = 500) -> dict:
        """
        Project all stored facts into the vault as Markdown notes.
        Creates notes in a dedicated domain folder for each fact.
        Returns {created, updated, skipped} counts.
        """
        result = {"created": 0, "updated": 0, "skipped": 0}
        facts = self.list_facts(limit=limit)

        for fact in facts:
            domain = fact.domain or "Knowledge"
            body = (
                f"## Fact\n{fact.content}\n\n"
                f"## Metadata\n"
                f"- entropic_id: {fact.id}\n"
                f"- source: {fact.source}\n"
                f"- importance: {fact.importance}\n"
                f"- created: {fact.created_at}\n\n"
                f"## Links\n- [[{domain}/Index]]\n"
            )
            tags = ["fact", "memory-engine"]
            if fact.tags:
                tags.extend(fact.tags)

            try:
                path = vault.write_note(
                    domain, fact.title, body,
                    tags=tags, domain=domain, source=fact.source,
                    frontmatter={"entropic_id": fact.id},
                    note_type="permanent", agent=True,
                )
                note = vault.read_note(path)
                index.upsert_note(note)
                index.upsert_edges_for_note(vault, note)
                result["created"] += 1
            except (OSError, ValueError, KeyError, sqlite3.Error) as exc:
                logger.warning("project_to_vault skipped fact %s: %s", fact.id, exc)
                result["skipped"] += 1

        return result

    # ── helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _build_reasons(
        *,
        fts_match: bool = False,
        exact_match: bool = False,
        vector_match: bool = False,
        recency_applied: bool = False,
        importance_applied: bool = False,
        triple_boost: bool = False,
        domain_filtered: bool = False,
        like_fallback: bool = False,
        match_error: bool = False,
    ) -> List[Any]:
        """Build a deterministic reason-token list for a single recall hit.

        Returns a list of string tokens. Callers that have numeric scores can
        later enrich individual entries into {"signal": ..., "score": ...}.
        'match_error' marks hits that surfaced via the LIKE fallback because
        the FTS5 MATCH expression was rejected (empty-result + reason token
        semantics — never an exception).
        """
        reasons: List[Any] = []
        if exact_match:
            reasons.append("exact")
        if fts_match:
            reasons.append("fts")
        elif like_fallback:
            reasons.append("fts")  # LIKE fallback is still an FTS-replacement match
        if vector_match:
            reasons.append("vector")
        if recency_applied:
            reasons.append("recency")
        if importance_applied:
            reasons.append("importance")
        if triple_boost:
            reasons.append("triple")
        if domain_filtered:
            reasons.append("domain")
        if match_error:
            reasons.append("match_error")
        return reasons

    def _make_title(self, content: str, max_len: int = 80) -> str:
        """Humanized title from fact content (naming convention v2.2.0+).

        Uses the shared derive_title() helper so DB titles and vault
        filenames share one convention (first sentence, markdown + emoji
        stripped, no 'Fact - ' prefix). Imported at module level — no
        per-call overhead, no hidden import cycle.
        """
        title = derive_title(content, max_len=max_len)
        if title:
            return title
        first_line = content.split("\n")[0].strip()
        return first_line[:max_len] or "fact"

    @staticmethod
    def _jaccard_similarity(a: str, b: str) -> float:
        """Jaccard similarity between two strings (word-level tokenization)."""
        set_a = set(a.lower().split())
        set_b = set(b.lower().split())
        if not set_a or not set_b:
            return 0.0
        intersection = set_a & set_b
        union = set_a | set_b
        return len(intersection) / len(union)

    # EM-109: critical tokens whose change must block a fuzzy in-place update
    _NUMBER_WORDS = {
        "zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
        "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
        "sixteen", "seventeen", "eighteen", "nineteen", "twenty", "thirty",
        "forty", "fifty", "sixty", "seventy", "eighty", "ninety", "hundred",
        "thousand", "million", "half", "quarter", "first", "second", "third",
    }
    _NEGATION_TOKENS = {
        "no", "not", "never", "without", "none", "nobody", "nothing",
        "cannot", "cant", "dont", "doesnt", "isnt", "arent", "wasnt",
        "werent", "wont", "wouldnt", "shouldnt", "couldnt", "didnt",
    }
    _TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9.\-_:]*")

    @classmethod
    def _critical_tokens(cls, text: str) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
        """(numbers/versions/IPs/dates, negations) as sorted tuples.

        Tokens are split on separators first so embedded number words in
        identifiers ("alpha-seven.internal") count too.
        """
        numbers: Set[str] = set()
        negations: Set[str] = set()
        for token in cls._TOKEN_RE.findall(text.lower()):
            for part in re.split(r"[.\-_:]+", token):
                if not part:
                    continue
                if any(ch.isdigit() for ch in part) or part in cls._NUMBER_WORDS:
                    numbers.add(part)
                if part in cls._NEGATION_TOKENS:
                    negations.add(part)
        return tuple(sorted(numbers)), tuple(sorted(negations))

    @classmethod
    def _safe_fuzzy_update(cls, content: str, old_content: str) -> bool:
        """EM-109: may a fuzzy near-duplicate update in place?

        Only when Jaccard >= 0.95 AND the numbers/versions/IPs/dates are
        identical AND the negation tokens are identical. Anything else must
        insert as a new fact (never a silent overwrite).
        """
        if cls._jaccard_similarity(content, old_content) < 0.95:
            return False
        return cls._critical_tokens(content) == cls._critical_tokens(old_content)

    def _find_fuzzy_duplicate(self, content: str, threshold: float = 0.8) -> Optional[str]:
        """Find an existing fact with Jaccard similarity >= threshold.

        Uses FTS pre-filter to avoid scanning all facts. Falls back to
        last-200 scan if the content is too short for FTS or the MATCH
        expression is refused.

        Returns the entropic_id of the duplicate, or None.
        """
        # Extract tokens for FTS query (strip chars that break FTS phrase syntax)
        tokens = [
            re.sub(r'[^\w]', '', w)
            for w in content.lower().split()
        ]
        tokens = [t for t in tokens if len(t) >= 3]
        if not tokens:
            # Too short for FTS; fall back to recent scan
            rows = self.db.execute(
                "SELECT id, content FROM facts ORDER BY updated_at DESC LIMIT 200"
            ).fetchall()
            for row in rows:
                if self._jaccard_similarity(content, row[1]) >= threshold:
                    return row[0]
            return None

        # Build FTS query via the shared builder (OR of token prefixes, capped)
        fts_terms = build_fts_query(content, fields=("content",), max_terms=10)
        rows: list = []
        fts_usable = bool(fts_terms)
        if fts_usable:
            rows, reason = run_fts_match(
                self.db,
                """
                SELECT f.id, f.content FROM facts_fts
                JOIN facts f ON facts_fts.rowid = f.rowid
                WHERE facts_fts MATCH ?
                LIMIT 50
                """,
                (fts_terms,),
            )
            if reason != FTS_REASON_OK:
                rows = []
                fts_usable = False
        if not fts_usable:
            # Too short for FTS (or MATCH refused) — fall back to recent scan
            rows = self.db.execute(
                "SELECT id, content FROM facts ORDER BY updated_at DESC LIMIT 200"
            ).fetchall()

        for row in rows:
            if self._jaccard_similarity(content, row[1]) >= threshold:
                return row[0]
        return None

    def _row_to_fact(self, row: sqlite3.Row) -> StoredFact:
        tags_str = row["tags"] or ""
        tags = [t.strip() for t in tags_str.split(",") if t.strip()]
        # sensitivity may be absent on very old rows mid-migration
        try:
            sens = row["sensitivity"] or "internal"
        except (KeyError, IndexError):
            sens = "internal"
        return StoredFact(
            id=row["id"],
            content=row["content"],
            title=row["title"] or "",
            source=row["source"] or "agent",
            importance=row["importance"] or 0.5,
            domain=row["domain"] or "Knowledge",
            tags=tags,
            sensitivity=sens,
            created_at=row["created_at"] or "",
            updated_at=row["updated_at"] or "",
            last_accessed=row["last_accessed"] or "",
            access_count=row["access_count"] or 0,
        )


    # ── Sprint A (v2) — Reflect + explicit recall tools (no schema changes) ──
    # Added after planner gate @ 2026-09-04: renamed recall_summary → recall_for_agent
    # to avoid collision with existing MemoryEngine.recall_summary aggregate.
    def recall_for_agent(self, query: str, top_k: int = 10, domain: Optional[str] = None) -> dict:
        """Explicit agent recall + reflection layer (Sprint A, v2).

        Reads top-k via existing recall(), synthesizes via prompt template,
        writes audit only via audit() (no storage write other than audit_log).
        Returns {facts: [...], reflect_summary: str, source_ids: [...]}.
        """
        facts = self.recall(query, top_k=top_k, domain=domain, scope="own")
        # Reflect: synthesize from recalled set only (no storage guarantee)
        reflect_summary = ""
        if facts:
            # Prompt-template-only synthesis (LLM called externally, not embedded)
            themes = sorted({f.tags[0] if f.tags else "general" for f in facts[:3]})
            reflect_summary = (
                f"Reflect on {len(facts)} recalled facts about '{query}': "
                f"known={len(facts)}, key themes={', '.join(themes)}."
            )
        # Audit-only write (no new storage)
        self.audit("reflect", detail=f"query={query[:200]};hits={len(facts)}")
        return {
            "facts": [
                {"id": f.id, "title": f.title or f.id, "domain": f.domain, "importance": f.importance}
                for f in facts
            ],
            "reflect_summary": reflect_summary,
            "source_ids": [f.id for f in facts],
        }

    def recall_related(self, fact_id: str, top_k: int = 10) -> List[StoredFact]:
        """Graph-neighbor recall via the triples table (Sprint A, v2).

        Resolves the seed fact, walks every (subject, predicate, object) triple
        that touches one of its entities (its id, title, or tags), and returns
        up to top_k facts that mention a neighboring entity. Direct neighbors
        first (v1); sibling/multi-hop out of scope. Runs entirely on self.db —
        no new tables.
        """
        seed = self.get_fact(fact_id)
        if not seed:
            return []
        entities: List[str] = [fact_id]
        if seed.title:
            entities.append(seed.title)
        entities.extend(seed.tags)

        related: List[str] = []  # neighbor entity names, in discovery order
        seen = {e for e in entities if e}
        for ent in sorted(seen):
            for row in self.db.execute(
                "SELECT subject, object FROM triples "
                "WHERE (subject = ? OR object = ?) "
                "AND (valid_until IS NULL OR valid_until = '')",
                (ent, ent),
            ).fetchall():
                other = row["object"] if row["subject"] == ent else row["subject"]
                if other and other not in seen:
                    seen.add(other)
                    related.append(other)

        results: List[StoredFact] = []
        for entity in related[:top_k]:
            row = self.db.execute(
                "SELECT * FROM facts "
                "WHERE id != ? AND (title = ? OR content LIKE ? ESCAPE '\\') "
                "ORDER BY importance DESC LIMIT 1",
                (fact_id, entity, f"%{escape_like(entity)}%"),
            ).fetchone()
            if row:
                fact = self._row_to_fact(row)
                fact.why_retrieved = self._build_reasons(triple_boost=True)
                results.append(fact)
        self.audit("recall_related", fact_id=fact_id, detail=f"neighbors={len(related)}")
        return results

