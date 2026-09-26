"""Job worker: claim, run a handler, record the outcome (card EM-209).

The transaction rule is the point of this module. Each step gets its own short
write transaction: claim, then heartbeat, then complete or fail. **The handler
runs outside all of them.** A handler that calls an embedding model or any
other slow service therefore never holds the SQLite write lock. Anything the
handler writes goes through ``ctx.store.transaction()``, one short transaction
per unit of work.

Handler contract:

- The signature is ``handler(job, ctx) -> None``. Returning means success.
- Handlers must be **idempotent**, because delivery is at-least-once: a handler
  that overruns its lease can be re-run by another worker. Key writes by
  something stable (the embed handler upserts on ``(owner, model)``).
- Raise ``PermanentJobError`` for input that can never succeed, such as a
  deleted memory or a malformed payload. The job goes straight to ``dead``.
  Any other exception is retried with backoff until ``max_attempts``.
- Call ``ctx.heartbeat()`` in long loops. If it returns False, the lease is
  gone: stop and return.
- Never put memory content in exception messages. ``last_error`` is capped,
  but it is still stored.
"""

from __future__ import annotations

import logging
import os
import socket
import threading
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterator, Optional

from ..clock import utc_now
from ..store.db import Store
from ..store.jobs import DEFAULT_LEASE_SECONDS, Job, JobQueue, sanitise_error

log = logging.getLogger("em.jobs")

Handler = Callable[[Job, "JobContext"], None]


class PermanentJobError(Exception):
    """Raised by a handler when retrying cannot help. The job goes to ``dead``."""


def default_worker_id() -> str:
    """``host:pid:rand`` — unique per process, readable in ``locked_by``."""
    return f"{socket.gethostname()}:{os.getpid()}:{os.urandom(3).hex()}"


@dataclass
class _Registration:
    handler: Handler
    lease_seconds: float


class HandlerRegistry:
    """Map of job type to handler. A worker only claims registered types."""

    def __init__(self) -> None:
        self._handlers: Dict[str, _Registration] = {}

    def register(
        self, job_type: str, handler: Handler | None = None, *, lease_seconds: float | None = None
    ):
        """Register ``handler`` for ``job_type``. Usable as a decorator."""

        def _add(fn: Handler) -> Handler:
            if job_type in self._handlers:
                raise ValueError(f"handler already registered for job type {job_type!r}")
            self._handlers[job_type] = _Registration(
                fn, float(lease_seconds) if lease_seconds is not None else DEFAULT_LEASE_SECONDS
            )
            return fn

        if handler is not None:
            return _add(handler)
        return _add

    def types(self) -> list[str]:
        return sorted(self._handlers)

    def get(self, job_type: str) -> _Registration | None:
        return self._handlers.get(job_type)

    def __contains__(self, job_type: object) -> bool:
        return job_type in self._handlers

    def __iter__(self) -> Iterator[str]:
        return iter(self.types())


@dataclass
class JobContext:
    """What a handler gets besides the job itself."""

    store: Store
    job: Job
    worker_id: str
    lease_seconds: float
    lease_lost: bool = field(default=False, init=False)

    def heartbeat(self) -> bool:
        """Extend the lease. False means another worker may own the job now."""
        if self.lease_lost:
            return False
        with self.store.transaction() as conn:
            ok = JobQueue(conn).heartbeat(
                self.job.id, self.worker_id, lease_seconds=self.lease_seconds
            )
        if not ok:
            self.lease_lost = True
        return ok


@dataclass(frozen=True)
class JobOutcome:
    job_id: str
    type: str
    #: ``done``, ``failed`` (will retry), ``dead``, or ``lost`` (the lease
    #: expired and another worker owns the row; nothing was recorded).
    status: str
    error: Optional[str] = None


