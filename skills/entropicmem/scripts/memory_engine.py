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
import math
import re
import fcntl
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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

    def remember(
        self,
        content: str,
        title: str = "",
        source: str = "agent",
        importance: float = 0.5,
        domain: str = "Knowledge",
        tags: Optional[List[str]] = None,
        session_id: str = "",
    ) -> str:
        """
        Store a durable fact. Returns the entropic_id.
        Deduplicates: if a fact with the same content hash exists, updates it.
        """
        self._acquire_write_lock()
        eid = StoredFact.make_id(content)
        tags_str = ", ".join(tags) if tags else ""
        now = datetime.now(timezone.utc).isoformat()

        existing = self.db.execute(
            "SELECT id FROM facts WHERE id = ?", (eid,)
        ).fetchone()

        if existing:
            self.db.execute(
                """UPDATE facts SET content=?, title=?, importance=?, domain=?,
                   tags=?, session_id=?, updated_at=?
                   WHERE id=?""",
                (content, title or self._make_title(content), importance,
                 domain, tags_str, session_id, now, eid),
            )
        else:
            # I1: Fuzzy deduplication — check for near-duplicate content
            fuzzy_id = self._find_fuzzy_duplicate(content)
            if fuzzy_id and fuzzy_id != eid:
                # Update the existing near-duplicate instead of creating a new fact
                self.db.execute(
                    """UPDATE facts SET content=?, title=?, importance=?, domain=?,
                       tags=?, session_id=?, updated_at=?
                       WHERE id=?""",
                    (content, title or self._make_title(content), importance,
                     domain, tags_str, session_id, now, fuzzy_id),
                )
                eid = fuzzy_id  # Return the existing fact's ID
            else:
                self.db.execute(
                    """INSERT INTO facts (id, content, title, source, importance, domain,
                       tags, session_id, created_at, updated_at, last_accessed)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (eid, content, title or self._make_title(content),
                     source, importance, domain, tags_str, session_id, now, now, now),
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
        self._release_write_lock()
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
            src = sqlite3.connect(str(self.db_path))
            dst = sqlite3.connect(str(backup_path))
            src.backup(dst)
            dst.close()
            src.close()
            return backup_path
        finally:
            self._release_write_lock()

    def forget(self, entropic_id: str) -> bool:
        """Delete a fact by entropic_id. Returns True if found and deleted."""
        self._acquire_write_lock()
        # I4: Auto-backup before destructive operation
        self._backup()
        # Get rowid before deleting from facts
        row = self.db.execute("SELECT rowid FROM facts WHERE id = ?", (entropic_id,)).fetchone()
        self.db.execute("DELETE FROM facts WHERE id = ?", (entropic_id,))
        if row:
            self.db.execute("DELETE FROM facts_fts WHERE rowid = ?", (row[0],))
        self.db.commit()
        self._release_write_lock()
        return row is not None

    def consolidate(self, max_age_days: int = 90, min_access_count: int = 0) -> dict:
        """Archive old, low-value facts (I3: memory consolidation).

        Facts older than max_age_days with access_count <= min_access_count
        are moved to an archive table. Returns stats.
        """
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

        cutoff = datetime.now(timezone.utc).timestamp() - (max_age_days * 86400)
        cutoff_iso = datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat()

        # Find candidates
        candidates = self.db.execute(
            """SELECT id FROM facts
               WHERE created_at < ? AND access_count <= ?""",
            (cutoff_iso, min_access_count),
        ).fetchall()

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
        return {"archived": archived, "cutoff_days": max_age_days}

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
        """
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

        # Exact-match boost
        exact_params = (query, StoredFact.make_id(query))
        if domain:
            exact_params = (*exact_params, domain)
        exact_rows = self.db.execute(
            f"""
            SELECT * FROM facts
            WHERE (content = ? OR id = ?) {("AND domain = ?" if domain else "")}
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
            WHERE facts_fts MATCH ? {where}
            ORDER BY f.importance DESC, rank
            LIMIT ?
            """,
            (fts_query, *params, top_k),
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
            like_where = "WHERE f.content LIKE ? OR f.title LIKE ? OR f.tags LIKE ? AND f.domain = ?"
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

                # Check not already stored
                eid = StoredFact.make_id(content)
                if self.get_fact(eid):
                    continue

                # Store — use raw content, don't transform (dedup works by hash)
                stored_id = self.remember(
                    content=content,
                    source=source,
                    importance=importance,
                    domain=domain,
                    tags=[tag],
                    session_id=session_id,
                )

                extracted.append({
                    "id": stored_id,
                    "content": content,
                    "domain": domain,
                    "importance": importance,
                    "tag": tag,
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

                stored_id = self.remember(
                    content=content,
                    source=source,
                    importance=importance,
                    domain=domain,
                    tags=["preference"],
                    session_id=session_id,
                )
                extracted.append({
                    "id": stored_id,
                    "content": content,
                    "domain": domain,
                    "importance": importance,
                    "tag": "preference",
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

    def recall_with_relevance(
        self,
        query: str,
        top_k: int = 10,
        domain: Optional[str] = None,
        min_relevance: float = 0.0,
        decay_enabled: bool = True,
        decay_half_life_days: float = 30.0,
        reinforcement_boost: float = 0.1,
    ) -> List[StoredFact]:
        """Full-text search with relevance scoring and temporal decay.

        Returns facts ranked by combined relevance + decay score.
        Uses FTS5 bm25() ranking normalized to 0-1 scale.
        Applies exponential temporal decay to older, unreinforced facts.
        Auto-reinforces returned facts.
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

        # Auto-reinforce returned facts
        for fact in results[:top_k]:
            self.reinforce(fact.id)

        return results[:top_k]

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
        first_line = content.split("\n")[0].strip()
        if len(first_line) > max_len:
            first_line = first_line[:max_len - 3] + "..."
        slug = first_line.lower().strip()
        slug = re.sub(r"[^a-z0-9\s-]", "", slug)
        slug = re.sub(r"\s+", "-", slug)
        return slug[:80] or "fact"

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

        Returns the entropic_id of the duplicate, or None.
        """
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
        return StoredFact(
            id=row["id"],
            content=row["content"],
            title=row["title"] or "",
            source=row["source"] or "agent",
            importance=row["importance"] or 0.5,
            domain=row["domain"] or "Knowledge",
            tags=tags,
            created_at=row["created_at"] or "",
            updated_at=row["updated_at"] or "",
            last_accessed=row["last_accessed"] or "",
            access_count=row["access_count"] or 0,
        )
