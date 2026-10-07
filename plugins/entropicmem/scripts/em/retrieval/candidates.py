"""Candidate generators — EM-302 (plan §3.6).

Each generator is a function ``(ctx: RetrievalContext) -> list[Candidate]``,
returning *ranked* ``(owner_type, owner_id, raw_score)`` triples restricted by
the caller's scope and, for memories, ``status='active'`` (§3.6):

| Generator  | Source                              | Default k |
|------------|-------------------------------------|-----------|
| ``bm25``   | ``memories_fts MATCH``              | 40        |
| ``entity`` | ``memory_entities`` (+1 hop)        | 30        |
| ``episodic`` | ``episodes_fts`` + time window    | 10        |
| ``recent`` | memories updated in the last 48 h   | 10        |
| ``pinned`` | ``pinned=1`` or ``kind='constraint'`` | 10      |

``vector`` is §3.6's sixth generator and is **not here**: §3.6 makes it
conditional on an embedding backend ("only if backend available and coverage
≥ 50%") and forbids re-reading vector blobs per query, so it belongs with the
backend and the numpy cache that EM-303 builds. ``GENERATOR_LIMITS`` still
carries its ``k`` because that is §3.6's table verbatim.

Two conventions this module fixes and the tests pin:

* **``raw_score`` is higher-is-better.** SQLite's ``bm25()`` is
  lower-is-better, so the FTS generators negate it; a source with no score of
  its own (``pinned``, ``recent``, ``entity`` direct) uses ``1.0``. The value
  is informational — §3.6's fusion is *rank*-based, so it consumes the order
  of the returned list, not this field.
* **Deadline discipline.** Every generator asks
  :meth:`RetrievalContext.out_of_time` *before* touching the database and
  again between result pages, so a generator whose deadline has passed does no
  SQL at all and one that runs out mid-scan returns what it has (§3.6's AC:
  "partial within 5 ms of deadline").

Stdlib only (plan §3.2).
"""

from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, List, Mapping, Optional, Sequence, Tuple

from ..clock import to_iso
from ..store.types import OWNER_ONLY_TIERS, Scope, may_read_owner_only
from .query import MAX_TERMS, AnalyzedQuery

__all__ = [
    "BM25_WEIGHTS",
    "Candidate",
    "MAX_TERMS",
    "GENERATOR_LIMITS",
    "GENERATORS",
    "OWNER_TYPE_EPISODE",
    "OWNER_TYPE_MEMORY",
    "RetrievalContext",
    "bm25",
    "entity",
    "episodic",
    "match_expression",
    "pinned",
    "recent",
    "scope_sql",
]

OWNER_TYPE_MEMORY = "memory"
OWNER_TYPE_EPISODE = "episode"

#: §3.6's per-generator default ``k``. ``vector`` is EM-303's generator; its
#: row is kept because it is the plan's table, and ``RetrievalContext.k`` will
#: find it when that card lands.
GENERATOR_LIMITS: Mapping[str, int] = {
    "bm25": 40,
    "vector": 40,
    "entity": 30,
    "episodic": 10,
    "recent": 10,
    "pinned": 10,
}

#: §3.6: ``bm25(memories_fts, 1.0, 0.5, 0.3, 0.1)`` — the weights for
#: ``content``, ``summary``, ``tags``, ``domain``, which is the column order
#: ``memories_fts`` is declared with (migration 0002).
BM25_WEIGHTS: Tuple[float, ...] = (1.0, 0.5, 0.3, 0.1)

_BM25_CALL = "bm25(memories_fts, " + ", ".join(repr(w) for w in BM25_WEIGHTS) + ")"

#: Rows fetched per page. The deadline is checked between pages, which is what
#: makes an interrupted generator return a *partial* list rather than nothing.
_PAGE = 10

#: §3.6's "recent" window. The card also says "in current session", which needs
#: a session id ``RetrievalContext`` does not carry (see the module docstring in
#: ``em/retrieval/__init__.py`` for the recorded gap).
RECENT_WINDOW = timedelta(hours=48)

#: §3.6/EM-308 score factor for one hop of expansion.
_HOP_FACTOR = 0.5

_WORD_RE = re.compile(r"\w+", re.UNICODE)


