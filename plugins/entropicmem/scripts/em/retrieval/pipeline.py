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
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from ..embeddings.cache import cached_vectors
from ..store.embeddings import cosine
from ..store.types import Scope
from . import candidates, diversity, fusion, gate
from .query import AnalyzedQuery, VocabularyCache, analyze

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
    #: True when the deadline cut the generator stage short (§4.2): at least one
    #: generator was skipped or abandoned because the deadline passed. A run
    #: without a deadline is never partial.
    partial: bool = False
    #: The generators the deadline skipped, in run order (an abandoned call is
    #: named too — its results were discarded).
    generators_skipped: Tuple[str, ...] = ()

    @property
    def ids(self) -> List[str]:
        return [ranking.owner_id for ranking in self.rankings]

    def text_of(self, ranking: Any) -> str:
        info = self.rows.get(ranking.key)
        return info.text if info is not None else ranking.owner_id


class GeneratorDeadline(Exception):
    """A ``generator_runner`` abandoned its call at the deadline (§4.2).

    The runner contract: raise this when the deadline (or the run budget) has
    passed and the generator's results must be discarded. ``retrieve`` then
    marks the result partial and skips the remaining generators — it never
    retries the call.
    """


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
    deadline: Optional[float] = None,
    generator_order: Optional[Sequence[str]] = None,
    generator_runner: Optional[
        Callable[[str, Callable[[candidates.RetrievalContext], List[Any]], candidates.RetrievalContext], List[Any]]
    ] = None,
    idf_cache: Optional[VocabularyCache] = None,
    write_generation: str = "",
) -> Retrieval:
    """Run §3.6's pipeline for one query.

    ``with_gate=True`` runs the whole thing — support test, score threshold,
    supersession/duplicate collapse, MMR. ``False`` stops after the rerank, which is
    the ordering-only view the ranking metrics need.

    ``now`` defaults to the wall clock; pass one to make a run reproducible.

    ``gate_config`` and ``rank_weights`` are the **calibration seam** (EM-306): the
    tune harness passes candidates through the real pipeline rather than a copy of
    it. ``None`` means the spec dataclass defaults (``gate.DEFAULT_GATE`` /
    ``fusion.DEFAULT_RANK_WEIGHTS``) — the eval adapter keeps that path on purpose,
    so the frozen suites and baselines measure the plan's numbers. The provider
    resolves its defaults from ``em.config`` (EM-407) and passes them explicitly:
    the shipped default is EM-306's calibration, and the split is pinned in
    ``tests/evals/test_adapter_v3.py``.

    ``query_vector`` and ``embedding_model`` are EM-303's seam. Both default to
    ``None``, and then the vector generator does not run and the gate's cosine
    condition stays off — the lexical path is unchanged. Passing both turns
    cosine on for this call **only when** ``gate_config`` was not supplied; an
    explicit config is obeyed, including ``cosine_enabled=False``.

    ``deadline``, ``generator_order`` and ``generator_runner`` are **EM-403's
    execution seams** (§4.2) and all default to today's behaviour: no deadline,
    :data:`candidates.GENERATORS`' own order, and a direct call. A deadline is an
    absolute ``time.monotonic()`` reading handed to every generator's context; when
    it passes, the remaining generators are skipped and the result is marked
    ``partial`` (with ``generators_skipped``). ``generator_order`` is the priority
    order partial results are kept in — the prefetch service passes §4.2's
    ``pinned → bm25 → entity → vector → episodic → recent``; the global mapping's
    order is deliberately untouched. ``generator_runner(name, generator, context)``
    executes each generator and may abandon a call by raising
    :class:`GeneratorDeadline` (the watchdog that makes the 1.5 s hard cap hold
    even for a generator that ignores the deadline contract).

    ``idf_cache``/``write_generation`` are §3.6's IDF cache (EM-403): with both,
    the analyzer's vocabulary read is served from the cache until a write moves
    the generation; with neither — every caller but the prefetch service — the
    vocabulary is read per call exactly as before.
    """
    moment = now or datetime.now(timezone.utc)
    analyzed = analyze(
        query,
        conn=conn,
        scope=scope,
        now=moment,
        idf_cache=idf_cache,
        write_generation=write_generation,
    )
    vector = tuple(query_vector) if query_vector else None

    order = tuple(generator_order) if generator_order is not None else tuple(candidates.GENERATORS)
    unknown = [name for name in order if name not in candidates.GENERATORS]
    if unknown:
        raise ValueError(f"unknown generators: {unknown!r}")

    results: Dict[str, List[Any]] = {}
    skipped: List[str] = []
    partial = False
    for index, name in enumerate(order):
        context = candidates.RetrievalContext(
            conn=conn,
            aq=analyzed,
            scope=scope,
            now=moment,
            deadline=deadline,
            query_vector=vector,
            embedding_model=embedding_model if vector else None,
        )
        if context.out_of_time():
            skipped = list(order[index:])
            partial = True
            break
        generator = candidates.GENERATORS[name]
        try:
            if generator_runner is None:
                results[name] = generator(context)
            else:
                results[name] = generator_runner(name, generator, context)
        except GeneratorDeadline:
            skipped = list(order[index:])
            partial = True
            break
        if context.out_of_time():
            # The generator finished, but it ran against the deadline and may
            # have returned a page-truncated list; the rest cannot do SQL at all.
            skipped = list(order[index + 1:])
            partial = True
            break

    fused = fusion.fuse(results, intent=analyzed.intent)
    features = fusion.load_features(conn, scope=scope, keys=fused.keys())
    ranked = fusion.rank(fused, features, now=moment, weights=rank_weights)

    rows = gate.load_rows(conn, scope=scope, keys=[r.key for r in ranked])
    if not with_gate:
        return Retrieval(
            analyzed=analyzed,
            rankings=ranked,
            rows=rows,
            partial=partial,
            generators_skipped=tuple(skipped),
        )

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
        # Episodes the episodic generator found by vector carry no cosine in a
        # `vector` result; hand the gate theirs so a vector-only episode can
        # pass the §3.6 cosine support condition too.
        ep_clause, ep_params = candidates.scope_sql(scope, table="e", owner_only=False)
        ep_entry = cached_vectors(
            conn,
            owner_type="episode",
            model=embedding_model,
            scope_clause=ep_clause,
            scope_params=ep_params,
            width=len(vector),
        )
        for candidate in results.get("episodic", []):
            stored = ep_entry.vector_of(candidate.owner_id)
            if stored is not None:
                cosines[(candidate.owner_type, candidate.owner_id)] = max(
                    0.0, cosine(vector, stored)
                )
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
        return Retrieval(
            analyzed=analyzed,
            rankings=[],
            rows=rows,
            partial=partial,
            generators_skipped=tuple(skipped),
        )

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
        entry = cached_vectors(
            conn,
            owner_type="memory",
            model=embedding_model,
            scope_clause=clause,
            scope_params=params,
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
        partial=partial,
        generators_skipped=tuple(skipped),
    )
