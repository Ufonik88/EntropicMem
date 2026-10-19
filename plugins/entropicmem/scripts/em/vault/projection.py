"""EM-601 slice 1 — the vault projection engine (S6's first card).

The vault is a *projection* of the store, not a second copy of it: every file
is rendered from rows, and a run that changes nothing writes nothing. The
contract, in full:

* **Only auto-sections are rewritten.** Each generated region sits between
  ``<!-- entropicmem:auto:begin id=… -->`` and ``…:end id=… -->`` markers;
  everything else in the file — the frontmatter, the human region between the
  frontmatter and the first marker, any section this run does not own — is
  copied back byte for byte. That is what lets a hand edit survive ten
  projection runs, and it is why a file whose markers the user deleted is left
  exactly as it is and reported by :func:`lint` rather than recreated over the
  user's prose.
* **Idempotent.** A file whose rendered bytes equal what is on disk is not
  touched at all, so a second run moves no mtime and creates no temp file.
* **Scoped like the store** (§3.5, the same clause ``MemoryStore.list``
  applies): ``scope_profile`` + ``scope_user`` (+ chat), so one scope's
  projection never renders another user's rows.
* **The owner-only tiers never reach a plaintext file.** §3.5 would let a
  profile-wide (owner) scope read ``sensitive``/``secret`` rows; this module
  excludes them outright regardless of scope. The vault is an unencrypted
  Markdown directory the user syncs and shares, so the store's strongest tier
  is not downgraded to it. Deliberate strengthening, recorded in CHANGELOG.
* **Forgetting erases, not just hides.** An entity whose rows are all gone is
  still *visited*, so an existing page is rewritten down to what remains
  rather than left behind with the forgotten line still in it — while an
  entity with nothing to show and no page yet is not created at all. The same
  applies to the unfiled page and to a day's journal page.

Slice 1 renders three page kinds — ``Entities/*.md``, ``Journal/*.md`` and
``Memories/Unfiled.md`` — and stops there. Recorded, not built:

* the ``project_vault`` job, its 60 s debounce and the provider's enqueue on
  write paths (slice 2), so nothing schedules a projection yet;
* the ``vault.projection`` mode switch (``none|entities|entities+journal|
  legacy``) — this module takes ``modes`` directly, and slice 2 maps config
  onto it; ``legacy`` stays v2's note-per-fact writer;
* month paging for ``Memories/Unfiled.md`` past 200 rows: paging needs a
  policy for the month file that stops being current, and that is a design
  decision of its own rather than a line of code;
* the journal is unbounded (one page per episode day, forever).

One root per scope: the projection runs for a single scope, and the "page
exists but nothing is projectable now" branch — the branch that erases a
forgotten memory's line — will happily rewrite an existing page emptier than
another scope left it.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import sqlite3
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from em.clock import short_id
from em.store.types import OWNER_ONLY_TIERS, Scope
from em.util.fsperm import chmod_posix
from em_internal.vault import Vault

AUTO_BEGIN = "<!-- entropicmem:auto:begin id={section} -->"
AUTO_END = "<!-- entropicmem:auto:end id={section} -->"

#: Page kinds this engine can render, and the modes a caller may name.
MODES: tuple[str, ...] = ("entities", "journal", "unfiled")

#: What :func:`lint` reports: a projected file that cannot be rewritten
#: safely. ``missing_markers`` means the markers are gone; the other two mean
#: the marker pairs no longer line up and a rewrite would guess at the user's
#: content.
PROBLEMS: tuple[str, ...] = ("missing_markers", "unbalanced_markers", "duplicate_markers")

#: A superseded fact's History is the *last* ten, newest first.
HISTORY_LIMIT = 10

#: ``sensitivity`` values (§3.5) withheld from the vault outright.
_FORBIDDEN_TIER_PLACEHOLDERS = ",".join("?" for _ in OWNER_ONLY_TIERS)

#: One marker per line, anywhere in a file. ``\\r?`` keeps CRLF files (the
#: Windows invariant) parseable, and the capture keeps the marker's own text so
#: an existing file's markers are copied back verbatim.
_MARKER_RE = re.compile(
    r"^[ \t]*(<!-- entropicmem:auto:(begin|end) id=([A-Za-z0-9_-]+) -->)[ \t]*\r?$",
    re.MULTILINE,
)


@dataclass(frozen=True)
class LintProblem:
    """One damaged projected file, reported by :func:`lint`."""

    path: Path
    problem: str


@dataclass
class ProjectionReport:
    """What one :func:`project` run did.

    ``written``/``unchanged``/``missing_markers`` hold **vault-relative** paths:
    the report describes the vault, and a caller comparing two runs needs paths
    that do not move when the root does.
    """

    written: list[Path] = field(default_factory=list)
    unchanged: list[Path] = field(default_factory=list)
    missing_markers: list[Path] = field(default_factory=list)

    @property
    def pages_written(self) -> int:
        """Pages actually rewritten or created this run."""
        return len(self.written)


# --- the auto-section engine ---------------------------------------------


def _parse_markers(text: str) -> tuple[list[dict[str, Any]], str | None]:
    """Split ``text`` into auto-section blocks.

    Returns ``(blocks, None)`` or ``([], problem)``. A file whose markers are
    unbalanced or duplicated cannot be rewritten without guessing at what the
    user meant, so it reports a problem instead of guessing.
    """
    marks: list[dict[str, Any]] = []
    for match in _MARKER_RE.finditer(text):
        marks.append(
            {
                "op": match.group(2),
                "id": match.group(3),
                "start": match.start(1),
                "end": match.end(1),
            }
        )

    blocks: list[dict[str, Any]] = []
    index = 0
    while index < len(marks):
        begin = marks[index]
        if begin["op"] != "begin" or index + 1 >= len(marks):
            return [], "unbalanced_markers"
        end = marks[index + 1]
        if end["op"] != "end" or end["id"] != begin["id"]:
            return [], "unbalanced_markers"
        blocks.append(
            {
                "id": begin["id"],
                "begin_start": begin["start"],
                "begin_end": begin["end"],
                "body_start": begin["end"],
                "body_end": end["start"],
                "end_start": end["start"],
                "end_end": end["end"],
            }
        )
        index += 2

    if not blocks:
        return [], "missing_markers"
    ids = [block["id"] for block in blocks]
    if len(ids) != len(set(ids)):
        return [], "duplicate_markers"
    return blocks, None


def _render_sections(sections: Sequence[tuple[str, str]]) -> str:
    """The marker blocks for a brand-new file, joined by blank lines."""
    parts: list[str] = []
    for position, (section, body) in enumerate(sections):
        if position:
            parts.append("")
        parts.append(AUTO_BEGIN.format(section=section))
        if body:
            parts.append(body)
        parts.append(AUTO_END.format(section=section))
    return "\n".join(parts)


def merge(
    existing: str | None,
    *,
    frontmatter: str,
    sections: Sequence[tuple[str, str]],
) -> tuple[str, str]:
    """New file text, and the action that produced it.

    Actions: ``created``, ``updated``, ``unchanged`` (identical bytes), and
    ``missing_markers`` — returned with the **existing text untouched**, which
    is the card's rule for a file the user gutted: never recreate it over their
    prose, and let :func:`lint` say so.

    On update only the bodies of sections this run owns are replaced. The
    frontmatter, the human region before the first marker, the gap between
    blocks, the trailing text after the last marker, and any section not in
    ``sections`` are copied through verbatim. A generated body takes the file's
    own line endings, so a CRLF vault does not end up half-CRLF.
    """
    if existing is None:
        return f"{frontmatter}\n{_render_sections(sections)}\n", "created"

    blocks, problem = _parse_markers(existing)
    if problem is not None:
        return existing, "missing_markers"

    wanted = dict(sections)
    present = {block["id"] for block in blocks}
    if not set(wanted).issubset(present):
        return existing, "missing_markers"

    eol = "\r\n" if "\r\n" in existing else "\n"
    parts: list[str] = [existing[: blocks[0]["begin_start"]]]
    for position, block in enumerate(blocks):
        if block["id"] in wanted:
            # The replaced region runs marker-to-marker, so it carries the
            # newlines that keep each marker on its own line: without them the
            # next run could not recognise the markers at all.
            raw = wanted[block["id"]]
            body = (eol + raw.replace("\n", eol) + eol) if raw else eol
        else:
            body = existing[block["body_start"] : block["body_end"]]
        parts.append(existing[block["begin_start"] : block["begin_end"]])
        parts.append(body)
        parts.append(existing[block["end_start"] : block["end_end"]])
        following = blocks[position + 1]["begin_start"] if position + 1 < len(blocks) else len(existing)
        parts.append(existing[block["end_end"] : following])

    text = "".join(parts)
    if text == existing:
        return existing, "unchanged"
    return text, "updated"


# --- writing --------------------------------------------------------------


def _atomic_write(target: Path, text: str) -> None:
    """Replace ``target`` in one rename; a failed write leaves no debris.

    Same contract as every other writer in the tree: the temp file lives in the
    destination directory (so the rename never crosses a filesystem) and is
    unlinked on any failure, never left beside the note for the user to trip
    over.
    """
    fd, temp_name = tempfile.mkstemp(dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        if target.exists():
            # mkstemp creates 0600; keep whatever mode the file already had.
            os.chmod(temp_name, target.stat().st_mode & 0o7777)
        os.replace(temp_name, target)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temp_name)
        raise


def _read_raw(path: Path) -> str:
    """Read the file's **bytes as text**, line endings untouched.

    ``Path.read_text`` opens in universal-newline mode, which turns every CRLF
    into LF on the way in: a round trip through it would silently rewrite the
    user's Windows vault as LF, and would make the idempotence comparison in
    :func:`_commit` miss every time. ``newline=""`` is the only way to see what
    is actually on disk.
    """
    with open(path, "r", encoding="utf-8", newline="") as handle:
        return handle.read()


def _commit(vault: Vault, relative: Path, text: str, action: str, report: ProjectionReport) -> None:
    if action == "missing_markers":
        report.missing_markers.append(relative)
        return
    target = vault.resolve_path(relative)
    if target.is_file() and _read_raw(target) == text:
        report.unchanged.append(relative)
        return
    parent_existed = target.parent.exists()
    target.parent.mkdir(parents=True, exist_ok=True)
    if not parent_existed:
        chmod_posix(target.parent, 0o700)
    _atomic_write(target, text)
    report.written.append(relative)


def _read(vault: Vault, relative: Path) -> str | None:
    target = vault.resolve_path(relative)
    return _read_raw(target) if target.is_file() else None


# --- row collection -------------------------------------------------------


def _clauses(
    scope: Scope,
    alias: str = "m",
    *,
    forbid_tiers: bool = True,
) -> tuple[list[str], list[Any]]:
    """The store's own read rule for one scope, plus this module's tier bar.

    ``scope_profile`` + ``scope_user`` (+ chat) is exactly what
    ``MemoryStore.list`` emits, so a projection shows its scope what the store
    would show it. The ``sensitivity`` exclusion is the one thing this module
    adds, and ``forbid_tiers=False`` is for the *candidate* query only — the
    rows that decide which entities to visit — never for a body that renders.
    """
    clauses = [f"{alias}.scope_profile=?", f"{alias}.scope_user=?"]
    values: list[Any] = [scope.profile, scope.user]
    if forbid_tiers:
        clauses.append(f"{alias}.sensitivity NOT IN ({_FORBIDDEN_TIER_PLACEHOLDERS})")
        values.extend(OWNER_ONLY_TIERS)
    if scope.chat:
        clauses.append(f"({alias}.scope_chat=? OR {alias}.scope_chat='')")
        values.append(scope.chat)
    return clauses, values


def _one_line(text: Any) -> str:
    """One renderable line: a bullet may never span physical lines."""
    return " ".join(str(text or "").split())


def _bullet(content: Any, memory_id: str | None = None) -> str:
    line = f"- {_one_line(content)}"
    if memory_id:
        line += f" ^m-{short_id(memory_id)}"
    return line


# --- entity pages ---------------------------------------------------------


def _entity_paths(vault: Vault, entities: Sequence[dict[str, Any]]) -> dict[str, Path]:
    """Vault-relative page path per entity id: stable, and never two on one name.

    Assignment runs in id order, not name order, so a new entity that sorts
    earlier can never renumber the pages already on disk — a filename that
    moves is a filename the user has notes pointing at. Two names that
    sanitise to one filename (``Acme/Corp`` and ``Acme Corp``) are told apart
    by the entity's own id, which is unique by construction.
    """
    taken: set[str] = set()
    paths: dict[str, Path] = {}
    for entity in sorted(entities, key=lambda row: row["id"]):
        base = vault.sanitize(entity["name"])
        name = f"{base} ({short_id(entity['id'])})" if base.casefold() in taken else base
        taken.add(name.casefold())
        paths[entity["id"]] = Path("Entities") / f"{name}.md"
    return paths


def _entity_frontmatter(entity: dict[str, Any], aliases: Sequence[str]) -> str:
    """Written once, at creation, and never rewritten (``merge`` preserves it)."""
    listed = ", ".join(_one_line(alias) for alias in aliases)
    return (
        "---\n"
        f"entropic_entity: {entity['id']}\n"
        f"name: {_one_line(entity['name'])}\n"
        f"kind: {_one_line(entity['kind'])}\n"
        f"aliases: [{listed}]\n"
        "---\n"
    )


def _linked_body(
    conn: sqlite3.Connection,
    entity_id: str,
    scope: Scope,
    *,
    status: str,
    limit: int | None = None,
) -> str:
    clauses, values = _clauses(scope)
    sql = (
        "SELECT m.id, m.content FROM memory_entities me JOIN memories m ON m.id=me.memory_id"
        f" WHERE me.entity_id=? AND m.status=? AND {' AND '.join(clauses)}"
        " ORDER BY m.updated_at DESC, m.id DESC"
    )
    params: list[Any] = [entity_id, status, *values]
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    return "\n".join(_bullet(row["content"], row["id"]) for row in rows)


def _relations_body(
    conn: sqlite3.Connection,
    entity: dict[str, Any],
    scope: Scope,
    *,
    names: dict[str, str],
    paths: dict[str, Path],
) -> str:
    """Relations as wikilinks, newest first, open relations only.

    A relation is rendered only while its source memory is still live: a
    ``forget`` must clear the lines that memory put on the page, not only its
    bullet. A relation with no source memory (added by hand or by extraction
    without a memory) has nothing to be forgotten and always renders.

    The link target is the *page's* filename when this run projects one, so an
    Obsidian click lands on the file that exists rather than on a name that
    might sanitise differently; an entity with no page of its own falls back to
    its plain name (Obsidian will create the note when it is opened).
    """
    rows = conn.execute(
        "SELECT r.subject_id, r.predicate, r.object_id, r.object_literal FROM relations r"
        " WHERE r.scope_profile=? AND r.valid_to IS NULL AND (r.subject_id=? OR r.object_id=?)"
        " AND (r.memory_id IS NULL OR EXISTS ("
        "   SELECT 1 FROM memories rm WHERE rm.id=r.memory_id AND rm.status='active'"
        f"   AND rm.sensitivity NOT IN ({_FORBIDDEN_TIER_PLACEHOLDERS})))"
        " ORDER BY r.created_at DESC, r.id",
        [scope.profile, entity["id"], entity["id"], *OWNER_ONLY_TIERS],
    ).fetchall()

    def link(target_id: str) -> str:
        if target_id in paths:
            return Path(paths[target_id]).stem
        return _one_line(names.get(target_id, ""))

    lines: list[str] = []
    for row in rows:
        predicate = _one_line(row["predicate"]) or "related_to"
        if row["subject_id"] == entity["id"]:
            if row["object_id"]:
                target = link(row["object_id"])
                lines.append(f"- {predicate} [[{target}]]" if target else f"- {predicate}")
            else:
                lines.append(f"- {predicate} {_one_line(row['object_literal'])}")
        else:
            source = link(row["subject_id"])
            lines.append(f"- [[{source}]] — {predicate}" if source else f"- {predicate}")
    return "\n".join(lines)


def _project_entities(
    conn: sqlite3.Connection, vault: Vault, scope: Scope, report: ProjectionReport
) -> None:
    # Candidates ignore status and tier: an entity whose every row was
    # forgotten must still be visited, or its existing page keeps the
    # forgotten line forever. What a *body* renders never ignores them.
    clauses, values = _clauses(scope, forbid_tiers=False)
    rows = conn.execute(
        "SELECT DISTINCT e.id, e.name, e.kind FROM entities e"
        " JOIN memory_entities me ON me.entity_id=e.id"
        " JOIN memories m ON m.id=me.memory_id"
        f" WHERE e.scope_profile=? AND {' AND '.join(clauses)}"
        " ORDER BY e.name COLLATE NOCASE, e.id",
        [scope.profile, *values],
    ).fetchall()
    if not rows:
        return

    entities = [dict(row) for row in rows]
    paths = _entity_paths(vault, entities)
    names = {
        row["id"]: row["name"]
        for row in conn.execute(
            "SELECT id, name FROM entities WHERE scope_profile=?", (scope.profile,)
        )
    }

    for entity in entities:
        relative = paths[entity["id"]]
        existing = _read(vault, relative)
        sections = [
            ("facts", _linked_body(conn, entity["id"], scope, status="active")),
            (
                "history",
                _linked_body(conn, entity["id"], scope, status="superseded", limit=HISTORY_LIMIT),
            ),
            ("relations", _relations_body(conn, entity, scope, names=names, paths=paths)),
        ]
        if existing is None and not any(body for _, body in sections):
            # Nothing to show and nothing there: creating an empty note would
            # publish the entity's name with no reason to exist.
            continue
        if existing is None:
            aliases = [
                row["alias_norm"]
                for row in conn.execute(
                    "SELECT alias_norm FROM entity_aliases WHERE entity_id=? ORDER BY alias_norm",
                    (entity["id"],),
                )
            ]
            frontmatter = _entity_frontmatter(entity, aliases)
        else:
            frontmatter = ""
        text, action = merge(existing, frontmatter=frontmatter, sections=sections)
        _commit(vault, relative, text, action, report)


# --- journal --------------------------------------------------------------


def _json_list(raw: Any) -> list[str]:
    """``decisions``/``open_loops`` are JSON arrays; anything else is one item.

    A malformed column must not fail the whole run — the episode still has a
    title and a summary worth rendering.
    """
    if isinstance(raw, list):
        return [str(item) for item in raw]
    try:
        parsed = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        return [str(raw)] if raw else []
    return [str(item) for item in parsed] if isinstance(parsed, list) else [str(parsed)]


def _project_journal(
    conn: sqlite3.Connection, vault: Vault, scope: Scope, report: ProjectionReport
) -> None:
    clauses, values = _clauses(scope, alias="e", forbid_tiers=False)
    rows = conn.execute(
        "SELECT e.id, e.title, e.summary, e.decisions, e.open_loops, e.created_at FROM episodes e"
        f" WHERE {' AND '.join(clauses)} ORDER BY e.created_at, e.id",
        values,
    ).fetchall()

    days: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        days.setdefault(str(row["created_at"])[:10], []).append(row)

    # A day whose episodes were pruned still has a page on disk; without this
    # it would keep the pruned episodes forever.
    folder = vault.root / "Journal"
    if folder.is_dir():
        for path in sorted(folder.glob("*.md")):
            with contextlib.suppress(OSError, UnicodeDecodeError):
                if _is_projected(_read_raw(path)):
                    days.setdefault(path.stem, [])

    for day, episodes in days.items():
        lines: list[str] = []
        for episode in episodes:
            title = _one_line(episode["title"]) or "(untitled)"
            summary = _one_line(episode["summary"])
            lines.append(f"- **{title}** — {summary}" if summary else f"- **{title}**")
            for label, column in (("Decided", "decisions"), ("Open", "open_loops")):
                for item in _json_list(episode[column]):
                    lines.append(f"  - {label}: {_one_line(item)}")

        relative = Path("Journal") / f"{day}.md"
        existing = _read(vault, relative)
        if existing is None and not lines:
            continue
        frontmatter = f"---\nentropic_vault: journal\ndate: {day}\n---\n" if existing is None else ""
        text, action = merge(existing, frontmatter=frontmatter, sections=[("episodes", "\n".join(lines))])
        _commit(vault, relative, text, action, report)


# --- unfiled --------------------------------------------------------------


def _project_unfiled(
    conn: sqlite3.Connection, vault: Vault, scope: Scope, report: ProjectionReport
) -> None:
    clauses, values = _clauses(scope)
    rows = conn.execute(
        "SELECT m.id, m.content FROM memories m"
        " WHERE m.status='active'"
        " AND NOT EXISTS (SELECT 1 FROM memory_entities me WHERE me.memory_id=m.id)"
        f" AND {' AND '.join(clauses)}"
        " ORDER BY m.updated_at DESC, m.id DESC",
        values,
    ).fetchall()

    relative = Path("Memories") / "Unfiled.md"
    existing = _read(vault, relative)
    if existing is None and not rows:
        return
    frontmatter = "---\nentropic_vault: unfiled\n---\n" if existing is None else ""
    body = "\n".join(_bullet(row["content"], row["id"]) for row in rows)
    text, action = merge(existing, frontmatter=frontmatter, sections=[("unfiled", body)])
    _commit(vault, relative, text, action, report)


# --- entry point ----------------------------------------------------------


def project(
    conn: sqlite3.Connection,
    root: Path | str,
    *,
    scope: Scope,
    modes: Sequence[str] = MODES,
) -> ProjectionReport:
    """Render the scope's memory into ``root``. Returns what changed.

    Unknown modes raise: a typo that silently renders nothing would read as
    "the vault is empty", which is the worst possible failure for a
    human-first view.
    """
    unknown = [mode for mode in modes if mode not in MODES]
    if unknown:
        raise ValueError(f"unknown projection mode(s) {unknown}; expected one of {list(MODES)}")

    vault = Vault(Path(root))
    report = ProjectionReport()
    if "entities" in modes:
        _project_entities(conn, vault, scope, report)
    if "journal" in modes:
        _project_journal(conn, vault, scope, report)
    if "unfiled" in modes:
        _project_unfiled(conn, vault, scope, report)
    return report


# --- lint -----------------------------------------------------------------


def _is_projected(text: str) -> bool:
    """True when the file declares itself the projection's output.

    The frontmatter key is the only thing left once the markers are gone, and
    it is exactly what :func:`lint` needs to tell a gutted projected page from
    the user's own notes.
    """
    if not text.startswith("---"):
        return False
    head = re.match(r"\A---\r?\n(.*?)\r?\n---\r?\n", text, re.DOTALL)
    if head is None:
        return False
    return bool(re.search(r"^(entropic_entity|entropic_vault):", head.group(1), re.MULTILINE))


def lint(root: Path | str) -> list[LintProblem]:
    """Every projected file under ``root`` whose auto-sections are unsafe.

    Unreadable files are skipped: lint is advisory and must not stop at one bad
    note. A file whose markers *and* frontmatter key the user both removed is
    invisible here by construction — the projection catches that case itself,
    when :func:`merge` reports ``missing_markers`` for the file it would have
    rewritten.
    """
    root_path = Path(root)
    if not root_path.is_dir():
        return []

    problems: list[LintProblem] = []
    for path in sorted(root_path.rglob("*.md")):
        try:
            text = _read_raw(path)
        except (OSError, UnicodeDecodeError):
            continue
        if not _is_projected(text):
            continue
        _, problem = _parse_markers(text)
        if problem is not None:
            problems.append(LintProblem(path=path.relative_to(root_path), problem=problem))
    return problems
