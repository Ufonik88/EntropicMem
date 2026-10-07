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
* the token packer and §3.6's full render (EM-307), so ``prefetch`` emits the
  minimal id-bearing bullet form the runner parses (``- [id] text``) with no token
  budget. ``prefetch_tokens`` is an "info" metric, not a gated one, so an unbudgeted
  block cannot fail a compare — but do not read that number as the shipped render;
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
from em.retrieval import pipeline  # noqa: E402
from em.store.db import Store  # noqa: E402
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

    def __init__(self, disable_embeddings: bool = True) -> None:
        # Accepted for interface parity with `engine_v2`. v3 has no embedding path
        # yet (EM-303), so there is nothing to force off; when EM-303 lands, this is
        # where the backend gets disabled for the `ci` suite.
        self.disable_embeddings = disable_embeddings
        self._tmpdirs: List[tempfile.TemporaryDirectory] = []
        self._stores: List[Store] = []

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

        return EvalHandle(
            scenario=scenario,
            ref_ids=ref_ids,
            noise_ids=noise_ids,
            extra={"store": store, "conn": store.reader(), "scope": scope},
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
        """
        outcome = pipeline.retrieve(
            handle.extra["conn"],
            scope=handle.extra["scope"],
            query=query,
            with_gate=with_gate,
        )
        return outcome.rankings, outcome.rows
