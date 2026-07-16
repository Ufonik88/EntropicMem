"""
mnemosyne_bridge.py — Mnemosyne ↔ Vault bridge for EntropicMem.

Reads from Mnemosyne (via public Mnemosyne class API) and writes
to the vault Mnemosyne/ folder. Supports export (M→V), import (V→M),
and dual remember() with entropic_id linking.

Stdlib-only core. Mnemosyne class is an optional runtime dependency.
"""

import hashlib
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from vault import Note, Vault, resolve_vault_path
from index import VaultIndex

# ── Mnemosyne availability check ────────────────────────────────────────────

MNEMOSYNE_AVAILABLE = False
MNEMOSYNE_DB_PATH = Path.home() / ".hermes" / "mnemosyne" / "data" / "mnemosyne.db"

try:
    _mnemo_path = os.environ.get(
        "ENTROPICMEM_MNEMOSYNE_DB",
        str(MNEMOSYNE_DB_PATH)
    )
    MNEMOSYNE_DB_PATH = Path(_mnemo_path)

    # Try importing Mnemosyne
    sys.path.insert(0, str(Path.home() / ".hermes" / "mnemosyne"))
    from mnemosyne.core.memory import Mnemosyne as _Mnemosyne
    MNEMOSYNE_AVAILABLE = MNEMOSYNE_DB_PATH.exists()
except (ImportError, ModuleNotFoundError):
    pass


# ── data types ──────────────────────────────────────────────────────────────

