"""EM-303 — the ``embed`` job, the ``embed_backfill`` job, and model identity.

Rules the tests pin:

* **No embedding inline.** ``MemoryStore.add`` only enqueues; the vector appears
  after a worker run, never during the write.
* **At-least-once delivery.** The handler upserts on ``(owner, model)`` and
  checks the job's ``version`` against the row, so a stale or repeated job
  cannot overwrite a newer vector.
* **A missing backend is a no-op, not a failure.** A box without fastembed/ST
  must not accumulate dead jobs; the backfill catches up when one appears.
* **Model identity is ``meta.embedding_model``.** ``ensure_embedding_model``
  queues one backfill per new model (dedupe key), and only writes the meta key
  once the backfill actually completes.

Invented data only: Acme.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from em.clock import freeze, to_iso, utc_now  # noqa: E402
from em.embeddings.backends import NoneBackend  # noqa: E402
from em.embeddings.jobs import (  # noqa: E402
    ensure_embedding_model,
    make_embed_backfill_handler,
    make_embed_handler,
)
from em.embeddings.service import EmbeddingService  # noqa: E402
from em.jobs import HandlerRegistry, JobWorker  # noqa: E402
from em.store.db import Store  # noqa: E402
from em.store.embeddings import put_embedding, stored_model, unpack_vector  # noqa: E402
from em.store.episodes import EpisodeStore  # noqa: E402
from em.store.jobs import JobQueue  # noqa: E402
from em.store.memories import MemoryStore  # noqa: E402
from em.store.migrations import migrate  # noqa: E402
from em.store.types import MemoryDraft, MemoryPatch, Scope  # noqa: E402

OWNER = Scope(profile="default")
MODEL = "fake-embed-1"
MODEL2 = "fake-embed-2"
NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)


def fake_vector(text: str) -> tuple:
    """Deterministic, and different for different text (unlike a length)."""
    return (float(sum(text.encode()) % 1000), 1.0, 0.0, 0.0)


class FakeBackend:
    name = "fake"
    dim = 4
    default_model = MODEL

    def __init__(self):
        self.embed_calls: list[int] = []

    def available(self) -> bool:
        return True

    def warm(self) -> None:
        pass

    def embed(self, texts):
        self.embed_calls.append(len(texts))
        return [list(fake_vector(t)) for t in texts]


@pytest.fixture
def store(tmp_path):
    saved = Store(str(tmp_path / "memory.db"))
    with saved.writer() as conn:
        migrate(conn)
    yield saved
    saved.close()


def _add(store, content, **kwargs):
    with store.transaction() as conn:
        result = MemoryStore(conn).add(
            MemoryDraft(content=content, source="agent", **kwargs), scope=OWNER, actor="tester"
        )
    assert result.ok, result
    return result.id


def _service(model=MODEL):
    return EmbeddingService(":memory:", backend=FakeBackend(), model=model)


def _run(store, handlers):
    registry = HandlerRegistry()
    for job_type, handler in handlers.items():
        registry.register(job_type, handler)
    return JobWorker(store, registry, worker_id="w").run_until_idle()


def _embed_rows(store, model=None):
    reader = store.reader()
    if model is None:
        return reader.execute("SELECT * FROM embeddings").fetchall()
    return reader.execute("SELECT * FROM embeddings WHERE model=?", (model,)).fetchall()


# --- enqueue ---------------------------------------------------------------


def test_add_enqueues_one_embed_job_for_the_new_version(store):
    memory_id = _add(store, "the Acme staging port is 9090")
    rows = store.reader().execute("SELECT type, payload, dedupe_key FROM jobs").fetchall()
    jobs = [row for row in rows if row["type"] == "embed"]
    assert len(jobs) == 1  # `add` also queues the link job; that one is EM-211's
    assert jobs[0]["dedupe_key"] == f"embed:{memory_id}:1"
    assert json.loads(jobs[0]["payload"]) == {"memory_id": memory_id, "version": 1}


def test_add_episode_enqueues_an_embed_job(store):
    with store.transaction() as conn:
        episode_id = EpisodeStore(conn).add_episode(
            scope=OWNER, kind="manual", title="Acme cutover", summary="moved the fleet"
        )
    rows = store.reader().execute(
        "SELECT type, payload, dedupe_key FROM jobs WHERE type='embed'"
    ).fetchall()
    assert len(rows) == 1
    payload = json.loads(rows[0]["payload"])
    assert payload["owner_type"] == "episode"
    assert payload["owner_id"] == episode_id
    assert payload["stamp"]
    assert rows[0]["dedupe_key"] == f"embed:episode:{episode_id}:{payload['stamp']}"


# --- the embed handler -----------------------------------------------------


def test_the_handler_writes_a_vector_for_the_active_memory(store):
    memory_id = _add(store, "the Acme staging port is 9090")
    outcomes = _run(store, {"embed": make_embed_handler(_service())})
    assert [o.status for o in outcomes] == ["done"]
    (row,) = _embed_rows(store, MODEL)
    assert row["owner_id"] == memory_id
    assert row["owner_type"] == "memory"
    assert unpack_vector(row["vector"]) == pytest.approx(
        fake_vector("the Acme staging port is 9090")
    )


def test_a_replayed_job_does_not_create_a_second_row(store):
    memory_id = _add(store, "the Acme staging port is 9090")
    _run(store, {"embed": make_embed_handler(_service())})
    with store.transaction() as conn:
        JobQueue(conn).enqueue(
            "embed", {"memory_id": memory_id, "version": 1}, dedupe_key="replay"
        )
    outcomes = _run(store, {"embed": make_embed_handler(_service())})
    assert [o.status for o in outcomes] == ["done"]
    assert len(_embed_rows(store, MODEL)) == 1


def test_a_non_active_memory_is_done_without_a_vector(store):
    memory_id = _add(store, "the Acme staging port is 9090")
    with store.transaction() as conn:
        conn.execute("UPDATE memories SET status='superseded' WHERE id=?", (memory_id,))
    outcomes = _run(store, {"embed": make_embed_handler(_service())})
    assert [o.status for o in outcomes] == ["done"]
    assert _embed_rows(store) == []


def test_a_missing_memory_goes_dead(store):
    with store.transaction() as conn:
        JobQueue(conn).enqueue(
            "embed", {"memory_id": "mem_missing", "version": 1}, dedupe_key="missing"
        )
    outcomes = _run(store, {"embed": make_embed_handler(_service())})
    assert [o.status for o in outcomes] == ["dead"]


def test_a_stale_version_never_overwrites_the_newer_vector(store):
    """The race the guard exists for: the memory changes *during* the embed call.

    A lease-expired duplicate reads version 1, calls the backend (slow), and by
    the time it writes, version 2 exists — with its own vector. The write-time
    version check is what keeps the stale job from clobbering it.

    Only **one** job is run: the simulated race itself bumps the version, which
    enqueues a successor job (as it should), and ``run_until_idle`` would chase
    that chain forever.
    """
    memory_id = _add(store, "the Acme staging port is 8080")
    service = _service()
    inner = service.backend.embed
    raced = {"done": False}

    def racing_embed(texts):
        # Simulate the newer write landing while the embedding call is in flight.
        if not raced["done"]:
            raced["done"] = True
            with store.transaction() as conn:
                result = MemoryStore(conn).update(
                    memory_id, MemoryPatch(content="the Acme staging port is 9090"),
                    actor="tester", reason="race",
                )
                assert result.ok, result
                put_embedding(
                    conn, owner_id=memory_id, model=MODEL,
                    vector=fake_vector("the Acme staging port is 9090"),
                    created_at=to_iso(utc_now()),
                )
        return inner(texts)

    service.backend.embed = racing_embed
    registry = HandlerRegistry()
    registry.register("embed", make_embed_handler(service))
    outcome = JobWorker(store, registry, worker_id="w").run_once()
    assert outcome is not None and outcome.status == "done"
    (row,) = _embed_rows(store, MODEL)
    assert unpack_vector(row["vector"]) == pytest.approx(
        fake_vector("the Acme staging port is 9090")
    )


def test_no_backend_is_a_noop_not_a_failure(store):
    _add(store, "the Acme staging port is 9090")
    service = EmbeddingService(":memory:", backend=NoneBackend())
    outcomes = _run(store, {"embed": make_embed_handler(service)})
    assert [o.status for o in outcomes] == ["done"]
    assert _embed_rows(store) == []


# --- episodes --------------------------------------------------------------


def test_the_handler_embeds_an_episode_title_and_summary(store):
    with store.transaction() as conn:
        episode_id = EpisodeStore(conn).add_episode(
            scope=OWNER, kind="manual", title="Acme cutover", summary="moved the fleet"
        )
    outcomes = _run(store, {"embed": make_embed_handler(_service())})
    assert [o.status for o in outcomes] == ["done"]
    (row,) = _embed_rows(store, MODEL)
    assert row["owner_type"] == "episode"
    assert row["owner_id"] == episode_id
    assert unpack_vector(row["vector"]) == pytest.approx(
        fake_vector("Acme cutover\nmoved the fleet")
    )


def test_a_stale_episode_job_does_not_overwrite_the_refined_summary(store):
    """The race: the episode is refined *during* the embedding call.

    The handler read the old text, the backend takes time, an upsert lands a
    refined summary (with its own vector), and the stale job then tries to
    write. Only the stamp checks — re-checked inside the write transaction —
    stop it. A plain replay cannot show this, because the handler re-reads the
    current text anyway.
    """
    with freeze(NOW):
        with store.transaction() as conn:
            episode_id = EpisodeStore(conn).add_episode(
                scope=OWNER, kind="session", session_id="sess-1",
                title="Acme cutover", summary="first draft",
            )
    (first_payload,) = [
        json.loads(row["payload"])
        for row in store.reader().execute("SELECT payload FROM jobs WHERE type='embed'").fetchall()
    ]
    # One deterministic job only: the original queue goes away.
    with store.transaction() as conn:
        conn.execute("DELETE FROM jobs")

    service = _service()
    inner = service.backend.embed
    raced = {"done": False}

    def racing_embed(texts):
        if not raced["done"]:
            raced["done"] = True
            with freeze(NOW + timedelta(milliseconds=5)):
                with store.transaction() as conn:
                    EpisodeStore(conn).upsert_episode(
                        scope=OWNER, kind="session", session_id="sess-1", window_seq=0,
                        title="Acme cutover", summary="refined summary",
                    )
                    put_embedding(
                        conn, owner_type="episode", owner_id=episode_id, model=MODEL,
                        vector=fake_vector("Acme cutover\nrefined summary"),
                        created_at=to_iso(utc_now()),
                    )
        return inner(texts)

    service.backend.embed = racing_embed
    with store.transaction() as conn:
        JobQueue(conn).enqueue(
            "embed",
            {
                "owner_type": "episode",
                "owner_id": episode_id,
                "stamp": first_payload["stamp"],
            },
            dedupe_key="stale-episode",
        )
    registry = HandlerRegistry()
    registry.register("embed", make_embed_handler(service))
    outcome = JobWorker(store, registry, worker_id="w").run_once()
    assert outcome is not None and outcome.status == "done"
    (row,) = _embed_rows(store, MODEL)
    assert unpack_vector(row["vector"]) == pytest.approx(
        fake_vector("Acme cutover\nrefined summary")
    )


# --- backfill and model identity -------------------------------------------


def test_ensure_embedding_model_queues_one_backfill_per_model(store):
    with store.transaction() as conn:
        first = ensure_embedding_model(conn, MODEL)
        second = ensure_embedding_model(conn, MODEL)
    assert first and first == second
    rows = store.reader().execute("SELECT type, dedupe_key FROM jobs").fetchall()
    assert [(r["type"], r["dedupe_key"]) for r in rows] == [
        ("embed_backfill", f"embed_backfill:{MODEL}")
    ]


def test_backfill_embeds_every_missing_memory_and_records_the_model(store):
    _add(store, "the Acme staging port is 9090")
    _add(store, "Bob Example waters the fern on Fridays")
    _add(store, "the kettle at Acme is blue")
    with store.transaction() as conn:
        ensure_embedding_model(conn, MODEL)
        assert stored_model(conn) == ""
    outcomes = _run(store, {"embed_backfill": make_embed_backfill_handler(_service())})
    assert [o.status for o in outcomes] == ["done"]
    assert len(_embed_rows(store, MODEL)) == 3
    assert stored_model(store.reader()) == MODEL


def test_backfill_covers_memories_and_episodes(store):
    _add(store, "the Acme staging port is 9090")
    _add(store, "Bob Example waters the fern on Fridays")
    with store.transaction() as conn:
        EpisodeStore(conn).add_episode(
            scope=OWNER, kind="manual", title="Acme cutover", summary="moved the fleet"
        )
        ensure_embedding_model(conn, MODEL)
    outcomes = _run(store, {"embed_backfill": make_embed_backfill_handler(_service())})
    assert [o.status for o in outcomes] == ["done"]
    rows = _embed_rows(store, MODEL)
    assert len(rows) == 3
    assert sorted(row["owner_type"] for row in rows) == ["episode", "memory", "memory"]
    assert stored_model(store.reader()) == MODEL


def test_backfill_pages_at_sixty_four(store):
    for i in range(70):
        _add(store, f"the Acme staging note number {i}")
    with store.transaction() as conn:
        ensure_embedding_model(conn, MODEL)
    service = _service()
    _run(store, {"embed_backfill": make_embed_backfill_handler(service)})
    assert len(_embed_rows(store, MODEL)) == 70
    assert service.backend.embed_calls == [64, 6]


def _rows_snapshot(store, model):
    return sorted(
        (
            row["owner_type"],
            row["owner_id"],
            row["content_hash"],
            row["created_at"],
            bytes(row["vector"]),
        )
        for row in _embed_rows(store, model)
    )


def test_backfill_is_idempotent_when_replayed(store):
    for i in range(70):
        _add(store, f"the Acme staging note number {i}")
    with store.transaction() as conn:
        EpisodeStore(conn).add_episode(
            scope=OWNER, kind="manual", title="Acme cutover", summary="moved the fleet"
        )
        ensure_embedding_model(conn, MODEL)
    _run(store, {"embed_backfill": make_embed_backfill_handler(_service())})
    before = _rows_snapshot(store, MODEL)
    assert len(before) == 71
    assert all(content_hash for *_rest, content_hash, _created, _vector in before)

    # Replay the same model: no new rows, no rewrites (created_at is the tell).
    with store.transaction() as conn:
        JobQueue(conn).enqueue(
            "embed_backfill", {"model": MODEL}, dedupe_key="replay-backfill"
        )
    outcomes = _run(store, {"embed_backfill": make_embed_backfill_handler(_service())})
    assert [o.status for o in outcomes] == ["done"]
    assert _rows_snapshot(store, MODEL) == before
    with store.transaction() as conn:
        assert ensure_embedding_model(conn, MODEL) is None
        assert stored_model(conn) == MODEL


def test_backfill_resumes_across_pages_after_a_failure(store):
    for i in range(70):
        _add(store, f"the Acme staging note number {i}")
    with store.transaction() as conn:
        ensure_embedding_model(conn, MODEL)

    flaky = _service()
    inner = flaky.backend.embed
    calls = {"n": 0}

    def failing(texts):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("acme backend down")
        return inner(texts)

    flaky.backend.embed = failing
    outcomes = _run(store, {"embed_backfill": make_embed_backfill_handler(flaky)})
    assert [o.status for o in outcomes] == ["failed"]  # retried, not dead
    assert len(_embed_rows(store, MODEL)) == 64  # the first page landed

    # Resume: only the remaining page is embedded; nothing duplicates.
    with store.transaction() as conn:
        JobQueue(conn).enqueue(
            "embed_backfill", {"model": MODEL}, dedupe_key="resume-backfill"
        )
    outcomes = _run(store, {"embed_backfill": make_embed_backfill_handler(_service())})
    assert [o.status for o in outcomes] == ["done"]
    rows = _embed_rows(store, MODEL)
    assert len(rows) == 70
    assert len({row["owner_id"] for row in rows}) == 70
    assert stored_model(store.reader()) == MODEL


def test_a_model_switch_backfills_the_new_model_and_leaves_the_old_rows(store):
    _add(store, "the Acme staging port is 9090")
    with store.transaction() as conn:
        ensure_embedding_model(conn, MODEL)
    _run(store, {"embed_backfill": make_embed_backfill_handler(_service(MODEL))})

    with store.transaction() as conn:
        assert ensure_embedding_model(conn, MODEL) is None  # nothing to do
        switched = ensure_embedding_model(conn, MODEL2)
    assert switched
    _run(store, {"embed_backfill": make_embed_backfill_handler(_service(MODEL2))})
    assert len(_embed_rows(store, MODEL)) == 1
    assert len(_embed_rows(store, MODEL2)) == 1
    assert stored_model(store.reader()) == MODEL2


def test_backfill_without_a_backend_leaves_the_model_unrecorded(store):
    _add(store, "the Acme staging port is 9090")
    with store.transaction() as conn:
        ensure_embedding_model(conn, MODEL)
    service = EmbeddingService(":memory:", backend=NoneBackend())
    outcomes = _run(store, {"embed_backfill": make_embed_backfill_handler(service)})
    assert [o.status for o in outcomes] == ["done"]
    assert _embed_rows(store) == []
    assert stored_model(store.reader()) == ""


# --- the CLI knows the new job types ---------------------------------------


def test_the_worker_cli_registers_both_embed_job_types(store, tmp_path):
    from em.jobs.cli import _KNOWN_TYPES, run_worker

    assert "embed" in _KNOWN_TYPES
    assert "embed_backfill" in _KNOWN_TYPES
    db = tmp_path / "memory2.db"
    opened = Store(str(db))
    with opened.writer() as conn:
        migrate(conn)
    with opened.transaction() as conn:
        ensure_embedding_model(conn, MODEL)
    opened.close()
    # No backend on this box: the backfill must still exit cleanly, job done.
    assert run_worker(db, once=True, types=["embed_backfill"]) == 0
    reopened = Store(str(db))
    try:
        assert stored_model(reopened.reader()) == ""
    finally:
        reopened.close()