class JobWorker:
    """Runs jobs from one ``Store`` with the handlers in a registry.

    Use ``run_once`` / ``run_until_idle`` from tests, CLI commands and the
    provider's idle hook. Use ``run`` for a long-lived background thread with a
    stop event.
    """

    def __init__(
        self,
        store: Store,
        registry: HandlerRegistry,
        *,
        worker_id: str | None = None,
    ) -> None:
        self.store = store
        self.registry = registry
        self.worker_id = worker_id or default_worker_id()

    def _claim(self) -> tuple[Job, _Registration] | None:
        types = self.registry.types()
        if not types:
            return None
        # Claim with the longest registered lease, then shorten it to the
        # handler's own lease once the type is known. Cheaper than one
        # claim query per type, and a short-lease job is never under-leased.
        longest = max(self.registry.get(t).lease_seconds for t in types)  # type: ignore[union-attr]
        with self.store.transaction() as conn:
            q = JobQueue(conn)
            job = q.claim(self.worker_id, types=types, lease_seconds=longest)
            if job is None:
                return None
            reg = self.registry.get(job.type)
            assert reg is not None  # claim filtered by registered types
            if reg.lease_seconds != longest:
                q.heartbeat(job.id, self.worker_id, lease_seconds=reg.lease_seconds)
                job = q.get(job.id) or job
        return job, reg

    def run_once(self) -> JobOutcome | None:
        """Claim and run at most one job. None when nothing is ready."""
        claimed = self._claim()
        if claimed is None:
            return None
        job, reg = claimed
        ctx = JobContext(self.store, job, self.worker_id, reg.lease_seconds)
        try:
            reg.handler(job, ctx)
        except PermanentJobError as exc:
            return self._record_failure(job, exc, permanent=True)
        except Exception as exc:  # noqa: BLE001 - every handler error is a job failure
            return self._record_failure(job, exc, permanent=False)
        except BaseException:
            # KeyboardInterrupt / SystemExit: give the job back without using
            # up an attempt, then let the interrupt through.
            try:
                with self.store.transaction() as conn:
                    JobQueue(conn).release(job.id, self.worker_id)
            finally:
                raise
        with self.store.transaction() as conn:
            ok = JobQueue(conn).complete(job.id, self.worker_id)
        if not ok:
            log.warning("job %s (%s): lease lost before completion", job.id, job.type)
            return JobOutcome(job.id, job.type, "lost")
        return JobOutcome(job.id, job.type, "done")

    def _record_failure(self, job: Job, exc: BaseException, *, permanent: bool) -> JobOutcome:
        err = sanitise_error(exc)
        with self.store.transaction() as conn:
            status = JobQueue(conn).fail(job.id, self.worker_id, exc, permanent=permanent)
        if status is None:
            log.warning("job %s (%s): lease lost before failure was recorded", job.id, job.type)
            return JobOutcome(job.id, job.type, "lost", err)
        # Type and id only: the payload may reference user content.
        log.warning("job %s (%s) %s after attempt %d: %s", job.id, job.type, status, job.attempts, err)
        return JobOutcome(job.id, job.type, status, err)

    def run_until_idle(self, *, max_jobs: int | None = None) -> list[JobOutcome]:
        """Run ready jobs until none is ready (or ``max_jobs`` ran)."""
        outcomes: list[JobOutcome] = []
        while max_jobs is None or len(outcomes) < max_jobs:
            outcome = self.run_once()
            if outcome is None:
                break
            outcomes.append(outcome)
        return outcomes

    def run(
        self,
        stop: threading.Event,
        *,
        poll_seconds: float = 5.0,
    ) -> int:
        """Loop until ``stop`` is set. Returns the number of jobs run.

        Sleeps at most ``poll_seconds`` between empty polls, less if a job
        becomes ready sooner. The sleep is ``stop.wait``, so shutdown is prompt.
        """
        count = 0
        while not stop.is_set():
            outcome = self.run_once()
            if outcome is not None:
                count += 1
                continue
            stop.wait(self._idle_delay(poll_seconds))
        return count

    def _idle_delay(self, poll_seconds: float) -> float:
        nxt = JobQueue(self.store.reader()).next_run_after(types=self.registry.types())
        if nxt is None:
            return poll_seconds
        wait = (nxt - utc_now()).total_seconds()
        return max(0.05, min(poll_seconds, wait))