def _monotonic() -> float:
    """``time.monotonic`` behind a name, so a test can drive the deadline."""
    return time.monotonic()


# --- scope (§3.5) ---------------------------------------------------------


def scope_sql(scope: Scope, *, table: str = "m", owner_only: bool = True) -> Tuple[str, List[Any]]:
    """The §3.5 read rule as a SQL fragment plus its parameters.

    Returns ``(clause, params)`` for ``WHERE <clause>`` against a table aliased
    ``table``. The clause is exactly ``MemoryStore._in_scope``:

    * same profile, and
    * the row is the caller's own or profile-wide, and
    * in a chat context, the row belongs to that chat or is chat-wide, and
    * an owner-only tier (``sensitive``/``secret``) is excluded unless the caller
      is the owner context.

    The owner decision comes from :func:`em.store.types.may_read_owner_only` and
    the chat decision from :func:`em.store.types.chat_in_scope` — the same two
    functions ``MemoryStore._in_scope`` calls — so the SQL form and the
    row-by-row form cannot disagree about who may read what, and
    ``tests/unit/test_em_retrieval_scope_sql.py`` cross-checks them against real
    rows rather than trusting that.

    ``table`` defaults to ``m`` because every retrieval query joins ``memories``
    as ``m``; pass ``table="e"`` for episodes, or ``table=""`` for a bare query.

    ``owner_only`` is False for a table with no ``sensitivity`` column —
    ``episodes`` is the only one — where the tier half of the rule cannot apply
    and only the profile/user/chat halves are emitted.
    """
    prefix = f"{table}." if table else ""
    clause = (
        f"{prefix}scope_profile = ?"
        f" AND ({prefix}scope_user = ? OR {prefix}scope_user = '')"
    )
    params: List[Any] = [scope.profile, scope.user]

    if scope.chat:
        clause += f" AND ({prefix}scope_chat = ? OR {prefix}scope_chat = '')"
        params.append(scope.chat)

    if owner_only and not may_read_owner_only(scope):
        # Exclude the owner-only tiers. The tier names come from the same tuple
        # `_in_scope` consults, so adding one there cannot forget the SQL side.
        #
        # No `IS NULL` escape is needed: `sensitivity` is NOT NULL in the schema
        # (pinned by a test), and if that ever changes, `NOT IN` excludes the
        # NULLs — the safe direction, since a row of unknown tier must not reach
        # a non-owner.
        placeholders = ", ".join("?" for _ in OWNER_ONLY_TIERS)
        clause += f" AND {prefix}sensitivity NOT IN ({placeholders})"
        params.extend(OWNER_ONLY_TIERS)

    return clause, params


# --- types ----------------------------------------------------------------


@dataclass(frozen=True)
class Candidate:
    """One ranked hit: §3.6's ``(owner_type, owner_id, raw_score)``.

    Deliberately three fields. The generator that produced a candidate is known
    to its caller (it named the function), and the rank is the candidate's
    position in the list, so fusion (EM-304) needs nothing else and this stays
    exactly the shape the plan specifies.
    """

    owner_type: str
    owner_id: str
    raw_score: float


@dataclass(frozen=True)
class RetrievalContext:
    """Everything a generator may look at.

    ``aq``, ``scope``, ``now``, ``limits`` and ``deadline`` are the fields §3.6
    names. ``conn`` is not in that list and is still required: a generator's
    whole job is SQL, and the stated signature ``(ctx) -> list[Candidate]``
    gives it nowhere else to get a read connection.

    ``deadline`` is an absolute ``time.monotonic()`` reading (``None`` = no
    deadline), not a wall-clock time, so it cannot be fooled by a clock change.
    ``limits`` overrides :data:`GENERATOR_LIMITS` per generator.
    """

    conn: sqlite3.Connection
    aq: AnalyzedQuery
    scope: Scope
    now: datetime
    deadline: Optional[float] = None
    limits: Mapping[str, int] = field(default_factory=dict)

    def k(self, generator: str) -> int:
        """The row cap for ``generator`` — its limit, else §3.6's default."""
        if generator in self.limits:
            return int(self.limits[generator])
        return int(GENERATOR_LIMITS[generator])

    def out_of_time(self) -> bool:
        """True once the wall has passed the deadline (§3.6's AC)."""
        if self.deadline is None:
            return False
        return _monotonic() >= self.deadline


