"""Abstention gate — EM-305 (plan §3.6).

The stage that decides whether the memory block should be shown at all:

    ranked hits ──▶ support test ──▶ score threshold ──▶ survivors
                   (coverage | cosine | entity | pinned)   (score ≥ min_score)

A candidate is **supported** iff at least one of these holds (§3.6):

* lexical coverage ≥ ``gate.min_coverage`` (default 0.34);
* vector cosine ≥ ``gate.min_cosine[model]``;
* an entity hit from the analyzer;
* ``pinned``.

then ``score ≥ gate.min_score`` (default 0.30). If nothing survives, the memory
section is omitted entirely — only pinned constraints and core deltas may remain.

**Coverage is specified "post-stem", and that is the trap this module exists to
avoid.** ``memories_fts`` is tokenized with ``porter unicode61``, and the standard
library has no porter stemmer, so a naive Python comparison under-counts exactly
where the tokenizer disagrees with the surface form — ``preferences`` against a
stored ``preferred``, ``runs`` against ``running`` — and because the gate is a
hard filter, an under-count silently abstains on an answer the generators had
already found. :func:`coverage` therefore measures with **the same tokenizer**:
the texts go into a transient in-memory FTS5 table declared exactly as
``memories_fts`` is, and one ``MATCH`` per query term reads back which candidates
contain it. "Post-stem" is then true by construction rather than approximated.

Stdlib only (plan §3.2).
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Optional, Sequence

from ..store.types import Scope
from .candidates import OWNER_TYPE_EPISODE, OWNER_TYPE_MEMORY, scope_sql
from .fusion import Key, Ranking

__all__ = [
    "DEFAULT_GATE",
    "GATE_MIN_COSINE",
    "GATE_MIN_COVERAGE",
    "GATE_MIN_SCORE",
    "GateConfig",
    "GateResult",
    "RowInfo",
    "apply_gate",
    "coverage",
    "index_tokenizer",
    "load_rows",
    "supported",
    "tokenizer_matches_index",
]

#: §3.6's defaults.
GATE_MIN_COVERAGE = 0.34
GATE_MIN_SCORE = 0.30
GATE_MIN_COSINE: Mapping[str, float] = {
    "bge-small-en-v1.5": 0.62,
    "all-MiniLM-L6-v2": 0.38,
}

#: The tokenizer ``memories_fts`` is declared with (migration 0002). Coverage has
#: to use the same one, or it measures a different notion of "the same word".
#:
#: **This constant is coupled to the index, and the coupling is pinned by a test
#: (`test_the_gate_tokenizer_matches_the_index_tokenizer`) rather than trusted.** An
#: index change that this constant did not follow would make coverage measure a
#: different tokenizer again — and because the gate is a hard filter, it would
#: start silently abstaining on answers the generators had found. If that test
#: fails, re-point :func:`coverage` at the new tokenizer; do not relax the test.
_TOKENIZE = "porter unicode61 remove_diacritics 2"

_TOKENIZE_RE = re.compile(r"tokenize\s*=\s*'([^']+)'")


@dataclass(frozen=True)
class GateConfig:
    """§3.6's ``gate.*`` thresholds.

    There is no config module yet (EM-407 owns it), so these are the spec's
    numbers as defaults the caller may override — the same shape as EM-301's
    ``extra_stopwords`` and EM-304's ``RankWeights``.
    """

    min_coverage: float = GATE_MIN_COVERAGE
    min_score: float = GATE_MIN_SCORE
    min_cosine: Mapping[str, float] = field(default_factory=lambda: dict(GATE_MIN_COSINE))
    #: §3.6's third support condition needs a cosine, which needs the embedding
    #: backend and a model name — EM-303. Until then the condition is present but
    #: **off**, and a caller with a cosine can switch it on and pass ``cosines``.
    cosine_enabled: bool = False


DEFAULT_GATE = GateConfig()


@dataclass(frozen=True)
class RowInfo:
    """What the gate needs from the row that a :class:`Ranking` does not carry."""

    text: str
    scope_user: str
    #: True when the row is pinned **or is a ``kind='constraint'`` row**: §3.6's
    #: generator table attaches "bypasses gate" to the pinned generator, whose
    #: input is ``pinned=1`` or ``kind='constraint'``. Reading only the column
    #: here filtered a constraint-kind row the generator had just surfaced —
    #: found by P0b's end-to-end run (the same shape of defect as P0a's raw id
    #: comparison).
    pinned: bool


@dataclass(frozen=True)
class GateResult:
    """The survivors, with the pinned ones always among them.

    §3.6's generator table says ``pinned`` "bypasses gate (still budgeted)", and
    its fallback says only pinned constraints may remain — so a pinned candidate
    is never filtered out here, and the renderer decides what a block containing
    nothing else looks like.
    """

    survivors: List[Ranking]

    @property
    def empty(self) -> bool:
        return not self.survivors

    @property
    def keeps_only_pinned(self) -> bool:
        return bool(self.survivors) and all(
            _is_pinned_signal(ranking) for ranking in self.survivors
        )


def _is_pinned_signal(ranking: Ranking) -> bool:
    """True when ``pinned`` is the only reason this hit could have survived."""
    return "pinned" in {signal.signal for signal in ranking.signals}


def load_rows(
    conn: sqlite3.Connection, *, scope: Scope, keys: Iterable[Key]
) -> Dict[Key, RowInfo]:
    """Load the gate's row inputs, keeping only rows this scope admits.

    The gate needs the candidate's **text** (for coverage; ``Ranking`` carries
    only scores and generator names), its ``scope_user`` (the collapse prefers the
    narrower scope) and whether it is ``pinned``. Like ``fusion.load_features``,
    both queries re-apply §3.5 through ``scope_sql`` and memories additionally
    require ``status='active'`` — deliberately redundant, because this is the last
    point before the text would be shown.

    ``pinned`` here is the §3.6 input, not merely the column: the pinned
    generator surfaces ``pinned=1`` **and** ``kind='constraint'`` rows, and the
    generator table's last column says its hits bypass the gate. Reading only
    the column dropped a constraint-kind row the generator had just found — a
    hard filter silently disagreeing with its own generator (found by P0b's
    end-to-end run; pinned by tests both ways).
    """
    wanted = set(keys)
    memory_ids = sorted({key[1] for key in wanted if key[0] == OWNER_TYPE_MEMORY})
    episode_ids = sorted({key[1] for key in wanted if key[0] == OWNER_TYPE_EPISODE})
    found: Dict[Key, RowInfo] = {}

    if memory_ids:
        clause, params = scope_sql(scope, table="m")
        marks = ",".join("?" for _ in memory_ids)
        rows = conn.execute(
            f"SELECT m.id, m.content, m.summary, m.scope_user, m.pinned, m.kind"
            f" FROM memories m WHERE m.id IN ({marks}) AND m.status = 'active' AND {clause}",
            (*memory_ids, *params),
        ).fetchall()
        for row in rows:
            text = f"{row['content']} {row['summary']}".strip()
            found[(OWNER_TYPE_MEMORY, str(row["id"]))] = RowInfo(
                text=text,
                scope_user=str(row["scope_user"]),
                pinned=bool(row["pinned"]) or str(row["kind"]) == "constraint",
            )

    if episode_ids:
        # `episodes` has no `sensitivity`/`visibility`, so the tier half of §3.5
        # cannot apply (the same reason the episodic generator passes
        # `owner_only=False`). It has no `pinned` either: an episode is a record,
        # so it can never bypass the gate.
        clause, params = scope_sql(scope, table="e", owner_only=False)
        marks = ",".join("?" for _ in episode_ids)
        rows = conn.execute(
            f"SELECT e.id, e.title, e.summary, e.scope_user"
            f" FROM episodes e WHERE e.id IN ({marks}) AND {clause}",
            (*episode_ids, *params),
        ).fetchall()
        for row in rows:
            found[(OWNER_TYPE_EPISODE, str(row["id"]))] = RowInfo(
                text=f"{row['title']} {row['summary']}".strip(),
                scope_user=str(row["scope_user"]),
                pinned=False,
            )

    return found


def index_tokenizer(conn: sqlite3.Connection) -> str:
    """The tokenizer ``memories_fts`` is *actually* declared with, read from the schema.

    The authority for the coupling :data:`_TOKENIZE` depends on.
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name = 'memories_fts'"
    ).fetchone()
    if row is None or not row[0]:
        return ""
    found = _TOKENIZE_RE.search(str(row[0]))
    return found.group(1) if found else ""


