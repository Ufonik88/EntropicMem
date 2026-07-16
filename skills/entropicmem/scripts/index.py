"""
index.py — SQLite FTS5 index + graph edges for EntropicMem.

Builds and queries a full-text search index over the vault, tracks
wikilink relationships, and feeds the graph visualizer with edges.

Stdlib-only (sqlite3).
"""

import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from vault import Note, Vault


# ── FTS schema ──────────────────────────────────────────────────────────────

FTS5_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
    note_id UNINDEXED,
    title,
    tags,
    body,
    domain,
    note_type,
    source,
    importance UNINDEXED,
    tokenize='porter unicode61'
);

CREATE TABLE IF NOT EXISTS notes_meta (
    note_id TEXT PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    domain TEXT DEFAULT '',
    note_type TEXT DEFAULT 'permanent',
    importance REAL DEFAULT 0.3,
    tags TEXT DEFAULT '',
    source TEXT DEFAULT '',
    source_url TEXT DEFAULT '',
    created TEXT DEFAULT '',
    updated TEXT DEFAULT '',
    agent INTEGER DEFAULT 0,
    entropic_id TEXT DEFAULT '',
    body_preview TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS graph_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    weight INTEGER DEFAULT 1,
    kind TEXT DEFAULT 'wikilink',
    UNIQUE(source_id, target_id, kind)
);

