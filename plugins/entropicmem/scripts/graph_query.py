"""
graph_query.py — Wikilink graph extraction and query layer for EntropicMem (Phase 10).

Works against the ONE unified `graph_edges` table — the same table the vault
index maintains in index.db and the triple sync maintains in memory.db — so
graph traversal reads real production edges instead of the legacy `links`
table that was never populated outside tests. Enables:
  - Graph traversal: find all notes connected to a target
  - Graph-aware recall: expand search results with linked context

Node ids are whatever the edge writer stored (note_ids in index.db). When a
`notes_meta` table is present, titles resolve to note_ids and back; without
it (e.g. memory.db) node ids are used as titles directly.

Stdlib-only. No external dependencies.
"""

import logging
import re
import sqlite3
from pathlib import Path
from typing import Dict, List, Set, Tuple

logger = logging.getLogger(__name__)

# ── schema (unified with index.py's graph_edges) ────────────────────────────

GRAPH_EDGE_SCHEMA = """
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
"""


def init_graph_schema(db: sqlite3.Connection) -> None:
    """Create the unified graph_edges table if it doesn't exist."""
    db.executescript(GRAPH_EDGE_SCHEMA)
    db.commit()


def init_links_schema(db: sqlite3.Connection) -> None:
    """Deprecated alias for init_graph_schema().

    The legacy `links` table is gone (it was never populated in production);
    edges live in graph_edges now. Kept so existing callers keep working.
    """
    init_graph_schema(db)


# ── extraction ──────────────────────────────────────────────────────────────

_WIKILINK_RE = re.compile(r"\[\[([^\]|]+?)(?:\|[^\]]+)?\]\]")


def extract_wikilinks(text: str) -> List[str]:
    """Extract all [[wikilink]] targets from text."""
    return _WIKILINK_RE.findall(text)


def extract_links_with_context(text: str) -> List[Tuple[str, str]]:
    """Extract wikilinks with surrounding context (±40 chars)."""
    results = []
    for m in _WIKILINK_RE.finditer(text):
        target = m.group(1)
        start = max(0, m.start() - 40)
        end = min(len(text), m.end() + 40)
        context = text[start:end].replace("\n", " ").strip()
        results.append((target, context))
    return results


# ── node/title resolution ───────────────────────────────────────────────────


def _has_table(db: sqlite3.Connection, name: str) -> bool:
    """True when `name` exists on this connection (schema probe)."""
    try:
        row = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
    except sqlite3.Error:
        return False
    return row is not None


def _node_ids_for(db: sqlite3.Connection, name: str) -> Set[str]:
    """All graph node ids a human name (title, note id, or note path) can refer to."""
    ids: Set[str] = {name}
    # Path-style callers ("Finance/Budget.md") also refer to the note's title.
    stem = Path(name).stem
    if stem and stem != name:
        ids.add(stem)
    if _has_table(db, "notes_meta"):
        try:
            rows = db.execute(
                "SELECT note_id FROM notes_meta WHERE title = ? OR note_id = ? OR path = ?",
                (name, name, name),
            ).fetchall()
        except sqlite3.Error as exc:
            logger.warning("notes_meta lookup failed for %r: %s", name, exc)
            rows = []
        ids.update(row[0] for row in rows)
    return ids


def _title_for(db: sqlite3.Connection, node_id: str) -> str:
    """Display title for a node id (falls back to the id itself)."""
    if _has_table(db, "notes_meta"):
        try:
            row = db.execute(
                "SELECT title FROM notes_meta WHERE note_id = ?", (node_id,)
            ).fetchone()
        except sqlite3.Error as exc:
            logger.warning("notes_meta lookup failed for %r: %s", node_id, exc)
            row = None
        if row and row[0]:
            return row[0]
    return node_id


# ── storage ─────────────────────────────────────────────────────────────────

def store_links(
    db: sqlite3.Connection,
    source_path: str,
    source_title: str,
    links: List[Tuple[str, str]],
) -> int:
    """Store extracted links for a note as graph_edges rows (kind='wikilink').

    The source node is the note title (falling back to its path) and each
    target node is the link target title. `context` is accepted for API
    compatibility but not stored (graph_edges has no context column).
    Duplicate edges are ignored. Returns count of newly created edges.
    """
    source_id = source_title or source_path
    count = 0
    for target, _context in links:
        if not target or target == source_id:
            continue
        cur = db.execute(
            "INSERT OR IGNORE INTO graph_edges (source_id, target_id, kind) "
            "VALUES (?, ?, 'wikilink')",
            (source_id, target),
        )
        count += cur.rowcount
    db.commit()
    return count


