"""
graph_query.py — Wikilink graph extraction and query layer for EntropicMem (Phase 10).

Extracts [[wikilinks]] from vault notes into a `links` table, enabling:
  - Graph traversal: find all notes connected to a target
  - Graph-aware recall: expand search results with linked context

Stdlib-only. No external dependencies.
"""

import re
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


# ── schema ──────────────────────────────────────────────────────────────────

LINKS_SCHEMA = """
CREATE TABLE IF NOT EXISTS links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_path TEXT NOT NULL,
    source_title TEXT NOT NULL,
    target_title TEXT NOT NULL,
    context TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_path, target_title)
);

CREATE INDEX IF NOT EXISTS idx_links_source ON links(source_path);
CREATE INDEX IF NOT EXISTS idx_links_target ON links(target_title);
"""


def init_links_schema(db: sqlite3.Connection) -> None:
    """Create the links table if it doesn't exist."""
    db.executescript(LINKS_SCHEMA)
    db.commit()


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


# ── storage ─────────────────────────────────────────────────────────────────

def store_links(
    db: sqlite3.Connection,
    source_path: str,
    source_title: str,
    links: List[Tuple[str, str]],
) -> int:
    """Store extracted links for a note. Returns count of new links."""
    count = 0
    for target, context in links:
        try:
            db.execute(
                """INSERT OR IGNORE INTO links (source_path, source_title, target_title, context)
                   VALUES (?, ?, ?, ?)""",
                (source_path, source_title, target, context),
            )
            count += db.total_changes
        except sqlite3.IntegrityError:
            pass
    db.commit()
    return count


def delete_links_for_note(db: sqlite3.Connection, source_path: str) -> None:
    """Remove all links from a note (used on note deletion/update)."""
    db.execute("DELETE FROM links WHERE source_path = ?", (source_path,))
    db.commit()


# ── queries ─────────────────────────────────────────────────────────────────

def get_outgoing_links(db: sqlite3.Connection, source_path: str) -> List[Dict]:
    """Get all links FROM a note."""
    rows = db.execute(
        "SELECT target_title, context FROM links WHERE source_path = ?",
        (source_path,),
    ).fetchall()
    return [{"target": r[0], "context": r[1]} for r in rows]


def get_incoming_links(db: sqlite3.Connection, target_title: str) -> List[Dict]:
    """Get all links TO a note (backlinks)."""
    rows = db.execute(
        "SELECT source_path, source_title, context FROM links WHERE target_title = ?",
        (target_title,),
    ).fetchall()
    return [{"source_path": r[0], "source_title": r[1], "context": r[2]} for r in rows]


def get_connected_notes(
    db: sqlite3.Connection,
    title: str,
    depth: int = 1,
) -> Dict[str, Set[str]]:
    """
    Find all notes connected to a target within N hops.

    Returns {"outgoing": set(), "incoming": set(), "all": set()}.
    """
    outgoing: Set[str] = set()
    incoming: Set[str] = set()
    visited: Set[str] = {title}
    frontier: Set[str] = {title}

    for _ in range(depth):
        next_frontier: Set[str] = set()
        for node in frontier:
            # Outgoing
            rows = db.execute(
                "SELECT target_title FROM links WHERE source_title = ?",
                (node,),
            ).fetchall()
            for (target,) in rows:
                if target not in visited:
                    outgoing.add(target)
                    next_frontier.add(target)
                    visited.add(target)

            # Incoming
            rows = db.execute(
                "SELECT source_title FROM links WHERE target_title = ?",
                (node,),
            ).fetchall()
            for (source,) in rows:
                if source not in visited:
                    incoming.add(source)
                    next_frontier.add(source)
                    visited.add(source)

        frontier = next_frontier

    return {
        "outgoing": outgoing,
        "incoming": incoming,
        "all": outgoing | incoming,
    }


def graph_stats(db: sqlite3.Connection) -> Dict:
    """Report link graph statistics."""
    total_links = db.execute("SELECT COUNT(*) FROM links").fetchone()[0]
    unique_sources = db.execute("SELECT COUNT(DISTINCT source_path) FROM links").fetchone()[0]
    unique_targets = db.execute("SELECT COUNT(DISTINCT target_title) FROM links").fetchone()[0]
    return {
        "total_links": total_links,
        "unique_sources": unique_sources,
        "unique_targets": unique_targets,
    }


# ── vault integration ───────────────────────────────────────────────────────

def rebuild_link_graph(db: sqlite3.Connection, vault) -> Dict:
    """
    Rebuild the entire link graph from vault notes.

    Args:
        db: SQLite connection with links table
        vault: Vault instance with list_notes() and read_note()

    Returns:
        {"notes_processed": int, "links_extracted": int}
    """
    init_links_schema(db)
    db.execute("DELETE FROM links")

    notes_processed = 0
    links_extracted = 0

    for rel_path in vault.list_notes(include_archive=False):
        try:
            note = vault.read_note(rel_path)
            links = extract_links_with_context(note.body)
            if links:
                store_links(db, str(rel_path), note.title, links)
                links_extracted += len(links)
            notes_processed += 1
        except Exception:
            continue

    db.commit()
    return {"notes_processed": notes_processed, "links_extracted": links_extracted}