def tokenizer_matches_index(conn: sqlite3.Connection) -> bool:
    """True when :func:`coverage` measures with the tokenizer the index was built with."""
    return index_tokenizer(conn) == _TOKENIZE


def coverage(
    terms: Sequence[str],
    texts: Mapping[Key, str],
    *,
    tokenize: str = _TOKENIZE,
) -> Dict[Key, float]:
    """Lexical coverage per candidate, **measured with FTS5's own tokenizer**.

    §3.6: "coverage = matched non-stopword query terms (post-stem) / total query
    terms, computed in Python on the candidate text". The numerator is the number
    of query terms FTS5 finds in the candidate's text; the denominator is the
    number of terms. Callers pass ``AnalyzedQuery.terms``, which EM-301 has already
    stripped of stopwords and 1-character tokens.

    The index is a throwaway in-memory FTS5 table declared with the same tokenizer
    as ``memories_fts``, so a term matches exactly when it would have matched in
    the real query — including across stems. One ``MATCH`` per term covers every
    candidate at once, so the cost is a table build plus at most 12 probes, not
    one query per candidate.

    With no usable terms every candidate scores 0.0: there is nothing to cover, and
    answering "fully covered" would let a query of pure stopwords through the gate
    on a lexical claim it has not earned. Such a query still surfaces entity or
    pinned hits, which is the honest outcome.
    """
    if not texts:
        return {}

    usable = [str(term) for term in terms if str(term).strip()]
    if not usable:
        return {key: 0.0 for key in texts}

    index = sqlite3.connect(":memory:")
    try:
        index.execute(f"CREATE VIRTUAL TABLE cover USING fts5(x, tokenize='{tokenize}')")
        by_rowid: Dict[int, Key] = {}
        for rowid, (key, text) in enumerate(texts.items(), start=1):
            by_rowid[rowid] = key
            index.execute(
                "INSERT INTO cover(rowid, x) VALUES (?, ?)", (rowid, text or "")
            )
        matched = {key: 0 for key in texts}
        for term in usable:
            expression = '"' + term.replace('"', '""') + '"'
            for row in index.execute(
                "SELECT rowid FROM cover WHERE cover MATCH ?", (expression,)
            ):
                matched[by_rowid[int(row[0])]] += 1
    finally:
        index.close()

    total = len(usable)
    return {key: count / total for key, count in matched.items()}


