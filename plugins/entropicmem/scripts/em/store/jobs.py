"""Durable job queue over the v3 ``jobs`` table (card EM-209).

Everything slow or retryable in v3 (embeddings, summaries, maintenance) runs
as a job, never inline in a write transaction. This module is the storage half:
plain SQL on a connection the caller owns, like every other ``em.store`` module.
The worker loop that claims jobs and runs handlers is ``em.jobs.worker``.

Semantics:

- **Enqueue is idempotent by dedupe key.** One key means one row. A queued or
  failed job with that key gets the new payload and schedule, so a retried
  write doesn't pile up duplicate work. A running, done or dead job is left
  alone. Anything that should run again, such as a daily maintenance job, puts
  the period in its key (``prune:2026-09-26``).
- **Claim is atomic and leased.** ``claim`` must run inside ``write_txn``
  (``BEGIN IMMEDIATE``), so two workers in two processes can never claim the
  same row. The claim sets ``locked_by`` and ``locked_until`` and increments
  ``attempts``.
- **A crash counts as an attempt.** ``attempts`` goes up at claim time, not at
  failure time. So a job whose handler kills the worker process (OOM,
  segfault, kill -9) still reaches ``max_attempts`` and becomes ``dead``,
  instead of crashing every worker that picks it up.
- **Expired leases are reclaimed.** A ``running`` job whose ``locked_until`` has
  passed is claimable again. Delivery is therefore at-least-once: a handler
  that overran its lease can race a second run. Handlers must be idempotent,
  and ``complete``/``fail`` report whether the caller still held the lease.
- **Lower priority number runs first** (0 is most urgent; the default is 5).
  The ``ix_jobs_ready`` index already covers ``(status, run_after, priority)``.
- **``last_error`` is sanitised.** It holds the exception type and a truncated
  first line only. Handlers must not put memory content in exception messages;
  this cap is the backstop, not the rule.

Timestamps are ``em.clock.to_iso`` strings (fixed width, UTC, ``Z``), so string
comparison in SQL is time comparison.
"""

from __future__ import annotations

import json
import random
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Iterable, Mapping, Optional

from ..clock import new_id, parse_iso, to_iso, utc_now

#: Every status the schema's CHECK constraint allows.
STATUSES = ("queued", "running", "done", "failed", "dead")

DEFAULT_PRIORITY = 5
DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_LEASE_SECONDS = 60.0

#: Retry backoff: ``BACKOFF_BASE * 2**(attempts-1)`` seconds, capped, +/-10 % jitter.
BACKOFF_BASE_SECONDS = 30.0
BACKOFF_CAP_SECONDS = 3600.0

#: ``last_error`` never holds more than this many characters.
MAX_ERROR_CHARS = 200