# --- FTS MATCH expression -------------------------------------------------


def _quote(term: str) -> str:
    """One literal FTS5 phrase, prefixed per §3.6's length rule."""
    quoted = '"' + term.replace('"', '""') + '"'
    return quoted + ("*" if len(term) >= 4 else "")


def match_expression(terms: Sequence[str]) -> str:
    """Build the FTS5 ``MATCH`` expression for a set of analyzed terms.

    EM-301 chooses *which* terms; this only renders them safely. Each term is
    reduced to ``\\w+`` runs so punctuation can never produce an FTS5 syntax
    error, tokens shorter than 2 characters are dropped (§3.6), terms of 4 or
    more characters get the prefix ``*`` and shorter ones are exact (§3.6), and
    the result is capped at :data:`MAX_TERMS`.

    Returns ``''`` when nothing usable remains. Callers **must** treat that as
    "no matches" and skip the query, never as "match everything".
    """
    kept: List[str] = []
    seen = set()
    for raw in terms:
        for token in _WORD_RE.findall(raw):
            key = token.lower()
            if len(token) < 2 or key in seen:
                continue
            seen.add(key)
            kept.append(token)
            if len(kept) >= MAX_TERMS:
                break
        if len(kept) >= MAX_TERMS:
            break
    return " OR ".join(_quote(t) for t in kept)


# --- fetch ----------------------------------------------------------------


def _fetch(ctx: RetrievalContext, sql: str, params: Sequence[Any], k: int) -> List[sqlite3.Row]:
    """Run ``sql`` in pages of :data:`_PAGE`, stopping at ``k`` or the deadline.

    ``sql`` must not carry its own ``LIMIT``/``OFFSET``. The deadline is checked
    *before* each page, so an expired context issues no query at all and one
    that expires mid-scan returns the pages already collected.
    """
    rows: List[sqlite3.Row] = []
    while len(rows) < k:
        if ctx.out_of_time():
            break
        want = min(_PAGE, k - len(rows))
        batch = ctx.conn.execute(
            sql + " LIMIT ? OFFSET ?", (*params, want, len(rows))
        ).fetchall()
        if not batch:
            break
        rows.extend(batch)
    return rows


# --- generators (§3.6) ----------------------------------------------------


def bm25(ctx: RetrievalContext) -> List[Candidate]:
    """Lexical search over ``memories_fts`` with §3.6's column weights."""
    expr = match_expression(ctx.aq.terms)
    if not expr:
        return []
    clause, scope_params = scope_sql(ctx.scope, table="m")
    sql = (
        f"SELECT m.id AS id, {_BM25_CALL} AS score "
        "FROM memories_fts JOIN memories m ON m.rid = memories_fts.rowid "
        "WHERE memories_fts MATCH ? AND m.status = 'active' AND " + clause + " "
        "ORDER BY score"
    )
    rows = _fetch(ctx, sql, [expr, *scope_params], ctx.k("bm25"))
    return [Candidate(OWNER_TYPE_MEMORY, r["id"], -float(r["score"] or 0.0)) for r in rows]


def pinned(ctx: RetrievalContext) -> List[Candidate]:
    """Pinned rows and constraints for the scope; these bypass the gate."""
    clause, params = scope_sql(ctx.scope, table="m")
    sql = (
        "SELECT m.id AS id FROM memories m "
        "WHERE m.status = 'active' AND (m.pinned = 1 OR m.kind = 'constraint') "
        "AND " + clause + " ORDER BY m.pinned DESC, m.updated_at DESC"
    )
    return [
        Candidate(OWNER_TYPE_MEMORY, r["id"], 1.0)
        for r in _fetch(ctx, sql, params, ctx.k("pinned"))
    ]


def recent(ctx: RetrievalContext) -> List[Candidate]:
    """Memories updated in the last 48 h, for temporal and lookup intents."""
    if ctx.aq.intent not in ("temporal", "lookup"):
        return []
    since = to_iso(ctx.now - RECENT_WINDOW)
    clause, params = scope_sql(ctx.scope, table="m")
    sql = (
        "SELECT m.id AS id FROM memories m "
        "WHERE m.status = 'active' AND m.updated_at >= ? AND " + clause + " "
        "ORDER BY m.updated_at DESC"
    )
    return [
        Candidate(OWNER_TYPE_MEMORY, r["id"], 1.0)
        for r in _fetch(ctx, sql, [since, *params], ctx.k("recent"))
    ]


