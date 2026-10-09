"""EM-303 — the vector cache: decode once per (db, model, scope), search fast.

The card's rule is "do not re-read blobs per query" (R10). The cache key is
``(db file, model, scope clause, params, numpy-or-python)``; the fingerprint is
``(row count, max rowid, write generation)`` where the generation is bumped by
``put_embedding``.

**The one recorded caveat, pinned below:** a raw-SQL rewrite of a vector that
leaves the row count, the max rowid and the generation unchanged is not seen
until the cache resets. That is the same shape v2's cache had; all writes that
go through ``put_embedding`` (the job handlers, the migration's own path at
build time) are seen immediately.

The 50k p95 test needs numpy and is skipped without it, like the graph tests
need fastapi; CI has no numpy, so the card's AC is measured on a box that
installs it.
"""

from __future__ import annotations

import importlib.util
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from em.clock import to_iso  # noqa: E402
from em.embeddings.cache import (  # noqa: E402
    cached_memory_vectors,
    reset_cache,
    search_memory_vectors,
)
from em.store.db import Store  # noqa: E402
from em.store.embeddings import (  # noqa: E402
    load_memory_vectors,
    pack_vector,
    put_embedding,
    rank_by_cosine,
)
from em.store.memories import MemoryStore  # noqa: E402
from em.store.migrations import migrate  # noqa: E402
from em.store.types import MemoryDraft, Scope  # noqa: E402

ALICE = Scope(profile="default", user="alice")
BOB = Scope(profile="default", user="bob")
NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
MODEL = "all-MiniLM-L6-v2"

CLAUSE, PARAMS = "m.scope_profile = ? AND m.scope_user = ?", ["default", "alice"]


@pytest.fixture
def store(tmp_path):
    saved = Store(str(tmp_path / "memory.db"))
    with saved.writer() as conn:
        migrate(conn)
    reset_cache()
    yield saved
    saved.close()
    reset_cache()


def _add(store, content, *, scope=ALICE):
    with store.transaction() as conn:
        result = MemoryStore(conn).add(
            MemoryDraft(content=content, source="agent"), scope=scope, actor="tester"
        )
    assert result.ok, result
    return result.id


def _embed(store, owner_id, vector):
    with store.transaction() as conn:
        put_embedding(
            conn,
            owner_id=owner_id,
            model=MODEL,
            vector=vector,
            created_at=to_iso(NOW),
        )


def test_the_cache_matches_the_uncached_loader_exactly(store):
    a = _add(store, "the staging port is 9090")
    b = _add(store, "the staging port is 8080")
    _embed(store, a, (1.0, 0.0))
    _embed(store, b, (0.0, 1.0))
    cached = search_memory_vectors(
        store.reader(),
        model=MODEL,
        scope_clause=CLAUSE,
        scope_params=PARAMS,
        query=(1.0, 0.0),
        k=10,
        use_numpy=False,
    )
    loaded = load_memory_vectors(
        store.reader(), model=MODEL, scope_clause=CLAUSE, scope_params=PARAMS
    )
    uncached = rank_by_cosine((1.0, 0.0), loaded, k=10)
    assert cached == uncached


def test_a_vector_written_through_put_embedding_is_seen_next_search(store):
    a = _add(store, "the staging port is 9090")
    _embed(store, a, (1.0, 0.0))
    first = search_memory_vectors(
        store.reader(), model=MODEL, scope_clause=CLAUSE, scope_params=PARAMS,
        query=(0.0, 1.0), k=10, use_numpy=False,
    )
    assert first == [(a, 0.0)]

    _embed(store, a, (0.0, 1.0))  # same row, new vector
    second = search_memory_vectors(
        store.reader(), model=MODEL, scope_clause=CLAUSE, scope_params=PARAMS,
        query=(0.0, 1.0), k=10, use_numpy=False,
    )
    assert second == [(a, 1.0)]


def test_a_deleted_row_invalidates_the_cache(store):
    a = _add(store, "the staging port is 9090")
    _embed(store, a, (1.0, 0.0))
    search_memory_vectors(
        store.reader(), model=MODEL, scope_clause=CLAUSE, scope_params=PARAMS,
        query=(1.0, 0.0), k=10, use_numpy=False,
    )
    with store.transaction() as conn:
        conn.execute("DELETE FROM embeddings WHERE owner_id=?", (a,))
    assert search_memory_vectors(
        store.reader(), model=MODEL, scope_clause=CLAUSE, scope_params=PARAMS,
        query=(1.0, 0.0), k=10, use_numpy=False,
    ) == []


def test_a_raw_same_length_rewrite_is_not_reread_until_reset(store):
    """The recorded caveat: raw SQL that leaves the fingerprint alone is stale."""
    a = _add(store, "the staging port is 9090")
    _embed(store, a, (1.0, 0.0))
    search_memory_vectors(
        store.reader(), model=MODEL, scope_clause=CLAUSE, scope_params=PARAMS,
        query=(1.0, 0.0), k=10, use_numpy=False,
    )
    with store.transaction() as conn:
        conn.execute(
            "UPDATE embeddings SET vector=? WHERE owner_id=?",
            (pack_vector((-1.0, 0.0)), a),
        )
    assert search_memory_vectors(
        store.reader(), model=MODEL, scope_clause=CLAUSE, scope_params=PARAMS,
        query=(1.0, 0.0), k=10, use_numpy=False,
    ) == [(a, 1.0)]  # cached value

    reset_cache()
    assert search_memory_vectors(
        store.reader(), model=MODEL, scope_clause=CLAUSE, scope_params=PARAMS,
        query=(1.0, 0.0), k=10, use_numpy=False,
    ) == [(a, -1.0)]  # the rewrite is visible after a reset


