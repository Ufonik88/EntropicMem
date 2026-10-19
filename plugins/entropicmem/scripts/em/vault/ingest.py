"""EM-604 — opt-in ingestion of human vault edits.

The projection (``em.vault.projection``) writes the store into Markdown; this is
the other direction, and it is **off by default** (``vault.ingest_human_edits``).
What it produces is a *proposal*, never a durable fact:

* A ``- <statement>`` line in an entity page's **human region** — the text
  before the page's first ``entropicmem:auto`` marker, outside every
  auto-section — becomes a ``pending`` memory with ``source="vault_edit"``,
  linked to that page's entity. It lands in the review queue, so the user's own
  note is a candidate the agent reviews rather than something the vault can
  push straight into the live store.
* A line the user *removed* from an auto-section is **not** ingested: the
  projection re-adds it from the live memory. Ingestion records it as a hint the
  ``review`` surface shows — ``user removed line for m-… - forget?`` — so the
  user can forget the memory instead of fighting the next projection.

Idempotent and safe on every projection pass: ``MemoryStore.add`` collapses an
exact ``(content, scope)`` duplicate to a no-op, so re-ingesting an unchanged
page writes nothing. A page whose markers were gutted is skipped, never guessed
at — the same rule the projection follows.

The removal baseline is deliberately stored, not inferred: the pass records the
block refs a page carried *last* time under ``meta`` and reports a removal only
for a ref that was there before, is gone now, and is still live. Ingesting a
freshly written fact (not yet on disk) can therefore never read as "removed".
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from em.clock import short_id
from em.store.entities import EntityStore
from em.store.memories import MemoryStore
from em.store.types import MemoryDraft, Scope
from em.vault.frontmatter import load_frontmatter
from em.vault.projection import _MARKER_RE, _parse_markers

log = logging.getLogger("entropicmem.vault")

#: The write-policy source a human page edit carries. ``evaluate_write``
#: quarantines it, so ``MemoryStore.add`` lands a pending row — the card's shape.
INGEST_SOURCE = "vault_edit"

#: The card's grammar: ``- <statement>`` at the start of a line (a ``---`` rule
#: or an indented sub-bullet is not a statement).
_STATEMENT_RE = re.compile(r"^-[ \t]+(\S.*?)[ \t]*$")

#: A projected bullet carries its memory as ``^m-<short>``.
_REF_RE = re.compile(r"\^m-([0-9A-Za-z]+)")


@dataclass
class IngestReport:
    """What one :func:`ingest` pass did: memories proposed, removals hinted."""

    added: list[str] = field(default_factory=list)
    hints: list[dict[str, Any]] = field(default_factory=list)


# --- meta keys ---------------------------------------------------------------


def _seen_key(scope: Scope, relative: str) -> str:
    """The block refs a page carried at the end of the *previous* pass."""
    return f"vault:seen:{scope.profile}:{scope.user}:{relative}"


def _hints_key(scope: Scope) -> str:
    return f"vault:hints:{scope.profile}:{scope.user}"


def _meta_get(conn: sqlite3.Connection, key: str) -> Any:
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def _meta_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?,?)", (key, value))


def _json_list(raw: Any) -> list:
    try:
        parsed = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


def _live_ids(conn: sqlite3.Connection, ids: tuple[str, ...]) -> set[str]:
    if not ids:
        return set()
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT id FROM memories WHERE status='active' AND id IN ({placeholders})", ids
    ).fetchall()
    return {row["id"] for row in rows}


# --- reading one page --------------------------------------------------------


def _in_profile(conn: sqlite3.Connection, entity_id: str, scope: Scope) -> bool:
    """The page belongs to this scope's profile (entities carry no user bucket).

    One root per scope is the projection's own rule, so the profile check is the
    one that matters: a page rendered for another profile never leaks into this
    one's store.
    """
    row = conn.execute(
        "SELECT scope_profile FROM entities WHERE id=?", (entity_id,)
    ).fetchone()
    return row is not None and row["scope_profile"] == scope.profile


def _human_region(body: str) -> str:
    """The page text before its first auto marker (frontmatter already removed)."""
    match = _MARKER_RE.search(body)
    return body[: match.start()] if match else body


def _statements(region: str) -> list[str]:
    out: list[str] = []
    for line in region.splitlines():
        match = _STATEMENT_RE.match(line)
        if match:
            statement = match.group(1).strip()
            if statement:
                out.append(statement)
    return out


def _facts_refs(text: str, blocks: list[dict[str, Any]]) -> set[str]:
    body = next(
        (text[b["body_start"] : b["body_end"]] for b in blocks if b["id"] == "facts"), ""
    )
    return set(_REF_RE.findall(body))


# --- the pass ----------------------------------------------------------------


def ingest(conn: sqlite3.Connection, root: "Path | str", *, scope: Scope, actor: str = "vault") -> IngestReport:
    """Read every entity page's human region for this scope. Returns the report.

    Runs inside the caller's transaction (the projection pass's), so the proposed
    memories, the removal baseline and the hints commit together.
    """
    report = IngestReport()
    folder = Path(root) / "Entities"
    if not folder.is_dir():
        return report

    store = MemoryStore(conn)
    entities = EntityStore(conn)
    hints = _load_hints(conn, scope)

    for path in sorted(folder.rglob("*.md")):
        try:
            text = _read_raw(path)
        except (OSError, UnicodeDecodeError):
            continue
        frontmatter, body = load_frontmatter(text)
        entity_id = str(frontmatter.get("entropic_entity") or "").strip()
        if not entity_id or not _in_profile(conn, entity_id, scope):
            continue
        blocks, problem = _parse_markers(text)
        if problem is not None:
            # No trustworthy structure: never guess at which lines are the
            # user's and which are the projection's.
            continue

        for statement in _statements(_human_region(body)):
            result = store.add(
                MemoryDraft(content=statement, source=INGEST_SOURCE, tags=("vault_edit",)),
                scope=scope,
                actor=actor,
            )
            if result.ok and result.id:
                entities.link_memory(result.id, entity_id)
                if result.decision != "noop_duplicate":
                    report.added.append(result.id)

        live = {
            short_id(row["id"]): row["id"]
            for row in conn.execute(
                "SELECT m.id FROM memory_entities me JOIN memories m ON m.id=me.memory_id"
                " WHERE me.entity_id=? AND m.status='active'",
                (entity_id,),
            ).fetchall()
        }
        relative = path.relative_to(Path(root)).as_posix()
        key = _seen_key(scope, relative)
        for ref in _json_list(_meta_get(conn, key)):
            if ref in live and ref not in _facts_refs(text, blocks):
                mid = live[ref]
                hints[mid] = {
                    "ref": f"m-{ref}",
                    "memory_id": mid,
                    "text": f"user removed line for m-{ref} - forget?",
                }
        _meta_set(conn, key, json.dumps(sorted(_facts_refs(text, blocks)), separators=(",", ":")))

    _save_hints(conn, scope, hints)
    report.hints = sorted(hints.values(), key=lambda hint: hint["ref"])
    return report


def _read_raw(path: Path) -> str:
    """Bytes as text, line endings untouched (a CRLF vault stays CRLF-aware)."""
    with open(path, "r", encoding="utf-8", newline="") as handle:
        return handle.read()


# --- the review surface ------------------------------------------------------


def _load_hints(conn: sqlite3.Connection, scope: Scope) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for item in _json_list(_meta_get(conn, _hints_key(scope))):
        if isinstance(item, dict) and item.get("memory_id"):
            out[item["memory_id"]] = item
    return out


def _save_hints(conn: sqlite3.Connection, scope: Scope, hints: dict[str, dict[str, Any]]) -> None:
    live = _live_ids(conn, tuple(hints))
    kept = {mid: hint for mid, hint in hints.items() if mid in live}
    _meta_set(
        conn, _hints_key(scope), json.dumps(list(kept.values()), separators=(",", ":"))
    )


def read_hints(conn: sqlite3.Connection, scope: Scope) -> list[dict[str, Any]]:
    """Removal hints for this scope, filtered to memories that are still live.

    A forgotten memory's hint is dropped at read time, so a ``forget`` between
    two passes never leaves a stale "forget?" prompt behind.
    """
    hints = _load_hints(conn, scope)
    live = _live_ids(conn, tuple(hints))
    return [hint for mid, hint in hints.items() if mid in live]
