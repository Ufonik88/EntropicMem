"""Fusion, rerank and explainability — EM-304 (plan §3.6).

The pipeline stage between the candidate generators and EM-305's gate:

    {generator: [Candidate, …]} ──▶ weighted RRF ──▶ feature rerank ──▶ ranked,
                                                       explained hits

**Weighted Reciprocal Rank Fusion**, exactly §3.6:

    rrf(d)   = Σ_g w_g / (60 + rank_g(d))
    rrf_n(d) = rrf(d) / Σ_{g ∈ G_active} (w_g / 61)     ∈ [0, 1]

where ``G_active`` is the set of generators that **ran and returned at least one
candidate**. That qualifier is load-bearing and is the one way to get this wrong:
normalising over *all configured* generators would cap a bm25-only hit at about
0.25, and because the abstention gate's ``min_score`` is applied to this scale
(§3.6), a perfectly good single-generator hit would then be discarded. The
reference denominator ``w_g / 61`` is the score that generator would have given a
candidate sitting at rank 1, so ``rrf_n`` is "how close to a rank-1 hit in every
active generator" — which is what makes the number comparable across queries.

**Feature rerank**, also exactly §3.6, with every weight and half-life in
:class:`RankWeights` (the spec's numbers; ``ranking.*`` config is EM-407's and the
gap is recorded in ``em/retrieval/__init__.py``):

    score    = 0.60*rrf_n + 0.15*importance + 0.10*recency + 0.10*confidence + 0.05*feedback
    recency  = 1.0                                  if decay_class == 'evergreen' or pinned
             = max(0.5, 0.5 ** (age_days / 180))    if 'standard'
             = 0.5 ** (age_days / 14)               if 'volatile'
    age_days = now - max(updated_at, last_accessed_at, valid_from)
    feedback = clamp(0.5 + 0.1*(helpful - 2*unhelpful), 0, 1)

**Tie-break** is ``(score desc, updated_at desc, id asc)`` (§3.6) and is total, so
two runs over the same inputs give the same order.

Stdlib only (plan §3.2).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from ..clock import parse_iso
from ..store.types import Scope
from .candidates import (
    OWNER_TYPE_EPISODE,
    OWNER_TYPE_MEMORY,
    Candidate,
    scope_sql,
)

__all__ = [
    "DEFAULT_RANK_WEIGHTS",
    "EPISODE_DEFAULTS",
    "Fused",
    "Features",
    "GENERATOR_WEIGHTS",
    "Key",
    "RRF_K",
    "RankWeights",
    "Ranking",
    "Signal",
    "feature_score",
    "feedback_factor",
    "fuse",
    "legacy_tokens",
    "load_features",
    "rank",
    "rank_candidates",
    "recency_factor",
    "weights_for",
]

#: A candidate's identity: §3.6's ``(owner_type, owner_id)``.
Key = Tuple[str, str]

#: §3.6's RRF constant, and the rank-1 reference used for normalisation.
RRF_K = 60.0
_RRF_REFERENCE = RRF_K + 1.0  # 61

#: §3.6's default generator weights, by intent, verbatim.
GENERATOR_WEIGHTS: Mapping[str, Mapping[str, float]] = {
    "lookup": {"bm25": 1.0, "vector": 1.0, "entity": 0.7, "episodic": 0.3, "recent": 0.2, "pinned": 0.5},
    "profile": {"bm25": 0.6, "vector": 0.8, "entity": 0.6, "episodic": 0.1, "recent": 0.1, "pinned": 1.0},
    "temporal": {"bm25": 0.7, "vector": 0.6, "entity": 0.5, "episodic": 1.0, "recent": 0.8, "pinned": 0.3},
    "procedural": {"bm25": 1.0, "vector": 1.0, "entity": 0.5, "episodic": 0.4, "recent": 0.2, "pinned": 0.5},
}


@dataclass(frozen=True)
class RankWeights:
    """§3.6's rerank weights and half-lives.

    Every number here is the plan's. §3.6 says they live in ``ranking.*`` config;
    there is no config module yet (EM-407 owns it), so they are parameters with
    the spec's values as defaults — the same shape as EM-301's
    ``extra_stopwords``. Do not invent a config system here.
    """

    rrf: float = 0.60
    importance: float = 0.15
    recency: float = 0.10
    confidence: float = 0.10
    feedback: float = 0.05
    standard_half_life_days: float = 180.0
    volatile_half_life_days: float = 14.0
    #: §3.6's ``max(0.5, …)`` floor for a ``standard`` memory.
    standard_floor: float = 0.5


DEFAULT_RANK_WEIGHTS = RankWeights()

#: Episode features the schema has no column for. §3.6's rerank is written for
#: memories and ``episodes`` lacks ``confidence``, ``decay_class``, ``pinned``,
#: ``last_accessed_at`` and the feedback counters, so each gets a named default
#: rather than a silent zero: an episode is a record, not a claim, so it is fully
#: trusted and undecayed, and its ``start_at`` (world time) fills the ``valid_from``
#: slot the age formula asks for.
EPISODE_DEFAULTS: Mapping[str, Any] = {
    "confidence": 1.0,
    "decay_class": "standard",
    "pinned": False,
}


@dataclass(frozen=True)
class Features:
    """The rerank inputs for one candidate.

    Defaults describe an ordinary memory; :func:`load_features` fills them from
    the row.
    """

    importance: float = 0.5
    confidence: float = 0.8
    decay_class: str = "standard"
    pinned: bool = False
    updated_at: Optional[datetime] = None
    last_accessed_at: Optional[datetime] = None
    valid_from: Optional[datetime] = None
    helpful: int = 0
    unhelpful: int = 0


@dataclass(frozen=True)
class Signal:
    """One generator's contribution to a fused score (§3.6's ``why_retrieved``)."""

    signal: str
    rank: int
    #: This generator's share of ``rrf_n`` — ``(w_g / (60+rank)) / denominator``.
    #: The shares of one candidate sum to its ``rrf_n``.
    contrib: float

    def as_dict(self) -> Dict[str, Any]:
        return {"signal": self.signal, "rank": self.rank, "contrib": self.contrib}


@dataclass(frozen=True)
class Fused:
    """One candidate after RRF, before the feature rerank."""

    rrf: float
    rrf_n: float
    signals: Tuple[Signal, ...]


@dataclass(frozen=True)
class Ranking:
    """A fused candidate with its final score and its explanation."""

    owner_type: str
    owner_id: str
    score: float
    rrf: float
    rrf_n: float
    recency: float
    feedback: float
    signals: Tuple[Signal, ...]
    #: §3.6's ``why_retrieved``: one dict per contributing generator, then flags.
    why: Tuple[Any, ...]

    @property
    def key(self) -> Key:
        return (self.owner_type, self.owner_id)


# --- weights --------------------------------------------------------------


def weights_for(intent: str, *, table: Optional[Mapping[str, Mapping[str, float]]] = None) -> Mapping[str, float]:
    """§3.6's generator weights for an intent.

    An unknown intent falls back to ``lookup`` (the analyzer's own default), and
    an unknown *generator* has weight 0.0 unless the caller supplies a table —
    EM-308's ``note_bm25``/``note_vector`` will bring their own. A zero weight
    contributes nothing to ``rrf`` and nothing to the normalising denominator, so
    an unweighted generator cannot deflate every other generator's score.
    """
    source = table if table is not None else GENERATOR_WEIGHTS
    return dict(source.get(intent) or source["lookup"])


# --- fusion ---------------------------------------------------------------


def fuse(
    results: Mapping[str, Sequence[Candidate]],
    *,
    intent: str = "lookup",
    weights: Optional[Mapping[str, float]] = None,
    table: Optional[Mapping[str, Mapping[str, float]]] = None,
) -> Dict[Key, Fused]:
    """Weighted RRF over the generators that returned candidates (§3.6).

    ``results`` maps a generator name to its **ranked** candidates — the order of
    each list *is* the rank, which is why :class:`~em.retrieval.candidates.Candidate`
    does not carry one. A generator absent from the mapping, or present with an
    empty list, did not run or found nothing, so it is not part of ``G_active``
    and does not appear in the normalising denominator.

    A repeated key within one generator counts once, at its best rank: a ranked
    list is a ranking, and letting a duplicate contribute twice would make the
    score depend on how many times a generator happened to emit it.
    """
    generator_weights = dict(weights) if weights is not None else weights_for(intent, table=table)

    # Pass 1: raw rrf per key, and the best rank each generator gave it.
    raw: Dict[Key, float] = {}
    contributions: Dict[Key, List[Tuple[str, int, float]]] = {}
    for generator in sorted(results):
        weight = float(generator_weights.get(generator, 0.0))
        seen: set = set()
        for position, candidate in enumerate(results[generator], start=1):
            key = (candidate.owner_type, candidate.owner_id)
            if key in seen:
                continue
            seen.add(key)
            share = weight / (RRF_K + position)
            raw[key] = raw.get(key, 0.0) + share
            contributions.setdefault(key, []).append((generator, position, share))

    # `G_active` = every generator that returned ≥ 1 candidate, whether or not its
    # weight is non-zero (a zero-weight one simply adds zero to both sides).
    active = [g for g, candidates in results.items() if candidates]
    denominator = sum(float(generator_weights.get(g, 0.0)) / _RRF_REFERENCE for g in active)

    fused: Dict[Key, Fused] = {}
    for key, total in raw.items():
        normalised = total / denominator if denominator > 0 else 0.0
        signals = tuple(
            Signal(
                signal=generator,
                rank=position,
                contrib=share / denominator if denominator > 0 else 0.0,
            )
            for generator, position, share in sorted(contributions.get(key, []))
        )
        fused[key] = Fused(rrf=total, rrf_n=normalised, signals=signals)
    return fused


# --- rerank ---------------------------------------------------------------


def _aware(moment: datetime) -> datetime:
    """Treat a naive timestamp as UTC, so subtraction never raises."""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=timezone.utc)


def age_days(features: Features, *, now: datetime) -> float:
    """§3.6's ``now - max(updated_at, last_accessed_at, valid_from)``, in days.

    Floored at zero: a row stamped in the future is "just now", not a negative age
    that would push ``recency`` above 1 and break the ``score ∈ [0, 1]`` claim.
    """
    stamps = [
        _aware(stamp)
        for stamp in (features.updated_at, features.last_accessed_at, features.valid_from)
        if stamp is not None
    ]
    if not stamps:
        return 0.0
    seconds = (_aware(now) - max(stamps)).total_seconds()
    return max(0.0, seconds / 86400.0)


def recency_factor(
    features: Features, *, now: datetime, weights: Optional[RankWeights] = None
) -> float:
    """§3.6's ``recency`` term."""
    config = weights or DEFAULT_RANK_WEIGHTS
    if features.decay_class == "evergreen" or features.pinned:
        return 1.0
    age = age_days(features, now=now)
    if features.decay_class == "volatile":
        return 0.5 ** (age / config.volatile_half_life_days)
    return max(config.standard_floor, 0.5 ** (age / config.standard_half_life_days))


def _clamp(value: float, low: float, high: float) -> float:
    return low if value < low else high if value > high else value


def feedback_factor(features: Features) -> float:
    """§3.6's ``clamp(0.5 + 0.1*(helpful - 2*unhelpful), 0, 1)``.

    An unhelpful vote costs twice a helpful one — telling the store it was wrong
    is stronger evidence than confirming it was right.
    """
    return _clamp(0.5 + 0.1 * (features.helpful - 2 * features.unhelpful), 0.0, 1.0)


def feature_score(
    rrf_n: float,
    features: Features,
    *,
    now: datetime,
    weights: Optional[RankWeights] = None,
) -> float:
    """§3.6's final score, in ``[0, 1]``."""
    config = weights or DEFAULT_RANK_WEIGHTS
    return (
        config.rrf * _clamp(rrf_n, 0.0, 1.0)
        + config.importance * _clamp(features.importance, 0.0, 1.0)
        + config.recency * recency_factor(features, now=now, weights=config)
        + config.confidence * _clamp(features.confidence, 0.0, 1.0)
        + config.feedback * feedback_factor(features)
    )


def rank(
    fused: Mapping[Key, Fused],
    features: Mapping[Key, Features],
    *,
    now: datetime,
    weights: Optional[RankWeights] = None,
    flags: Mapping[Key, Sequence[str]] | None = None,
) -> List[Ranking]:
    """Rerank fused candidates and order them deterministically (§3.6).

    A fused key with no entry in ``features`` is **dropped**: features come from a
    scoped row load, so an absent key means the row is not visible to this caller
    (or has gone away since the generators ran), and ranking a row the caller may
    not read is exactly what the scope rule exists to prevent.
    """
    ordered: List[Tuple[float, float, str, str, Ranking]] = []
    for key, entry in fused.items():
        found = features.get(key)
        if found is None:
            continue
        score = feature_score(entry.rrf_n, found, now=now, weights=weights)
        why: Tuple[Any, ...] = tuple(s.as_dict() for s in entry.signals) + tuple(
            flags.get(key, ()) if flags else ()
        )
        ranking = Ranking(
            owner_type=key[0],
            owner_id=key[1],
            score=score,
            rrf=entry.rrf,
            rrf_n=entry.rrf_n,
            recency=recency_factor(found, now=now, weights=weights),
            feedback=feedback_factor(found),
            signals=entry.signals,
            why=why,
        )
        # §3.6's `(score desc, updated_at desc, id asc)`, made total by
        # `owner_type` so a memory and an episode can never exchange places
        # between runs.
        updated = _aware(found.updated_at).timestamp() if found.updated_at else float("-inf")
        ordered.append((-score, -updated, key[0], key[1], ranking))

    ordered.sort(key=lambda row: row[:4])
    return [row[4] for row in ordered]


def legacy_tokens(ranking: Ranking) -> List[Any]:
    """The flat, v2-shaped reason list §3.6 keeps for one minor version.

    ``why_retrieved_tokens`` is the string-only form the provider and the facade
    have always emitted (``["fts", "recency"]``); wiring it onto the recall path
    belongs to the provider card, so this is the conversion function only.
    """
    tokens: List[Any] = []
    for signal in ranking.signals:
        if signal.signal not in tokens:
            tokens.append(signal.signal)
    for flag in ranking.why[len(ranking.signals):]:
        if flag not in tokens:
            tokens.append(flag)
    return tokens


# --- features from the store ----------------------------------------------


def _parse_optional(value: Any) -> Optional[datetime]:
    return parse_iso(value) if value else None


def _features_of_memory(row: Mapping[str, Any]) -> Features:
    return Features(
        importance=float(row["importance"]),
        confidence=float(row["confidence"]),
        decay_class=str(row["decay_class"]),
        pinned=bool(row["pinned"]),
        updated_at=_parse_optional(row["updated_at"]),
        last_accessed_at=_parse_optional(row["last_accessed_at"]),
        valid_from=_parse_optional(row["valid_from"]),
        helpful=int(row["helpful_count"]),
        unhelpful=int(row["unhelpful_count"]),
    )


def _features_of_episode(row: Mapping[str, Any]) -> Features:
    return Features(
        importance=float(row["importance"]),
        confidence=EPISODE_DEFAULTS["confidence"],
        decay_class=EPISODE_DEFAULTS["decay_class"],
        pinned=EPISODE_DEFAULTS["pinned"],
        updated_at=_parse_optional(row["updated_at"]),
        # An episode's world time is `start_at` (§3.6/§3.10), which is what the
        # age formula wants in the `valid_from` slot.
        valid_from=_parse_optional(row["start_at"]),
    )


def load_features(
    conn: sqlite3.Connection, *, scope: Scope, keys: Iterable[Key]
) -> Dict[Key, Features]:
    """Load rerank features for ``keys``, keeping only rows this scope admits.

    §3.6's rerank needs columns no candidate carries — ``importance``,
    ``confidence``, ``decay_class``, ``pinned``, three timestamps and the feedback
    counters — so they are fetched here rather than pushed into
    :class:`~em.retrieval.candidates.Candidate`, which the plan fixes at three
    fields.

    Both queries apply §3.5 through ``scope_sql`` (memories also require
    ``status='active'``, which §3.6 requires of every candidate). It is
    deliberately redundant with the generators: this is the last point before a
    row's content would be shown, and a scope mistake in a generator should not be
    able to surface here.
    """
    wanted = set(keys)
    memory_ids = sorted({key[1] for key in wanted if key[0] == OWNER_TYPE_MEMORY})
    episode_ids = sorted({key[1] for key in wanted if key[0] == OWNER_TYPE_EPISODE})
    found: Dict[Key, Features] = {}

    if memory_ids:
        clause, params = scope_sql(scope, table="m")
        marks = ",".join("?" for _ in memory_ids)
        rows = conn.execute(
            f"SELECT m.* FROM memories m WHERE m.id IN ({marks})"
            f" AND m.status = 'active' AND {clause}",
            (*memory_ids, *params),
        ).fetchall()
        for row in rows:
            found[(OWNER_TYPE_MEMORY, str(row["id"]))] = _features_of_memory(row)

    if episode_ids:
        # `episodes` has no `sensitivity`/`visibility`, so the tier half of §3.5
        # cannot apply to it (the same reason the episodic generator passes
        # `owner_only=False`).
        clause, params = scope_sql(scope, table="e", owner_only=False)
        marks = ",".join("?" for _ in episode_ids)
        rows = conn.execute(
            f"SELECT e.* FROM episodes e WHERE e.id IN ({marks}) AND {clause}",
            (*episode_ids, *params),
        ).fetchall()
        for row in rows:
            found[(OWNER_TYPE_EPISODE, str(row["id"]))] = _features_of_episode(row)

    return found


def rank_candidates(
    conn: sqlite3.Connection,
    *,
    results: Mapping[str, Sequence[Candidate]],
    scope: Scope,
    intent: str = "lookup",
    now: datetime,
    weights: Optional[RankWeights] = None,
    temporal_filter: bool = False,
    entity_names: Optional[Mapping[str, str]] = None,
) -> List[Ranking]:
    """Fuse, load features and rerank, with §3.6's per-hit explanation flags.

    ``temporal_filter`` should be true when an analyzed time window was applied,
    and ``entity_names`` maps a detected entity id to its human name — the two
    facts the flags need that neither a candidate nor a row carries. The third
    §3.6 flag, ``superseded_note``, belongs to EM-305's collapse and is not
    emitted here.
    """
    fused = fuse(results, intent=intent)
    features = load_features(conn, scope=scope, keys=fused.keys())

    flags: Dict[Key, List[str]] = {}
    for key, entry in fused.items():
        names = [signal.signal for signal in entry.signals]
        per_hit: List[str] = []
        if temporal_filter and "episodic" in names:
            per_hit.append("temporal_filter")
        if "entity" in names:
            for entity_id, name in (entity_names or {}).items():
                per_hit.append(f"entity:{name or entity_id}")
        flags[key] = per_hit

    return rank(fused, features, now=now, weights=weights, flags=flags)
