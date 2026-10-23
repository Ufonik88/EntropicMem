"""EM-705 — hard delete covers the embeddings and the vault projection.

``MemoryStore.purge`` already removed the row, its versions, relations, outbox
rows, entity links/sightings; the card closes its two holes:

* the memory's vector rows stayed in ``embeddings`` after the fact was gone —
  personal content surviving an explicit erase, which the §8 privacy budgets
  name directly;
* the vault kept rendering the fact until something else happened to re-run a
  projection, so ``purge`` gains an optional ``schedule_projection`` callback —
  a callback, not a store→vault import (``em.vault.schedule`` imports
  ``em.store``, so the reverse import would cycle). The store never swallows a
  callback error: callers pass fail-soft callbacks.

Proofs pinned here: the vector rows are gone (count proof + the invariant-6
``iterdump`` scan), a re-embed of a purged id writes nothing (the embed handler
refuses a missing owner), the callback fires exactly once with the purged id
and is not swallowed, and the E2E: purge + one regeneration leaves no vault
file carrying the text.

Stale ``embed:<id>:<version>`` job rows for a purged memory are *not* cleaned —
the handler already permanent-errors on a missing owner — and that stays out
of scope here.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
for _entry in (str(REPO), str(SCRIPTS)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from em.store.db import Store  # noqa: E402
from em.store.embeddings import put_embedding  # noqa: E402
from em.store.memories import MemoryStore  # noqa: E402
from em.store.migrations import migrate  # noqa: E402
from em.store.types import MemoryDraft, Scope  # noqa: E402

OWNER = Scope(profile="default")
SENTENCE = "The staging port is 9090 and the deploy window is Thursday."
OTHER = "The archive retention policy is thirty days."


class _Embedder:
    """A minimal embedding-service fake for the embed job handler."""

    model = "fake-model"
    available = True

    @staticmethod
    def embed_texts(texts):
        return [[0.1] * 4 for _ in texts]


class _Ctx:
    def __init__(self, store: Store) -> None:
        self.store = store


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path / "memory.db"))
    try:
        with s.writer() as conn:
            migrate(conn)
        yield s
    finally:
        s.close()


def _mid(s: Store, content: str) -> str:
    with s.transaction() as conn:
        return MemoryStore(conn).add(
            MemoryDraft(content=content, status="active"), scope=OWNER, actor="tester"
        ).id


def _embed(s: Store, owner_id: str, model: str, owner_type: str = "memory") -> None:
    with s.transaction() as conn:
        put_embedding(
            conn,
            owner_id=owner_id,
            model=model,
            vector=(0.1, 0.2, 0.3, 0.4),
            owner_type=owner_type,
            content_hash=f"hash-{owner_id}",
            created_at="2026-10-23T00:00:00Z",
        )


def _embed_count(s: Store, owner_id: str, owner_type: str = "memory") -> int:
    with s.reader() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM embeddings WHERE owner_type=? AND owner_id=?",
            (owner_type, owner_id),
        ).fetchone()[0]


# --- the embeddings rows -------------------------------------------------------


def test_purge_removes_the_memory_embedding_rows(store):
    """The count proof: the purged memory's vectors go with the fact."""
    gone = _mid(store, SENTENCE)
    kept = _mid(store, OTHER)
    _embed(store, gone, "fake-model")
    _embed(store, kept, "fake-model")
    assert _embed_count(store, gone) == 1, "precondition: the vector exists"

    with store.transaction() as conn:
        MemoryStore(conn).purge(gone, actor="tester")

    assert _embed_count(store, gone) == 0, "the purged memory's vector rows survived"
    assert _embed_count(store, kept) == 1, "another memory's vector is untouched"


def test_purge_leaves_episode_vectors_alone(store):
    """The delete is narrow: one memory's rows (every model), never episodes."""
    gone = _mid(store, SENTENCE)
    _embed(store, gone, "fake-model-a")
    _embed(store, gone, "fake-model-b")
    episode_id = "ep_0000000001"
    _embed(store, episode_id, "fake-model-a", owner_type="episode")

    with store.transaction() as conn:
        MemoryStore(conn).purge(gone, actor="tester")

    assert _embed_count(store, gone) == 0
    assert _embed_count(store, gone, owner_type="episode") == 0, (
        "no memory row is named like the episode id"
    )
    assert _embed_count(store, episode_id, owner_type="episode") == 1, (
        "episode vectors are not memory rows; purge does not touch them"
    )


def test_no_vector_insert_for_a_purged_id_survives_in_the_iterdump(store):
    """Invariant 6's whole-database proof, extended to ``embeddings``: no dump
    line that inserts an embeddings row may carry the purged id. (The audit log
    deliberately keeps the purge's target id, so the whole dump is not asserted
    id-free — the way the EM-208 sighting test scans for the name, not the id.)"""
    gone = _mid(store, SENTENCE)
    kept = _mid(store, OTHER)
    _embed(store, gone, "fake-model")
    _embed(store, kept, "fake-model")

    with store.transaction() as conn:
        MemoryStore(conn).purge(gone, actor="tester")

    with store.reader() as conn:
        dump = "".join(conn.iterdump())
    vector_lines = [ln for ln in dump.splitlines() if 'INSERT INTO "embeddings"' in ln]
    assert vector_lines, "precondition: vector insert lines exist in the dump"
    assert not any(gone in ln for ln in vector_lines), (
        "the purged memory's vector insert survived in the dump"
    )
    assert any(kept in ln for ln in vector_lines), "the surviving vector is still dumped"


