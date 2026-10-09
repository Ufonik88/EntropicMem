"""v3 engine adapter: drives the `em` retrieval pipeline over a migrated v3 store.

This is the adapter EM-306 tunes and the one that produces the end-to-end v3 number
the cutover re-decision waits on. It measures **the pipeline as built** — the same
functions the provider will call — rather than a re-implementation, so a score here
is a score for `analyze → GENERATORS → fuse → rank → gate → collapse → mmr`.

Two deliberate asymmetries with `engine_v2`, both mirroring how the v2 adapter
already separates ranking from abstention:

* ``search`` runs the pipeline **without the gate**. Ranking metrics measure ORDER;
  the gate is a filter, and letting it truncate here would score abstention twice.
  This is the same reason the v2 adapter recalls with ``min_relevance=0.0``.
* ``prefetch`` runs the pipeline **with the gate**, then collapses and diversifies,
  and returns ``''`` when nothing survives — which is what `abstain_correct` reads.

**What is not here, and why:**
* the vector generator and the gate's cosine condition, because EM-303 owns the
  embedding backend — a v3 score today is lexical, entity and episodic only;
* §3.6's block. EM-307 can render a gated retrieval, and this ``prefetch``
  deliberately does not call it: the bullet stays ``- [id] text`` with the
  stored id and no token budget. A short citation would stop the runner
  matching ids, and a budget can drop an id this bullet emits. Switching is a
  separate change. ``prefetch_tokens`` is an "info" metric, so the missing
  budget cannot fail a compare — but this number is not the shipped render;
* anything to do with a v2 store: this adapter builds a v3 one and never migrates or
  touches a live database.
"""

from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

from evals.adapters.base import AdapterBase, EvalHandle, Hit
from evals.dataset import Scenario
from evals.noise import generate

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _REPO_ROOT / "plugins" / "entropicmem" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from em.clock import to_iso  # noqa: E402
from em.embeddings.service import EmbeddingService, memory_text  # noqa: E402
from em.retrieval import pipeline  # noqa: E402
from em.store.db import Store  # noqa: E402
from em.store.embeddings import put_embedding  # noqa: E402
from em.store.memories import MemoryStore  # noqa: E402
from em.store.migrations import migrate  # noqa: E402
from em.store.types import MemoryDraft, Scope  # noqa: E402

#: The eval profile. Every scenario in the shipped suites is single-owner
#: (``scope_user: ""``), so one profile-wide scope is the whole story.
_PROFILE = "eval"

#: The bullet shape ``evals.runner.parse_injected_ids`` reads (``^- [id]``).
_BULLET = "- [{id}] {text}"


