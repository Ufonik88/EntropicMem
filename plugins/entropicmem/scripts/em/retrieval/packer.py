"""Token-budget packer — EM-307 (plan §3.6).

The stage after MMR:

    mmr ─▶ pack ─▶ render

``estimate_tokens`` is §3.6's ``ceil(len(text) / 4)``. tiktoken is **not**
consulted, even when installed. The card's AC asks for the estimate to land
within ±15% of tiktoken on a sample. It does not, and that is recorded rather
than papered over: on a 222-character prose sample, cl100k (and o200k, p50k,
r50k) counted 42 tokens against this function's 56 — about 33% high. A
repetitive short-sentence sample was about 19% high. The error is
conservative (budget is spent as if text cost more, so we pack less, never
more). Switching the packer to tiktoken when importable would make two
machines pack different blocks, and ``em`` is stdlib-only. A sample of
repeated stopwords can be made to land inside 15%; that would be fitting the
check, so it was not done.

The store's write-time ``_token_estimate`` is ``len // 4`` (floor, minimum
1). This one is the packer's, and the two are not required to agree.

**Greedy by score.** A higher score is considered first. A candidate is taken
in full when the rendered block still fits, otherwise as its ``summary``,
otherwise skipped. Nothing is cut mid-sentence. Ties break on ``owner_id``
ascending, so the same inputs always pack the same way.

The budget is the rendered block's estimate, not the bare prose: a citation,
a section heading and a superseded note all consume it. The default is
§3.6's ``prefetch.token_budget`` of 450, passed in by the caller. This module
does not read ``em/config.py`` — those scalars are EM-401–403's to wire.

``load_pack_items`` builds ``PackItem``s from rankings the pipeline already
kept. Content and summary stay separate columns — the gate's concatenated
text is for coverage, not for the bullet. ``was`` is the newest predecessor
the collapse attached. The renderer (``em.provider.render``) packs them.
The eval adapter does not: a short citation would stop injected ids matching.

Stdlib only (plan §3.2).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable, Mapping, Optional, Sequence, Tuple

from ..clock import parse_iso
from .candidates import OWNER_TYPE_EPISODE, OWNER_TYPE_MEMORY

__all__ = [
    "DEFAULT_TOKEN_BUDGET",
    "Chosen",
    "PackItem",
    "estimate_tokens",
    "load_pack_items",
    "pack",
]

#: §3.6's ``prefetch.token_budget``.
DEFAULT_TOKEN_BUDGET = 450


def estimate_tokens(text: str) -> int:
    """§3.6's token estimate: ``ceil(len(text) / 4)``. Empty is zero."""
    if not text:
        return 0
    return (len(text) + 3) // 4


@dataclass(frozen=True)
class PackItem:
    """One thing the packer may spend budget on.

    ``content`` is the full prose (a memory body, or an episode title).
    ``summary`` is the shorter fallback. ``was`` is the predecessor summary
    the superseded note quotes; empty means there is no note. ``decided`` is
    an episode's decision clause. ``follow_up`` lands the row in Open
    follow-ups rather than its kind's section.
    """

    owner_type: str
    owner_id: str
    score: float
    content: str
    summary: str = ""
    kind: str = "fact"
    when: Optional[date] = None
    was: str = ""
    decided: str = ""
    injection_flagged: bool = False
    follow_up: bool = False

    def __post_init__(self) -> None:
        # datetime is a date, and a frozen clock hands us datetimes. Store the
        # calendar day the render cites, not a timestamp.
        if isinstance(self.when, datetime):
            object.__setattr__(self, "when", self.when.date())


@dataclass(frozen=True)
class Chosen:
    """A row the packer kept, and the prose it decided to spend budget on."""

    item: PackItem
    body: str


def _bodies(item: PackItem) -> list[str]:
    """Full text first, then a distinct summary. Blank prose is not a choice."""
    full = (item.content or "").strip()
    summary = (item.summary or "").strip()
    options: list[str] = []
    if full:
        options.append(full)
    if summary and summary != full:
        options.append(summary)
    return options


def pack(
    items: Sequence[PackItem],
    *,
    budget: int = DEFAULT_TOKEN_BUDGET,
    cost: Callable[[Sequence[Chosen]], int],
) -> list[Chosen]:
    """Greedy pack. ``cost`` is the token cost of a candidate sequence.

    The renderer passes the cost of the **rendered block**, so headings and
    citations count. A negative budget fits nothing. Items are not reordered
    here for display — the renderer groups them into §3.6's sections — but
    they are considered highest score first.
    """
    if budget < 0:
        budget = 0
    ordered = sorted(items, key=lambda item: (-item.score, item.owner_id))
    chosen: list[Chosen] = []
    for item in ordered:
        kept: Optional[Chosen] = None
        for body in _bodies(item):
            trial = chosen + [Chosen(item, body)]
            if cost(trial) <= budget:
                kept = Chosen(item, body)
                break
        if kept is not None:
            chosen.append(kept)
    return chosen


