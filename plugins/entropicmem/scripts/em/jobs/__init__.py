"""``em.jobs`` — the background job framework (card EM-209).

``em.store.jobs.JobQueue`` is the durable queue (SQL on the ``jobs`` table);
``em.jobs.worker.JobWorker`` claims jobs and runs registered handlers.

Stdlib-only (plan §3.2). Never imports the Hermes host or the provider layer.
"""

from .worker import (
    HandlerRegistry,
    JobContext,
    JobWorker,
    PermanentJobError,
    default_worker_id,
)

#: Formation job types whose handlers this build actually carries. The
#: provider only enqueues a window extraction when ``"extract_window"`` is in
#: here (EM-411's second capture gate): a build without the handler must not
#: queue work nothing can run. **EM-502 registered both handlers** — the
#: extraction slice 2 — so the gate now passes and EM-411's capture enqueues
#: become live (with ``formation.mode != "off"``).
BUILT_FORMATION_HANDLERS: frozenset[str] = frozenset(
    {"extract_window", "extract_session"}
)

__all__ = [
    "BUILT_FORMATION_HANDLERS",
    "HandlerRegistry",
    "JobContext",
    "JobWorker",
    "PermanentJobError",
    "default_worker_id",
]
