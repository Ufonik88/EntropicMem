"""The query-embedding seam for the v3 read paths — EM-412.

The owner-approved wiring: one callable is handed to every read site that
wants a query vector — the tool search path, ``PrefetchService``'s async
precompute half and the facade's flag-on ``recall_with_relevance`` — and
this module is the one place it is built, so the three sites cannot drift
on the owner's rules:

* **Hard fail-soft, wall-clock bounded.** Every backend call runs on a
  short-lived daemon thread the seam joins for at most ``timeout_s``
  (default: ``openai_compat``'s 20 s per-call bound, so the local backends
  are bounded too). Any failure — a raised exception, a timeout past the
  bound — returns ``None`` and the caller serves the lexical result. Nothing
  propagates: an embed can never fail a search, and it cannot stall the
  calling (search / prefetch) thread past the bound. A call arriving while
  a previous embed is still running past its bound fast-fails instead of
  queueing behind it.
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
import threading
from typing import Any, List, Optional

log = logging.getLogger("em.embeddings.query")

__all__ = ["DEFAULT_TIMEOUT_S", "QueryEmbedder"]

#: The seam's wall-clock bound, per call. Matches ``openai_compat``'s per-call
#: timeout so the paid backend keeps its approved bound and the local backends
#: (which ship without one) gain it.
DEFAULT_TIMEOUT_S = 20.0


class QueryEmbedder:
    """``EmbeddingService.embed_query`` behind the read-path rules."""

    def __init__(
        self,
        service: Any,
        *,
        session_id: str = "",
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self.session_id = session_id or ""
        self.calls = 0
        self.embedded = 0
        self.failed = 0
        self.timeout_s = float(timeout_s)
        self._service = service
        self._inflight: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    @property
    def model(self) -> str:
        """The model the vectors are for — stored rows must name it exactly."""
        return str(getattr(self._service, "model", "") or "")

    def __call__(self, text: str) -> Optional[List[float]]:
        self.calls += 1
        holder: List[Any] = []
        with self._lock:
            prior = self._inflight
            if prior is not None and prior.is_alive():
                # Its result is already discarded; do not queue behind it.
                self.failed += 1
                log.debug(
                    "query embedding skipped (session %s): a previous embed is"
                    " still running past its %.1f s bound",
                    self.session_id or "-",
                    self.timeout_s,
                )
                return None
            thread = threading.Thread(
                target=self._embed_into,
                args=(text, holder),
                name="em-query-embed",
                daemon=True,
            )
            self._inflight = thread
            thread.start()
        thread.join(self.timeout_s)
        if thread.is_alive():
            # The daemon thread is left to finish; its result is discarded and
            # it never blocks exit. Later calls fast-fail until it does.
            self.failed += 1
            log.debug(
                "query embedding timed out (session %s): past the %.1f s bound;"
                " serving the lexical result",
                self.session_id or "-",
                self.timeout_s,
            )
            return None
        outcome = holder[0] if holder else None
        if isinstance(outcome, BaseException):
            self.failed += 1
            log.debug(
                "query embedding failed (session %s): %s: %s",
                self.session_id or "-",
                type(outcome).__name__,
                outcome,
            )
            return None
        if outcome is None:
            return None
        self.embedded += 1
        log.debug(
            "query embedding #%d for session %s (embedded=%d failed=%d)",
            self.calls,
            self.session_id or "-",
            self.embedded,
            self.failed,
        )
        return list(outcome)

    def _embed_into(self, text: str, holder: List[Any]) -> None:
        """The worker half; the vector, ``None`` or the exception lands in ``holder``."""
        try:
            holder.append(self._service.embed_query(text or ""))
        except Exception as exc:  # noqa: BLE001 - carried to the caller thread
            holder.append(exc)

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
