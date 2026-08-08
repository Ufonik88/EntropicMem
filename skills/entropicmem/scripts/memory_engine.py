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

import hashlib
import json
import os
import math
import re
import fcntl
import sqlite3
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from vault import derive_title  # naming convention helper (stdlib-only, acyclic)

try:
    from policy import evaluate_write, normalize_sensitivity, redact_for_prefetch
    POLICY_AVAILABLE = True
except ImportError:
    POLICY_AVAILABLE = False

# ── optional embedding support (Phase 7: semantic search) ──────────────────

try:
    from embeddings import (
        EMBEDDER_AVAILABLE as _EMB_AVAIL,
        NUMPY_AVAILABLE as _NP_AVAIL,
        cosine_similarity,
        delete_embedding,
        embed_text,
        embedding_coverage,
        hybrid_rank,
        init_embeddings_schema,
        store_embedding,
        vector_search,
    )
    EMBEDDINGS_AVAILABLE = _EMB_AVAIL and _NP_AVAIL
except ImportError:
    EMBEDDINGS_AVAILABLE = False

# ── temporal query parsing (Phase 8) ────────────────────────────────────────

try:
    from temporal import extract_temporal_filter
    TEMPORAL_AVAILABLE = True
except ImportError:
    TEMPORAL_AVAILABLE = False

# ── PII detection (Phase 9) ─────────────────────────────────────────────────

try:
    from pii import check_pii, scan_pii, redact_pii
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
    access_count INTEGER DEFAULT 0
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

# ── auto-extraction patterns ────────────────────────────────────────────────

# Heuristic patterns for extracting facts from conversation text without an LLM.
# Each pattern produces (content, domain, importance) tuples.