def test_scope_is_part_of_the_cache_key(store):
    a = _add(store, "alice keeps a red notebook", scope=ALICE)
    _embed(store, a, (1.0, 0.0))
    assert search_memory_vectors(
        store.reader(), model=MODEL, scope_clause=CLAUSE, scope_params=PARAMS,
        query=(1.0, 0.0), k=10, use_numpy=False,
    ) == [(a, 1.0)]
    bob = search_memory_vectors(
        store.reader(), model=MODEL,
        scope_clause="m.scope_profile = ? AND m.scope_user = ?", scope_params=["default", "bob"],
        query=(1.0, 0.0), k=10, use_numpy=False,
    )
    assert bob == []


def test_ties_are_deterministic_even_when_the_loader_returns_unsorted_rows(store, monkeypatch):
    """The snapshot sorts by id, so numpy's stable argsort is a guarantee.

    The end-to-end path happens to return memory-row order today, which is id
    order — so the sort cannot be observed through SQL. Stubbing the loader
    with deliberately unsorted rows is what pins it; without the sort, the
    numpy path would hand back the loader's order for equal scores.
    """
    import em.embeddings.cache as cache

    monkeypatch.setattr(
        cache, "load_vectors",
        lambda *a, **k: [("mem_b", (1.0, 0.0)), ("mem_a", (1.0, 0.0))],
    )
    reset_cache()
    modes = [False] + ([True] if importlib.util.find_spec("numpy") is not None else [])
    for mode in modes:
        found = cache.search_memory_vectors(
            store.reader(), model=MODEL, scope_clause=CLAUSE, scope_params=PARAMS,
            query=(1.0, 0.0), k=10, use_numpy=mode,
        )
        assert [owner for owner, _ in found] == ["mem_a", "mem_b"], f"mode={mode}"
    entry = cache.cached_memory_vectors(
        store.reader(), model=MODEL, scope_clause=CLAUSE, scope_params=PARAMS,
        use_numpy=False,
    )
    assert entry.ids == ("mem_a", "mem_b")


def test_the_snapshot_exposes_one_vector_by_id(store):
    a = _add(store, "the staging port is 9090")
    _embed(store, a, (0.25, 0.75))
    entry = cached_memory_vectors(
        store.reader(), model=MODEL, scope_clause=CLAUSE, scope_params=PARAMS,
        use_numpy=False,
    )
    assert entry.ids == (a,)
    assert entry.vector_of(a) == pytest.approx((0.25, 0.75))
    assert entry.vector_of("mem_nope") is None


def test_numpy_and_python_paths_agree(store):
    pytest.importorskip("numpy")
    a = _add(store, "the staging port is 9090")
    b = _add(store, "the staging port is 8080")
    _embed(store, a, (1.0, 0.0))
    _embed(store, b, (0.6, 0.8))
    args = dict(model=MODEL, scope_clause=CLAUSE, scope_params=PARAMS, query=(1.0, 0.0), k=10)
    python = search_memory_vectors(store.reader(), use_numpy=False, **args)
    matrix = search_memory_vectors(store.reader(), use_numpy=True, **args)
    assert [owner for owner, _ in matrix] == [owner for owner, _ in python]
    for (_, py_score), (_, np_score) in zip(python, matrix):
        assert py_score == pytest.approx(np_score, abs=1e-6)


def test_50k_vectors_search_p95_under_25ms_with_numpy(tmp_path):
    """The card's AC: 50k vectors, numpy, p95 < 25 ms."""
    pytest.importorskip("numpy")
    db = tmp_path / "big.db"
    saved = Store(str(db))
    with saved.writer() as conn:
        migrate(conn)

    dim = 128
    stamp = to_iso(NOW)
    memory_rows = []
    embedding_rows = []
    for i in range(50_000):
        owner_id = f"mem_{i:06d}"
        vector = [((i * 31 + j * 7) % 100) / 100.0 for j in range(dim)]
        memory_rows.append(
            (owner_id, "default", "alice", "user", "fact", f"note {i}", f"h{i:06d}", "agent", stamp, stamp)
        )
        embedding_rows.append(("memory", owner_id, MODEL, dim, pack_vector(vector), "", stamp))
    with saved.transaction() as conn:
        conn.executemany(
            "INSERT INTO memories (id, scope_profile, scope_user, visibility, kind,"
            " content, content_hash, source, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            memory_rows,
        )
        conn.executemany(
            "INSERT INTO embeddings (owner_type, owner_id, model, dim, vector,"
            " content_hash, created_at) VALUES (?,?,?,?,?,?,?)",
            embedding_rows,
        )

    reader = saved.reader()
    query = [((j * 13) % 100) / 100.0 for j in range(dim)]
    search_memory_vectors(
        reader, model=MODEL, scope_clause=CLAUSE, scope_params=PARAMS,
        query=query, k=10, use_numpy=True,
    )  # warm: build the matrix before timing

    samples = []
    for probe in range(20):
        probe_query = [(value + probe) % 1.0 for value in query]
        started = time.perf_counter()
        found = search_memory_vectors(
            reader, model=MODEL, scope_clause=CLAUSE, scope_params=PARAMS,
            query=probe_query, k=10, use_numpy=True,
        )
        samples.append((time.perf_counter() - started) * 1000.0)
        assert len(found) == 10
    samples.sort()
    p95 = samples[int(0.95 * len(samples)) - 1]
    assert p95 < 25.0, f"50k search p95 {p95:.2f} ms > 25 ms (samples: {samples})"
    saved.close()
