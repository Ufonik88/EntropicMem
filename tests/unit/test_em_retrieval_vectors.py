"""EM-303's first slice — cosine over vectors already stored.

No backend, no numpy, no embed call. A query vector is supplied by the caller
or the generator does nothing. Coverage below 50% disables it. The default
``retrieve`` (no query vector) does not turn cosine on.

Invented data only: Acme, Alice, Bob.
"""

from __future__ import annotations

import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from em.clock import freeze, to_iso  # noqa: E402
from em.retrieval.pipeline import retrieve  # noqa: E402
from em.store.db import Store  # noqa: E402
from em.store.embeddings import cosine, pack_vector, put_embedding, unpack_vector  # noqa: E402
from em.store.memories import MemoryStore  # noqa: E402
from em.store.migrations import migrate  # noqa: E402
from em.store.types import MemoryDraft, Scope  # noqa: E402

ALICE = Scope(profile="default", user="alice")
BOB = Scope(profile="default", user="bob")
NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
MODEL = "all-MiniLM-L6-v2"
OTHER = "bge-small-en-v1.5"


@pytest.fixture
def store(tmp_path):
    saved = Store(str(tmp_path / "memory.db"))
    with saved.writer() as conn:
        migrate(conn)
    yield saved
    saved.close()


def _add(store, content, *, scope=ALICE):
    with store.transaction() as conn:
        result = MemoryStore(conn).add(
            MemoryDraft(content=content, source="agent"),
            scope=scope,
            actor="tester",
        )
    assert result.ok, result
    return result.id


def _embed(store, owner_id, vector, *, model=MODEL):
    with store.transaction() as conn:
        put_embedding(
            conn,
            owner_id=owner_id,
            model=model,
            vector=vector,
            created_at=to_iso(NOW),
        )


def _content_hash(store, memory_id):
    return store.reader().execute(
        "SELECT content_hash FROM memories WHERE id=?", (memory_id,)
    ).fetchone()["content_hash"]


def _embed_with_hash(store, owner_id, vector, content_hash, *, model=MODEL):
    with store.transaction() as conn:
        put_embedding(
            conn,
            owner_id=owner_id,
            model=model,
            vector=vector,
            content_hash=content_hash,
            created_at=to_iso(NOW),
        )


def test_cosine_is_the_normalised_dot_product():
    assert cosine((1.0, 0.0), (1.0, 0.0)) == pytest.approx(1.0)
    assert cosine((1.0, 0.0), (0.0, 1.0)) == pytest.approx(0.0)
    assert cosine((1.0, 0.0), (1.0, 1.0)) == pytest.approx(1.0 / math.sqrt(2.0))
    assert cosine((0.0, 0.0), (1.0, 0.0)) == 0.0
    assert cosine((1.0, 0.0), (1.0,)) == 0.0


def test_blobs_roundtrip_and_a_short_blob_is_skipped():
    blob = pack_vector((0.5, -1.25, 3.0))
    assert unpack_vector(blob) == pytest.approx((0.5, -1.25, 3.0))
    assert unpack_vector(b"\x00\x01\x02") is None
    assert unpack_vector(b"") is None


def test_a_paraphrase_with_no_shared_words_survives_when_the_vector_matches(store):
    with freeze(NOW):
        aligned = _add(store, "llamas enjoy twilight at Acme")
        orthogonal = _add(store, "invoices are filed on Fridays")
        _embed(store, aligned, (1.0, 0.0))
        _embed(store, orthogonal, (0.0, 1.0))
    conn = store.reader()
    query = "orbital decay of a satellite"
    without = retrieve(conn, scope=ALICE, query=query, with_gate=True, now=NOW)
    assert aligned not in without.ids
    assert orthogonal not in without.ids

    with_vector = retrieve(
        conn,
        scope=ALICE,
        query=query,
        with_gate=True,
        now=NOW,
        query_vector=(1.0, 0.0),
        embedding_model=MODEL,
    )
    assert aligned in with_vector.ids
    assert orthogonal not in with_vector.ids
    hit = next(ranking for ranking in with_vector.rankings if ranking.owner_id == aligned)
    assert "vector" in {signal.signal for signal in hit.signals}


