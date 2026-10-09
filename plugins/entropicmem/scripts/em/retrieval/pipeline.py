"""The §3.6 pipeline as one callable — EM-302 through EM-305 in order.

    analyze ─▶ GENERATORS ─▶ fuse ─▶ rank ─▶ [gate ─▶ collapse ─▶ mmr]

Two callers need exactly this sequence and must not drift apart: the v3 eval adapter
(it is what the eval numbers measure) and the provider's shadow read (P0). Before
this module existed the adapter held the only copy, and the shadow would have been a
second one — which is how two "identical" pipelines stop being identical.

``with_gate=False`` stops after the feature rerank. That is the shape the eval
adapter's ``search`` needs, because ranking metrics measure ORDER and letting the
abstention filter truncate the list would score abstention twice.

**What this module is not:** it does not render (EM-307's ``render_retrieval``
does, from the rankings and predecessors returned here), and it does not own
the vector generator or the gate's cosine condition (EM-303). The eval adapter
still emits its own bullets: a short citation would stop injected ids matching.

Stdlib only (plan §3.2).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..embeddings.cache import cached_memory_vectors
from ..store.embeddings import cosine
from ..store.types import Scope
from . import candidates, diversity, fusion, gate
from .query import AnalyzedQuery, analyze

__all__ = ["Retrieval", "retrieve"]


def _pairwise_similarity(vectors: Dict[Tuple[str, str], Tuple[float, ...]], texts: Dict[Tuple[str, str], str]):
    """MMR's redundancy function (§3.6): cosine when both have a vector, else Jaccard.

    A negative cosine is clamped to 0.0: MMR's redundancy is a penalty in
    ``[0, 1]``, and an opposed pair must not earn a bonus. A pair where either
    side has no vector falls back to token Jaccard, which is why ``texts`` is
    passed here as well.
    """

    def similarity(left: Tuple[str, str], right: Tuple[str, str]) -> float:
        left_vector = vectors.get(left)
        right_vector = vectors.get(right)
        if left_vector is not None and right_vector is not None:
            return max(0.0, cosine(left_vector, right_vector))
        return diversity.jaccard(
            diversity.tokens(texts.get(left, "")),
            diversity.tokens(texts.get(right, "")),
        )

    return similarity


@dataclass(frozen=True)
class Retrieval:
    """One query's outcome, with everything a caller needs to explain or render it."""

    analyzed: AnalyzedQuery
    rankings: List[Any]
    #: The gate's row inputs, keyed by ``(owner_type, owner_id)``. Present for every
    #: key the caller may render text for, including keys the gate dropped.
    rows: Dict[Tuple[str, str], gate.RowInfo] = field(default_factory=dict)
    #: Successor key → predecessors that earned a ``superseded_note``. Empty
    #: unless ``with_gate`` ran the collapse, and only for keys still in
    #: ``rankings`` after MMR. The renderer quotes these; this module does not.
    predecessors: Dict[Tuple[str, str], Tuple[Any, ...]] = field(default_factory=dict)

    @property
    def ids(self) -> List[str]:
        return [ranking.owner_id for ranking in self.rankings]

    def text_of(self, ranking: Any) -> str:
        info = self.rows.get(ranking.key)
        return info.text if info is not None else ranking.owner_id


def retrieve(
    conn: sqlite3.Connection,
    *,
    scope: Scope,
    query: str,
    now: Optional[datetime] = None,
    with_gate: bool = False,
    gate_config: Optional[gate.GateConfig] = None,
    rank_weights: Optional[fusion.RankWeights] = None,
    query_vector: Optional[Sequence[float]] = None,
    embedding_model: Optional[str] = None,
) -> Retrieval:
    """Run §3.6's pipeline for one query.

    ``with_gate=True`` runs the whole thing — support test, score threshold,
    supersession/duplicate collapse, MMR. ``False`` stops after the rerank, which is
    the ordering-only view the ranking metrics need.

    ``now`` defaults to the wall clock; pass one to make a run reproducible.

    ``gate_config`` and ``rank_weights`` are the **calibration seam** (EM-306): the
    tune harness passes candidates through the real pipeline rather than a copy of it.
    ``None`` — what the provider and the eval adapter pass — means the spec defaults,
    so nothing about the shipped path changes until the config is wired (EM-401–403).

    ``query_vector`` and ``embedding_model`` are EM-303's seam. Both default to
    ``None``, and then the vector generator does not run and the gate's cosine
    condition stays off — the lexical path is unchanged. Passing both turns
    cosine on for this call **only when** ``gate_config`` was not supplied; an
    explicit config is obeyed, including ``cosine_enabled=False``.
    """
    moment = now or datetime.now(timezone.utc)
    analyzed = analyze(query, conn=conn, scope=scope, now=moment)
    vector = tuple(query_vector) if query_vector else None

    results: Dict[str, List[Any]] = {}
    for name, generator in candidates.GENERATORS.items():
        context = candidates.RetrievalContext(
            conn=conn,
            aq=analyzed,
            scope=scope,
            now=moment,
            query_vector=vector,
            embedding_model=embedding_model if vector else None,
        )
        results[name] = generator(context)

    fused = fusion.fuse(results, intent=analyzed.intent)
    features = fusion.load_features(conn, scope=scope, keys=fused.keys())
    ranked = fusion.rank(fused, features, now=moment, weights=rank_weights)

    rows = gate.load_rows(conn, scope=scope, keys=[r.key for r in ranked])
    if not with_gate:
        return Retrieval(analyzed=analyzed, rankings=ranked, rows=rows)

    texts = {key: info.text for key, info in rows.items()}
    coverages = gate.coverage(list(analyzed.terms), texts)
    cosines = None
    model_name = None
    settings = gate_config
    if vector is not None and embedding_model:
        cosines = {
            (candidate.owner_type, candidate.owner_id): float(candidate.raw_score)
            for candidate in results.get("vector", [])
        }
        model_name = embedding_model
        if gate_config is None:
            settings = replace(gate.DEFAULT_GATE, cosine_enabled=True)
    gated = gate.apply_gate(
        ranked,
        rows=rows,
        coverages=coverages,
        config=settings,
        cosines=cosines,
        model=model_name,
    )
    if gated.empty:
        return Retrieval(analyzed=analyzed, rankings=[], rows=rows)

    survivors = gated.survivors
    collapsed = diversity.collapse(
        survivors,
        texts=texts,
        scope_users={key: info.scope_user for key, info in rows.items()},
        predecessors=diversity.load_predecessors(
            conn, scope=scope, keys=[r.key for r in survivors]
        ),
        now=moment,
    )
    mmr_similarities = None
    if vector is not None and embedding_model:
        clause, params = candidates.scope_sql(scope, table="m")
        entry = cached_memory_vectors(
            conn, model=embedding_model, scope_clause=clause, scope_params=params
        )
        vectors_by_key = {}
        for owner_id in entry.ids:
            stored = entry.vector_of(owner_id)
            if stored is not None:
                vectors_by_key[(candidates.OWNER_TYPE_MEMORY, owner_id)] = stored
        mmr_similarities = _pairwise_similarity(vectors_by_key, texts)
    kept = diversity.mmr(collapsed.kept, texts=texts, similarities=mmr_similarities)
    kept_keys = {ranking.key for ranking in kept}
    noted = {
        key: predecessors
        for key, predecessors in collapsed.predecessors.items()
        if key in kept_keys
    }
    return Retrieval(
        analyzed=analyzed,
        rankings=kept,
        rows=rows,
        predecessors=noted,
    )
