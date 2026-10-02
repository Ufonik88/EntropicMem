"""EM-211 Chunk 4: the v3 facade engine — the READ half over ``em.store``.

``V3Engine`` keeps the v2 ``MemoryEngine`` API (the exact surface the Hermes
provider uses is pinned in ``em.facade.contract``) on top of the v3 storage
core. This file implements the reads: ``get_fact`` (including ``legacy_id``
resolution, which is what the provider's mirror lookup needs), ``stats``,
``recall_with_relevance``, ``recall_hybrid`` and ``next_episode_wave``.

The write methods (``remember``, ``forget``, ``touch``, ``add_episode``,
``consolidate``, ``extract_and_store``, ``prune_pending``) exist as
correctly-shaped stubs that raise :class:`NotImplementedError` — the contract
signature test can register the facade today, and Chunk 5 replaces each stub
with the real write path. Nothing here is wired into the provider yet.

Design notes for reviewers:

* Recall borrows v2's ``StoredFact`` and scoring helpers
  (``build_fts_query``, ``coverage``, ``run_fts_match``, the LIKE fallback)
  from ``memory_engine`` — lazily, because at 3.0 ``memory_engine.py`` becomes
  a back-compat shim over this facade and a module-level import would be a
  cycle — so the parity suite pins identical behaviour while S3 builds the
  real v3 retriever. Returned ``StoredFact.id`` is ``legacy_id`` when the row
  carries one (migrated or mirrored rows) else the v3 id, the card's rule.
* Only ``status='active'`` memories recall, and a ``deleted`` row reads as
  absent through ``get_fact`` too: v2's ``forget`` removed the row outright.
  Pending rows surface through ``get_fact`` by id (v2 kept them in a separate
  table the recall paths never touched) but never through recall.
* ``recall_hybrid``'s vector leg is EM-303; until it lands, hybrid is the
  FTS-only pass — exactly what v2 does when embeddings are off.
  ``expand_links`` and ``auto_reinforce`` are accepted and inert: graph
  expansion needs the v2 ``graph_edges`` (it moves with the mirror chunk) and
  reinforcement is a write (Chunk 5). Recorded as ``Deviation:`` in the PR.

Stdlib-only apart from the v2 helpers named above; never imports the provider
or the Hermes host (plan §3.2).
"""

from __future__ import annotations

import json
import logging
import math
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from ..clock import utc_now
from ..store.db import Store
from ..store.memories import MemoryStore
from ..store.migrations import migrate
from ..store.types import Scope

logger = logging.getLogger("em.facade.engine")

__all__ = ["V3Engine"]

#: fts columns on ``memories_fts`` the facade searches (v2's ``title`` lives
#: in ``summary`` in v3).
_FTS_FIELDS = ("content", "summary", "tags")


def _v2():
    """The v2 ``memory_engine`` module, resolved lazily.

    Chunk 4 borrows v2's ``StoredFact`` and scoring helpers so the parity
    suite pins identical behaviour until S3 ships the v3 retriever. The
    import must NOT be at module level: at 3.0 ``memory_engine.py`` turns into
    a back-compat shim over this facade, and a top-level import there×here
    would deadlock. ``sys.modules`` makes the repeated call a dict lookup.
    """
    mod = sys.modules.get("memory_engine")
    if mod is None:
        import memory_engine as mod
    return mod


def _row_to_fact(row: Dict[str, Any]) -> Any:
    """Build the v2 view of one v3 ``memories`` row.

    ``id`` is ``legacy_id`` when present (migrated v2 rows and mirrored rows
    carry the content-derived id), else the v3 id — the card's rule.
    """
    StoredFact = _v2().StoredFact
    legacy = row.get("legacy_id") or ""
    try:
        tags = json.loads(row.get("tags") or "[]")
    except (TypeError, ValueError):
        tags = []
    return StoredFact(
        id=legacy or row["id"],
        content=row["content"],
        title=row.get("summary") or "",
        source=row.get("source") or "agent",
        importance=row["importance"] if row.get("importance") is not None else 0.5,
        domain=row.get("domain") or "Knowledge",
        tags=list(tags) if isinstance(tags, list) else [],
        created_at=row.get("created_at") or "",
        updated_at=row.get("updated_at") or "",
        last_accessed=row.get("last_accessed_at") or "",
        access_count=row.get("access_count") or 0,
        sensitivity=row.get("sensitivity") or "internal",
    )


def _decay_factor(
    fact: Any,
    now_ts: datetime,
    half_life_days: float,
    decay_floor: float,
    evergreen_domains: set,
) -> float:
    """EM-106 decay semantics, the same rule the v2 engine applies (parity)."""
    if (
        fact.importance >= 0.75
        or fact.domain in evergreen_domains
        or fact.source in ("built_in_memory", "promoted")
        or "pinned" in (fact.tags or [])
    ):
        return 1.0
    parse = _v2()._parse_ts
    stamps = [s for s in (parse(fact.updated_at), parse(fact.last_accessed)) if s]
    if not stamps:
        return 1.0
    age_days = max(0.0, (now_ts - max(stamps)).total_seconds() / 86400.0)
    lam = math.log(2) / half_life_days if half_life_days > 0 else 0.0
    return max(decay_floor, math.exp(-lam * age_days))


