"""
memory_engine.py — Standalone SQLite memory engine for EntropicMem.

Provides:
  - Durable fact storage with FTS5 search
  - Graph edges (wikilink relationships)
  - entropic_id-based deduplication and round-trip identity
  - Export to vault as Markdown projection (optional)

Stdlib-only. No external memory dependencies.
"""

import hashlib
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

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
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
    relevance_score: float = 0.0  # FTS5 rank-based relevance (0-1)

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
        self.db = sqlite3.connect(str(self.db_path))
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self) -> None:
        self.db.executescript(MEMORY_SCHEMA)
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    # ── CRUD ────────────────────────────────────────────────────────────

    def remember(
        self,
        content: str,
        title: str = "",
        source: str = "agent",
        importance: float = 0.5,
        domain: str = "Knowledge",
        tags: Optional[List[str]] = None,
    ) -> str:
        """
        Store a durable fact. Returns the entropic_id.
        Deduplicates: if a fact with the same content hash exists, updates it.
        """
        eid = StoredFact.make_id(content)
        tags_str = ", ".join(tags) if tags else ""
        now = datetime.now(timezone.utc).isoformat()

        existing = self.db.execute(
            "SELECT id FROM facts WHERE id = ?", (eid,)
        ).fetchone()

        if existing:
            self.db.execute(
                """UPDATE facts SET content=?, title=?, importance=?, domain=?,
                   tags=?, updated_at=?
                   WHERE id=?""",
                (content, title or self._make_title(content), importance,
                 domain, tags_str, now, eid),
            )
        else:
            self.db.execute(
                """INSERT INTO facts (id, content, title, source, importance, domain,
                   tags, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (eid, content, title or self._make_title(content),
                 source, importance, domain, tags_str, now, now),
            )

        # Upsert FTS (FTS5 uses content-addressable rowid; delete by matching content)
        self.db.execute("DELETE FROM facts_fts WHERE facts_fts MATCH ?", (eid,))
        self.db.execute(
            "INSERT INTO facts_fts (content, title, tags, domain) VALUES (?, ?, ?, ?)",
            (content, title or "", tags_str, domain),
        )
        self.db.commit()
        return eid

    def forget(self, entropic_id: str) -> bool:
        """Delete a fact by entropic_id. Returns True if found and deleted."""
        self.db.execute("DELETE FROM facts WHERE id = ?", (entropic_id,))
        # FTS5 rowid = facts rowid; delete by matching content hash via join isn't needed
        # since the facts_fts content matches exactly; just delete the facts row
        pass
        self.db.commit()
        return self.db.execute("SELECT changes()").fetchone()[0] > 0

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

        This matters for migration parity: every written fact must be
        recallable by its own content.
        """
        # Sanitize query for FTS5: escape double quotes only
        clean = query.replace('"', '""')
        # Use parameterized FTS query — do NOT interpolate query into the MATCH string
        fts_query = f'content: "{clean}"* OR title: "{clean}"* OR tags: "{clean}"*'

        where = ""
        params: tuple = ()
        if domain:
            where = "AND facts_fts.domain = ?"
            params = (domain,)

        # ── Exact-match boost: content or id equals query ──────────────
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

        # FTS5 MATCH with parameterized query
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
            # de-dup exact from FTS results, keep exact first
            seen = {f.id for f in exact}
            combined = exact + [f for f in fts_hits if f.id not in seen]
            return combined[:top_k]

        # ── LIKE fallback for non-token-aligned queries ───────────────
        # Use parameterized LIKE, not string interpolation
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
        import re
        slug = first_line.lower().strip()
        slug = re.sub(r"[^a-z0-9\s-]", "", slug)
        slug = re.sub(r"\s+", "-", slug)
        return slug[:80] or "fact"

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
        )

    def recall_with_relevance(
        self,
        query: str,
        top_k: int = 10,
        domain: Optional[str] = None,
        min_relevance: float = 0.0,
    ) -> List[StoredFact]:
        """Full-text search with relevance scoring.

        Returns facts ranked by relevance score. Uses FTS5 bm25() ranking
        normalized to 0-1 scale. Filters by minimum relevance threshold.

        Args:
            query: Search query
            top_k: Maximum results to return
            domain: Optional domain filter
            min_relevance: Minimum relevance score (0-1) to include
        """
        if not query.strip():
            return []

        # Sanitize query for FTS5
        clean = query.replace('"', '""')

        # Split query into words for better matching
        words = clean.split()
        if len(words) > 1:
            # Build OR query for each word
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
        # bm25() returns negative scores (lower = more relevant)
        # We normalize to 0-1 where 1 = most relevant
        rows = self.db.execute(
            f"""
            SELECT f.*, bm25(facts_fts) as rank
            FROM facts_fts
            JOIN facts f ON facts_fts.rowid = f.rowid
            WHERE facts_fts MATCH ? {where}
            ORDER BY rank
            LIMIT ?
            """,
            (fts_query, *params, top_k * 2),  # Get extra for filtering
        ).fetchall()

        if not rows:
            # Fallback to LIKE search
            return self._recall_like_fallback(query, top_k, domain, min_relevance)

        # Normalize bm25 scores to 0-1
        # bm25 returns negative values; more negative = more relevant
        ranks = [row["rank"] for row in rows]
        min_rank = min(ranks)
        max_rank = max(ranks)
        rank_range = max_rank - min_rank if max_rank != min_rank else 1.0

        results = []
        for row in rows:
            fact = self._row_to_fact(row)
            # Normalize: 0 = least relevant, 1 = most relevant
            if rank_range > 0:
                fact.relevance_score = 1.0 - ((row["rank"] - min_rank) / rank_range)
            else:
                fact.relevance_score = 1.0

            # Apply minimum relevance filter
            if fact.relevance_score >= min_relevance:
                results.append(fact)

        # Sort by relevance score (descending)
        results.sort(key=lambda f: f.relevance_score, reverse=True)
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

        # Assign relevance scores based on importance for LIKE results
        results = []
        for row in rows:
            fact = self._row_to_fact(row)
            # Use importance as a proxy for relevance when using LIKE
            fact.relevance_score = fact.importance * 0.8  # Scale down to differentiate from FTS5
            if fact.relevance_score >= min_relevance:
                results.append(fact)

        return results
