"""Entity linking entry point (v3 §3.6, card EM-208).

The plan puts the linker here and the store in ``em/store/entities.py``. This
module is the small, importable surface the formation pipeline uses:

    linker = EntityLinker(conn, scope)
    linked = linker.link(memory_dict)

``link`` must be cheap enough to run inline on the write path (the p95 budget
is 2 ms per memory at 10k entities), which is why alias resolution is an exact
indexed probe per n-gram rather than a scan.
"""

from __future__ import annotations

import sqlite3

from ..jobs import PermanentJobError
from ..store.entities import (
    MAX_NGRAM,
    EntityStore,
    candidate_phrases,
    ngrams,
    normalise,
    time_link,
)
from ..store.memories import MemoryStore
from ..store.types import Scope

__all__ = [
    "LINK_JOB_TYPE",
    "EntityLinker",
    "EntityStore",
    "MAX_NGRAM",
    "candidate_phrases",
    "make_link_handler",
    "ngrams",
    "normalise",
    "time_link",
]

#: The job type ``MemoryStore`` queues as ``link:<memory_id>:<version>``.
LINK_JOB_TYPE = "link"


class EntityLinker:
    """Bind a scope once, then link memory dicts.

    The plan's API is ``EntityLinker.link(memory)``, so the scope is a
    constructor argument rather than a per-call one.
    """

    def __init__(self, conn: sqlite3.Connection, scope: Scope) -> None:
        self._conn = conn
        self._scope = scope
        self._store = EntityStore(conn)

    @property
    def store(self) -> EntityStore:
        return self._store

    def link(self, memory: dict) -> list[str]:
        """Link one memory to entities. Returns the entity ids now linked."""
        return self._store.link(memory["id"], memory.get("content", ""), scope=self._scope)


def make_link_handler():
    """Handler for ``link`` jobs: bind one memory to entities.

    This is the whole point of the card: entity work runs here, off the write
    path, never inside the transaction that created the memory. The handler
    opens its own short transaction through ``ctx.store.transaction()``.

    Idempotent, because delivery is at-least-once. ``EntityStore.link`` upserts
    its links (``INSERT OR IGNORE``) and a proposed phrase's sighting counter
    counts *distinct memories*, so a re-run after a lost lease converges rather
    than inflating the graph.

    Two inputs can never succeed and go straight to ``dead``: a payload with no
    ``memory_id``, and a memory that no longer exists (purged). A memory that is
    simply not live yet — pending, archived or forgotten — is **not** a failure:
    there is nothing to link, so the job is done. That distinction matters
    because deletion is asynchronous; a ``forget`` is a status change, and the
    link job queued before it can still be claimed.
    """

    def handle(job, ctx) -> None:
        memory_id = str(job.payload.get("memory_id") or "")
        if not memory_id:
            raise PermanentJobError("link job has no memory_id")
        with ctx.store.transaction() as conn:
            row = MemoryStore(conn).get(memory_id)
            if row is None:
                raise PermanentJobError(f"memory {memory_id} no longer exists")
            if row.get("status") != "active":
                return
            # The row's own scope, never a default: linking under the wrong
            # profile would put one profile's names into another's graph.
            scope = Scope(
                profile=row.get("scope_profile") or "",
                user=row.get("scope_user") or "",
                chat=row.get("scope_chat") or "",
            )
            EntityLinker(conn, scope).link(row)

    return handle
