"""The §3.6 pipeline as one callable — EM-302 through EM-305 in order.

    analyze ─▶ GENERATORS ─▶ fuse ─▶ rank ─▶ [gate ─▶ collapse ─▶ mmr]

Two callers need exactly this sequence and must not drift apart: the v3 eval adapter
(it is what the eval numbers measure) and the provider's shadow read (P0). Before
this module existed the adapter held the only copy, and the shadow would have been a
second one — which is how two "identical" pipelines stop being identical.

``with_gate=False`` stops after the feature rerank. That is the shape the eval
adapter's ``search`` needs, because ranking metrics measure ORDER and letting the
abstention filter truncate the list would score abstention twice.

**What this module is not:** it is not the packer or the renderer (EM-307), and it
does not own the vector generator or the gate's cosine condition (EM-303). It returns
rankings and the rows their text came from; what a caller *does* with them is the
caller's business.

Stdlib only (plan §3.2).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from ..store.types import Scope
from . import candidates, diversity, fusion, gate
from .query import AnalyzedQuery, analyze

__all__ = ["Retrieval", "retrieve"]


@dataclass(frozen=True)
class Retrieval:
    """One query's outcome, with everything a caller needs to explain or render it."""

    analyzed: AnalyzedQuery
    rankings: List[Any]
    #: The gate's row inputs, keyed by ``(owner_type, owner_id)``. Present for every
    #: key the caller may render text for, including keys the gate dropped.
    rows: Dict[Tuple[str, str], gate.RowInfo] = field(default_factory=dict)

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
    """
    moment = now or datetime.now(timezone.utc)
    analyzed = analyze(query, conn=conn, scope=scope, now=moment)

    results: Dict[str, List[Any]] = {}
    for name, generator in candidates.GENERATORS.items():
        context = candidates.RetrievalContext(conn=conn, aq=analyzed, scope=scope, now=moment)
        results[name] = generator(context)

    fused = fusion.fuse(results, intent=analyzed.intent)
    features = fusion.load_features(conn, scope=scope, keys=fused.keys())
    ranked = fusion.rank(fused, features, now=moment, weights=rank_weights)

    rows = gate.load_rows(conn, scope=scope, keys=[r.key for r in ranked])
    if not with_gate:
        return Retrieval(analyzed=analyzed, rankings=ranked, rows=rows)

    texts = {key: info.text for key, info in rows.items()}
    coverages = gate.coverage(list(analyzed.terms), texts)
    gated = gate.apply_gate(ranked, rows=rows, coverages=coverages, config=gate_config)
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
    return Retrieval(
        analyzed=analyzed,
        rankings=diversity.mmr(collapsed.kept, texts=texts),
        rows=rows,
    )
