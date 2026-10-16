"""The query-embedding seam for the v3 read paths — EM-412.

The owner-approved wiring: one callable is handed to every read site that
wants a query vector — the tool search path, ``PrefetchService``'s async
precompute half and the facade's flag-on ``recall_with_relevance`` — and
this module is the one place it is built, so the three sites cannot drift
on the owner's rules:

* **Hard fail-soft.** Any backend failure — a raised exception, an
  ``openai_compat`` timeout past its per-call bound — returns ``None`` and
  the caller serves the lexical result. Nothing propagates: an embed can
  never fail a search, and it cannot stall it past the backend's own
  per-call timeout.
* **Counted per session.** One instance per provider (i.e. per session):
  a debug line per call and one ``log_summary()`` line with the session's
  totals, so a potentially paid backend's usage is visible.

Flag gating is the caller's: the provider builds this only when
``embeddings.enabled`` is on, and passes ``None`` otherwise — which is what
keeps the served paths byte-identical with the flag off.

Stdlib-only; the backend and the model name live in the ``EmbeddingService``
handed in.
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

log = logging.getLogger("em.embeddings.query")

__all__ = ["QueryEmbedder"]


class QueryEmbedder:
    """``EmbeddingService.embed_query`` behind the read-path rules."""

    def __init__(self, service: Any, *, session_id: str = "") -> None:
        self.session_id = session_id or ""
        self.calls = 0
        self.embedded = 0
        self.failed = 0
        self._service = service

    @property
    def model(self) -> str:
        """The model the vectors are for — stored rows must name it exactly."""
        return str(getattr(self._service, "model", "") or "")

    def __call__(self, text: str) -> Optional[List[float]]:
        self.calls += 1
        try:
            vector = self._service.embed_query(text or "")
        except Exception as exc:  # noqa: BLE001 - the search path never breaks on an embed
            self.failed += 1
            log.debug(
                "query embedding failed (session %s): %s: %s",
                self.session_id or "-",
                type(exc).__name__,
                exc,
            )
            return None
        if vector is None:
            return None
        self.embedded += 1
        log.debug(
            "query embedding #%d for session %s (embedded=%d failed=%d)",
            self.calls,
            self.session_id or "-",
            self.embedded,
            self.failed,
        )
        return list(vector)

    def log_summary(self) -> None:
        """The session's totals, one INFO line — only when it embedded at all."""
        if not self.calls:
            return
        log.info(
            "query embeddings this session: %d call(s), %d embedded, %d failed,"
            " model=%s (session %s)",
            self.calls,
            self.embedded,
            self.failed,
            self.model,
            self.session_id or "-",
        )
