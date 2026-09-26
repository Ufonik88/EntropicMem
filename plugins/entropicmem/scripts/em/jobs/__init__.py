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

__all__ = [
    "HandlerRegistry",
    "JobContext",
    "JobWorker",
    "PermanentJobError",
    "default_worker_id",
]