class V3Engine:
    """The v2 engine API over the v3 store (Chunk 4: reads; writes in Chunk 5)."""

    def __init__(
        self,
        db_path: "Path | str",
        *,
        profile_id: str = "default",
        scope_user: str = "",
        scope_chat: str = "",
    ) -> None:
        self.db_path = Path(db_path)
        self.store = Store(self.db_path)
        # Profile-wide by default (v2 had one owner per DB): the facade maps a
        # v2 profile onto Scope(profile=..., user="") — §3.5's profile-wide
        # read. The gateway identity / owner-only rule lands with a later
        # EM-211 chunk, which is why this is a constructor argument and never
        # an environment read.
        self.scope = Scope(profile=profile_id, user=scope_user, chat=scope_chat)
        with self.store.writer() as conn:
            migrate(conn)

    # --- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        self.store.close()

    def __enter__(self) -> "V3Engine":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    # --- reads ---------------------------------------------------------------

    def _reader(self) -> sqlite3.Connection:
        return self.store.reader()

    def get_fact(self, entropic_id: str) -> Optional[Any]:
        """Resolve by v3 id, v2 ``legacy_id`` (the mirror-lookup path) or id prefix.

        A ``deleted`` row reads as absent: v2's ``forget`` removed the row, so
        callers test absence with ``is None``.
        """
        row = MemoryStore(self._reader()).get(entropic_id)
        if row is None or row["status"] == "deleted":
            return None
        return _row_to_fact(row)

    def stats(self) -> dict:
        conn = self._reader()
        count = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE status='active'"
        ).fetchone()[0]
        domains = conn.execute(
            "SELECT domain, COUNT(*) AS cnt FROM memories WHERE status='active'"
            " GROUP BY domain ORDER BY cnt DESC"
        ).fetchall()
        return {
            "fact_count": int(count),
            "db_path": str(self.db_path),
            "domains": {r["domain"]: int(r["cnt"]) for r in domains},
        }

    def next_episode_wave(self, episode_base: str) -> int:
        """Next ``{base}_wN`` for migrated/legacy-tagged episode ids (v2 parity).

        v3 episode ids are ULIDs; the wave naming lives in ``legacy_id`` (what
        the v2-to-v3 migration writes, and what the writes chunk will keep
        writing), so the cadence-digest logic survives the cutover untouched.
        """
        like = _v2().escape_like(episode_base) + "_w%"
        rows = self._reader().execute(
            "SELECT legacy_id FROM episodes WHERE legacy_id LIKE ? ESCAPE '\\'",
            (like,),
        ).fetchall()
        n = 0
        for row in rows:
            tail = str(row["legacy_id"]).rsplit("_w", 1)[-1]
            if tail.isdigit():
                n = max(n, int(tail))
        return n + 1

    def recall_with_relevance(
        self,
        query: str,
        top_k: int = 10,
        domain: Optional[str] = None,
        min_relevance: float = 0.0,
        decay_enabled: bool = True,
        decay_half_life_days: float = 90.0,
        decay_floor: float = 0.5,
        evergreen_domains: Optional[Sequence[str]] = None,
        reinforcement_boost: float = 0.1,
        auto_reinforce: bool = False,
    ) -> List[Any]:
        """EM-105/EM-106 scoring over the v3 ``memories_fts`` index.

        Same formula as v2 — relevance = 0.75*coverage + 0.25*rank_bonus,
        combined = relevance * decay * (0.85 + 0.3*importance), clipped — so
        the parity suite pins identical behaviour while S3 replaces this with
        the v3 retriever. ``auto_reinforce`` is accepted and inert here:
        reinforcement is a write and lands with Chunk 5 (``Deviation``).
        """
        if not query.strip():
            return []

        v2 = _v2()
        fts_query = v2.build_fts_query(query, fields=_FTS_FIELDS)
        where = ""
        params: tuple = ()
        if domain:
            where = "AND m.domain = ?"
            params = (domain,)

        match_failed = False
        rows: list = []
        if fts_query:
            rows, fts_reason = v2.run_fts_match(
                self._reader(),
                "SELECT m.*, bm25(memories_fts) AS rank"
                " FROM memories_fts JOIN memories m ON memories_fts.rowid = m.rid"
                f" WHERE memories_fts MATCH ? AND m.status='active' {where}"
                " ORDER BY rank LIMIT ?",
                (fts_query, *params, top_k * 2),
            )
            match_failed = fts_reason == v2.FTS_REASON_MATCH_ERROR

        if not rows:
            if not v2._like_fallback_ok(query, match_failed):
                return []
            return self._like_fallback(query, top_k, domain, min_relevance, match_failed)

        query_terms = v2.coverage_terms(query)
        evergreen: set = (
            set(evergreen_domains) if evergreen_domains is not None else {"People"}
        )
        now_ts = utc_now()

        results: List[Any] = []
        for idx, row in enumerate(rows):
            fact = _row_to_fact(dict(row))
            text = " ".join(
                p for p in (fact.title, fact.content, " ".join(fact.tags or [])) if p
            )
            lex = v2.coverage(query_terms, text)
            rank_bonus = 1.0 / (1.0 + 0.15 * idx)
            relevance = 0.75 * lex + 0.25 * rank_bonus
            fact.decay_score = (
                _decay_factor(fact, now_ts, decay_half_life_days, decay_floor, evergreen)
                if decay_enabled
                else 1.0
            )
            combined = min(
                1.0, max(0.0, relevance * fact.decay_score * (0.85 + 0.3 * fact.importance))
            )
            if combined >= min_relevance:
                fact.relevance_score = combined
                fact.why_retrieved = v2.MemoryEngine._build_reasons(
                    fts_match=True,
                    recency_applied=decay_enabled,
                    importance_applied=True,
                    domain_filtered=bool(domain),
                ) + [{"signal": "coverage", "value": round(lex, 4)}]
                results.append(fact)

        results.sort(key=lambda f: f.relevance_score, reverse=True)
        return results[:top_k]

    def _like_fallback(
        self,
        query: str,
        top_k: int,
        domain: Optional[str],
        min_relevance: float,
        match_error: bool,
    ) -> List[Any]:
        """Escaped literal LIKE sweep — v2's symbol-query path, same rule."""
        v2 = _v2()
        where = ""
        params: tuple = ()
        if domain:
            where = "AND domain = ?"
            params = (domain,)
        like = f"%{v2.escape_like(query)}%"
        rows = self._reader().execute(
            "SELECT * FROM memories"
            " WHERE status='active' AND (content LIKE ? ESCAPE '\\'"
            "  OR summary LIKE ? ESCAPE '\\' OR tags LIKE ? ESCAPE '\\')"
            f" {where} ORDER BY importance DESC LIMIT ?",
            (like, like, like, *params, top_k),
        ).fetchall()
        results = []
        for row in rows:
            fact = _row_to_fact(dict(row))
            fact.relevance_score = fact.importance * 0.8
            if fact.relevance_score >= min_relevance:
                fact.why_retrieved = v2.MemoryEngine._build_reasons(
                    like_fallback=True,
                    importance_applied=True,
                    domain_filtered=bool(domain),
                    match_error=match_error,
                )
                results.append(fact)
        return results

    def recall_hybrid(
        self,
        query: str,
        top_k: int = 10,
        domain: Optional[str] = None,
        fts_weight: float = 0.6,
        vec_weight: float = 0.4,
        expand_links: bool = False,
        auto_reinforce: bool = False,
    ) -> List[Any]:
        """Hybrid recall. Chunk 4: the FTS leg only.

        v2 already falls back to exactly this when embeddings are off, and the
        v3 vector search is EM-303's job (the ``embed`` queue is not wired to
        a retriever yet). ``expand_links`` needs the v2 graph tables and moves
        with the mirror chunk; both differences are ``Deviation:`` in the PR.
        """
        return self.recall_with_relevance(query, top_k=top_k, domain=domain)

    # --- write stubs (Chunk 5 replaces each with the real write path) -------

    def remember(
        self,
        content: str = "",
        title: str = "",
        source: str = "agent",
        importance: float = 0.5,
        domain: str = "Knowledge",
        tags: Optional[List[str]] = None,
        session_id: str = "",
        sensitivity: Optional[str] = None,
        actor: Optional[str] = None,
    ) -> str:
        raise NotImplementedError("EM-211 writes chunk: remember over MemoryStore.add")

    def forget(self, entropic_id: str, *, confirm: bool = False) -> bool:
        raise NotImplementedError("EM-211 writes chunk: forget as a status transition")

    def touch(self, fact_ids: Sequence[str]) -> int:
        raise NotImplementedError("EM-211 writes chunk: touch via MemoryStore.touch")

    def extract_and_store(
        self,
        user_text: str = "",
        assistant_text: str = "",
        session_id: str = "",
        source: str = "auto_extracted",
        min_confidence: float = 0.4,
        promote: bool = True,
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError("EM-211 writes chunk: extraction pipeline")

    def prune_pending(self, older_than_days: int = 30) -> int:
        raise NotImplementedError("EM-211 writes chunk: pending TTL prune")

    def add_episode(
        self,
        title: str = "",
        summary: str = "",
        *,
        start_ts: Optional[str] = None,
        end_ts: Optional[str] = None,
        source_session: str = "",
        linked_fact_ids: Optional[List[str]] = None,
        importance: float = 0.5,
        domain: str = "Knowledge",
        source: str = "agent",
        episode_id: Optional[str] = None,
    ) -> str:
        raise NotImplementedError("EM-211 writes chunk: EpisodeStore.add_episode")

    def consolidate(
        self,
        max_age_days: int = 90,
        min_access_count: int = 0,
        dry_run: bool = True,
        confirm: bool = False,
        evergreen_domains: Optional[Sequence[str]] = None,
    ) -> dict:
        raise NotImplementedError("EM-211 writes chunk: consolidation report")