def delete_links_for_note(db: sqlite3.Connection, source_path: str) -> None:
    """Remove all wikilink edges from a note (used on note deletion/update)."""
    source_ids = _node_ids_for(db, source_path)
    if _has_table(db, "notes_meta"):
        try:
            rows = db.execute(
                "SELECT note_id FROM notes_meta WHERE path = ?", (source_path,)
            ).fetchall()
            source_ids.update(row[0] for row in rows)
        except sqlite3.Error as exc:
            logger.warning("notes_meta path lookup failed for %r: %s", source_path, exc)
    for sid in source_ids:
        db.execute(
            "DELETE FROM graph_edges WHERE source_id = ? AND kind = 'wikilink'",
            (sid,),
        )
    db.commit()


# ── queries ─────────────────────────────────────────────────────────────────

def get_outgoing_links(db: sqlite3.Connection, source_path: str) -> List[Dict]:
    """Get all links FROM a note (accepts a title or a note id/path).

    Reads every edge kind (wikilinks and synced triple edges are all real
    connections); only writes are wikilink-scoped.
    """
    if not _has_table(db, "graph_edges"):
        return []
    out: List[Dict] = []
    seen: Set[str] = set()
    for sid in _node_ids_for(db, source_path):
        rows = db.execute(
            "SELECT target_id FROM graph_edges WHERE source_id = ?",
            (sid,),
        ).fetchall()
        for row in rows:
            target_id = row[0]
            if target_id in seen:
                continue
            seen.add(target_id)
            out.append({
                "target": _title_for(db, target_id),
                "target_id": target_id,
                "context": "",  # not stored on graph_edges
            })
    return out


def get_incoming_links(db: sqlite3.Connection, target_title: str) -> List[Dict]:
    """Get all links TO a note (backlinks; accepts a title or a note id)."""
    if not _has_table(db, "graph_edges"):
        return []
    out: List[Dict] = []
    seen: Set[str] = set()
    for tid in _node_ids_for(db, target_title):
        rows = db.execute(
            "SELECT source_id FROM graph_edges WHERE target_id = ?",
            (tid,),
        ).fetchall()
        for row in rows:
            source_id = row[0]
            if source_id in seen:
                continue
            seen.add(source_id)
            out.append({
                "source_path": source_id if not _has_table(db, "notes_meta") else "",
                "source_title": _title_for(db, source_id),
                "source_id": source_id,
                "context": "",  # not stored on graph_edges
            })
    return out


def get_connected_notes(
    db: sqlite3.Connection,
    title: str,
    depth: int = 1,
) -> Dict[str, Set[str]]:
    """
    Find all notes connected to a target within N hops over graph_edges.

    Returns {"outgoing": set(), "incoming": set(), "all": set()} of titles
    (node ids when no notes_meta is present). A database without a
    graph_edges table yields empty sets — never an exception.
    """
    empty = {"outgoing": set(), "incoming": set(), "all": set()}
    if not _has_table(db, "graph_edges"):
        return empty

    outgoing: Set[str] = set()
    incoming: Set[str] = set()
    seed_ids = _node_ids_for(db, title)
    visited: Set[str] = set(seed_ids)
    frontier: Set[str] = set(seed_ids)

    try:
        for _ in range(depth):
            next_frontier: Set[str] = set()
            for node in frontier:
                # Outgoing
                rows = db.execute(
                    "SELECT target_id FROM graph_edges WHERE source_id = ?", (node,)
                ).fetchall()
                for (target,) in rows:
                    if target not in visited:
                        outgoing.add(target)
                        next_frontier.add(target)
                        visited.add(target)

                # Incoming
                rows = db.execute(
                    "SELECT source_id FROM graph_edges WHERE target_id = ?", (node,)
                ).fetchall()
                for (source,) in rows:
                    if source not in visited:
                        incoming.add(source)
                        next_frontier.add(source)
                        visited.add(source)

            frontier = next_frontier
    except sqlite3.OperationalError as exc:
        logger.warning("graph traversal failed for %r: %s", title, exc)
        return empty

    out_titles = {_title_for(db, n) for n in outgoing} - {title}
    in_titles = {_title_for(db, n) for n in incoming} - {title}
    return {
        "outgoing": out_titles,
        "incoming": in_titles,
        "all": out_titles | in_titles,
    }


def graph_stats(db: sqlite3.Connection) -> Dict:
    """Report link graph statistics over graph_edges (all edge kinds)."""
    if not _has_table(db, "graph_edges"):
        return {"total_links": 0, "unique_sources": 0, "unique_targets": 0}
    total_links = db.execute("SELECT COUNT(*) FROM graph_edges").fetchone()[0]
    unique_sources = db.execute(
        "SELECT COUNT(DISTINCT source_id) FROM graph_edges"
    ).fetchone()[0]
    unique_targets = db.execute(
        "SELECT COUNT(DISTINCT target_id) FROM graph_edges"
    ).fetchone()[0]
    return {
        "total_links": total_links,
        "unique_sources": unique_sources,
        "unique_targets": unique_targets,
    }
