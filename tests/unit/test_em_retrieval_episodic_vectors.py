"""EM-303 episode vectors reach the search path EM-307's renderer reads.

Before this, episode vectors were written and never read: `episodic` was
FTS-only and the gate had no cosine for episode rows. Now the generator
appends vector-ranked episodes (under the same 50% coverage gate as memories)
and the pipeline hands their cosines to the gate, so a paraphrase with no
lexical overlap can be ranked and `render_retrieval` prints it under
"Recent episodes".

The stored stamp is the episode's `updated_at`; a read compares it with the
current row the same way memory reads compare `content_hash`.

Invented data only: Acme.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from em.clock import freeze, to_iso  # noqa: E402
from em.embeddings.jobs import make_embed_handler  # noqa: E402
from em.embeddings.service import EmbeddingService  # noqa: E402
from em.jobs import HandlerRegistry, JobWorker  # noqa: E402
from em.provider.render import render_retrieval  # noqa: E402
from em.retrieval.pipeline import retrieve  # noqa: E402
from em.store.db import Store  # noqa: E402
from em.store.embeddings import put_embedding  # noqa: E402
from em.store.episodes import EpisodeStore  # noqa: E402
from em.store.migrations import migrate  # noqa: E402
from em.store.types import Scope  # noqa: E402

OWNER = Scope(profile="default")
NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
MODEL = "all-MiniLM-L6-v2"
QUERY = "what did they decide about the migration?"


@pytest.fixture
def store(tmp_path):
    saved = Store(str(tmp_path / "memory.db"))
    with saved.writer() as conn:
        migrate(conn)
    yield saved
    saved.close()


def _add_episode(store, title, summary=""):
    with store.transaction() as conn:
        return EpisodeStore(conn).add_episode(
            scope=OWNER, kind="manual", title=title, summary=summary
        )


def _embed_episode(store, episode_id, vector):
    stamp = store.reader().execute(
        "SELECT updated_at FROM episodes WHERE id=?", (episode_id,)
    ).fetchone()["updated_at"]
    with store.transaction() as conn:
        put_embedding(
            conn,
            owner_type="episode",
            owner_id=episode_id,
            model=MODEL,
            vector=vector,
            content_hash=str(stamp),
            created_at=to_iso(NOW),
        )


def _retrieve(store, query=QUERY):
    return retrieve(
        store.reader(),
        scope=OWNER,
        query=query,
        with_gate=True,
        now=NOW,
        query_vector=(1.0, 0.0),
        embedding_model=MODEL,
    )


def test_a_vector_only_episode_is_ranked_and_rendered(store):
    with freeze(NOW):
        target = _add_episode(store, "Acme fleet cutover to example signaling", "object numbers are hub ids")
        other = _add_episode(store, "invoices are filed on Fridays")
        _embed_episode(store, target, (1.0, 0.0))
        _embed_episode(store, other, (0.0, 1.0))
    found = _retrieve(store)
    assert target in found.ids
    assert other not in found.ids

    block = render_retrieval(store.reader(), found)
    assert "### Recent episodes" in block
    assert "example signaling" in block


def test_below_half_episode_coverage_disables_vector_recall(store):
    with freeze(NOW):
        target = _add_episode(store, "Acme fleet cutover to example signaling", "object numbers are hub ids")
        _add_episode(store, "invoices are filed on Fridays")
        _add_episode(store, "the kettle at Acme is blue")
        _embed_episode(store, target, (1.0, 0.0))
    found = _retrieve(store)
    assert target not in found.ids


def test_a_stale_episode_stamp_excludes_the_vector(store):
    with freeze(NOW):
        with store.transaction() as conn:
            episode = EpisodeStore(conn).add_episode(
                scope=OWNER, kind="session", session_id="sess-1",
                title="Acme fleet cutover to example signaling", summary="object numbers are hub ids",
            )
        _embed_episode(store, episode, (1.0, 0.0))
    # Refine the episode without re-embedding: the stamp moves, the vector is stale.
    with freeze(NOW + timedelta(milliseconds=5)):
        with store.transaction() as conn:
            EpisodeStore(conn).upsert_episode(
                scope=OWNER, kind="session", session_id="sess-1", window_seq=0,
                title="Acme fleet cutover to example signaling", summary="object numbers are hub ids, revised",
            )
    found = _retrieve(store)
    assert episode not in found.ids


def test_lexical_and_vector_hits_do_not_duplicate(store):
    with freeze(NOW):
        episode = _add_episode(store, "the Acme migration decision", "object numbers are hub ids")
        _embed_episode(store, episode, (1.0, 0.0))
    found = _retrieve(store, query="Acme migration decision")
    assert found.ids.count(episode) == 1


def test_a_partial_new_model_backfill_never_uses_old_model_vectors(store):
    """Same rule as memories: a half-switched model never mixes episode rows."""
    old_model = "bge-small-en-v1.5"
    with freeze(NOW):
        switched = _add_episode(store, "Acme fleet cutover to example signaling")
        old_only = _add_episode(store, "invoices are filed on Fridays")
        for episode_id in (switched, old_only):
            with store.transaction() as conn:
                put_embedding(
                    conn, owner_type="episode", owner_id=episode_id, model=old_model,
                    vector=(1.0, 0.0), created_at=to_iso(NOW),
                )
        _embed_episode(store, switched, (1.0, 0.0))  # new model, 1 of 2 = 50%
    found = _retrieve(store)
    assert switched in found.ids
    assert old_only not in found.ids


def test_a_stale_episode_is_excluded_logged_and_restored_by_the_re_embed_queue(store, caplog):
    with freeze(NOW):
        with store.transaction() as conn:
            episode = EpisodeStore(conn).add_episode(
                scope=OWNER, kind="session", session_id="sess-1",
                title="Acme fleet cutover to example signaling",
                summary="object numbers are hub ids",
            )
        _embed_episode(store, episode, (1.0, 0.0))
    with freeze(NOW + timedelta(milliseconds=5)):
        with store.transaction() as conn:
            EpisodeStore(conn).upsert_episode(
                scope=OWNER, kind="session", session_id="sess-1", window_seq=0,
                title="Acme fleet cutover to example signaling",
                summary="object numbers are hub ids, revised",
            )

    caplog.set_level(logging.INFO, logger="em.retrieval.vectors")
    assert episode not in _retrieve(store).ids
    assert "stale vector(s) excluded" in caplog.text

    class Fake:
        name = "fake"
        default_model = MODEL
        dim = 2

        def available(self):
            return True

        def warm(self):
            pass

        def embed(self, texts):
            return [[1.0, 0.0] for _ in texts]

    registry = HandlerRegistry()
    registry.register(
        "embed", make_embed_handler(EmbeddingService(":memory:", backend=Fake(), model=MODEL))
    )
    outcomes = JobWorker(store, registry, worker_id="w").run_until_idle()
    assert any(outcome.status == "done" for outcome in outcomes)
    assert episode in _retrieve(store).ids