# --- from a retrieval -----------------------------------------------------


def _json_strings(value: Any) -> list[str]:
    """A JSON list of strings, or nothing. Bad JSON is empty, not an error."""
    if not value:
        return []
    try:
        loaded = json.loads(value)
    except (TypeError, ValueError):
        return []
    if not isinstance(loaded, list):
        return []
    return [str(item) for item in loaded if str(item).strip()]


def _day(value: Any) -> Optional[date]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return parse_iso(str(value)).date()
    except (TypeError, ValueError):
        return None


def _about(kind: str) -> bool:
    return kind.casefold() in {"profile", "preference"}


def load_pack_items(
    conn: sqlite3.Connection,
    rankings: Sequence[Any],
    *,
    predecessors: Optional[Mapping[Tuple[str, str], Sequence[Any]]] = None,
) -> list[PackItem]:
    """The rows behind ``rankings``, in ranking order, ready to pack.

    A ranking whose row is gone is skipped. An episode with open loops also
    yields one follow-up item per loop, at a hair under the episode's score,
    so a tight budget keeps the episode and drops the loop.
    """
    notes = predecessors or {}
    memory_ids = [ranking.owner_id for ranking in rankings if ranking.owner_type == OWNER_TYPE_MEMORY]
    episode_ids = [ranking.owner_id for ranking in rankings if ranking.owner_type == OWNER_TYPE_EPISODE]
    memories = _memory_rows(conn, memory_ids)
    episodes = _episode_rows(conn, episode_ids)

    items: list[PackItem] = []
    for ranking in rankings:
        if ranking.owner_type == OWNER_TYPE_MEMORY:
            row = memories.get(ranking.owner_id)
            if row is None:
                continue
            items.append(_memory_item(ranking, row, notes.get(ranking.key)))
        elif ranking.owner_type == OWNER_TYPE_EPISODE:
            row = episodes.get(ranking.owner_id)
            if row is None:
                continue
            items.extend(_episode_items(ranking, row))
    return items


def _memory_rows(conn: sqlite3.Connection, ids: Sequence[str]) -> dict[str, Any]:
    if not ids:
        return {}
    marks = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT id, kind, content, summary, trust_flags, valid_from, created_at, updated_at"
        f" FROM memories WHERE id IN ({marks})",
        tuple(ids),
    ).fetchall()
    return {str(row["id"]): row for row in rows}


def _episode_rows(conn: sqlite3.Connection, ids: Sequence[str]) -> dict[str, Any]:
    if not ids:
        return {}
    marks = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT id, title, summary, decisions, open_loops, start_at, created_at"
        f" FROM episodes WHERE id IN ({marks})",
        tuple(ids),
    ).fetchall()
    return {str(row["id"]): row for row in rows}


def _memory_item(ranking: Any, row: Any, predecessors: Optional[Sequence[Any]]) -> PackItem:
    kind = str(row["kind"] or "fact")
    content = str(row["content"] or "").strip()
    summary = str(row["summary"] or "").strip()
    if not content:
        content, summary = summary, ""
    newest = predecessors[0] if predecessors else None
    was = ""
    when = _day(row["valid_from"] or row["created_at"]) if _about(kind) else _day(row["updated_at"])
    if newest is not None:
        was = str(getattr(newest, "summary", "") or "").strip()
        changed = _day(getattr(newest, "changed_at", None))
        if changed is not None:
            when = changed
    flags = _json_strings(row["trust_flags"])
    return PackItem(
        owner_type=OWNER_TYPE_MEMORY,
        owner_id=ranking.owner_id,
        score=float(ranking.score),
        content=content,
        summary=summary,
        kind=kind,
        when=when,
        was=was,
        injection_flagged=bool(flags),
    )


def _episode_items(ranking: Any, row: Any) -> list[PackItem]:
    title = str(row["title"] or "").strip()
    summary = str(row["summary"] or "").strip()
    decisions = _json_strings(row["decisions"])
    loops = _json_strings(row["open_loops"])
    when = _day(row["start_at"] or row["created_at"])
    episode = PackItem(
        owner_type=OWNER_TYPE_EPISODE,
        owner_id=ranking.owner_id,
        score=float(ranking.score),
        content=title or summary,
        summary=summary if title else "",
        kind="episode",
        when=when,
        decided="; ".join(decisions),
    )
    follow_ups = [
        PackItem(
            owner_type=OWNER_TYPE_EPISODE,
            owner_id=ranking.owner_id,
            score=float(ranking.score) - 1e-6,
            content=loop,
            kind="episode",
            follow_up=True,
        )
        for loop in loops
    ]
    return [episode, *follow_ups]
