"""The ``embed`` and ``embed_backfill`` job handlers — EM-303.

Both handlers follow EM-209's contract: they run **outside** the write
transaction, open their own short transactions through ``ctx.store``, are
idempotent (upsert on ``(owner_type, owner_id, model)``), and heartbeat in
long loops.

* ``embed`` — one owner, queued by ``MemoryStore.add``/``update`` with
  ``{memory_id, version}`` or by ``EpisodeStore`` with
  ``{owner_type: "episode", owner_id, stamp}``. A stale version/stamp (the row
  moved on) is a no-op, re-checked **inside the write transaction**, so a late
  job can never overwrite a newer vector. A missing owner (purged) is
  permanent; an owner that is not ``active`` yet is simply done.
* ``embed_backfill`` — the model-switch path. ``ensure_embedding_model``
  queues one per new model (dedupe key), and the handler pages memories and
  episodes that lack a vector for it, 64 at a time, then records
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
    pending_embed_texts,
    put_embedding,
    set_stored_model,
    stored_model,
)
from ..store.episodes import EpisodeStore
from ..store.jobs import JobQueue
from ..store.memories import MemoryStore
from .service import BATCH_SIZE, EmbeddingService, episode_text, memory_text

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
    """Handler for ``embed`` jobs: one memory or one episode, one vector."""

    def handle(job, ctx) -> None:
        owner_type = str(job.payload.get("owner_type") or "memory")
        if owner_type == "episode":
            _embed_episode(job, ctx, service)
            return
        _embed_memory(job, ctx, service)

    return handle


def _embed_memory(job, ctx, service: EmbeddingService) -> None:
    memory_id = str(job.payload.get("memory_id") or job.payload.get("owner_id") or "")
    if not memory_id:
        raise PermanentJobError("embed job has no memory_id")
    version = job.payload.get("version")

    # Read with a short reader connection; the embedding call happens outside
    # every transaction (invariant 2).
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


def _embed_episode(job, ctx, service: EmbeddingService) -> None:
    episode_id = str(job.payload.get("owner_id") or job.payload.get("memory_id") or "")
    if not episode_id:
        raise PermanentJobError("embed job has no owner_id")
    stamp = job.payload.get("stamp")

    row = EpisodeStore(ctx.store.reader()).get_episode(episode_id)
    if row is None:
        raise PermanentJobError(f"episode {episode_id} no longer exists")
    if stamp is not None and str(row.get("updated_at") or "") != str(stamp):
        return  # a newer upsert has its own job
    text = episode_text(row.get("title") or "", row.get("summary") or "")
    if not text or not service.available:
        return
    vector = service.embed_texts([text])[0]
    with ctx.store.transaction() as conn:
        if stamp is not None:
            latest = EpisodeStore(conn).get_episode(episode_id)
            if latest is None or str(latest.get("updated_at") or "") != str(stamp):
                return
        put_embedding(
            conn,
            owner_type="episode",
            owner_id=episode_id,
            model=service.model,
            vector=vector,
            created_at=to_iso(utc_now()),
        )


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
            pending = pending_embed_texts(reader, model=model, limit=BATCH_SIZE)
            if not pending:
                break
            texts = [
                memory_text(a, b) if owner_type == "memory" else episode_text(a, b)
                for (owner_type, _id, a, b) in pending
            ]
            vectors = service.embed_texts(texts)  # raises -> the job retries
            with ctx.store.transaction() as conn:
                for (owner_type, owner_id, _a, _b), vector in zip(pending, vectors):
                    put_embedding(
                        conn,
                        owner_type=owner_type,
                        owner_id=owner_id,
                        model=model,
                        vector=vector,
                        created_at=to_iso(utc_now()),
                    )

        with ctx.store.transaction() as conn:
            set_stored_model(conn, model)

    return handle