# --- a re-embed of a purged id writes nothing -----------------------------------


def test_a_reembed_of_a_purged_id_writes_nothing(store):
    """The queued ``embed`` job outlives a purge (cleaning it is out of scope);
    the handler must refuse a missing owner, so no vector can reappear."""
    from em.embeddings.jobs import make_embed_handler
    from em.jobs.worker import PermanentJobError

    gone = _mid(store, SENTENCE)
    with store.reader() as conn:
        row = conn.execute(
            "SELECT * FROM jobs WHERE type='embed' AND status='queued' LIMIT 1"
        ).fetchone()
    assert row is not None, "precondition: the add pipeline enqueued an embed job"

    with store.transaction() as conn:
        MemoryStore(conn).purge(gone, actor="tester")
    assert _embed_count(store, gone) == 0, "precondition: the purge also took the vectors"

    job = SimpleNamespace(payload={"memory_id": gone, "version": 1})
    with pytest.raises(PermanentJobError, match="no longer exists"):
        make_embed_handler(_Embedder())(job, _Ctx(store))
    assert _embed_count(store, gone) == 0, "a re-embed of a purged id wrote nothing"


# --- the projection callback ----------------------------------------------------


def test_purge_works_without_a_callback(store):
    """The kwarg is optional: today's callers unchanged."""
    mid = _mid(store, SENTENCE)
    with store.transaction() as conn:
        MemoryStore(conn).purge(mid, actor="tester")
    with store.reader() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM memories WHERE id=?", (mid,)
        ).fetchone()[0] == 0


def test_the_projection_callback_fires_exactly_once_with_the_purged_id(store):
    gone = _mid(store, SENTENCE)
    kept = _mid(store, OTHER)
    calls: list[str] = []
    with store.transaction() as conn:
        MemoryStore(conn).purge(gone, actor="tester", schedule_projection=calls.append)
    assert calls == [gone], "one callback, for the purged id only"
    with store.reader() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM memories WHERE id=?", (kept,)
        ).fetchone()[0] == 1


def test_a_raising_projection_callback_is_not_swallowed(store):
    """No try/except around the callback in the store: the rollover cost is a
    failed purge, so a caller wraps its own callback (fail-soft) — the point is
    that a silently swallowed producer error cannot leave the caller believing
    a projection is scheduled."""
    mid = _mid(store, SENTENCE)

    def boom(memory_id: str) -> None:
        raise RuntimeError("the projection schedule exploded")

    def _purge_with_boom() -> None:
        with store.transaction() as conn:
            MemoryStore(conn).purge(mid, actor="tester", schedule_projection=boom)

    # The raise must escape the caller's transaction for write_txn to roll it
    # back — so the pytest.raises wraps the whole transaction, not the purge.
    with pytest.raises(RuntimeError, match="projection schedule"):
        _purge_with_boom()
    with store.reader() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM memories WHERE id=?", (mid,)
        ).fetchone()[0] == 1, "the rolled-back transaction left the row standing"


# --- the E2E proof --------------------------------------------------------------


def test_purge_then_one_reprojection_leaves_no_vault_file_with_the_text(tmp_path, store):
    """The card's E2E: the vault had the fact, the purge scheduled a
    regeneration, and one ``project()`` run later no file under the vault
    carries the text (the real choreography: ``schedule_projection`` is what
    enqueues a ``project_vault`` job; here the regeneration is run directly)."""
    from em.vault.projection import project

    root = tmp_path / "vault"
    mid = _mid(store, SENTENCE)
    with store.transaction() as conn:
        project(conn, root, scope=OWNER, modes=("unfiled",))
    page = root / "Memories" / "Unfiled.md"
    assert page.is_file(), "precondition: the projection wrote the unfiled page"
    assert SENTENCE in page.read_text(encoding="utf-8"), (
        "precondition: the live fact is rendered"
    )

    scheduled: list[str] = []
    with store.transaction() as conn:
        MemoryStore(conn).purge(mid, actor="tester", schedule_projection=scheduled.append)
        for scheduled_id in scheduled:
            # The real choreography: the callback enqueues one project_vault
            # job, and the worker later runs the projection. The regeneration
            # runs here only because the callback fired — a schedule that
            # silently never fires leaves the fact rendered in the vault.
            project(conn, root, scope=OWNER, modes=("unfiled",))
    assert scheduled == [mid], "the purge scheduled exactly one regeneration"

    texts = [(path, path.read_text(encoding="utf-8")) for path in sorted(root.rglob("*.md"))]
    assert texts, "precondition: the vault has pages"
    for path, text in texts:
        assert SENTENCE not in text, f"the purged fact still renders in {path.name}"