class EngineV3Adapter(AdapterBase):
    """One scenario per handle: a fresh temp v3 store, driven by the real pipeline."""

    name = "v3"

    def __init__(
        self,
        disable_embeddings: bool = True,
        *,
        gate_config: Any = None,
        rank_weights: Any = None,
        embedding_service: Any = None,
    ) -> None:
        # Same contract as `engine_v2`: the ci/hard suites pass True and stay
        # lexical; any other suite passes False and uses vectors when a backend
        # is available. ``embedding_service=None`` builds one from the
        # environment on first use (``none`` backend unless fastembed /
        # sentence-transformers / an OpenAI-compatible endpoint is configured);
        # tests inject a deterministic one.
        self.disable_embeddings = disable_embeddings
        # EM-306's calibration seam: the tune harness builds one adapter per candidate.
        # ``None`` — what every other caller passes — is the spec defaults.
        self._gate_config = gate_config
        self._rank_weights = rank_weights
        self._embedding_service = embedding_service
        self._tmpdirs: List[tempfile.TemporaryDirectory] = []
        self._stores: List[Store] = []

    def _service(self) -> Any:
        if self._embedding_service is None:
            self._embedding_service = EmbeddingService(":memory:")
        return self._embedding_service

    def _active_service(self) -> Any:
        """The service to use, or ``None`` when embeddings are off/unavailable."""
        if self.disable_embeddings:
            return None
        service = self._service()
        return service if service.available else None

    @property
    def retrieval_mode(self) -> str:
        """``"vector"`` only when this run will actually embed queries."""
        if self.disable_embeddings:
            return "lexical"
        return "vector" if self._service().available else "lexical"

    # ── adapter interface ──────────────────────────────────────────────

    def load(self, scenario: Scenario) -> EvalHandle:
        tmp = tempfile.TemporaryDirectory(prefix="em-eval-v3-")
        self._tmpdirs.append(tmp)
        store = Store(str(Path(tmp.name) / "memory.db"))
        self._stores.append(store)
        with store.writer() as conn:
            migrate(conn)

        scope = Scope(profile=_PROFILE)
        ref_ids: Dict[str, str] = {}
        with store.transaction() as conn:
            memories = MemoryStore(conn)
            for index, memory in enumerate(scenario.memories):
                result = memories.add(
                    MemoryDraft(
                        content=memory.content,
                        kind=memory.kind,
                        domain=memory.domain,
                        importance=memory.importance,
                        source="agent",
                        status="active",
                    ),
                    scope=scope,
                    actor="eval",
                )
                if not result.ok:
                    raise RuntimeError(
                        f"{scenario.scenario_id}: scenario memory refused by policy "
                        f"({result.reason_code}): {memory.content!r}"
                    )
                ref_ids[f"${index}"] = result.id
                if memory.age_days:
                    # §3.6's age is `now - max(updated_at, last_accessed_at, valid_from)`,
                    # so the seed stamp is `updated_at` (and `created_at` to stay
                    # coherent). The live clock is the right "now" here: the ages are
                    # relative, not absolute.
                    stamp = to_iso(datetime.now(timezone.utc) - timedelta(days=memory.age_days))
                    conn.execute(
                        "UPDATE memories SET created_at=?, updated_at=? WHERE id=?",
                        (stamp, stamp, result.id),
                    )

        noise_ids = set()
        with store.transaction() as conn:
            memories = MemoryStore(conn)
            for content in generate(
                scenario.noise.generator, scenario.noise.count, scenario.noise.seed
            ):
                result = memories.add(
                    MemoryDraft(content=content, importance=0.3, source="agent", status="active"),
                    scope=scope,
                    actor="eval",
                )
                if result.ok:
                    noise_ids.add(result.id)

        service = self._active_service()
        if service is not None:
            self._embed_documents(store, service)

        return EvalHandle(
            scenario=scenario,
            ref_ids=ref_ids,
            noise_ids=noise_ids,
            extra={"store": store, "conn": store.reader(), "scope": scope},
        )

    def _embed_documents(self, store: Store, service: Any) -> None:
        """Embed every memory in the scenario store (EM-303's document side).

        Without this a query vector would have nothing to match. The service is
        already warm after this call, and the ``ci``/``hard`` suites never reach
        here because they pass ``disable_embeddings=True``.
        """
        rows = store.reader().execute(
            "SELECT id, content, summary FROM memories"
        ).fetchall()
        if not rows:
            return
        texts = [memory_text(row["summary"] or "", row["content"] or "") for row in rows]
        vectors = service.embed_texts(texts)
        stamp = to_iso(datetime.now(timezone.utc))
        with store.transaction() as conn:
            for row, vector in zip(rows, vectors):
                put_embedding(
                    conn,
                    owner_id=row["id"],
                    model=service.model,
                    vector=vector,
                    created_at=stamp,
                )

    def search(self, handle: EvalHandle, query: str, k: int = 5) -> List[Hit]:
        ranked, rows = self._run(handle, query, with_gate=False)
        hits: List[Hit] = []
        for ranking in ranked[:k]:
            info = rows.get(ranking.key)
            hits.append(
                Hit(
                    id=ranking.owner_id,
                    content=info.text if info is not None else "",
                    score=float(ranking.score),
                )
            )
        return hits

    def prefetch(self, handle: EvalHandle, query: str) -> str:
        kept, rows = self._run(handle, query, with_gate=True)
        if not kept:
            return ""
        lines = []
        for ranking in kept:
            info = rows.get(ranking.key)
            lines.append(
                _BULLET.format(
                    id=ranking.owner_id,
                    text=info.text if info is not None else ranking.owner_id,
                )
            )
        return "\n".join(lines) + "\n"

    # ── lifecycle ───────────────────────────────────────────────────────

    def finish(self, handle: EvalHandle) -> None:
        pass  # temp dirs are cleaned in shutdown, one store per handle

    def shutdown(self) -> None:
        for store in self._stores:
            try:
                store.close()
            except Exception:
                pass
        self._stores.clear()
        for tmp in self._tmpdirs:
            try:
                tmp.cleanup()
            except Exception:
                pass
        self._tmpdirs.clear()

    # ── the pipeline ────────────────────────────────────────────────────

    def _run(
        self, handle: EvalHandle, query: str, *, with_gate: bool
    ) -> Tuple[List[Any], Dict[Any, Any]]:
        """Drive §3.6's pipeline. Returns ``(rankings, rows)``.

        The sequence itself lives in ``em.retrieval.pipeline``, because the provider's
        shadow read (P0) needs exactly the same one — two copies of an "identical"
        pipeline is how they stop being identical. ``rows`` comes back either way so
        the caller can render text for keys the gate dropped as well as those it kept.

        EM-303: when vectors are enabled and a backend is available, the query is
        embedded here (offline; never the prefetch thread) and both the generator
        and the gate's cosine condition see it. The frozen suites disable this.
        """
        service = self._active_service()
        query_vector = service.embed_query(query) if service is not None else None
        embedding_model = service.model if (service is not None and query_vector) else None
        outcome = pipeline.retrieve(
            handle.extra["conn"],
            scope=handle.extra["scope"],
            query=query,
            with_gate=with_gate,
            gate_config=self._gate_config,
            rank_weights=self._rank_weights,
            query_vector=query_vector,
            embedding_model=embedding_model,
        )
        return outcome.rankings, outcome.rows
