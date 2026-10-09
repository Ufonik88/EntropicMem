"""The ``embed`` and ``embed_backfill`` job handlers — EM-303.

Both handlers follow EM-209's contract: they run **outside** the write
transaction, open their own short transactions through ``ctx.store``, are
idempotent (upsert on ``(owner, model)``), and heartbeat in long loops.

* ``embed`` — one memory, queued by ``MemoryStore.add``/``update`` with
  ``{memory_id, version}``. A stale version (the row moved on) is a no-op, so
  a late job can never overwrite a newer vector. A missing memory (purged) is
  permanent; a memory that is not ``active`` yet is simply done.
* ``embed_backfill`` — the model-switch path. ``ensure_embedding_model``
  queues one per new model (dedupe key), and the handler pages the memories
  that lack a vector for it, 64 at a time, then records
  ``meta.embedding_model``. Without a backend it returns without writing the
  meta key, so a later run — after the optional package is installed — still
  sees the switch and backfills.

**No prefetch/agent path may import this module's handlers**: embeddings run
only in the worker thread (the card's AC).
"""

from __future__ import annotations

import sqlite3
from typing import Callable, Optional

from ..clock import to_iso, utc_now
from ..jobs.worker import PermanentJobError
from ..store.embeddings import (
    pending_memory_texts,
    put_embedding,
    set_stored_model,
    stored_model,
)
from ..store.jobs import JobQueue
from ..store.memories import MemoryStore
from .service import BATCH_SIZE, EmbeddingService, memory_text

__all__ = [
    "ensure_embedding_model",
    "make_embed_backfill_handler",
    "make_embed_handler",
]


def ensure_embedding_model(conn: sqlite3.Connection, model: str) -> Optional[str]:
    """Queue a backfill when ``model`` differs from the recorded one.

    Returns the job id, or ``None`` when the store already records this model.
    Safe to call on every initialize: the dedupe key makes it one queued job
    per model. The meta key is written by the backfill on completion, not here,
    so a backend-less box never claims a model it has not filled.
    """
    wanted = (model or "").strip()
    if not wanted or wanted == stored_model(conn):
        return None
    return JobQueue(conn).enqueue(
        "embed_backfill",
        {"model": wanted},
        dedupe_key=f"embed_backfill:{wanted}",
    )


def make_embed_handler(service: EmbeddingService) -> Callable:
    """Handler for ``embed`` jobs: one memory, one vector."""

    def handle(job, ctx) -> None:
        memory_id = str(job.payload.get("memory_id") or "")
        if not memory_id:
            raise PermanentJobError("embed job has no memory_id")
        version = job.payload.get("version")

        # Read with a short reader connection; the embedding call happens
        # outside every transaction (invariant 2).
        row = MemoryStore(ctx.store.reader()).get(memory_id)
        if row is None:
            raise PermanentJobError(f"memory {memory_id} no longer exists")
        if row.get("status") != "active":
            return
        if version is not None and int(version) != int(row.get("version") or 0):
            return  # a newer version has its own job; this one is stale
        text = memory_text(row.get("summary") or "", row.get("content") or "")
        if not text or not service.available:
            return
        vector = service.embed_texts([text])[0]
        # Re-check the version inside the write transaction: the read above
        # happened before a (possibly slow) embedding call, and a newer version
        # may have landed since. Without this, a lease-expired duplicate could
        # overwrite the newer vector.
        with ctx.store.transaction() as conn:
            if version is not None:
                latest = MemoryStore(conn).get(memory_id)
                if latest is None or int(latest.get("version") or 0) != int(version):
                    return
            put_embedding(
                conn,
                owner_id=memory_id,
                model=service.model,
                vector=vector,
                content_hash=str(row.get("content_hash") or ""),
                created_at=to_iso(utc_now()),
            )

    return handle


def make_embed_backfill_handler(service: EmbeddingService) -> Callable:
    """Handler for ``embed_backfill`` jobs: fill a model, then record it."""

    def handle(job, ctx) -> None:
        model = str(job.payload.get("model") or service.model or "").strip()
        if not model:
            raise PermanentJobError("embed_backfill job has no model")
        if not service.available:
            return  # no backend: do not record a model we did not fill

        reader = ctx.store.reader()
        while True:
            if not ctx.heartbeat():
                return
            pending = pending_memory_texts(reader, model=model, limit=BATCH_SIZE)
            if not pending:
                break
            texts = [memory_text(summary, content) for (_id, summary, content) in pending]
            vectors = service.embed_texts(texts)  # raises -> the job retries
            with ctx.store.transaction() as conn:
                for (memory_id, _summary, _content), vector in zip(pending, vectors):
                    put_embedding(
                        conn,
                        owner_id=memory_id,
                        model=model,
                        vector=vector,
                        created_at=to_iso(utc_now()),
                    )

        with ctx.store.transaction() as conn:
            set_stored_model(conn, model)

    return handle
