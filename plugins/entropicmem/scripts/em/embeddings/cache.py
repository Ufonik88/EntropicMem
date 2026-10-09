"""The vector cache: decode blobs once, search the matrix per query — EM-303.

The card's R10 fix: "vector search: numpy matrix cache per ``(db path, model,
write_generation_embeddings)``; do not re-read blobs per query".

What is cached is a **snapshot** of the rows a scope can see, loaded through
the same ``scope_sql`` clause the generators use — §3.5 stays in SQL, it is not
reimplemented in numpy, because a second copy of the owner rule is how the two
would drift. The snapshot key therefore includes the scope clause and params;
the db path and model are in it too, and a query's dimension is checked before
scoring.

The fingerprint is ``(row count, max rowid, write_generation)``:
``put_embedding`` bumps the generation, inserts change the count, and deletions
or replacements change the count or max rowid. The one thing it cannot see —
recorded, and pinned by a test — is a raw-SQL rewrite that leaves all three
untouched; every write that goes through the store's helper is seen.

With numpy the search is one matrix-vector product; without it the same result
comes from the pure-Python cosine (the cache still saves the blob decode).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..store.embeddings import load_memory_vectors, rank_by_cosine
from ..store.embeddings import write_generation as _write_generation

try:  # optional: the pure-Python path is complete without it
    import numpy as _np
except ImportError:  # pragma: no cover - exercised on any box without numpy
    _np = None

__all__ = [
    "CachedVectors",
    "cached_memory_vectors",
    "reset_cache",
    "search_memory_vectors",
]

#: Bound on snapshots kept per process, so a long-lived worker cannot grow
#: without limit. Insertion-ordered; the oldest is dropped first.
_MAX_ENTRIES = 16

_LOCK = threading.Lock()
_CACHE: "Dict[tuple, CachedVectors]" = {}


@dataclass
class CachedVectors:
    """One immutable snapshot of the in-scope, active memory vectors."""

    fingerprint: Tuple[int, int, int]
    ids: Tuple[str, ...]
    mode: str  # "numpy" | "python"
    _rows: Optional[List[Tuple[float, ...]]] = None
    _matrix: Any = None
    _norms: Any = None
    _index: Optional[Dict[str, int]] = None

    @property
    def count(self) -> int:
        return len(self.ids)

    def vector_of(self, owner_id: str) -> Optional[Tuple[float, ...]]:
        """The vector for one id, or ``None``. Copies at most one row."""
        position = (self._index or {}).get(owner_id)
        if position is None:
            return None
        if self.mode == "numpy":
            return tuple(float(value) for value in self._matrix[position])
        return self._rows[position]


def _db_key(conn) -> str:
    row = conn.execute("PRAGMA database_list").fetchone()
    path = str(row[2]) if row and row[2] else ""
    return path or f"mem:{id(conn)}"


def _fingerprint(conn, model: str) -> Tuple[int, int, int]:
    row = conn.execute(
        "SELECT COUNT(*) AS n, COALESCE(MAX(rowid), 0) AS m FROM embeddings"
        " WHERE owner_type = 'memory' AND model = ?",
        (model,),
    ).fetchone()
    return (int(row["n"]), int(row["m"]), int(_write_generation()))


def _resolve_mode(use_numpy: Optional[bool]) -> str:
    if use_numpy is True and _np is None:
        raise RuntimeError("numpy is not installed; pass use_numpy=False")
    if use_numpy is False:
        return "python"
    return "numpy" if _np is not None else "python"


def _build(conn, *, model: str, scope_clause: str, scope_params: Sequence[object], mode: str, fingerprint):
    loaded = load_memory_vectors(
        conn, model=model, scope_clause=scope_clause, scope_params=scope_params
    )
    loaded.sort(key=lambda pair: pair[0])  # stable tie-break = id ascending
    ids = tuple(owner_id for owner_id, _ in loaded)
    index = {owner_id: position for position, owner_id in enumerate(ids)}
    if mode == "numpy":
        if loaded:
            matrix = _np.asarray([vector for _, vector in loaded], dtype=_np.float32)
            norms = _np.linalg.norm(matrix, axis=1)
        else:
            matrix = _np.zeros((0, 0), dtype=_np.float32)
            norms = _np.zeros((0,), dtype=_np.float32)
        return CachedVectors(fingerprint, ids, mode, _matrix=matrix, _norms=norms, _index=index)
    rows = [tuple(vector) for _, vector in loaded]
    return CachedVectors(fingerprint, ids, mode, _rows=rows, _index=index)


def cached_memory_vectors(
    conn,
    *,
    model: str,
    scope_clause: str,
    scope_params: Sequence[object],
    use_numpy: Optional[bool] = None,
) -> CachedVectors:
    """The snapshot for ``(db, model, scope, mode)``, rebuilding when stale."""
    mode = _resolve_mode(use_numpy)
    key = (_db_key(conn), model, scope_clause, tuple(str(p) for p in scope_params), mode)
    fingerprint = _fingerprint(conn, model)
    with _LOCK:
        entry = _CACHE.get(key)
        if entry is not None and entry.fingerprint == fingerprint:
            return entry
    built = _build(
        conn,
        model=model,
        scope_clause=scope_clause,
        scope_params=scope_params,
        mode=mode,
        fingerprint=fingerprint,
    )
    with _LOCK:
        _CACHE[key] = built
        while len(_CACHE) > _MAX_ENTRIES:
            _CACHE.pop(next(iter(_CACHE)))
    return built


def _search_numpy(entry: CachedVectors, query: Sequence[float], k: int) -> List[Tuple[str, float]]:
    if not entry.ids or entry._matrix.shape[1] != len(query):
        return []
    query_vector = _np.asarray(query, dtype=_np.float32)
    query_norm = float(_np.linalg.norm(query_vector))
    if query_norm == 0.0:
        return []
    denominator = entry._norms * query_norm
    scores = _np.zeros(len(entry.ids), dtype=_np.float32)
    usable = denominator > 0
    if usable.any():
        scores[usable] = (entry._matrix[usable] @ query_vector) / denominator[usable]
    order = _np.argsort(-scores, kind="stable")
    if k < 0:
        return []
    return [(entry.ids[int(index)], float(scores[int(index)])) for index in order[:k]]


def search_memory_vectors(
    conn,
    *,
    model: str,
    scope_clause: str,
    scope_params: Sequence[object],
    query: Sequence[float],
    k: int,
    use_numpy: Optional[bool] = None,
) -> List[Tuple[str, float]]:
    """Top-``k`` in-scope memories by cosine, from the cached snapshot."""
    entry = cached_memory_vectors(
        conn,
        model=model,
        scope_clause=scope_clause,
        scope_params=scope_params,
        use_numpy=use_numpy,
    )
    if entry.mode == "numpy":
        return _search_numpy(entry, query, k)
    rows = list(zip(entry.ids, entry._rows or []))
    return rank_by_cosine(query, rows, k=k)


def reset_cache() -> None:
    """Drop every snapshot. For tests and for a caller that knows it changed data."""
    with _LOCK:
        _CACHE.clear()
