"""Supersession/duplicate collapse and MMR diversity — EM-305 (plan §3.6).

The two stages after the gate:

    survivors ──▶ collapse ──▶ MMR diversity ──▶ token packer (EM-307)

**Collapse** (§3.6: "drop `superseded` (but mark successor with `(updated <date>;
was: <old summary>)` when the old one was a candidate or changed < 30 days ago)")
does three things here:

* superseded *rows* are already absent — ``status='active'`` is enforced all the
  way down from the generators, so "drop superseded" is a property of the pipeline
  rather than a filter repeated here;
* **exact-hash duplicates across scopes** collapse, preferring the narrower scope.
  The content hash cannot do this: ``MemoryStore._content_hash`` mixes the scope
  *into* the digest, so two identical sentences in different scopes hash
  differently. The collapse therefore groups on the loaded **text**, which is what
  the hash was derived from anyway;
* a successor whose predecessor changed inside :data:`SUPERSEDED_NOTE_WINDOW`
  gains the ``superseded_note`` flag, and its predecessors come back on
  :class:`CollapseResult` for the renderer. §3.6's other disjunct — "or the old one
  was a candidate" — cannot arise in an active-only pipeline, and that is recorded
  rather than faked.

**Diversity** is MMR with λ = 0.7 over the top 20 (§3.6), on embedding cosine with
a **token-Jaccard fallback** — which is the path taken today, since the embeddings
are EM-303's. Hits past the top 20 are not diversified and keep their rank order.

Stdlib only (plan §3.2).
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from ..clock import parse_iso
from ..store.types import Scope
from .candidates import OWNER_TYPE_MEMORY, scope_sql
from .fusion import Key, Ranking

__all__ = [
    "MMR_LAMBDA",
    "MMR_TOP",
    "SUPERSEDED_NOTE_FLAG",
    "SUPERSEDED_NOTE_WINDOW",
    "CollapseResult",
    "Predecessor",
    "collapse",
    "jaccard",
    "load_predecessors",
    "mmr",
    "render_superseded_note",
    "tokens",
]

#: §3.6's MMR parameters.
MMR_LAMBDA = 0.7
MMR_TOP = 20

#: §3.6's "changed < 30 days ago".
SUPERSEDED_NOTE_WINDOW = timedelta(days=30)

#: The `why_retrieved` flag a successor carries when its predecessor changed
#: recently (§3.6 lists it by this name).
SUPERSEDED_NOTE_FLAG = "superseded_note"

_WORD_RE = re.compile(r"\w+", re.UNICODE)


# --- diversity ------------------------------------------------------------


def tokens(text: str) -> frozenset:
    """The candidate's token set, for the Jaccard fallback."""
    return frozenset(token.casefold() for token in _WORD_RE.findall(text or ""))


def jaccard(left: frozenset, right: frozenset) -> float:
    """Set similarity in ``[0, 1]``; two empty sets are *not* similar."""
    if not left or not right:
        return 0.0
    union = left | right
    return len(left & right) / len(union)


def mmr(
    rankings: Sequence[Ranking],
    *,
    texts: Mapping[Key, str],
    lambda_: float = MMR_LAMBDA,
    top: int = MMR_TOP,
) -> List[Ranking]:
    """Maximal Marginal Relevance over the top ``top`` hits (§3.6).

    Greedy and deterministic: each step takes the candidate with the highest
    ``λ * score − (1 − λ) * max similarity to anything already chosen``, ties going
    to the better-ranked one. Only the head is diversified — §3.6 scopes MMR to
    "the top 20" — and the remainder keeps its order behind it.
    """
    if len(rankings) <= 1:
        return list(rankings)

    head = list(rankings[:top])
    tail = list(rankings[top:])
    sets = {ranking.key: tokens(texts.get(ranking.key, "")) for ranking in rankings}

    chosen = [head.pop(0)]
    while head:
        best_index = 0
        best_value: Optional[float] = None
        for index, candidate in enumerate(head):
            redundancy = max(
                (jaccard(sets[candidate.key], sets[picked.key]) for picked in chosen),
                default=0.0,
            )
            value = lambda_ * candidate.score - (1.0 - lambda_) * redundancy
            if best_value is None or value > best_value:
                best_index, best_value = index, value
        chosen.append(head.pop(best_index))

    return chosen + tail


# --- collapse -------------------------------------------------------------


@dataclass(frozen=True)
class Predecessor:
    """A memory this one replaced."""

    memory_id: str
    summary: str
    changed_at: Optional[datetime]


@dataclass(frozen=True)
class CollapseResult:
    kept: List[Ranking]
    #: Successor key → the predecessors that earn a ``superseded_note``.
    predecessors: Dict[Key, Tuple[Predecessor, ...]]
    #: Keys dropped as duplicates of a narrower-scoped twin.
    duplicates: Tuple[Key, ...]


def render_superseded_note(predecessor: Predecessor) -> str:
    """§3.6's rendering: ``(updated <date>; was: <old summary>)``."""
    when = predecessor.changed_at.date().isoformat() if predecessor.changed_at else "unknown"
    return f"(updated {when}; was: {predecessor.summary})"


