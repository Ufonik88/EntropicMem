"""The vector cache: decode blobs once, search the matrix per query — EM-303.

The card's R10 fix: "vector search: numpy matrix cache per ``(db path, model,
write_generation_embeddings)``; do not re-read blobs per query".

What is cached is a **snapshot** of the rows a scope can see, loaded through
the same ``scope_sql`` clause the generators use — §3.5 stays in SQL, it is not
reimplemented in numpy, because a second copy of the owner rule is how the two
would drift. The snapshot key is ``(db, owner_type, model, scope clause,
scope params, mode, width)``: a query's dimension is checked before scoring,
so a same-name model whose artifact changed width can never be padded,
truncated or mixed.

The fingerprint is ``(row count, max rowid, write_generation)``:
``put_embedding`` bumps the generation, inserts change the count, and deletions
or replacements change the count or max rowid. The one thing it cannot see —
recorded, and pinned by a test — is a raw-SQL rewrite that leaves all three
untouched; every write that goes through the store's helper is seen.

With numpy the search is one matrix-vector product; without it the same result
comes from the pure-Python cosine (the cache still saves the blob decode). A
snapshot whose rows disagree about their width falls back to the Python path
rather than building a ragged array.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..store.embeddings import load_vectors, rank_by_cosine
from ..store.embeddings import write_generation as _write_generation

try:  # optional: the pure-Python path is complete without it
    import numpy as _np
except ImportError:  # pragma: no cover - exercised on any box without numpy
    _np = None

__all__ = [
    "CachedVectors",
    "cached_memory_vectors",
    "cached_vectors",
    "reset_cache",
    "search_memory_vectors",
    "search_vectors",
]

#: Bound on snapshots kept per process, so a long-lived worker cannot grow
#: without limit. Insertion-ordered; the oldest is dropped first.
_MAX_ENTRIES = 16

_LOCK = threading.Lock()
_CACHE: "Dict[tuple, CachedVectors]" = {}


@dataclass
class CachedVectors:
    """One immutable snapshot of the in-scope vectors for one owner type."""

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


def _fingerprint(conn, owner_type: str, model: str) -> Tuple[int, int, int]:
    row = conn.execute(
        "SELECT COUNT(*) AS n, COALESCE(MAX(rowid), 0) AS m FROM embeddings"
        " WHERE owner_type = ? AND model = ?",
        (owner_type, model),
    ).fetchone()
    return (int(row["n"]), int(row["m"]), int(_write_generation()))


def _resolve_mode(use_numpy: Optional[bool]) -> str:
    if use_numpy is True and _np is None:
        raise RuntimeError("numpy is not installed; pass use_numpy=False")
    if use_numpy is False:
        return "python"
    return "numpy" if _np is not None else "python"


def _build(conn, *, owner_type, model, scope_clause, scope_params, mode, width, fingerprint):
    loaded = load_vectors(
        conn,
        owner_type=owner_type,
        model=model,
        scope_clause=scope_clause,
        scope_params=scope_params,
        width=width,
    )
    loaded.sort(key=lambda pair: pair[0])  # stable tie-break = id ascending
    ids = tuple(owner_id for owner_id, _ in loaded)
    index = {owner_id: position for position, owner_id in enumerate(ids)}
    if mode == "numpy":
        widths = {len(vector) for _, vector in loaded}
        if len(widths) > 1:
            mode = "python"  # ragged: a matrix would be wrong or raise
        elif loaded:
            matrix = _np.asarray([vector for _, vector in loaded], dtype=_np.float32)
            norms = _np.linalg.norm(matrix, axis=1)
            return CachedVectors(fingerprint, ids, mode, _matrix=matrix, _norms=norms, _index=index)
        else:
            matrix = _np.zeros((0, 0), dtype=_np.float32)
            norms = _np.zeros((0,), dtype=_np.float32)
            return CachedVectors(fingerprint, ids, mode, _matrix=matrix, _norms=norms, _index=index)
    rows = [tuple(vector) for _, vector in loaded]
    return CachedVectors(fingerprint, ids, mode, _rows=rows, _index=index)


def cached_vectors(
    conn,
    *,
    owner_type: str = "memory",
    model: str,
    scope_clause: str,
    scope_params: Sequence[object],
    use_numpy: Optional[bool] = None,
    width: Optional[int] = None,
) -> CachedVectors:
    """The snapshot for ``(db, owner_type, model, scope, mode, width)``."""
    mode = _resolve_mode(use_numpy)
    key = (
        _db_key(conn),
        owner_type,
        model,
        scope_clause,
        tuple(str(p) for p in scope_params),
        mode,
        width,
    )
    fingerprint = _fingerprint(conn, owner_type, model)
    with _LOCK:
        entry = _CACHE.get(key)
        if entry is not None and entry.fingerprint == fingerprint:
            return entry
    built = _build(
        conn,
        owner_type=owner_type,
        model=model,
        scope_clause=scope_clause,
        scope_params=scope_params,
        mode=mode,
        width=width,
        fingerprint=fingerprint,
    )
    with _LOCK:
        _CACHE[key] = built
        while len(_CACHE) > _MAX_ENTRIES:
            _CACHE.pop(next(iter(_CACHE)))
    return built


def cached_memory_vectors(
    conn,
    *,
    model: str,
    scope_clause: str,
    scope_params: Sequence[object],
    use_numpy: Optional[bool] = None,
    width: Optional[int] = None,
) -> CachedVectors:
    """The memory half, under the long-standing name."""
    return cached_vectors(
        conn,
        owner_type="memory",
        model=model,
        scope_clause=scope_clause,
        scope_params=scope_params,
        use_numpy=use_numpy,
        width=width,
    )


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


def search_vectors(
    conn,
    *,
    owner_type: str = "memory",
    model: str,
    scope_clause: str,
    scope_params: Sequence[object],
    query: Sequence[float],
    k: int,
    use_numpy: Optional[bool] = None,
) -> List[Tuple[str, float]]:
    """Top-``k`` in-scope vectors of ``owner_type`` by cosine, from the snapshot."""
    entry = cached_vectors(
        conn,
        owner_type=owner_type,
        model=model,
        scope_clause=scope_clause,
        scope_params=scope_params,
        use_numpy=use_numpy,
        width=len(query),
    )
    if entry.mode == "numpy":
        return _search_numpy(entry, query, k)
    rows = list(zip(entry.ids, entry._rows or []))
    return rank_by_cosine(query, rows, k=k)


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
    """The memory half, under the long-standing name."""
    return search_vectors(
        conn,
        owner_type="memory",
        model=model,
        scope_clause=scope_clause,
        scope_params=scope_params,
        query=query,
        k=k,
        use_numpy=use_numpy,
    )


def reset_cache() -> None:
    """Drop every snapshot. For tests and for a caller that knows it changed data."""
    with _LOCK:
        _CACHE.clear()
