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

What a caller does with the chosen rows is the renderer's (``em.provider.render``).
``pipeline.retrieve`` does not call this yet: the eval adapter still emits full
ids, and §3.6's short citation would stop those ids matching.

Stdlib only (plan §3.2).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable, Optional, Sequence

__all__ = [
    "DEFAULT_TOKEN_BUDGET",
    "Chosen",
    "PackItem",
    "estimate_tokens",
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