def collapse(
    rankings: Sequence[Ranking],
    *,
    texts: Mapping[Key, str],
    scope_users: Mapping[Key, str],
    predecessors: Optional[Mapping[Key, Sequence[Predecessor]]] = None,
    now: Optional[datetime] = None,
    window: timedelta = SUPERSEDED_NOTE_WINDOW,
) -> CollapseResult:
    """Collapse duplicates and supersession chains, and flag recent successors.

    Two collapses, both from §3.6:

    * **exact duplicates across scopes** — identical text keeps the *narrower*
      scope (a user-scoped row over a profile-wide one), ties to the better rank.
      Two users storing one sentence is the case this exists for: the sentence is
      one answer, and the row that belongs to the asking user is the one to show;
    * **chains (safety)** — if one surviving candidate is the predecessor of
      another, they are one chain with two live members (only reachable after a
      ``restore``), so the older one goes. Candidates are otherwise active-only, so
      a chain has exactly one live member and this is a guard, not a filter.

    The order of the input is preserved, so MMR's view of "best first" is intact.
    """
    moment = now or datetime.now(timezone.utc)
    order = {ranking.key: index for index, ranking in enumerate(rankings)}

    # 1. exact duplicates across scopes.
    groups: Dict[str, List[Ranking]] = {}
    kept: List[Ranking] = []
    for ranking in rankings:
        text = (texts.get(ranking.key) or "").strip()
        if text:
            groups.setdefault(text, []).append(ranking)
        else:
            kept.append(ranking)

    duplicates: List[Key] = []
    for group in groups.values():
        if len(group) == 1:
            kept.append(group[0])
            continue

        def preference(ranking: Ranking) -> Tuple[int, int]:
            # narrower scope first (a user-scoped row beats a profile-wide one),
            # then the better rank.
            narrow = 0 if scope_users.get(ranking.key, "") else 1
            return (narrow, order[ranking.key])

        winner = min(group, key=preference)
        kept.append(winner)
        duplicates.extend(r.key for r in group if r.key != winner.key)

    kept.sort(key=lambda ranking: order[ranking.key])

    # 2. chain safety: drop an older member of a live chain.
    chains = {key: {p.memory_id for p in group} for key, group in (predecessors or {}).items()}
    superseded_live = {
        other.key
        for ranking in kept
        for other in kept
        if other.key != ranking.key and other.key[1] in chains.get(ranking.key, set())
    }
    if superseded_live:
        # `other` is an ancestor of a member that is also live: the chain has two
        # active members, and the successor is the one to keep.
        kept = [ranking for ranking in kept if ranking.key not in superseded_live]

    # 3. the note, for successors whose predecessor changed recently.
    noted: Dict[Key, Tuple[Predecessor, ...]] = {}
    flagged: List[Ranking] = []
    for ranking in kept:
        recent = tuple(
            predecessor
            for predecessor in (predecessors or {}).get(ranking.key, ())
            if predecessor.changed_at is None or (moment - predecessor.changed_at) <= window
        )
        if recent:
            noted[ranking.key] = recent
            flagged.append(replace(ranking, why=ranking.why + (SUPERSEDED_NOTE_FLAG,)))
        else:
            flagged.append(ranking)

    return CollapseResult(kept=flagged, predecessors=noted, duplicates=tuple(duplicates))


def load_predecessors(
    conn: sqlite3.Connection, *, scope: Scope, keys: Iterable[Key]
) -> Dict[Key, Tuple[Predecessor, ...]]:
    """The superseded rows each candidate replaced (§3.6), newest first.

    ``superseded_by`` points forward, so the predecessors of a key are the rows
    whose ``superseded_by`` is that id. The change time is ``valid_to`` — set when
    the row was superseded — falling back to ``updated_at`` for a row migrated
    without one. Scope is applied: a predecessor belongs to its successor's scope,
    and a note must not quote text the caller may not read.
    """
    memory_ids = sorted({key[1] for key in set(keys) if key[0] == OWNER_TYPE_MEMORY})
    if not memory_ids:
        return {}

    clause, params = scope_sql(scope, table="m")
    marks = ",".join("?" for _ in memory_ids)
    rows = conn.execute(
        f"SELECT m.id, m.superseded_by, m.summary, m.content,"
        f" COALESCE(m.valid_to, m.updated_at) AS changed_at"
        f" FROM memories m WHERE m.superseded_by IN ({marks})"
        f" AND m.status = 'superseded' AND {clause}"
        f" ORDER BY changed_at DESC",
        (*memory_ids, *params),
    ).fetchall()

    grouped: Dict[Key, List[Predecessor]] = {}
    for row in rows:
        key = (OWNER_TYPE_MEMORY, str(row["superseded_by"]))
        grouped.setdefault(key, []).append(
            Predecessor(
                memory_id=str(row["id"]),
                summary=str(row["summary"] or row["content"]),
                changed_at=parse_iso(row["changed_at"]) if row["changed_at"] else None,
            )
        )
    return {key: tuple(group) for key, group in grouped.items()}