CREATE INDEX IF NOT EXISTS idx_edges_source ON graph_edges(source_id);
CREATE INDEX IF NOT EXISTS idx_edges_target ON graph_edges(target_id);
CREATE INDEX IF NOT EXISTS idx_meta_domain ON notes_meta(domain);
CREATE INDEX IF NOT EXISTS idx_meta_type ON notes_meta(note_type);
CREATE INDEX IF NOT EXISTS idx_meta_importance ON notes_meta(importance DESC);
"""


# ── data classes ────────────────────────────────────────────────────────────

@dataclass
class SearchHit:
    """A single FTS search result."""
    note_id: str
    path: str
    title: str
    domain: str = ""
    note_type: str = "permanent"
    importance: float = 0.3
    tags: List[str] = field(default_factory=list)
    snippet: str = ""          # FTS5 highlight snippet
    rank: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "note_id": self.note_id,
            "path": self.path,
            "title": self.title,
            "domain": self.domain,
            "note_type": self.note_type,
            "importance": self.importance,
            "tags": self.tags,
            "snippet": self.snippet,
            "rank": self.rank,
        }


@dataclass
class GraphEdge:
    """A link between two notes."""
    source_id: str
    target_id: str
    weight: int = 1
    kind: str = "wikilink"


# ── index class ─────────────────────────────────────────────────────────────

class VaultIndex:
    """SQLite FTS5 index over an EntropicMem vault."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path).resolve()
        self.db = sqlite3.connect(str(self.db_path))
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def _init_schema(self) -> None:
        """Create tables if they don't exist."""
        self.db.executescript(FTS5_SCHEMA)
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    # ── CRUD ────────────────────────────────────────────────────────────

    def rebuild(self, vault: Vault, include_archive: bool = False) -> int:
        """Full rebuild: drop all data and reindex every note in the vault."""
        self.db.execute("DELETE FROM notes_fts")
        self.db.execute("DELETE FROM notes_meta")
        self.db.execute("DELETE FROM graph_edges")

        count = 0
        for rel in vault.list_notes(include_archive=include_archive):
            note = vault.read_note(rel)
            self.upsert_note(note)
            count += 1

        # Phase 2: build graph edges after all notes are indexed
        self._rebuild_edges(vault)

        self.db.commit()
        return count

    def _rebuild_edges(self, vault: Vault) -> None:
        """Scan all notes for [[wikilinks]] and rebuild graph_edges."""
        self.db.execute("DELETE FROM graph_edges")
        known_titles: Dict[str, str] = {}  # title → note_id
        for row in self.db.execute("SELECT note_id, title FROM notes_meta"):
            known_titles[row["title"]] = row["note_id"]

        for row in self.db.execute("SELECT note_id, path FROM notes_meta"):
            note = vault.read_note(Path(row["path"]))
            links = vault.extract_wikilinks(note.body)
            for link in links:
                target_id = known_titles.get(link)
                if target_id and target_id != row["note_id"]:
                    try:
                        self.db.execute(
                            "INSERT INTO graph_edges (source_id, target_id, kind) VALUES (?, ?, 'wikilink')",
                            (row["note_id"], target_id),
                        )
                    except sqlite3.IntegrityError:
                        # duplicate edge — increment weight
                        self.db.execute(
                            "UPDATE graph_edges SET weight = weight + 1 WHERE source_id = ? AND target_id = ?",
                            (row["note_id"], target_id),
                        )

    def upsert_note(self, note: Note) -> None:
        """Insert or update a note in the index."""
        note_id = note.note_id
        path_str = str(note.path)

        # Upsert metadata
        self.db.execute(
            """INSERT INTO notes_meta (note_id, path, title, domain, note_type,
               importance, tags, source, source_url, created, updated, agent,
               entropic_id, body_preview)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(note_id) DO UPDATE SET
                path=excluded.path, title=excluded.title, domain=excluded.domain,
                note_type=excluded.note_type, importance=excluded.importance,
                tags=excluded.tags, source=excluded.source, source_url=excluded.source_url,
                created=excluded.created, updated=excluded.updated, agent=excluded.agent,
                entropic_id=excluded.entropic_id, body_preview=excluded.body_preview""",
            (
                note_id, path_str, note.title,
                note.domain, note.note_type,
                note.importance,
                ", ".join(note.tags) if note.tags else "",
                note.source, note.source_url,
                note.created, note.updated,
                1 if note.agent else 0,
                note.entropic_id or note.compute_entropic_id(),
                note.body[:500],
            ),
        )

        # Upsert FTS
        tags_str = " ".join(note.tags) if note.tags else ""
        self.db.execute(
            "DELETE FROM notes_fts WHERE note_id = ?", (note_id,)
        )
        self.db.execute(
            """INSERT INTO notes_fts (note_id, title, tags, body, domain, note_type, source, importance)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                note_id, note.title, tags_str,
                note.body, note.domain, note.note_type,
                note.source, note.importance,
            ),
        )
        self.db.commit()

    def upsert_edges_for_note(self, vault: 'Vault', note: 'Note') -> None:
        """Extract wikilinks from a note and create graph edges."""
        note_id = note.note_id

        # Remove old edges from this source
        self.db.execute('DELETE FROM graph_edges WHERE source_id = ?', (note_id,))

        links = vault.extract_wikilinks(note.body)
        known = {}
        for row in self.db.execute('SELECT title, note_id FROM notes_meta'):
            known[row['title']] = row['note_id']

        for link in links:
            target_id = known.get(link)
            if target_id and target_id != note_id:
                try:
                    self.db.execute(
                        "INSERT INTO graph_edges (source_id, target_id, kind) VALUES (?, ?, 'wikilink')",
                        (note_id, target_id),
                    )
                except Exception:
                    self.db.execute(
                        "UPDATE graph_edges SET weight = weight + 1 WHERE source_id = ? AND target_id = ?",
                        (note_id, target_id),
                    )
        self.db.commit()

    def delete_note(self, note_id: str) -> None:
        """Remove a note from the index and its edges."""
        self.db.execute("DELETE FROM notes_fts WHERE note_id = ?", (note_id,))
        self.db.execute("DELETE FROM notes_meta WHERE note_id = ?", (note_id,))
        self.db.execute(
            "DELETE FROM graph_edges WHERE source_id = ? OR target_id = ?",
            (note_id, note_id),
        )
        self.db.commit()

    def get_note(self, note_id: str) -> Optional[dict]:
        """Retrieve note metadata by note_id."""
        row = self.db.execute(
            "SELECT * FROM notes_meta WHERE note_id = ?", (note_id,)
        ).fetchone()
        return dict(row) if row else None

    # ── search ──────────────────────────────────────────────────────────

    def search_fts(
        self, query: str, top_k: int = 10, domain: Optional[str] = None
    ) -> List[SearchHit]:
        """
        Full-text search over title, tags, and body using FTS5.
        Returns ranked results with highlight snippets.
        """
        # Sanitize query for FTS5: escape double quotes only
        clean_query = query.replace('"', '""')
        # Build FTS5 query string with parameterized values
        fts_query = f'title: "{clean_query}"* OR tags: "{clean_query}"* OR body: "{clean_query}"*'

        where = ""
        params: tuple = ()
        if domain:
            where = "AND notes_meta.domain = ?"
            params = (domain,)

        rows = self.db.execute(
            f"""SELECT
                notes_fts.note_id,
                notes_fts.title,
                notes_fts.domain,
                notes_fts.note_type,
                notes_fts.importance,
                notes_fts.tags,
                snippet(notes_fts, 4, '[HL]', '[/HL]', '...', 32) AS snippet,
                rank
            FROM notes_fts
            JOIN notes_meta ON notes_fts.note_id = notes_meta.note_id
            WHERE notes_fts MATCH ? {where}
            ORDER BY rank
            LIMIT ?""",
            (fts_query, *params, top_k),
        ).fetchall()

        hits = []
        for row in rows:
            tags = [t.strip() for t in (row["tags"] or "").split(",") if t.strip()]
            meta_row = self.db.execute(
                "SELECT path FROM notes_meta WHERE note_id = ?", (row["note_id"],)
            ).fetchone()
            path = meta_row["path"] if meta_row else ""
            hits.append(SearchHit(
                note_id=row["note_id"],
                path=path,
                title=row["title"],
                domain=row["domain"] or "",
                note_type=row["note_type"] or "permanent",
                importance=row["importance"] or 0.3,
                tags=tags,
                snippet=(row["snippet"] or "").replace("[HL]", "**").replace("[/HL]", "**"),
                rank=float(row["rank"]) if row["rank"] else 0.0,
            ))
        return hits

    def search_by_title(self, title: str) -> List[SearchHit]:
        """Exact or prefix title search (for link resolution)."""
        rows = self.db.execute(
            """SELECT note_id, title, domain, note_type, importance, tags, path, body_preview
            FROM notes_meta WHERE title LIKE ? LIMIT 10""",
            (f"%{title}%",),
        ).fetchall()
        hits = []
        for row in rows:
            tags = [t.strip() for t in (row["tags"] or "").split(",") if t.strip()]
            hits.append(SearchHit(
                note_id=row["note_id"],
                path=row["path"] or "",
                title=row["title"],
                domain=row["domain"] or "",
                note_type=row["note_type"] or "permanent",
                importance=row["importance"] or 0.3,
                tags=tags,
                snippet=(row["body_preview"] or "")[:200],
            ))
        return hits

    # ── backlinks ───────────────────────────────────────────────────────

    def get_backlinks(self, note_id: str) -> List[str]:
        """Find notes that link to the given note_id via wikilinks."""
        rows = self.db.execute(
            """SELECT DISTINCT e.source_id
            FROM graph_edges e
            WHERE e.target_id = ?
            ORDER BY e.weight DESC
            LIMIT 50""",
            (note_id,),
        ).fetchall()
        return [r["source_id"] for r in rows]

    def get_outlinks(self, note_id: str) -> List[str]:
        """Find notes that the given note links to."""
        rows = self.db.execute(
            """SELECT DISTINCT e.target_id
            FROM graph_edges e
            WHERE e.source_id = ?
            ORDER BY e.weight DESC
            LIMIT 50""",
            (note_id,),
        ).fetchall()
        return [r["target_id"] for r in rows]

    # ── graph ───────────────────────────────────────────────────────────

    def get_graph_edges(
        self,
        domain: Optional[str] = None,
        min_weight: int = 1,
    ) -> List[GraphEdge]:
        """Return all graph edges, optionally filtered by domain."""
        if domain:
            rows = self.db.execute(
                """SELECT e.source_id, e.target_id, e.weight, e.kind
                FROM graph_edges e
                JOIN notes_meta m1 ON e.source_id = m1.note_id
                JOIN notes_meta m2 ON e.target_id = m2.note_id
                WHERE m1.domain = ? AND m2.domain = ? AND e.weight >= ?
                ORDER BY e.weight DESC""",
                (domain, domain, min_weight),
            ).fetchall()
        else:
            rows = self.db.execute(
                """SELECT source_id, target_id, weight, kind
                FROM graph_edges WHERE weight >= ?
                ORDER BY weight DESC""",
                (min_weight,),
            ).fetchall()
        return [GraphEdge(r["source_id"], r["target_id"], r["weight"], r["kind"]) for r in rows]

    def get_graph_nodes(
        self,
        domain: Optional[str] = None,
        min_importance: float = 0.0,
        max_nodes: int = 500,
    ) -> List[dict]:
        """Return nodes for graph visualization."""
        where = "WHERE importance >= ?"
        params: tuple = (min_importance,)
        if domain:
            where += " AND domain = ?"
            params = (min_importance, domain)

        rows = self.db.execute(
            f"""SELECT note_id, title, domain, note_type, importance, tags, path
            FROM notes_meta {where}
            ORDER BY importance DESC
            LIMIT ?""",
            (*params, max_nodes),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── stats ───────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Return index statistics."""
        note_count = self.db.execute(
            "SELECT COUNT(*) as cnt FROM notes_meta"
        ).fetchone()["cnt"]
        edge_count = self.db.execute(
            "SELECT COUNT(*) as cnt FROM graph_edges"
        ).fetchone()["cnt"]
        domains = self.db.execute(
            "SELECT domain, COUNT(*) as cnt FROM notes_meta WHERE domain != '' GROUP BY domain ORDER BY cnt DESC"
        ).fetchall()
        return {
            "note_count": note_count,
            "edge_count": edge_count,
            "db_path": str(self.db_path),
            "domains": {r["domain"]: r["cnt"] for r in domains},
        }
