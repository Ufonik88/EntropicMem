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
        """Full-text search over stored facts."""
        clean = query.replace('"', '""')
        fts_query = f'content: "{clean}"* OR title: "{clean}"* OR tags: "{clean}"*'

        where = ""
        params: tuple = ()
        if domain:
            where = "AND facts_fts.domain = ?"
            params = (domain,)

        rows = self.db.execute(
            f"""SELECT f.* FROM facts_fts
            JOIN facts f ON facts_fts.rowid = f.rowid
            WHERE facts_fts MATCH ? {where}
            ORDER BY f.importance DESC, rank
            LIMIT ?""",
            (fts_query, *params, top_k),
        ).fetchall()

        return [self._row_to_fact(r) for r in rows]

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
