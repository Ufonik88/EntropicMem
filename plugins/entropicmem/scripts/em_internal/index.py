"""
index.py — SQLite FTS5 index + graph edges for EntropicMem.

Builds and queries a full-text search index over the vault, tracks
wikilink relationships, and feeds the graph visualizer with edges.

Stdlib-only (sqlite3).
"""

import hashlib
import logging
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from em.util.fsperm import chmod_posix
from em_internal.vault import Note, Vault, note_id_for_path

logger = logging.getLogger(__name__)

# ── shared FTS5 query building (single home: memory_engine) ─────────────────
#
# The one MATCH-expression builder for the whole codebase lives in
# memory_engine.py (which must stay self-contained for standalone copies).
# Re-exported here so vault-search callers keep one import site.

from memory_engine import (  # noqa: F401,E402 (shared FTS5 query layer)
    FTS_REASON_MATCH_ERROR,
    FTS_REASON_OK,
    MAX_FTS_TERMS,
    build_fts_query,
    escape_like,
    phrase_query,
    run_fts_match,
)

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
    body_preview TEXT DEFAULT '',
    content_hash TEXT DEFAULT '',
    mtime_ns INTEGER DEFAULT 0,
    size INTEGER DEFAULT 0
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

#: The index's schema generation, in ``PRAGMA user_version``. **Version 2**
#: (EM-602 slice 2) changed ``note_id`` from "the path with its top directory
#: dropped" to the full vault-relative path, so an older database's ids are
#: recomputed from each row's ``path`` on open. **Version 3** (EM-603) adds
#: ``mtime_ns``/``size`` so a refresh can skip a note whose ``stat`` has not
#: moved without reading or hashing it.
SCHEMA_VERSION = 3

#: The version at which the note-id rule changed; the migration below stamps it.
NOTE_ID_VERSION = 2

#: Transient prefix for the two-pass rename (a note id is a path, so it can
#: never contain a NUL). Parked ids cannot collide with the new ones.
_MIGRATING = "\x00migrating\x00"


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


