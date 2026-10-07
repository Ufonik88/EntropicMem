"""``AnalyzedQuery`` and the analyzer that produces one (§3.6, EM-301).

The pipeline, in §3.6's order:

    text ──▶ strip <memory-context> ──▶ \\w+ tokens ──▶ drop stopwords/len<2
         ──▶ IDF-select ≤ 12 terms ──▶ intent ──▶ entities ──▶ temporal

Everything here is deterministic and stdlib-only. EM-302 consumes the result;
EM-310 owns the *full* temporal grammar (this module handles the common shapes
and says so); EM-407 owns the config that supplies ``extra_stopwords``.

Two gaps §3.6 names that have no source in this repo yet, both recorded rather
than invented:

* **``write_generation``.** §3.6 says the IDF table is "cached per
  ``write_generation``". Nothing in the store defines or maintains one, so
  :func:`vocabulary` reads the view on each call. It is a cheap indexed read;
  the cache wants the counter, which is a store change and not this card's.
* **``query_rewrite``.** §3.6 makes it optional and background-only. There is no
  config module to enable it and no rewrite hook to call, so nothing does.
"""

from __future__ import annotations

import math
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from ..store.entities import MAX_NGRAM, ngrams
from ..store.types import Scope
from .stopwords import STOPWORDS
from .temporal import TimeRange

__all__ = [
    "INTENTS",
    "MAX_TERMS",
    "AnalyzedQuery",
    "analyze",
    "detect_entities",
    "detect_intent",
    "detect_temporal",
    "idf",
    "select_terms",
    "strip_memory_context",
    "tokenize",
    "vocabulary",
]

#: §3.6's intent heuristic labels. ``lookup`` is the default.
INTENTS: Tuple[str, ...] = ("profile", "temporal", "procedural", "lookup")

#: §3.6: "Max 12 terms". EM-301 selects them; `candidates.match_expression`
#: applies the same cap defensively when rendering, and imports this constant.
MAX_TERMS = 12

_WORD_RE = re.compile(r"\w+", re.UNICODE)

#: §3.6: "strip ``<memory-context>…</memory-context>`` blocks defensively". The
#: host already strips its own skill scaffolding before calling the provider,
#: so this is a second line — a model that echoes a memory block back as its
#: query must not have that block analysed as query terms.
_MEMORY_CONTEXT_RE = re.compile(
    r"<memory-context\b[^>]*>.*?</memory-context\s*>", re.IGNORECASE | re.DOTALL
)


@dataclass(frozen=True)
class AnalyzedQuery:
    """The six fields §3.6 names, in the order the plan names them.

    ``raw`` is the message as received; ``text`` is the text actually analysed
    (``<memory-context>`` blocks removed). ``terms`` are the IDF-selected
    tokens — a candidate generator quotes them for FTS5, it does not re-select
    them.
    """

    raw: str
    text: str
    terms: Tuple[str, ...] = ()
    temporal: Optional[TimeRange] = None
    entities: Tuple[str, ...] = ()
    intent: str = "lookup"


# --- text -----------------------------------------------------------------


def strip_memory_context(text: str) -> str:
    """Remove every ``<memory-context>…</memory-context>`` block (§3.6)."""
    return _MEMORY_CONTEXT_RE.sub(" ", text)


def tokenize(text: str) -> List[str]:
    """``\\w+`` runs, in order (§3.6). Casefolding happens at selection."""
    return _WORD_RE.findall(text)


# --- terms ----------------------------------------------------------------


def idf(n_docs: int, doc_freq: int) -> float:
    """§3.6's IDF: ``log((N - df + 0.5) / (df + 0.5) + 1)``.

    ``N`` is the number of *active* memories, not the number of rows. With no
    documents every term scores zero, which is what makes ``select_terms``
    fall back to its length ordering on an empty store rather than ranking by
    a meaningless spread.
    """
    if n_docs <= 0:
        return 0.0
    return math.log((n_docs - doc_freq + 0.5) / (doc_freq + 0.5) + 1.0)