@dataclass
class ExportResult:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: List[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.created + self.updated + self.skipped


# ── bridge class ────────────────────────────────────────────────────────────

class MnemosyneBridge:
    """Read/write bridge between Mnemosyne and the vault."""

    def __init__(self, vault: Vault, index: VaultIndex, mnemosyne_db: Optional[Path] = None):
        self.vault = vault
        self.index = index
        self.db_path = mnemosyne_db or MNEMOSYNE_DB_PATH
        self._mnemo: Any = None

    @property
    def mnemosyne(self):
        """Lazy-init Mnemosyne instance."""
        if self._mnemo is None and MNEMOSYNE_AVAILABLE and self.db_path.exists():
            self._mnemo = _Mnemosyne(db_path=str(self.db_path))
        return self._mnemo

    @property
    def available(self) -> bool:
        return MNEMOSYNE_AVAILABLE and self.db_path.exists()

    # ── dual remember ──────────────────────────────────────────────────

    def remember(
        self,
        content: str,
        domain: str = "Knowledge",
        tags: Optional[List[str]] = None,
        importance: float = 0.5,
        source: str = "agent",
        scope: str = "global",
    ) -> Tuple[Optional[str], Optional[Path]]:
        """
        Write a durable fact to BOTH Mnemosyne and the vault.

        Returns (mnemosyne_id, vault_path). mnemosyne_id is None if Mnemosyne unavailable.
        entropic_id = SHA256(content)[:16] links both sides.
        """
        entropic_id = hashlib.sha256(content.encode()).hexdigest()[:16]
        tags = tags or ["durable", "agent"]
        title = f"Fact - {content[:60]}"

        # 1. Write to Mnemosyne
        mnemo_id = None
        if self.available:
            try:
                mnemo_id = self.mnemosyne.remember(
                    content=content,
                    source=source,
                    importance=importance,
                    scope=scope,
                    metadata={"entropic_id": entropic_id, "domain": domain, "tags": ",".join(tags)},
                )
            except Exception as e:
                print(f"[bridge] Mnemosyne remember failed: {e}", file=sys.stderr)

        # 2. Write to vault
        body = (
            f"## Fact\n{content}\n\n"
            f"## Mnemosyne\n"
            f"- memory_id: {mnemo_id or 'N/A (Mnemosyne unavailable)'}\n"
            f"- entropic_id: {entropic_id}\n\n"
            f"## Source\n- {source}\n\n"
            f"## Links\n- [[{domain}/Index]]\n- [[Mnemosyne Dashboard]]\n"
        )
        path = self.vault.write_note(
            domain, title, body,
            tags=tags, domain=domain, source=source,
            frontmatter={"entropic_id": entropic_id},
        )
        note = self.vault.read_note(path)
        self.index.upsert_note(note)
        self.index.upsert_edges_for_note(self.vault, note)

        return mnemo_id, path

    # ── export: Mnemosyne → Vault ──────────────────────────────────────

    def export_to_vault(
        self,
        since: Optional[str] = None,
        limit: int = 500,
        verbose: bool = False,
    ) -> ExportResult:
        """
        Export Mnemosyne memories (scope=global) to vault/Mnemosyne/ as permanent notes.
        Skips notes that already exist with matching entropic_id (dedup via content hash).
        """
        result = ExportResult()

        if not self.available:
            result.errors.append("Mnemosyne DB not available")
            return result

        try:
            memories = self._fetch_memories(since=since, limit=limit)
        except Exception as e:
            result.errors.append(f"Failed to fetch memories: {e}")
            return result

        mnemosyne_dir = self.vault.root / "Mnemosyne"
        mnemosyne_dir.mkdir(exist_ok=True)

        for mem in memories:
            content = mem.get("content", "")
            if not content.strip():
                result.skipped += 1
                continue

            entropic_id = hashlib.sha256(content.encode()).hexdigest()[:16]
            source = mem.get("source", "mnemosyne")
            importance_val = mem.get("importance", 0.5)
            mem_id = mem.get("id", "")
            created = mem.get("created_at", "") or mem.get("timestamp", "")

            # Check if note already exists with same entropic_id
            existing = self._find_by_entropic_id(entropic_id)
            if existing:
                result.skipped += 1
                if verbose:
                    print(f"  [skip] {entropic_id[:8]} already exists in vault")
                continue

            # Create note in Mnemosyne/ folder
            title = self._make_title(content)
            body = (
                f"## Memory\n{content}\n\n"
                f"## Metadata\n"
                f"- mnemosyne_id: {mem_id}\n"
                f"- entropic_id: {entropic_id}\n"
                f"- source: {source}\n"
                f"- importance: {importance_val}\n"
                f"- created: {created}\n\n"
                f"## Links\n- [[Mnemosyne Dashboard]]\n"
            )
            tags = ["mnemosyne", "auto-exported"]

            try:
                path = self.vault.write_note(
                    "Mnemosyne", title, body,
                    tags=tags, domain="Mnemosyne", source="mnemosyne",
                    note_type="permanent", agent=True,
                    _allow_protected=True,
                )
                note = self.vault.read_note(path)
                note.entropic_id = entropic_id
                self.index.upsert_note(note)
                result.created += 1
                if verbose:
                    print(f"  [created] {path}")
            except Exception as e:
                result.errors.append(f"Write failed for {entropic_id[:8]}: {e}")

        self.index.db.commit()
        return result

    def _fetch_memories(self, since: Optional[str] = None, limit: int = 500) -> List[dict]:
        """Fetch memories from Mnemosyne DB (read-only SQL). Filters by metadata_json scope or fetches all."""
        if not self.available:
            return []

        memories = []
        try:
            import sqlite3
            db = sqlite3.connect(str(self.db_path))
            db.row_factory = sqlite3.Row

            # Fetch memories with metadata_json containing scope='global' or importance >= 0.5
            # Also accept any memory (scope column doesn't exist — scope stored in metadata_json)
            if since:
                query = """
                    SELECT id, content, source, importance, created_at, metadata_json, session_id
                    FROM memories
                    WHERE (metadata_json LIKE '%"scope": "global"%'
                           OR metadata_json LIKE '%"scope":"global"%'
                           OR importance >= 0.7)
                      AND created_at >= ?
                    ORDER BY importance DESC, created_at DESC
                    LIMIT ?
                """
                rows = db.execute(query, (since, limit)).fetchall()
            else:
                query = """
                    SELECT id, content, source, importance, created_at, metadata_json, session_id
                    FROM memories
                    WHERE metadata_json LIKE '%"scope": "global"%'
                       OR metadata_json LIKE '%"scope":"global"%'
                       OR importance >= 0.7
                    ORDER BY importance DESC, created_at DESC
                    LIMIT ?
                """
                rows = db.execute(query, (limit,)).fetchall()

            memories = [dict(r) for r in rows]
            db.close()
        except Exception as e:
            if verbose := getattr(self, '_verbose', False):
                print(f"[bridge] SQL fetch error: {e}", file=sys.stderr)

        return memories

    # ── helpers ────────────────────────────────────────────────────────

    def _make_title(self, content: str, max_len: int = 80) -> str:
        """Make a note title from memory content."""
        first_line = content.split("\n")[0].strip()
        if len(first_line) > max_len:
            first_line = first_line[:max_len - 3] + "..."
        return self.vault.sanitize(first_line)

    def _find_by_entropic_id(self, entropic_id: str) -> Optional[Path]:
        """Check if a note with this entropic_id already exists in the vault."""
        for rel in self.vault.list_notes(folder="Mnemosyne", include_archive=False):
            try:
                note = self.vault.read_note(rel)
                if note.entropic_id == entropic_id:
                    return rel
            except Exception:
                continue
        return None
