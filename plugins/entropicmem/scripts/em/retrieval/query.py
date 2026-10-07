"""``AnalyzedQuery`` — what the generators are handed (§3.6).

Only the *type* lives here today. EM-301 owns this file and adds the analyzer
that produces it (tokenising, the stopword list, IDF term selection, the intent
heuristic, entity-alias lookup); EM-302 consumes it. Keeping the shape here
rather than in ``candidates.py`` means EM-301 fills in a file that already
exists, and the two cards cannot disagree about the field names.

``query_rewrite`` (§3.6, optional) is likewise EM-301's: it only ever runs on
the background precompute path, so nothing here calls it.

Stdlib only (plan §3.2); no Hermes imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from .temporal import TimeRange

__all__ = ["INTENTS", "AnalyzedQuery"]

#: §3.6's intent heuristic labels. ``lookup`` is the default.
INTENTS: Tuple[str, ...] = ("profile", "temporal", "procedural", "lookup")


@dataclass(frozen=True)
class AnalyzedQuery:
    """The six fields §3.6 names, in the order the plan names them.

    ``raw`` is the message as received; ``text`` is the text actually analysed
    (the host strips its skill scaffolding and EM-301 strips any
    ``<memory-context>`` block defensively). ``terms`` are the IDF-selected
    tokens EM-301 chose — a candidate generator quotes them for FTS5, it does
    not re-select them.
    """

    raw: str
    text: str
    terms: Tuple[str, ...] = ()
    temporal: Optional[TimeRange] = None
    entities: Tuple[str, ...] = ()
    intent: str = "lookup"