def supported(
    ranking: Ranking,
    *,
    coverage: float,
    pinned: bool,
    entity_hit: bool,
    cosine: Optional[float] = None,
    model: Optional[str] = None,
    config: Optional[GateConfig] = None,
) -> bool:
    """§3.6's support test — "at least one holds".

    Pinned bypasses outright (§3.6's generator table: "bypasses gate (still
    budgeted)"), so it does not need coverage, a cosine or an entity.
    """
    if pinned:
        return True
    settings = config or DEFAULT_GATE
    if coverage >= settings.min_coverage:
        return True
    if entity_hit:
        return True
    if settings.cosine_enabled and cosine is not None and model is not None:
        threshold = settings.min_cosine.get(model)
        if threshold is not None and cosine >= threshold:
            return True
    return False


def apply_gate(
    rankings: Sequence[Ranking],
    *,
    rows: Mapping[Key, RowInfo],
    coverages: Mapping[Key, float],
    config: Optional[GateConfig] = None,
    cosines: Optional[Mapping[Key, float]] = None,
    model: Optional[str] = None,
) -> GateResult:
    """Keep the supported candidates that also clear the score threshold.

    A ranking with no ``RowInfo`` is dropped: the row is not visible to this
    caller, or it stopped being active after the generators ran, and the gate must
    not be the place where that is discovered by rendering it.
    """
    settings = config or DEFAULT_GATE
    survivors: List[Ranking] = []

    for ranking in rankings:
        info = rows.get(ranking.key)
        if info is None:
            continue
        if info.pinned:
            survivors.append(ranking)
            continue
        entity_hit = any(signal.signal == "entity" for signal in ranking.signals)
        if not supported(
            ranking,
            coverage=coverages.get(ranking.key, 0.0),
            pinned=False,
            entity_hit=entity_hit,
            cosine=(cosines or {}).get(ranking.key),
            model=model,
            config=settings,
        ):
            continue
        if ranking.score < settings.min_score:
            continue
        survivors.append(ranking)

    return GateResult(survivors=survivors)