def test_coverage_below_half_disables_the_generator(store):
    with freeze(NOW):
        aligned = _add(store, "llamas enjoy twilight at Acme")
        _add(store, "invoices are filed on Fridays")
        _add(store, "the kettle is blue")
        _embed(store, aligned, (1.0, 0.0))
    conn = store.reader()
    found = retrieve(
        conn,
        scope=ALICE,
        query="orbital decay of a satellite",
        with_gate=True,
        now=NOW,
        query_vector=(1.0, 0.0),
        embedding_model=MODEL,
    )
    assert aligned not in found.ids


def test_exactly_half_is_enough(store):
    with freeze(NOW):
        aligned = _add(store, "llamas enjoy twilight at Acme")
        _add(store, "invoices are filed on Fridays")
        _embed(store, aligned, (1.0, 0.0))
    conn = store.reader()
    found = retrieve(
        conn,
        scope=ALICE,
        query="orbital decay of a satellite",
        with_gate=True,
        now=NOW,
        query_vector=(1.0, 0.0),
        embedding_model=MODEL,
    )
    assert aligned in found.ids


def test_another_users_vector_is_invisible(store):
    with freeze(NOW):
        alice = _add(store, "llamas enjoy twilight at Acme", scope=ALICE)
        bob_a = _add(store, "bob keeps a red notebook", scope=BOB)
        bob_b = _add(store, "bob waters the fern", scope=BOB)
        _embed(store, alice, (1.0, 0.0))
        _embed(store, bob_a, (0.0, 1.0))
        _embed(store, bob_b, (0.0, 1.0))
    conn = store.reader()
    found = retrieve(
        conn,
        scope=BOB,
        query="orbital decay of a satellite",
        with_gate=True,
        now=NOW,
        query_vector=(1.0, 0.0),
        embedding_model=MODEL,
    )
    assert alice not in found.ids


def test_a_different_model_does_not_count(store):
    with freeze(NOW):
        aligned = _add(store, "llamas enjoy twilight at Acme")
        other = _add(store, "invoices are filed on Fridays")
        _embed(store, aligned, (1.0, 0.0), model=OTHER)
        _embed(store, other, (0.0, 1.0), model=OTHER)
    conn = store.reader()
    found = retrieve(
        conn,
        scope=ALICE,
        query="orbital decay of a satellite",
        with_gate=True,
        now=NOW,
        query_vector=(1.0, 0.0),
        embedding_model=MODEL,
    )
    assert aligned not in found.ids


def test_an_unknown_model_has_no_cosine_threshold(store):
    """§3.6 names two model thresholds. An unnamed model must not invent one."""
    with freeze(NOW):
        aligned = _add(store, "llamas enjoy twilight at Acme")
        _embed(store, aligned, (1.0, 0.0), model="acme-test-model")
    conn = store.reader()
    found = retrieve(
        conn,
        scope=ALICE,
        query="orbital decay of a satellite",
        with_gate=True,
        now=NOW,
        query_vector=(1.0, 0.0),
        embedding_model="acme-test-model",
    )
    assert aligned not in found.ids


def test_an_explicit_gate_config_can_keep_cosine_off(store):
    from em.retrieval.gate import GateConfig

    with freeze(NOW):
        aligned = _add(store, "llamas enjoy twilight at Acme")
        _embed(store, aligned, (1.0, 0.0))
    conn = store.reader()
    found = retrieve(
        conn,
        scope=ALICE,
        query="orbital decay of a satellite",
        with_gate=True,
        now=NOW,
        query_vector=(1.0, 0.0),
        embedding_model=MODEL,
        gate_config=GateConfig(cosine_enabled=False),
    )
    assert aligned not in found.ids