def content_hash(note: Note) -> str:
    """Deterministic hash of everything the index rows depend on.

    The incremental rebuild diff uses this to detect changed notes without
    re-reading whole bodies on every comparison. Path is excluded: a path
    change produces a new note_id, which the diff sees as add + remove.
    """
    payload = "\x00".join([
        note.title,
        note.body,
        ",".join(note.tags or []),
        note.domain,
        note.note_type,
        f"{note.importance:.4f}",
        note.source,
        note.source_url or "",
        note.created or "",
        note.updated or "",
        str(bool(note.agent)),
        note.entropic_id or note.compute_entropic_id(),
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ── index class ─────────────────────────────────────────────────────────────

class VaultIndex:
    """SQLite FTS5 index over an EntropicMem vault."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path).resolve()
        self.db = sqlite3.connect(str(self.db_path), timeout=30)
        chmod_posix(self.db_path, 0o600)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def _init_schema(self) -> None:
        """Create tables if they don't exist, then run lightweight migrations."""
        self.db.executescript(FTS5_SCHEMA)
        # content_hash arrived in v2.6 (incremental rebuild diff); existing
        # databases predate the column, so add it in place.
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(notes_meta)")}
        if "content_hash" not in columns:
            self.db.execute(
                "ALTER TABLE notes_meta ADD COLUMN content_hash TEXT DEFAULT ''"
            )
        # EM-603: the stat columns the incremental refresh relies on. A v2
        # database gets them as 0, which never matches a real stat — so the
        # first refresh reads every note once to backfill, then goes quiet.
        if "mtime_ns" not in columns:
            self.db.execute(
                "ALTER TABLE notes_meta ADD COLUMN mtime_ns INTEGER DEFAULT 0"
            )
        if "size" not in columns:
            self.db.execute("ALTER TABLE notes_meta ADD COLUMN size INTEGER DEFAULT 0")
        self.db.commit()
        self._migrate_note_ids()
        self._stamp_schema_version()

    def _stamp_schema_version(self) -> None:
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version < SCHEMA_VERSION:
            self.db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            self.db.commit()

    def _migrate_note_ids(self) -> None:
        """Rewrite pre-EM-602 note ids to the vault-relative-path rule.

        The old id dropped the path's top directory, so it cannot be inverted;
        the row's own ``path`` can, and that is the rule (`note_id_for_path`).
        ``notes_meta``, ``notes_fts`` and the ``kind='wikilink'`` endpoints of
        ``graph_edges`` all carry the id, so all three move together —
        ``kind='triple:*'`` edges carry entity/triple ids and are left alone.
        Runs once per database and is a no-op on a fresh or migrated store.
        """
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version >= NOTE_ID_VERSION:
            return
        mapping = {}
        for row in self.db.execute("SELECT note_id, path FROM notes_meta").fetchall():
            new_id = note_id_for_path(row["path"])
            if new_id != row["note_id"]:
                mapping[row["note_id"]] = new_id
        if mapping:
            with self.db:
                self._rename_note_ids(mapping)
                self._rename_wikilink_endpoints(mapping)
        self.db.execute(f"PRAGMA user_version = {NOTE_ID_VERSION}")
        self.db.commit()

    def _rename_note_ids(self, mapping: Dict[str, str]) -> None:
        """Two passes, so a rename can never collide with its own primary key."""
        for old in mapping:
            for table in ("notes_meta", "notes_fts"):
                self.db.execute(
                    f"UPDATE {table} SET note_id = ? WHERE note_id = ?",
                    (_MIGRATING + old, old),
                )
        for old, new in mapping.items():
            for table in ("notes_meta", "notes_fts"):
                self.db.execute(
                    f"UPDATE {table} SET note_id = ? WHERE note_id = ?",
                    (new, _MIGRATING + old),
                )

    def _rename_wikilink_endpoints(self, mapping: Dict[str, str]) -> None:
        for old, new in mapping.items():
            self.db.execute(
                "UPDATE graph_edges SET source_id = ? WHERE source_id = ? AND kind = 'wikilink'",
                (new, old),
            )
            self.db.execute(
                "UPDATE graph_edges SET target_id = ? WHERE target_id = ? AND kind = 'wikilink'",
                (new, old),
            )

    def close(self) -> None:
        self.db.close()

    # ── CRUD ────────────────────────────────────────────────────────────

    def rebuild(self, vault: Vault, include_archive: bool = False) -> int:
        """Rebuild the index from the vault, incrementally.

        Diffs the vault against the last index state and rewrites only the
        notes that changed. Unchanged rows stay untouched, and non-wikilink
        edges (synced triples) are never wiped, so a refresh no longer
        re-creates the index.db/memory.db split-brain. Falls back to a full
        wipe-and-rebuild if the diff cannot be applied cleanly.
        """
        try:
            return self._rebuild_diff(vault, include_archive=include_archive)
        except Exception as exc:  # noqa: BLE001 - the fallback is unconditional
            print(
                f"entropicmem: incremental rebuild failed ({exc!r}); "
                "falling back to full rebuild",
                file=sys.stderr,
            )
            return self.rebuild_full(vault, include_archive=include_archive)

    def rebuild_full(self, vault: Vault, include_archive: bool = False) -> int:
        """Full rebuild: drop all data and reindex every note in the vault.

        Kept as the fallback path for the incremental diff and for callers
        that explicitly want a clean slate. Wipes graph_edges entirely, so
        triple edges must be re-synced afterwards (see the refresh wrapper
        ordering note).
        """
        self.db.execute("DELETE FROM notes_fts")
        self.db.execute("DELETE FROM notes_meta")
        self.db.execute("DELETE FROM graph_edges")

        count = 0
        for rel_text, info in vault.iter_note_stats(include_archive=include_archive):
            note = vault.read_note(Path(rel_text))
            self.upsert_note(note, stamp=(info.st_mtime_ns, info.st_size))
            count += 1

        # Phase 2: build graph edges after all notes are indexed
        self._rebuild_edges(vault)

        self.db.commit()
        return count

    def _rebuild_diff(self, vault: Vault, include_archive: bool = False) -> int:
        """Per-note diff rebuild: see rebuild() for the contract.

        EM-603: the first cut is the file's ``(st_mtime_ns, st_size)``. A note
        whose stat matches its stored row is not opened, parsed or hashed at
        all, so an unchanged vault costs one ``stat`` per note. Only a moved
        stat reads the file, and the content hash still decides whether the row
        is *changed* — a bare ``touch`` refreshes the stat columns and nothing
        else. ``rebuild_full`` is the escape hatch for a same-size, same-mtime
        rewrite, which no stat-based refresh can see.
        """
        rows: Dict[str, tuple] = {}
        for row in self.db.execute(
            "SELECT note_id, title, content_hash, mtime_ns, size FROM notes_meta"
        ):
            rows[row["note_id"]] = (
                row["title"],
                row["content_hash"] or "",
                int(row["mtime_ns"] or 0),
                int(row["size"] or 0),
            )

        added: List[Note] = []
        changed: List[Note] = []
        stamps: Dict[str, tuple] = {}
        touched: List[tuple] = []  # (note_id, (mtime_ns, size))
        renamed: List[tuple] = []  # (note_id, old_title, new_title)
        seen: set = set()
        for rel_text, info in vault.iter_note_stats(include_archive=include_archive):
            note_id = note_id_for_path(rel_text)
            seen.add(note_id)
            # The walk reports the stat it already had from the directory read,
            # and never follows a symlink, so no per-note resolve or extra stat
            # is needed here. Every caller-supplied path still goes through
            # `resolve_path`; these paths are our own walk under the resolved
            # root.
            stamp = (info.st_mtime_ns, info.st_size)
            stored = rows.get(note_id)
            if stored is not None and (stored[2], stored[3]) == stamp:
                continue  # the stat has not moved: no read, no hash
            rel = Path(rel_text)
            try:
                note = vault.read_note(rel)
            except (OSError, ValueError) as exc:
                logger.warning("index: cannot read %s: %s", rel, exc)
                continue
            stamps[note_id] = stamp
            if stored is None:
                added.append(note)
            elif content_hash(note) != stored[1]:
                changed.append(note)
                if stored[0] != note.title:
                    renamed.append((note_id, stored[0], note.title))
            else:
                touched.append((note_id, stamp))

        for note_id in sorted(nid for nid in rows if nid not in seen):
            self.delete_note(note_id)

        for note_id, (mtime_ns, size) in touched:
            self.db.execute(
                "UPDATE notes_meta SET mtime_ns = ?, size = ? WHERE note_id = ?",
                (mtime_ns, size, note_id),
            )

        # Two-phase so intra-batch cross-links resolve: all metadata first (the
        # link resolver reads titles from notes_meta), then all edges. The
        # title map is built once for the batch (per-note rescans would be
        # O(N^2) on a full-diff run).
        for note in added + changed:
            self.upsert_note(note, stamp=stamps.get(note.note_id))
        known_titles: Dict[str, str] = {}
        for row in self.db.execute("SELECT title, note_id FROM notes_meta"):
            known_titles[row["title"]] = row["note_id"]
        for note in added + changed:
            self.upsert_edges_for_note(vault, note, known_titles=known_titles)

        # A changed title map can flip whether OTHER notes' [[links]] resolve
        # (renames drop old links, additions and renames can revive dangling
        # ones). Re-extract the sources that can possibly be affected:
        # notes with live in-edges to a renamed note, plus notes whose bodies
        # mention one of the affected titles.
        rescan_titles = [note.title for note in added]
        candidates: set = set()
        for note_id, old_title, new_title in renamed:
            rescan_titles.append(old_title)
            rescan_titles.append(new_title)
            for row in self.db.execute(
                "SELECT DISTINCT source_id FROM graph_edges "
                "WHERE target_id = ? AND kind = 'wikilink'",
                (note_id,),
            ).fetchall():
                candidates.add(row["source_id"])
        candidates.update(self._fts_link_candidates(rescan_titles))
        already = {note.note_id for note in added + changed}
        for candidate_id in sorted(candidates - already):
            meta = self.get_note(candidate_id)
            if not meta:
                continue
            try:
                note = vault.read_note(Path(meta["path"]))
            except (OSError, ValueError, KeyError) as exc:
                # unreadable source heals on its next write
                logger.warning("edge rescan skipped unreadable note %s: %s", meta.get("path"), exc)
                continue
            self.upsert_edges_for_note(vault, note, known_titles=known_titles)

        self.db.commit()
        return len(seen)

    def _fts_link_candidates(self, titles: List[str], limit_per_title: int = 200) -> set:
        """Notes whose bodies likely mention one of `titles`.

        Best-effort FTS5 phrase scan over indexed bodies; a title FTS refuses
        simply contributes no candidates (its edges heal on the next touch of
        the source). Work per title is bounded, so a hub-title rename cannot
        trigger an unbounded rescan.
        """
        found: set = set()
        for title in titles:
            phrase = phrase_query(title)
            if not phrase:
                continue
            rows, reason = run_fts_match(
                self.db,
                "SELECT note_id FROM notes_fts WHERE notes_fts MATCH ? LIMIT ?",
                (f"body: {phrase}", limit_per_title),
            )
            if reason != FTS_REASON_OK:
                continue
            found.update(row["note_id"] for row in rows)
        return found

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

    def upsert_note(self, note: Note, *, stamp: Optional[tuple] = None) -> None:
        """Insert or update a note in the index.

        ``stamp`` is the file's ``(st_mtime_ns, st_size)`` — the pair the
        incremental refresh compares before reading a note (EM-603). A caller
        that does not pass it stores ``(0, 0)``, which never matches a real
        stat, so the next refresh reads that one note once and fills it in.
        """
        note_id = note.note_id
        path_str = str(note.path)
        mtime_ns, size = stamp if stamp is not None else (0, 0)

        # Upsert metadata
        self.db.execute(
            """INSERT INTO notes_meta (note_id, path, title, domain, note_type,
               importance, tags, source, source_url, created, updated, agent,
               entropic_id, body_preview, content_hash, mtime_ns, size)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(note_id) DO UPDATE SET
                path=excluded.path, title=excluded.title, domain=excluded.domain,
                note_type=excluded.note_type, importance=excluded.importance,
                tags=excluded.tags, source=excluded.source, source_url=excluded.source_url,
                created=excluded.created, updated=excluded.updated, agent=excluded.agent,
                entropic_id=excluded.entropic_id, body_preview=excluded.body_preview,
                content_hash=excluded.content_hash, mtime_ns=excluded.mtime_ns,
                size=excluded.size""",
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
                content_hash(note),
                mtime_ns,
                size,
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

    def upsert_edges_for_note(
        self, vault: 'Vault', note: 'Note',
        known_titles: Optional[Dict[str, str]] = None,
    ) -> None:
        """Extract wikilinks from a note and create graph edges.

        Only wikilink edges are replaced; kind='triple:*' edges are written
        by the triples sync and must never be deleted by a note write (that
        is what kept recreating the index.db/memory.db split-brain).

        known_titles: optional prebuilt {title: note_id} map. Batch callers
        (the incremental diff) pass it so the resolver is not re-scanned per
        note, which is O(N^2) on a full-diff run.
        """
        note_id = note.note_id

        # Remove old wikilink edges from this source
        self.db.execute(
            "DELETE FROM graph_edges WHERE source_id = ? AND kind = 'wikilink'",
            (note_id,),
        )

        links = vault.extract_wikilinks(note.body)
        known = known_titles
        if known is None:
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
                except sqlite3.IntegrityError:
                    # duplicate edge — increment weight
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
        self, query: str, top_k: int = 10, domain: Optional[str] = None,
        fts_query: Optional[str] = None,
    ) -> List[SearchHit]:
        """
        Full-text search over title, tags, and body using FTS5.
        Returns ranked results with highlight snippets.

        Uses the shared build_fts_query() (token OR-prefix, metacharacter-safe,
        term-capped) so vault search and fact recall mean the same thing for
        the same query. Pass a prebuilt ``fts_query`` to reuse one expression
        across layers. A rejected MATCH expression yields [] (logged), never an
        exception.
        """
        if fts_query is None:
            fts_query = build_fts_query(query, fields=("title", "tags", "body"))
        if not fts_query:
            return []

        where = ""
        params: tuple = ()
        if domain:
            where = "AND notes_meta.domain = ?"
            params = (domain,)

        rows, reason = run_fts_match(
            self.db,
            f"""SELECT
                notes_fts.note_id,
                notes_fts.title,
                notes_fts.domain,
                notes_fts.note_type,
                notes_fts.importance,
                notes_fts.tags,
                notes_meta.path,
                snippet(notes_fts, 4, '[HL]', '[/HL]', '...', 32) AS snippet,
                rank
            FROM notes_fts
            JOIN notes_meta ON notes_fts.note_id = notes_meta.note_id
            WHERE notes_fts MATCH ? {where}
            ORDER BY rank
            LIMIT ?""",
            (fts_query, *params, top_k),
        )
        if reason != FTS_REASON_OK:
            return []

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
                snippet=(row["snippet"] or "").replace("[HL]", "**").replace("[/HL]", "**"),
                rank=float(row["rank"]) if row["rank"] else 0.0,
            ))
        return hits

    def search_by_title(self, title: str) -> List[SearchHit]:
        """Exact or prefix title search (for link resolution)."""
        rows = self.db.execute(
            """SELECT note_id, title, domain, note_type, importance, tags, path, body_preview
            FROM notes_meta WHERE title LIKE ? ESCAPE '\\' LIMIT 10""",
            (f"%{escape_like(title)}%",),
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
        include_bodies: bool = False,
    ) -> List[dict]:
        """Return nodes for graph visualization.

        ``include_bodies`` gates the ``notes_fts`` join: reading every note's
        full body is only needed when the caller embeds bodies (the modal and
        ``--include-bodies`` exports). EM-605 slice 2.5 measured it as the whole
        cost of a 5k-node export — 7.7 s of a 7.7 s export against 1.1 s with
        the join dropped — so the default path reads ``notes_meta`` only and
        reports the preview it already has.
        """
        where = "WHERE m.importance >= ?"
        params: tuple = (min_importance,)
        if domain:
            where += " AND m.domain = ?"
            params = (min_importance, domain)

        columns = (
            "m.note_id, m.title, m.domain, m.note_type, m.importance,"
            " m.tags, m.path, m.body_preview"
        )
        if include_bodies:
            sql = f"""SELECT {columns}, f.body AS full_body
            FROM notes_meta m
            LEFT JOIN notes_fts f ON f.note_id = m.note_id
            {where}
            ORDER BY m.importance DESC
            LIMIT ?"""
        else:
            sql = f"""SELECT {columns}
            FROM notes_meta m
            {where}
            ORDER BY m.importance DESC
            LIMIT ?"""
        rows = self.db.execute(sql, (*params, max_nodes)).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["full_body"] = d.pop("full_body", None) or d.get("body_preview") or ""
            results.append(d)
        return results

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
