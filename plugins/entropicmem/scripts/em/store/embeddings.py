"""Stored embedding vectors — the read half of EM-303.

The ``embeddings`` table already exists (migration 0002). This module loads
the rows a search is allowed to see, in **one** query, and turns the blob
back into floats.

The blob is native-endian float32, the same layout v2 wrote
(``struct.pack(f"{n}f", ...)`` and numpy's ``float32.tobytes()`` on the
machines this project runs). A blob that is not a whole number of floats is
skipped, not raised: one corrupt row must not take down a prefetch.

**Not in this module, on purpose:**

* no embedding backend and no ``embed()`` call — a query path that embeds is
  the card's forbidden prefetch-thread call;
* no numpy matrix cache and no 50k search — that is the rest of EM-303;
* no model-switch backfill.

Stdlib only (plan §3.2).
"""

from __future__ import annotations

import sqlite3
import struct
from typing import Optional, Sequence

__all__ = [
    "VECTOR_MIN_COVERAGE",
    "count_active_memories",
    "cosine",
    "load_memory_vectors",
    "pack_vector",
    "put_embedding",
    "rank_by_cosine",
    "unpack_vector",
]

#: §3.6: the vector generator runs only when coverage is at least this.
VECTOR_MIN_COVERAGE = 0.5


def cosine(left: Sequence[float], right: Sequence[float]) -> float:
    """Cosine similarity in ``[-1, 1]``. A zero or mismatched vector is 0.

    Not a normalised dot-product that pretends every stored vector is unit
    length: v2's embedder normalises, a hand-written test vector might not,
    and those must not compare equal by accident.
    """
    if not left or len(left) != len(right):
        return 0.0
    dot = 0.0
    left_norm = 0.0
    right_norm = 0.0
    for a, b in zip(left, right):
        dot += a * b
        left_norm += a * a
        right_norm += b * b
    if left_norm <= 0.0 or right_norm <= 0.0:
        return 0.0
    return dot / ((left_norm ** 0.5) * (right_norm ** 0.5))


def rank_by_cosine(
    query: Sequence[float],
    rows: Sequence[tuple[str, Sequence[float]]],
    *,
    k: int,
) -> list[tuple[str, float]]:
    """Highest cosine first. Ties break on ``owner_id`` ascending. ``k`` caps."""
    scored = [(owner_id, cosine(query, vector)) for owner_id, vector in rows if len(vector) == len(query)]
    scored.sort(key=lambda item: (-item[1], item[0]))
    if k < 0:
        return []
    return scored[:k]


def pack_vector(values: Sequence[float]) -> bytes:
    """Native-endian float32 blob. Empty is empty."""
    if not values:
        return b""
    return struct.pack(f"{len(values)}f", *[float(value) for value in values])


def unpack_vector(blob: object) -> Optional[tuple[float, ...]]:
    """Floats, or ``None`` when the blob is not a float32 sequence."""
    if not isinstance(blob, (bytes, bytearray)):
        return None
    if len(blob) == 0 or len(blob) % 4 != 0:
        return None
    count = len(blob) // 4
    try:
        return struct.unpack(f"{count}f", blob)
    except struct.error:
        return None


def put_embedding(
    conn: sqlite3.Connection,
    *,
    owner_id: str,
    model: str,
    vector: Sequence[float],
    owner_type: str = "memory",
    content_hash: str = "",
    created_at: str,
) -> None:
    """Insert or replace one vector. Tests and a future embed job share this."""
    conn.execute(
        "INSERT OR REPLACE INTO embeddings (owner_type, owner_id, model, dim,"
        " vector, content_hash, created_at) VALUES (?,?,?,?,?,?,?)",
        (
            owner_type,
            owner_id,
            model,
            len(vector),
            pack_vector(vector),
            content_hash,
            created_at,
        ),
    )


def load_memory_vectors(
    conn: sqlite3.Connection,
    *,
    model: str,
    scope_clause: str,
    scope_params: Sequence[object],
) -> list[tuple[str, tuple[float, ...]]]:
    """In-scope active memories that have a usable vector for ``model``.

    One statement. A corrupt blob is omitted. The scope clause is the one
    ``scope_sql`` already built; this function does not invent a second rule.
    """
    rows = conn.execute(
        "SELECT e.owner_id AS owner_id, e.vector AS vector FROM embeddings e "
        "JOIN memories m ON m.id = e.owner_id "
        "WHERE e.owner_type = 'memory' AND e.model = ? "
        "AND m.status = 'active' AND " + scope_clause,
        (model, *scope_params),
    ).fetchall()
    loaded: list[tuple[str, tuple[float, ...]]] = []
    for row in rows:
        vector = unpack_vector(row["vector"])
        if vector is None:
            continue
        loaded.append((str(row["owner_id"]), vector))
    return loaded


def count_active_memories(
    conn: sqlite3.Connection,
    *,
    scope_clause: str,
    scope_params: Sequence[object],
) -> int:
    """Active memories in the same scope the vector load uses. The denominator."""
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM memories m WHERE m.status = 'active' AND " + scope_clause,
        tuple(scope_params),
    ).fetchone()
    if row is None:
        return 0
    return int(row["n"])