def select_terms(
    tokens: Sequence[str],
    *,
    doc_freq: Optional[Mapping[str, int]] = None,
    n_docs: int = 0,
    extra_stopwords: Iterable[str] = (),
    max_terms: int = MAX_TERMS,
) -> Tuple[str, ...]:
    """Choose up to ``max_terms`` terms, by IDF then length (§3.6).

    Drops stopwords — the built-in list plus ``extra_stopwords`` — and tokens
    shorter than 2 characters, casefolds, de-duplicates, then orders by
    descending IDF, then descending length as the tiebreak. Returns casefolded
    terms: FTS5's ``unicode61`` folds case anyway, and returning the folded form
    means two spellings of one word cannot occupy two slots.
    """
    blocked = STOPWORDS | {word.casefold() for word in extra_stopwords}
    folded = [token.casefold() for token in tokens]
    unique = {t for t in folded if len(t) >= 2 and t not in blocked}
    if not unique:
        # §3.6 does not cover "every token was dropped", and it is not a corner
        # case: "who am I" is the `profile` intent's own example and every word
        # in it is a stopword. v2's EM-104 rule (R2) covers it, so it is carried
        # forward: the raw tokens come back with the length rule applied as far
        # as possible without emptying the query. Without this, an identity
        # question would retrieve nothing.
        unique = {t for t in folded if len(t) >= 2}
        if not unique:
            return ()

    frequencies = doc_freq or {}
    ranked = sorted(unique, key=lambda t: (-idf(n_docs, frequencies.get(t, 0)), -len(t), t))
    return tuple(ranked[:max_terms])


def _phrase(term: str) -> str:
    """One literal FTS5 phrase, for a frequency probe."""
    return '"' + term.replace('"', '""') + '"'


def vocabulary(
    conn: sqlite3.Connection, terms: Iterable[str] = ()
) -> Tuple[Dict[str, int], int]:
    """``(term -> document frequency, active memory count)`` for IDF (§3.6).

    The base map is ``memories_vocab``, the ``fts5vocab`` view migration ``0004``
    creates, exactly as §3.6 says. **One thing §3.6 does not account for:**
    ``memories_fts`` is tokenized with ``porter``, so the view's ``term`` values
    are *stems* — it holds ``stage``, not ``staging``. A raw query token therefore
    misses the view for every word whose stem differs (``running`` -> ``run``,
    ``preferences`` -> ``prefer``, …), and the map would report df 0 for most real
    tokens, collapsing IDF into a length ordering.

    So each requested ``term`` the view does not carry is counted with an FTS5
    ``MATCH`` against ``memories_fts``, which applies the *same* tokenizer and so
    is guaranteed to agree with the query the generators will run. Most tokens
    are their own stem and are answered by the view; only the stemmed minority
    costs a probe.

    ``N`` is the number of *active* memories (§3.6), while the view describes the
    whole FTS index — the two differ by exactly the non-active rows, which is the
    plan's design and not something to "fix" here.
    """
    row = conn.execute("SELECT COUNT(*) FROM memories WHERE status = 'active'").fetchone()
    n_docs = int(row[0]) if row else 0

    try:
        rows = conn.execute("SELECT term, doc FROM memories_vocab").fetchall()
        frequencies = {str(r["term"]).casefold(): int(r["doc"]) for r in rows}
    except sqlite3.OperationalError:
        frequencies = {}

    for term in dict.fromkeys(terms):
        key = term.casefold()
        if key in frequencies:
            continue
        found = conn.execute(
            "SELECT COUNT(*) FROM memories_fts WHERE memories_fts MATCH ?", (_phrase(term),)
        ).fetchone()
        frequencies[key] = int(found[0]) if found else 0

    return frequencies, n_docs


# --- intent ---------------------------------------------------------------