_EXTRACTION_PATTERNS: List[Tuple[str, str, float, str]] = [
    # Pattern                     Domain           Imp  Description
    (r"(the|my)\s+(\w+\s+){0,4}(budget|account|salary|income|expense|financ)",
     "Finance",        0.7, "financial"),
    (r"(ajax|security|alarm|detector|hub|camera|sensor)\s{1,3}(systems?|app|device|migration)",
     "Ajax Systems",   0.8, "ajax"),
    (r"(hermes|agent|plugin|skill|tool|model|provider)\s{1,3}(config|setup|install|error|memory)",
     "Infrastructure", 0.7, "hermes"),
    (r"(entropicmem|memory|vault|engine|index|retrieval)",
     "Infrastructure", 0.6, "entropicmem"),
    (r"(obsidian|vault|note|logseq)\s{1,3}(sync|backup|cleanup|migrat)",
     "Infrastructure", 0.6, "obsidian"),
    (r"(prefer|want|like|need|don't want|hate|dislike)\s{1,3}(to\s+)?(\w+\s+){1,6}\.",
     "People",         0.5, "preference"),
    (r"(customer|partner|installer|distributor)\s{1,3}(call|meeting|demo|pitch|follow)",
     "Projects",       0.6, "customer"),
    (r"(roadshow|webinar|certification|training|event)\s{1,3}(2026|\d{1,2}\s*\w+\s*2026)",
     "Projects",       0.7, "event"),
    (r"(twitter|x\s*post|social|content|viral|growth|follow)",
     "X-Growth",       0.6, "social"),
    (r"(fix|bug|error|crash|fail|broken)\s{1,3}(\w+\s+){1,5}(in|on|with)",
     "Infrastructure", 0.5, "bug"),
    (r"(python|node|rust|golang?|typescript|bash)\s{1,3}(version|update|upgrade|install)",
     "Infrastructure", 0.5, "dev-env"),
    (r"(email|gmail|google\s*workspace|calendar)\s{1,3}(setup|sync|config|problem)",
     "Workflows",      0.6, "productivity"),
    (r"(release|shipped|launched|deployed|merged|pr\s*#?\d+)",
     "Projects",       0.5, "release"),
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

    @staticmethod
    def make_id(content: str) -> str:
        """Deterministic entropic_id from content."""
        return hashlib.sha256(content.encode()).hexdigest()[:16]


# ── engine ──────────────────────────────────────────────────────────────────


class MemoryEngine:
    """Standalone memory engine. One SQLite database, no external deps."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
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
        
        # Concurrency guard: file lock for write serialization
        lock_path = self.db_path.parent / f"{self.db_path.name}.lock"
        self._lock_fd = open(lock_path, "w")
        self._write_locked = False
        
        self._init_schema()
    
    def _acquire_write_lock(self) -> None:
        """Acquire exclusive file lock for write operations."""
        if not self._write_locked:
            try:
                fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._write_locked = True
            except OSError:
                # Lock held by another process — wait briefly
                fcntl.flock(self._lock_fd, fcntl.LOCK_EX)
                self._write_locked = True
    
    def _release_write_lock(self) -> None:
        """Release file lock after write operations."""
        if self._write_locked:
            fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
            self._write_locked = False

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
            self._release_write_lock()
        except (OSError, ValueError):
            pass  # lock already released or fd closed
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
        actor: str = "agent",
        session_id: str = "",
        fact_id: str = "",
        detail: str = "",
        ok: bool = True,
    ) -> None:
        """Append-only audit event (best-effort)."""
        try:
            self.db.execute(
                """INSERT INTO audit_log (action, actor, session_id, fact_id, detail, ok)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (action, actor, session_id, fact_id, detail[:2000], 1 if ok else 0),
            )
            self.db.commit()
        except Exception:
            pass

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

    def promote_pending(self, pending_id: str, *, actor: str = "agent") -> Optional[str]:
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
            sensitivity="internal",
            actor="promote_pending",
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
        actor: str = "agent",
    ) -> str:
        """
        Store a durable fact. Returns the entropic_id.
        Deduplicates: if a fact with the same content hash exists, updates it.

        Phase 9: PII detection/redaction applied before storage.
        Phase 2: sensitivity tiers + write policy (block secrets, quarantine auto).
        """
        content = self._sanitize_fact_text(content)
        if not content:
            raise ValueError("empty content after sanitize")

        # Phase 2 write policy
        tier = "internal"
        if POLICY_AVAILABLE:
            tier = normalize_sensitivity(sensitivity, domain)
            action, reason = evaluate_write(
                content, domain=domain, sensitivity=tier, source=source
            )
            if action == "block":
                self.audit("remember_blocked", actor=actor, session_id=session_id, detail=reason or "", ok=False)
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

        self._acquire_write_lock()
        eid = StoredFact.make_id(content)
        tags_str = ", ".join(tags) if tags else ""
        now = datetime.now(timezone.utc).isoformat()

        existing = self.db.execute(
            "SELECT id FROM facts WHERE id = ?", (eid,)
        ).fetchone()

        if existing:
            # Phase 11.3: snapshot before update
            self.snapshot_version(eid, source="dedup_update")
            self.db.execute(
                """UPDATE facts SET content=?, title=?, importance=?, domain=?,
                   tags=?, session_id=?, updated_at=?, sensitivity=?
                   WHERE id=?""",
                (content, title or self._make_title(content), importance,
                 domain, tags_str, session_id, now, tier, eid),
            )
        else:
            # I1: Fuzzy deduplication — check for near-duplicate content
            fuzzy_id = self._find_fuzzy_duplicate(content)
            if fuzzy_id and fuzzy_id != eid:
                # Phase 11.3: snapshot before fuzzy update
                self.snapshot_version(fuzzy_id, source="fuzzy_dedup_update")
                # Update the existing near-duplicate instead of creating a new fact
                self.db.execute(
                    """UPDATE facts SET content=?, title=?, importance=?, domain=?,
                       tags=?, session_id=?, updated_at=?, sensitivity=?
                       WHERE id=?""",
                    (content, title or self._make_title(content), importance,
                     domain, tags_str, session_id, now, tier, fuzzy_id),
                )
                eid = fuzzy_id  # Return the existing fact's ID
            else:
                self.db.execute(
                    """INSERT INTO facts (id, content, title, source, importance, domain,
                       tags, session_id, created_at, updated_at, last_accessed, sensitivity)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (eid, content, title or self._make_title(content),
                     source, importance, domain, tags_str, session_id, now, now, now, tier),
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
        self.db.commit()
        # Phase 7: generate and store embedding (best-effort, non-blocking)
        if EMBEDDINGS_AVAILABLE:
            try:
                vec = embed_text(content)
                if vec:
                    store_embedding(self.db, eid, vec)
            except Exception:
                pass  # embedding failure should never block remember()
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
        self._acquire_write_lock()
        # I4: Auto-backup before destructive operation
        self._backup()
        # Get rowid before deleting from facts
        row = self.db.execute("SELECT rowid FROM facts WHERE id = ?", (entropic_id,)).fetchone()
        self.db.execute("DELETE FROM facts WHERE id = ?", (entropic_id,))
        if row:
            self.db.execute("DELETE FROM facts_fts WHERE rowid = ?", (row[0],))
        # Phase 7: remove embedding if present
        if EMBEDDINGS_AVAILABLE:
            delete_embedding(self.db, entropic_id)
        self.db.commit()
        self._release_write_lock()
        self.audit("forget", fact_id=entropic_id, ok=row is not None)
        return row is not None

    def consolidate(self, max_age_days: int = 90, min_access_count: int = 0, dry_run: bool = True, confirm: bool = False) -> dict:
        """Archive old, low-value facts (I3: memory consolidation).

        Facts older than max_age_days with access_count <= min_access_count
        are moved to an archive table. Returns stats.

        If dry_run=True, reports what would be archived without modifying anything.
        """
        cutoff = datetime.now(timezone.utc).timestamp() - (max_age_days * 86400)
        cutoff_iso = datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat()

        # Find candidates
        candidates = self.db.execute(
            """SELECT id FROM facts
               WHERE created_at < ? AND access_count <= ?""",
            (cutoff_iso, min_access_count),
        ).fetchall()

        if dry_run or not confirm:
            return {
                "archived": 0,
                "would_archive": len(candidates),
                "cutoff_days": max_age_days,
                "dry_run": True,
                "confirm_required": not confirm,
            }

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
                archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        archived = 0
        for (fid,) in candidates:
            # Copy to archive
            self.db.execute(
                """INSERT OR REPLACE INTO facts_archive
                   (id, content, title, source, importance, domain, tags,
                    session_id, created_at, updated_at, last_accessed, access_count)
                   SELECT id, content, title, source, importance, domain, tags,
                          session_id, created_at, updated_at, last_accessed, access_count
                   FROM facts WHERE id = ?""",
                (fid,),
            )
            # Delete from facts + FTS
            row = self.db.execute("SELECT rowid FROM facts WHERE id = ?", (fid,)).fetchone()
            self.db.execute("DELETE FROM facts WHERE id = ?", (fid,))
            if row:
                self.db.execute("DELETE FROM facts_fts WHERE rowid = ?", (row[0],))
            archived += 1

        self.db.commit()
        self.audit("consolidate", detail=f"archived={archived};days={max_age_days}")
        return {"archived": archived, "cutoff_days": max_age_days, "dry_run": False}

    def recall(
        self,
        query: str,
        top_k: int = 10,
        domain: Optional[str] = None,
    ) -> List[StoredFact]:
        """Full-text search over stored facts.

        Returns facts ranked by relevance. An EXACT content/id match is
        always surfaced first (so a fact is always self-retrievable),
        followed by FTS5 prefix matches and a LIKE fallback.

        Phase 8: supports NL temporal queries ("last Tuesday", "2 weeks ago").
        """
        # Phase 8: extract temporal filter from query
        temporal_range = None
        if TEMPORAL_AVAILABLE:
            query, temporal_range = extract_temporal_filter(query)

        clean = query.replace('"', '""')

        # Split multi-word queries into per-word OR terms (matches recall_with_relevance strategy)
        words = clean.split()
        if len(words) > 1:
            word_queries = []
            for w in words:
                if w:
                    word_queries.append(f'content: "{w}"*')
                    word_queries.append(f'title: "{w}"*')
                    word_queries.append(f'tags: "{w}"*')
            fts_query = " OR ".join(word_queries)
        else:
            fts_query = f'content: "{clean}"* OR title: "{clean}"* OR tags: "{clean}"*'

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

        # FTS5 MATCH
        rows = self.db.execute(
            f"""
            SELECT f.* FROM facts_fts
            JOIN facts f ON facts_fts.rowid = f.rowid
            WHERE facts_fts MATCH ? {where} {date_where}
            ORDER BY f.importance DESC, rank
            LIMIT ?
            """,
            (fts_query, *params, *date_params, top_k),
        ).fetchall()
        fts_hits = [self._row_to_fact(r) for r in rows]
        if fts_hits:
            seen = {f.id for f in exact}
            combined = exact + [f for f in fts_hits if f.id not in seen]
            return combined[:top_k]

        # LIKE fallback
        like_params = (f"%{query}%", f"%{query}%", f"%{query}%")
        if domain:
            like_params = (*like_params, domain)
            like_where = "WHERE (f.content LIKE ? OR f.title LIKE ? OR f.tags LIKE ?) AND f.domain = ?"
        else:
            like_where = "WHERE f.content LIKE ? OR f.title LIKE ? OR f.tags LIKE ?"
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
        seen = {f.id for f in exact}
        combined = exact + [f for f in like_hits if f.id not in seen]
        return combined[:top_k]

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
    ) -> List[Dict[str, Any]]:
        """
        Extract durable facts from conversation text using heuristic patterns.
        Stores extracted facts via remember(). Returns list of extracted facts.

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

                # Check not already stored or pending
                eid = StoredFact.make_id(content)
                if self.get_fact(eid):
                    continue
                if self.db.execute("SELECT 1 FROM pending_facts WHERE id = ?", (eid,)).fetchone():
                    continue

                # Quarantine — never auto-promote into durable facts
                stored_id = self.quarantine_fact(
                    content=content,
                    source=source,
                    importance=importance,
                    domain=domain,
                    tags=[tag],
                    session_id=session_id,
                    reason="auto_extract",
                )

                extracted.append({
                    "id": stored_id,
                    "content": content,
                    "domain": domain,
                    "importance": importance,
                    "tag": tag,
                    "pending": True,
                })

        # Preference detection via common patterns
        preference_patterns = [
            (r"(?:i|we|ufonik)\s+(?:prefer|want|like|use|using|need)\s+(.+?)(?:\.\s|$)", "People", 0.5),
            (r"(?:don't|do not|never)\s+(?:want|like|need|use)\s+(.+?)(?:\.\s|$)", "People", 0.5),
        ]

        for pattern, domain, importance in preference_patterns:
            for m in re.finditer(pattern, combined, re.IGNORECASE):
                content = f"Preference: {m.group(1).strip().capitalize().rstrip('.')}."
                if len(content) < 15 or len(content) > 300:
                    continue

                eid = StoredFact.make_id(content)
                if self.get_fact(eid):
                    continue
                if self.db.execute("SELECT 1 FROM pending_facts WHERE id = ?", (eid,)).fetchone():
                    continue

                stored_id = self.quarantine_fact(
                    content=content,
                    source=source,
                    importance=importance,
                    domain=domain,
                    tags=["preference"],
                    session_id=session_id,
                    reason="auto_extract_preference",
                )
                extracted.append({
                    "id": stored_id,
                    "content": content,
                    "domain": domain,
                    "importance": importance,
                    "tag": "preference",
                    "pending": True,
                })

        return extracted

    # ── temporal decay & reinforcement ──────────────────────────────────

    def reinforce(self, entropic_id: str) -> bool:
        """
        Boost a fact: update last_accessed to now and increment access_count.
        Returns True if the fact was found and reinforced.
        """
        self._acquire_write_lock()
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
        self._release_write_lock()
        return True

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

    def recall_with_relevance(
        self,
        query: str,
        top_k: int = 10,
        domain: Optional[str] = None,
        min_relevance: float = 0.0,
        decay_enabled: bool = True,
        decay_half_life_days: float = 30.0,
        reinforcement_boost: float = 0.1,
        auto_reinforce: bool = False,
    ) -> List[StoredFact]:
        """Full-text search with relevance scoring and temporal decay.

        Returns facts ranked by combined relevance + decay score.
        Uses FTS5 bm25() ranking normalized to 0-1 scale.
        Applies exponential temporal decay to older, unreinforced facts.
        Auto-reinforce is opt-in (default False) to avoid write-on-read.
        """
        if not query.strip():
            return []

        # Sanitize query for FTS5
        clean = query.replace('"', '""')

        # Split query for OR matching
        words = clean.split()
        if len(words) > 1:
            word_queries = [f'content: "{w}"*' for w in words if w]
            fts_query = " OR ".join(word_queries)
        else:
            fts_query = f'content: "{clean}"* OR title: "{clean}"* OR tags: "{clean}"*'

        where = ""
        params: tuple = ()
        if domain:
            where = "AND f.domain = ?"
            params = (domain,)

        # Get FTS5 results with bm25 rank
        rows = self.db.execute(
            f"""
            SELECT f.*, bm25(facts_fts) as rank
            FROM facts_fts
            JOIN facts f ON facts_fts.rowid = f.rowid
            WHERE facts_fts MATCH ? {where}
            ORDER BY rank
            LIMIT ?
            """,
            (fts_query, *params, top_k * 2),
        ).fetchall()

        if not rows:
            return self._recall_like_fallback(query, top_k, domain, min_relevance)

        # Normalize bm25 scores to 0-1
        ranks = [row["rank"] for row in rows]
        min_rank = min(ranks)
        max_rank = max(ranks)
        rank_range = max_rank - min_rank if max_rank != min_rank else 1.0

        # Compute decay factor
        lambda_decay = math.log(2) / decay_half_life_days if decay_enabled else 0
        now_ts = datetime.now(timezone.utc)

        results = []
        for row in rows:
            fact = self._row_to_fact(row)

            # Normalize relevance: 0 = least, 1 = most
            if rank_range > 0:
                fact.relevance_score = 1.0 - ((row["rank"] - min_rank) / rank_range)
            else:
                fact.relevance_score = 1.0

            # Compute temporal decay
            if decay_enabled and fact.last_accessed:
                try:
                    last = datetime.fromisoformat(fact.last_accessed)
                    # Handle timezone-naive datetimes
                    if last.tzinfo is None:
                        last = last.replace(tzinfo=timezone.utc)
                    days_since = (now_ts - last).total_seconds() / 86400.0
                    fact.decay_score = math.exp(-lambda_decay * days_since)
                except (ValueError, OverflowError):
                    fact.decay_score = 1.0
            else:
                fact.decay_score = 1.0

            # Reinforcement boost: cap at 10 accesses
            boost = 1.0 + reinforcement_boost * min(fact.access_count, 10)
            combined_score = fact.relevance_score * fact.decay_score * boost

            # Apply min relevance filter
            if combined_score >= min_relevance:
                # Override relevance_score with combined for sorting
                fact.relevance_score = combined_score
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
        """Expand recall results with linked vault notes (Phase 10.2).

        For each result whose title appears in the link graph, fetch
        connected notes and append them as context facts with a
        reduced relevance score.
        """
        try:
            from graph_query import init_links_schema, get_connected_notes
        except ImportError:
            return results

        conn = self.db  # reuse engine connection (links table may exist)
        try:
            init_links_schema(conn)
        except Exception:
            return results

        seen_ids = {f.id for f in results}
        expanded = list(results)
        base_score = min(f.relevance_score for f in results) if results else 0.1

        for fact in results[:5]:  # expand top 5 only
            title = fact.title or fact.content[:60]
            connected = get_connected_notes(conn, title, depth=1)
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
            except Exception:
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
        clean = query.replace('"', '""')
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
        rows = self.db.execute(
            "SELECT e.* FROM episodes_fts f JOIN episodes e ON e.rowid = f.rowid "
            f"WHERE episodes_fts MATCH ?{where} "
            "ORDER BY e.start_ts ASC, e.created_at ASC LIMIT ?",
            (clean, *window_params, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def rebuild_episodes_fts(self) -> int:
        """Rebuild episodes_fts from the episodes table (orphan repair).

        Deletes are not FTS-triggered (no AFTER DELETE trigger on episodes),
        so removing episodes leaves stale rows. Returns the FTS row count.
        """
        self._acquire_write_lock()
        try:
            self.db.execute("DELETE FROM episodes_fts")
            self.db.execute(
                "INSERT INTO episodes_fts (rowid, title, summary) "
                "SELECT rowid, title, summary FROM episodes"
            )
            self.db.commit()
            return self.db.execute(
                "SELECT COUNT(*) FROM episodes_fts"
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
    ) -> List[StoredFact]:
        """Fallback LIKE-based search when FTS5 returns no results."""
        where = ""
        params: tuple = ()
        if domain:
            where = "AND domain = ?"
            params = (domain,)

        like_params = (f"%{query}%", f"%{query}%", f"%{query}%")
        rows = self.db.execute(
            f"""
            SELECT * FROM facts
            WHERE (content LIKE ? OR title LIKE ? OR tags LIKE ?) {where}
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
            except Exception:
                result["skipped"] += 1

        return result

    # ── helpers ─────────────────────────────────────────────────────────

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

    def _find_fuzzy_duplicate(self, content: str, threshold: float = 0.8) -> Optional[str]:
        """Find an existing fact with Jaccard similarity >= threshold.

        Uses FTS pre-filter to avoid scanning all facts. Falls back to
        last-200 scan if FTS returns no candidates (very short content).

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

        # Build FTS query: OR of token prefixes
        fts_terms = " OR ".join(f'content:"{t}"*' for t in tokens[:10])  # Cap at 10 tokens
        try:
            rows = self.db.execute(
                """
                SELECT f.id, f.content FROM facts_fts
                JOIN facts f ON facts_fts.rowid = f.rowid
                WHERE facts_fts MATCH ?
                LIMIT 50
                """,
                (fts_terms,),
            ).fetchall()
        except Exception:
            # FTS query failed; fall back to recent scan
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