def test_a_corrupt_blob_is_skipped_not_raised(store):
    with freeze(NOW):
        good = _add(store, "llamas enjoy twilight at Acme")
        bad = _add(store, "invoices are filed on Fridays")
        _embed(store, good, (1.0, 0.0))
        with store.transaction() as conn:
            conn.execute(
                "INSERT INTO embeddings (owner_type, owner_id, model, dim, vector,"
                " content_hash, created_at) VALUES ('memory',?,?,?,?,?,?)",
                (bad, MODEL, 2, b"\x00\x01\x02", "", to_iso(NOW)),
            )
    conn = store.reader()
    found = retrieve(
        conn,
        scope=ALICE,
        query="orbital decay of a satellite",
        with_gate=True,
        now=NOW,
        query_vector=(1.0, 0.0),
        embedding_model=MODEL,
    )
    assert good in found.ids
    assert bad not in found.ids


def test_no_query_vector_issues_no_vector_sql(store):
    from em.retrieval.candidates import RetrievalContext, vector
    from em.retrieval.query import AnalyzedQuery

    class Recording:
        def __init__(self, conn):
            self._conn = conn
            self.queries: list[str] = []

        def execute(self, sql, params=()):
            self.queries.append(sql)
            return self._conn.execute(sql, params)

    with freeze(NOW):
        memory_id = _add(store, "llamas enjoy twilight at Acme")
        _embed(store, memory_id, (1.0, 0.0))
    analyzed = AnalyzedQuery(
        raw="llamas", text="llamas", terms=("llamas",), temporal=None, entities=(), intent="lookup"
    )
    ctx = RetrievalContext(
        conn=Recording(store.reader()),
        aq=analyzed,
        scope=ALICE,
        now=NOW,
    )
    assert vector(ctx) == []
    assert ctx.conn.queries == []


def test_a_stale_content_hash_excludes_the_vector(store):
    """A vector only serves the text it was embedded from.

    The row's stored ``content_hash`` is compared with the memory's current
    one on every read; a mismatch means the text changed after the embedding
    and the vector is excluded until the queued re-embed lands. Nothing is
    ever silently mixed.
    """
    with freeze(NOW):
        fresh = _add(store, "llamas enjoy twilight at Acme")
        stale = _add(store, "invoices are filed on Fridays")
        _embed_with_hash(store, fresh, (1.0, 0.0), _content_hash(store, fresh))
        _embed_with_hash(store, stale, (1.0, 0.0), "deadbeef")
    found = retrieve(
        store.reader(),
        scope=ALICE,
        query="orbital decay of a satellite",
        with_gate=True,
        now=NOW,
        query_vector=(1.0, 0.0),
        embedding_model=MODEL,
    )
    assert fresh in found.ids
    assert stale not in found.ids


def test_a_vector_of_another_width_is_filtered_not_mixed(store):
    """A same-name model whose artifact changed width cannot pad or crash."""
    with freeze(NOW):
        two = _add(store, "llamas enjoy twilight at Acme")
        three = _add(store, "invoices are filed on Fridays")
        _embed(store, two, (1.0, 0.0))
        _embed(store, three, (1.0, 0.0, 0.0))
    from em.embeddings.cache import cached_vectors

    snapshot = cached_vectors(
        store.reader(), model=MODEL, scope_clause="m.scope_profile = ? AND m.scope_user = ?",
        scope_params=[ALICE.profile, ALICE.user], width=2,
    )
    assert snapshot.count == 1  # the width-3 row is not in the query's snapshot
    found = retrieve(
        store.reader(),
        scope=ALICE,
        query="orbital decay of a satellite",
        with_gate=True,
        now=NOW,
        query_vector=(1.0, 0.0),
        embedding_model=MODEL,
    )
    assert two in found.ids
    assert three not in found.ids
