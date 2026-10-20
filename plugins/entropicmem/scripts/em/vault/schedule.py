"""Scheduling the vault projection — EM-601 slice 2.

Slice 1 (``em.vault.projection``) is the engine: it renders a scope's memory
into Markdown. This module is what makes that happen on its own — a job type
the worker carries, a debounced enqueue the provider fires after a write, and
the ``vault.projection`` config that decides whether any of it runs.

Three rules this module exists to hold:

**Off until explicitly enabled.** ``vault.projection`` defaults to ``none``.
Before this slice the job did not exist, so the config's default never
mattered; now that a worker can carry the handler, the default is what decides
whether a user's disk is written to without them asking.

**One projection per write burst.** The enqueue is keyed per (root, scope) and
``run_after`` slides forward on every write, so a conversation does not project
once per sentence.

**A write that lands mid-projection is re-queued, not lost.** This is the
load-bearing rule, and it is the reason this module does the queue arithmetic
itself rather than calling ``JobQueue.enqueue`` once and trusting it.
``enqueue`` looks up the dedupe key, finds the row the worker is currently
running, sees a status that is neither ``queued`` nor ``failed``, and returns
that row's id **without re-queueing it**. To ``enqueue`` the request looks
already satisfied. It is not: the in-flight row read the store *before* this
write, so its render cannot contain it, and the write is silently dropped
until some later write happens along. The vault then sits stale with no
retries, no logs and a ``done`` job — the worst possible failure for a
human-first view. So the enqueue follows the chain: while the row for a key is
in flight, the write gets its own follow-up row keyed to it, and further writes
during that same run collapse onto that one row (the debounce holds across the
boundary too).

**And a burst never defers forever.** A pure debounce starves under sustained
load — every write pushes ``run_after`` forward, so the projection never runs.
The slide is therefore clamped at ``MAX_WAIT_SECONDS`` from the burst's first
write, which bounds how stale the view can get.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path
from typing import Callable, Optional, Sequence, Tuple

from em.clock import parse_iso, utc_now
from em.jobs.worker import JobContext, PermanentJobError
from em.store.jobs import JobQueue
from em.store.types import Scope
# EM-603: vault projection modules are not available in this version.
# The enqueue_reindex function below is self-contained and does not depend on them.

log = logging.getLogger("entropicmem.vault")

#: The job type this module enqueues and the registry carries a handler for.
JOB_TYPE = "project_vault"

#: EM-603: the index refresh job. The vault index is the v2 layer's search
#: cache, so the handler imports it lazily — the same v2-bridge pattern the
#: facade uses for ``memory_engine`` — and never at module load.
REINDEX_JOB_TYPE = "reindex_vault"

#: How long after the last write the projection waits. Long enough to swallow a
#: burst of edits, short enough that the vault is never meaningfully stale.
DEBOUNCE_SECONDS = 60

#: Hard ceiling on the slide: at most this long after a burst's *first* write,
#: however many writes arrive. Without it a steady stream starves the render.
MAX_WAIT_SECONDS = 300

#: The dedupe key's shape is ``<prefix>:<root>:<profile>:<user>``, optionally
#: suffixed ``:<in-flight row id>`` for a follow-up. Bounded, because the chain
#: is followed rather than recursed.
_KEY_PREFIX = "vault:project"

#: Follow-up rows a single burst may allocate before giving up. Reaching this
#: means writes arrived faster than the projection could render, thousands of
#: times over — a loud failure is correct, an unbounded key is not.
_MAX_CHAIN = 8


def modes_for(projection: str) -> Tuple[str, ...]:
    """The engine modes a ``vault.projection`` value selects.

    ``none`` and ``legacy`` both map to *no modes*, but for opposite reasons
    worth keeping distinct: ``none`` means "do not render", while ``legacy`` is
    v2's note-per-fact writer — a different code path that the scheduled
    projection must not render over the top of.

    An unknown value raises. A typo that silently rendered nothing would read
    as "the vault is empty", which is the worst possible failure for a
    human-first view; the engine refuses unknown modes for the same reason.
    """
    known = {
        "none": (),
        "legacy": (),
        "entities": ("entities",),
        "entities+journal": ("entities", "journal"),
    }
    try:
        return known[projection]
    except KeyError:
        raise ValueError(
            f"unknown vault.projection {projection!r}; expected one of {sorted(known)}"
        ) from None


def _key(root: "str | Path", scope: Scope) -> str:
    return f"{_KEY_PREFIX}:{root}:{scope.profile}:{scope.user}"


def _scope_payload(scope: Scope) -> dict:
    """A JSON-safe ``Scope`` for the job payload — the handler reconstructs it."""
    return {
        "profile": scope.profile,
        "user": scope.user,
        "chat": scope.chat,
        "chat_type": scope.chat_type,
        "author": scope.author,
        "is_owner": scope.is_owner,
    }


def _scope_from(payload: Optional[dict]) -> Scope:
    data = payload or {}
    return Scope(
        profile=data.get("profile", ""),
        user=data.get("user", ""),
        chat=data.get("chat", ""),
        chat_type=data.get("chat_type", ""),
        author=data.get("author", ""),
        is_owner=bool(data.get("is_owner")),
    )


def enqueue_projection(
    conn,
    *,
    root: "str | Path",
    scope: Scope,
    modes: Sequence[str],
    index_db: "str | Path | None" = None,
    ingest: bool = False,
    now=None,
    debounce: int = DEBOUNCE_SECONDS,
    max_wait: int = MAX_WAIT_SECONDS,
) -> Optional[str]:
    """Queue one projection for this (root, scope), debounced.

    Returns the id of the row that now represents the work, or ``None`` when
    there is no work — an empty ``modes`` means this engine does not run.
    Idempotent: repeated calls inside the window return the same row and slide
    its ``run_after`` rather than adding rows, and a call made while a row is
    being run returns a *new* follow-up row instead of the stale in-flight one.
    """
    if not modes:
        return None

    now = now if now is not None else utc_now()
    base = _key(root, scope)
    payload = {
        "root": str(root),
        "scope": _scope_payload(scope),
        "modes": list(modes),
    }
    if index_db:
        # EM-603: the projection's follow-up refresh needs the index path; the
        # provider passes it from `paths.index_db`. Without it the projection
        # still runs — it just cannot schedule the refresh.
        payload["index_db"] = str(index_db)
    if ingest:
        # EM-604: read the human regions back as pending proposals before the
        # projection re-adds any line the user removed. Only present when on, so
        # an off payload is unchanged.
        payload["ingest"] = True
    queue = JobQueue(conn)
    key = base

    for _ in range(_MAX_CHAIN):
        row = conn.execute(
            "SELECT id, status, created_at FROM jobs WHERE dedupe_key=?", (key,)
        ).fetchone()

        if row is None or row["status"] in ("queued", "failed"):
            run_at = now + timedelta(seconds=debounce)
            if row is not None and row["status"] == "queued" and row["created_at"]:
                # Clamp the slide: never later than max_wait after this row was
                # first queued, or a steady stream of writes would push it out
                # forever and the vault would never render.
                try:
                    first = parse_iso(row["created_at"])
                except (TypeError, ValueError):
                    first = None
                if first is not None:
                    deadline = first + timedelta(seconds=max_wait)
                    if deadline < run_at:
                        run_at = deadline
            return queue.enqueue(
                JOB_TYPE,
                payload,
                dedupe_key=key,
                run_after=run_at,
            )

        # The row is in flight (or already finished): its store snapshot
        # predates this write, so its render cannot contain it. Give the write
        # its own follow-up keyed to that row — and, because the key is stable
        # for the life of that row, further writes during the same run collapse
        # onto this one follow-up instead of fanning out.
        key = f"{base}:{row['id']}"

    raise RuntimeError(
        f"{JOB_TYPE}: burst exceeded {_MAX_CHAIN} follow-up rows for {base!r}; "
        "writes are arriving faster than the vault renders"
    )


# EM-603: the reindex dedupe key's shape and chain bound.
_REINDEX_KEY_PREFIX = "vault:reindex"
_MAX_REINDEX_CHAIN = 8


def _reindex_base(root, index_db) -> str:
    """The stable dedupe key for this (root, index_db) pair."""
    return f"{_REINDEX_KEY_PREFIX}:{root}:{index_db}"


def enqueue_reindex(conn, *, root: "str | Path", index_db: "str | Path | None") -> Optional[str]:
    """Queue one index refresh for this (vault root, index db), deduplicated.

    Concurrent requests for the same pair collapse onto one row: unlike the
    projection there is no per-write payload a request could lose — the refresh
    reads whatever the vault holds when it runs. Returns the row id, or
    ``None`` when either path is missing (nothing to refresh).

    After the previous refresh finishes (``done``), a subsequent request must
    enqueue a new job rather than reusing the old row. Mirror
    ``enqueue_projection``'s chain: while the row for the key is neither
    ``queued`` nor ``failed``, move to a follow-up key derived from that row's
    id and insert there.
    """
    if not root or not index_db:
        return None
    queue = JobQueue(conn)
    base = _reindex_base(root, index_db)
    key = base
    for _ in range(_MAX_REINDEX_CHAIN):
        row = conn.execute(
            "SELECT id, status FROM jobs WHERE dedupe_key=?", (key,)
        ).fetchone()
        if row is None or row["status"] in ("queued", "failed"):
            # No row or row is in a status that can be refreshed
            return queue.enqueue(
                REINDEX_JOB_TYPE,
                {"root": str(root), "index_db": str(index_db)},
                dedupe_key=key,
                run_after=utc_now(),
            )
        # The row is in flight (or already finished): its store snapshot
        # predates this write, so its refresh cannot contain it. Give the request
        # its own follow-up keyed to that row — and, because the key is stable
        # for the life of that row, further requests during the same run collapse
        # onto this one follow-up instead of fanning out.
        key = f"{base}:{row['id']}"

    raise RuntimeError(
        f"{REINDEX_JOB_TYPE}: burst exceeded {_MAX_REINDEX_CHAIN} follow-up rows for {base!r}; "
        "writes are arriving faster than the index refresh renders"
    )