def episodic(ctx: RetrievalContext) -> List[Candidate]:
    """Episodes by FTS, optionally narrowed by an analyzed time window.

    Returns ``owner_type='episode'`` (§3.6). ``episodes`` has no ``status`` and
    no ``sensitivity`` column, so neither applies: the scope clause is the
    profile/user half only, and every episode row is live.
    """
    expr = match_expression(ctx.aq.terms)
    if not expr:
        return []
    clause, scope_params = scope_sql(ctx.scope, table="e", owner_only=False)
    where = ["episodes_fts MATCH ?", clause]
    params: List[Any] = [expr, *scope_params]

    window = ctx.aq.temporal
    if window is not None:
        # §3.6/§3.10: an episode's world time is `start_at`, falling back to
        # when it was written.
        column = "COALESCE(e.start_at, e.created_at)"
        if window.start is not None:
            where.append(f"{column} >= ?")
            params.append(to_iso(window.start))
        if window.end is not None:
            where.append(f"{column} <= ?")
            params.append(to_iso(window.end))

    sql = (
        "SELECT e.id AS id, bm25(episodes_fts) AS score "
        "FROM episodes_fts JOIN episodes e ON e.rid = episodes_fts.rowid "
        "WHERE " + " AND ".join(where) + " ORDER BY score"
    )
    rows = _fetch(ctx, sql, params, ctx.k("episodic"))
    return [Candidate(OWNER_TYPE_EPISODE, r["id"], -float(r["score"] or 0.0)) for r in rows]


def entity(ctx: RetrievalContext) -> List[Candidate]:
    """Memories mentioning a detected entity, then one hop out via relations.

    Direct hits score ``1.0``; a memory reached through a relation scores
    ``0.5``, the same one-hop factor EM-308 uses for wikilink expansion. The
    hop is only walked if the direct pass left room under ``k`` (and time on
    the clock), so a query with easily-satisfied direct hits stays cheap.
    """
    entity_ids = list(ctx.aq.entities)
    if not entity_ids:
        return []
    k = ctx.k("entity")
    marks = ", ".join("?" for _ in entity_ids)
    clause, scope_params = scope_sql(ctx.scope, table="m")

    direct_sql = (
        "SELECT m.id AS id FROM memory_entities me JOIN memories m ON m.id = me.memory_id "
        f"WHERE me.entity_id IN ({marks}) AND m.status = 'active' AND {clause} "
        "ORDER BY m.importance DESC, m.updated_at DESC"
    )
    direct = _fetch(ctx, direct_sql, [*entity_ids, *scope_params], k)
    out = [Candidate(OWNER_TYPE_MEMORY, r["id"], 1.0) for r in direct]
    seen = {c.owner_id for c in out}
    if len(out) >= k or ctx.out_of_time():
        return out

    hop_sql = (
        "SELECT DISTINCT m.id AS id FROM relations r JOIN memories m ON m.id = r.memory_id "
        f"WHERE (r.subject_id IN ({marks}) OR r.object_id IN ({marks})) "
        f"AND r.memory_id IS NOT NULL AND r.scope_profile = ? "
        "AND m.status = 'active' AND " + clause + " "
        "ORDER BY m.importance DESC, m.updated_at DESC"
    )
    hop_params = [*entity_ids, *entity_ids, ctx.scope.profile, *scope_params]
    for row in _fetch(ctx, hop_sql, hop_params, k):
        if row["id"] in seen:
            continue
        seen.add(row["id"])
        out.append(Candidate(OWNER_TYPE_MEMORY, row["id"], _HOP_FACTOR))
        if len(out) >= k:
            break
    return out


#: §3.6's generators, by name. ``vector`` joins in EM-303.
GENERATORS: Mapping[str, Callable[[RetrievalContext], List[Candidate]]] = {
    "bm25": bm25,
    "entity": entity,
    "episodic": episodic,
    "recent": recent,
    "pinned": pinned,
}