#: Ordered by precedence. The patterns are §3.6's own examples, widened only to
#: the phrasings the labelled table in the tests actually uses.
_INTENT_PATTERNS: Tuple[Tuple[str, "re.Pattern[str]"], ...] = (
    (
        "temporal",
        re.compile(
            r"\b(?:when|what\s+time|how\s+long\s+ago|last\s+time|"
            r"yesterday|today|tomorrow|tonight|"
            r"this\s+(?:week|month|year)|last\s+(?:night|week|month|year)|"
            r"\d+\s+(?:days?|weeks?|months?|years?)\s+ago|recently|earlier)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "procedural",
        re.compile(
            r"\b(?:how\s+(?:do|does|can|should|would|to)\b|steps?|procedure|process)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "profile",
        re.compile(
            r"\b(?:who\s+am\s+i|who\s+are\s+we|"
            r"my\s+(?:name|preferences?|profile|details|settings)|"
            r"about\s+me|do\s+i\s+(?:like|prefer|use)|what\s+do\s+i)\b",
            re.IGNORECASE,
        ),
    ),
)


def detect_intent(text: str) -> str:
    """Classify the query into one of :data:`INTENTS` (§3.6).

    First matching pattern wins, in the order declared above: an explicit time
    word, then a how-do-I, then an identity question, else ``lookup``. The
    order matters for overlap ("how do I change my preferences" is procedural,
    not profile) and is pinned by the labelled table.
    """
    for intent, pattern in _INTENT_PATTERNS:
        if pattern.search(text):
            return intent
    return "lookup"


# --- entities -------------------------------------------------------------


def detect_entities(
    text: str,
    *,
    conn: sqlite3.Connection,
    scope: Scope,
    max_ngram: int = MAX_NGRAM,
) -> Tuple[str, ...]:
    """Entity ids mentioned in ``text`` (§3.6).

    Every normalised n-gram up to 4 tokens is looked up against
    ``entity_aliases``, longest first, so "Zorp Systems" resolves before the
    bare "Zorp" can claim the mention. One indexed ``IN`` probe rather than one
    query per n-gram, which is the shape that holds the p95 budget.

    The join through ``entities`` is deliberate: ``entity_aliases`` alone is keyed
    by alias, so two profiles that both know an "Acme" would resolve to whichever
    row the primary key found first. The profile is the scope.
    """
    grams = ngrams(text, max_n=max_ngram)
    if not grams:
        return ()
    placeholders = ",".join("?" for _ in grams)
    rows = conn.execute(
        "SELECT ea.alias_norm AS gram, ea.entity_id AS entity_id"
        " FROM entity_aliases ea JOIN entities e ON e.id = ea.entity_id"
        f" WHERE ea.alias_norm IN ({placeholders}) AND e.scope_profile = ?",
        (*grams, scope.profile),
    ).fetchall()
    by_gram = {str(r["gram"]): str(r["entity_id"]) for r in rows}
    found: List[str] = []
    for gram in grams:  # ngrams() is longest-first, and order is the ranking
        entity_id = by_gram.get(gram)
        if entity_id is not None and entity_id not in found:
            found.append(entity_id)
    return tuple(found)


# --- temporal -------------------------------------------------------------

_ISO_DATE = r"(\d{4})-(\d{2})-(\d{2})"
_BETWEEN_RE = re.compile(rf"\bbetween\s+{_ISO_DATE}\s+and\s+{_ISO_DATE}\b", re.IGNORECASE)
_SINCE_RE = re.compile(rf"\bsince\s+{_ISO_DATE}\b", re.IGNORECASE)
_BEFORE_RE = re.compile(rf"\bbefore\s+{_ISO_DATE}\b", re.IGNORECASE)
_LAST_N_RE = re.compile(r"\blast\s+(\d+)\s+(day|week|month|year)s?\b", re.IGNORECASE)
_LAST_ONE_RE = re.compile(r"\blast\s+(day|week|month|year)\b", re.IGNORECASE)
_ISO_RE = re.compile(rf"\b{_ISO_DATE}\b")


def _parse_iso(year: str, month: str, day: str) -> datetime:
    return datetime(int(year), int(month), int(day), tzinfo=timezone.utc)


def _months_back(now: datetime, months: int) -> datetime:
    index = now.year * 12 + (now.month - 1) - months
    year, month = divmod(index, 12)
    month += 1
    # Clamp the day so 31 March minus one month is 28/29 February, not an error.
    day = min(now.day, _days_in_month(year, month))
    return now.replace(year=year, month=month, day=day)


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        return 31
    return (datetime(year, month + 1, 1) - timedelta(days=1)).day


def detect_temporal(text: str, *, now: datetime) -> Optional[TimeRange]:
    """The temporal window a query asks for, or ``None`` (§3.6).

    This is the *common* grammar §3.6 lists: an ISO date, "since X", "before X",
    "between X and Y", and "last N days/weeks/months/years" as a **range**.
    **The full grammar is EM-310's** — month-name dates ("in March 2026"),
    weekdays, "earlier this week", "N days ago", and the ``timezone`` config all
    belong to that card, and are deliberately absent here rather than
    half-implemented.

    Bounds are inclusive; a bare date is the whole of that day, and an
    unbounded end ("since X") is left open rather than defaulted, so the caller
    decides what "now" means for its own clock.
    """
    match = _BETWEEN_RE.search(text)
    if match:
        start = _parse_iso(*match.group(1, 2, 3))
        end = _parse_iso(*match.group(4, 5, 6))
        if start > end:
            # A reversed range is malformed. Returning no window is honest;
            # falling through would let the bare-date rule match one of the two
            # dates and silently answer a different question.
            return None
        return TimeRange(start=start, end=end + timedelta(days=1))

    match = _SINCE_RE.search(text)
    if match:
        return TimeRange(start=_parse_iso(*match.group(1, 2, 3)))

    match = _BEFORE_RE.search(text)
    if match:
        return TimeRange(end=_parse_iso(*match.group(1, 2, 3)))

    match = _LAST_N_RE.search(text) or _LAST_ONE_RE.search(text)
    if match:
        count = int(match.group(1)) if match.re is _LAST_N_RE else 1
        unit = match.group(2 if match.re is _LAST_N_RE else 1).lower()
        if unit == "day":
            start = now - timedelta(days=count)
        elif unit == "week":
            start = now - timedelta(weeks=count)
        elif unit == "month":
            start = _months_back(now, count)
        else:
            try:
                start = now.replace(year=now.year - count)
            except ValueError:  # 29 February
                start = now.replace(year=now.year - count, day=28)
        return TimeRange(start=start, end=now)

    match = _ISO_RE.search(text)
    if match:
        day = _parse_iso(*match.group(1, 2, 3))
        return TimeRange(start=day, end=day + timedelta(days=1))

    return None


# --- the analyzer ---------------------------------------------------------


def analyze(
    text: str,
    *,
    conn: sqlite3.Connection,
    scope: Scope,
    now: Optional[datetime] = None,
    extra_stopwords: Iterable[str] = (),
    max_terms: int = MAX_TERMS,
) -> AnalyzedQuery:
    """Turn one user message into an :class:`AnalyzedQuery` (§3.6, EM-301).

    ``text`` is the **current message only** — prior turns are deliberately not
    concatenated (§3.6); the session's topic signal reaches retrieval separately
    through the prefetch service.

    ``conn`` and ``scope`` are needed for the two lookups: IDF reads
    ``memories_vocab``, and entity detection resolves aliases *within the
    profile*, so one profile's "Acme" cannot resolve to another's.
    """
    normalized = strip_memory_context(text)
    tokens = tokenize(normalized)
    frequencies, n_docs = vocabulary(conn, tokens)
    return AnalyzedQuery(
        raw=text,
        text=normalized,
        terms=select_terms(
            tokens,
            doc_freq=frequencies,
            n_docs=n_docs,
            extra_stopwords=extra_stopwords,
            max_terms=max_terms,
        ),
        temporal=detect_temporal(normalized, now=now or datetime.now(timezone.utc)),
        entities=detect_entities(normalized, conn=conn, scope=scope),
        intent=detect_intent(normalized),
    )