@dataclass(frozen=True)
class Job:
    id: str
    type: str
    payload: dict[str, Any]
    dedupe_key: Optional[str]
    status: str
    priority: int
    attempts: int
    max_attempts: int
    run_after: str
    locked_by: Optional[str]
    locked_until: Optional[str]
    last_error: Optional[str]
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Job":
        try:
            payload = json.loads(row["payload"]) if row["payload"] else {}
        except ValueError:
            payload = {}
        return cls(
            id=row["id"],
            type=row["type"],
            payload=payload,
            dedupe_key=row["dedupe_key"],
            status=row["status"],
            priority=int(row["priority"]),
            attempts=int(row["attempts"]),
            max_attempts=int(row["max_attempts"]),
            run_after=row["run_after"],
            locked_by=row["locked_by"],
            locked_until=row["locked_until"],
            last_error=row["last_error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


def backoff_seconds(
    attempts: int,
    *,
    base: float = BACKOFF_BASE_SECONDS,
    cap: float = BACKOFF_CAP_SECONDS,
    rand: Callable[[], float] = random.random,
) -> float:
    """Delay before retry number ``attempts`` (1-based): exponential, capped,
    +/-10 % jitter so a batch that failed together doesn't retry together."""
    raw = min(cap, base * (2 ** max(0, attempts - 1)))
    return raw * (0.9 + 0.2 * rand())


def sanitise_error(exc: BaseException | str) -> str:
    """``Type: first line`` truncated to ``MAX_ERROR_CHARS``."""
    if isinstance(exc, BaseException):
        text = f"{type(exc).__name__}: {exc}"
    else:
        text = str(exc)
    first = text.strip().splitlines()[0] if text.strip() else ""
    return first[:MAX_ERROR_CHARS]


def _dumps(payload: Mapping[str, Any]) -> str:
    return json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class JobQueue:
    """Queue operations on one connection. The caller owns the transaction.

    ``enqueue`` is meant to run inside the caller's write transaction, so a
    memory and its embed job commit together. ``claim``, ``complete``, ``fail``,
    ``heartbeat`` and ``release`` each need a write transaction of their own
    (``em.jobs.worker`` wraps them). None of them commits.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # --- producing --------------------------------------------------------

    def enqueue(
        self,
        type: str,
        payload: Mapping[str, Any] | None = None,
        *,
        dedupe_key: str | None = None,
        priority: int = DEFAULT_PRIORITY,
        run_after: datetime | None = None,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> str:
        """Add a job, or refresh the queued/failed job holding ``dedupe_key``.

        Returns the id of the row that now represents the work.
        """
        if not type:
            raise ValueError("job type is required")
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        now = to_iso(utc_now())
        when = to_iso(run_after) if run_after is not None else now
        body = _dumps(payload or {})
        if dedupe_key is not None:
            row = self._conn.execute(
                "SELECT id, status FROM jobs WHERE dedupe_key=?", (dedupe_key,)
            ).fetchone()
            if row is not None:
                if row["status"] in ("queued", "failed"):
                    self._conn.execute(
                        "UPDATE jobs SET payload=?, run_after=?, priority=?, updated_at=?"
                        " WHERE id=?",
                        (body, when, priority, now, row["id"]),
                    )
                return row["id"]
        job_id = new_id("job")
        self._conn.execute(
            "INSERT INTO jobs (id, type, payload, dedupe_key, status, priority, attempts,"
            " max_attempts, run_after, created_at, updated_at)"
            " VALUES (?,?,?,?,'queued',?,0,?,?,?,?)",
            (job_id, type, body, dedupe_key, priority, max_attempts, when, now, now),
        )
        return job_id

    # --- consuming --------------------------------------------------------

    def claim(
        self,
        worker_id: str,
        *,
        types: Iterable[str] | None = None,
        lease_seconds: float = DEFAULT_LEASE_SECONDS,
    ) -> Job | None:
        """Claim the most urgent ready job. Call inside ``write_txn``.

        Ready means ``queued`` or ``failed`` with ``run_after`` reached, or
        ``running`` with an expired lease. ``types`` limits the claim to job
        types this worker can run, so a worker never takes work it has no
        handler for (an older build must leave newer job types alone).

        A reclaimed job that has used up its attempts is marked ``dead``
        instead of claimed, and the search goes on.
        """
        if not worker_id:
            raise ValueError("worker_id is required")
        type_list = sorted(set(types)) if types is not None else None
        if type_list is not None and not type_list:
            return None
        while True:
            now_dt = utc_now()
            now = to_iso(now_dt)
            sql = (
                "SELECT * FROM jobs WHERE ("
                " (status IN ('queued','failed') AND run_after <= ?)"
                " OR (status = 'running' AND locked_until IS NOT NULL AND locked_until < ?))"
            )
            params: list[Any] = [now, now]
            if type_list is not None:
                sql += f" AND type IN ({','.join('?' * len(type_list))})"
                params.extend(type_list)
            sql += " ORDER BY priority ASC, run_after ASC, id ASC LIMIT 1"
            row = self._conn.execute(sql, params).fetchone()
            if row is None:
                return None
            if row["status"] == "running" and row["attempts"] >= row["max_attempts"]:
                # Its last attempt died holding the lease. Don't hand it out again.
                self._conn.execute(
                    "UPDATE jobs SET status='dead', locked_by=NULL, locked_until=NULL,"
                    " last_error=COALESCE(last_error, 'lease expired on final attempt'),"
                    " updated_at=? WHERE id=?",
                    (now, row["id"]),
                )
                continue
            until = to_iso(now_dt + timedelta(seconds=lease_seconds))
            self._conn.execute(
                "UPDATE jobs SET status='running', locked_by=?, locked_until=?,"
                " attempts=attempts+1, updated_at=? WHERE id=?",
                (worker_id, until, now, row["id"]),
            )
            return self.get(row["id"])

    def heartbeat(self, job_id: str, worker_id: str, *, lease_seconds: float = DEFAULT_LEASE_SECONDS) -> bool:
        """Extend a lease this worker still holds. False means it was lost."""
        now_dt = utc_now()
        cur = self._conn.execute(
            "UPDATE jobs SET locked_until=?, updated_at=?"
            " WHERE id=? AND status='running' AND locked_by=?",
            (to_iso(now_dt + timedelta(seconds=lease_seconds)), to_iso(now_dt), job_id, worker_id),
        )
        return cur.rowcount == 1

    def complete(self, job_id: str, worker_id: str) -> bool:
        """Mark done. False means the lease was lost (another worker may have
        re-run the job; idempotent handlers make that harmless)."""
        cur = self._conn.execute(
            "UPDATE jobs SET status='done', locked_by=NULL, locked_until=NULL,"
            " last_error=NULL, updated_at=? WHERE id=? AND status='running' AND locked_by=?",
            (to_iso(utc_now()), job_id, worker_id),
        )
        return cur.rowcount == 1

    def fail(
        self,
        job_id: str,
        worker_id: str,
        error: BaseException | str,
        *,
        permanent: bool = False,
        rand: Callable[[], float] = random.random,
    ) -> str | None:
        """Record a failed attempt. Returns the new status (``failed`` with a
        backoff, or ``dead``), or None if this worker no longer held the lease.
        """
        row = self._conn.execute(
            "SELECT attempts, max_attempts FROM jobs"
            " WHERE id=? AND status='running' AND locked_by=?",
            (job_id, worker_id),
        ).fetchone()
        if row is None:
            return None
        now_dt = utc_now()
        dead = permanent or row["attempts"] >= row["max_attempts"]
        status = "dead" if dead else "failed"
        run_after = now_dt if dead else now_dt + timedelta(seconds=backoff_seconds(row["attempts"], rand=rand))
        self._conn.execute(
            "UPDATE jobs SET status=?, locked_by=NULL, locked_until=NULL, last_error=?,"
            " run_after=?, updated_at=? WHERE id=?",
            (status, sanitise_error(error), to_iso(run_after), to_iso(now_dt), job_id),
        )
        return status

    def release(self, job_id: str, worker_id: str) -> bool:
        """Hand a claimed job back without using up an attempt (graceful
        shutdown before the handler started)."""
        cur = self._conn.execute(
            "UPDATE jobs SET status='queued', locked_by=NULL, locked_until=NULL,"
            " attempts=MAX(attempts-1, 0), updated_at=?"
            " WHERE id=? AND status='running' AND locked_by=?",
            (to_iso(utc_now()), job_id, worker_id),
        )
        return cur.rowcount == 1

    # --- operating --------------------------------------------------------

    def get(self, job_id: str) -> Job | None:
        row = self._conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return Job.from_row(row) if row is not None else None

    def get_by_key(self, dedupe_key: str) -> Job | None:
        row = self._conn.execute("SELECT * FROM jobs WHERE dedupe_key=?", (dedupe_key,)).fetchone()
        return Job.from_row(row) if row is not None else None

    def stats(self) -> dict[str, dict[str, int]]:
        """``{type: {status: count}}`` over the whole table."""
        out: dict[str, dict[str, int]] = {}
        for row in self._conn.execute(
            "SELECT type, status, count(*) AS n FROM jobs GROUP BY type, status"
        ):
            out.setdefault(row["type"], {})[row["status"]] = int(row["n"])
        return out

    def list(
        self, *, status: str | None = None, type: str | None = None, limit: int = 100
    ) -> list[Job]:
        if status is not None and status not in STATUSES:
            raise ValueError(f"unknown job status: {status!r}")
        sql = "SELECT * FROM jobs WHERE 1=1"
        params: list[Any] = []
        if status is not None:
            sql += " AND status=?"
            params.append(status)
        if type is not None:
            sql += " AND type=?"
            params.append(type)
        sql += " ORDER BY updated_at DESC, id DESC LIMIT ?"
        params.append(int(limit))
        return [Job.from_row(r) for r in self._conn.execute(sql, params)]

    def retry_dead(self, job_id: str) -> bool:
        """Operator action: give a dead job a fresh set of attempts."""
        now = to_iso(utc_now())
        cur = self._conn.execute(
            "UPDATE jobs SET status='queued', attempts=0, run_after=?, updated_at=?"
            " WHERE id=? AND status='dead'",
            (now, now, job_id),
        )
        return cur.rowcount == 1

    def prune(self, *, done_older_than_days: float = 7, dead_older_than_days: float = 30) -> int:
        """Delete finished rows past their retention. Returns rows deleted.

        Dead jobs are kept longer than done ones because they are the evidence
        an operator needs.
        """
        now = utc_now()
        done_cut = to_iso(now - timedelta(days=done_older_than_days))
        dead_cut = to_iso(now - timedelta(days=dead_older_than_days))
        cur = self._conn.execute(
            "DELETE FROM jobs WHERE (status='done' AND updated_at < ?)"
            " OR (status='dead' AND updated_at < ?)",
            (done_cut, dead_cut),
        )
        return cur.rowcount

    def next_run_after(self, *, types: Iterable[str] | None = None) -> datetime | None:
        """Earliest time any claimable job becomes ready (for idle sleeps)."""
        sql = (
            "SELECT min(t) AS t FROM ("
            " SELECT run_after AS t, type FROM jobs WHERE status IN ('queued','failed')"
            " UNION ALL"
            " SELECT locked_until AS t, type FROM jobs WHERE status='running' AND locked_until IS NOT NULL"
            ")"
        )
        params: list[Any] = []
        if types is not None:
            type_list = sorted(set(types))
            if not type_list:
                return None
            sql += f" WHERE type IN ({','.join('?' * len(type_list))})"
            params.extend(type_list)
        row = self._conn.execute(sql, params).fetchone()
        return parse_iso(row["t"]) if row is not None and row["t"] else None
