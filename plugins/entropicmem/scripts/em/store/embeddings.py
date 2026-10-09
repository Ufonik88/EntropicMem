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
    "EMBEDDING_MODEL_KEY",
    "VECTOR_MIN_COVERAGE",
    "count_active_memories",
    "count_episodes",
    "cosine",
    "load_memory_vectors",
    "load_vectors",
    "missing_memory_count",
    "pack_vector",
    "pending_embed_texts",
    "put_embedding",
    "rank_by_cosine",
    "set_stored_model",
    "stored_model",
    "unpack_vector",
    "write_generation",
]

#: The ``meta`` key naming the model the store is currently embedding with.
EMBEDDING_MODEL_KEY = "embedding_model"

#: §3.6: the vector generator runs only when coverage is at least this.
VECTOR_MIN_COVERAGE = 0.5

#: Bumped by every ``put_embedding``. The cache's fingerprint includes it, so an
#: in-place REPLACE that leaves count and max rowid unchanged is still seen.
_WRITE_GENERATION = 0


def write_generation() -> int:
    """How many times ``put_embedding`` has written in this process."""
    return _WRITE_GENERATION


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
    global _WRITE_GENERATION
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
    _WRITE_GENERATION += 1


def load_vectors(
    conn: sqlite3.Connection,
    *,
    owner_type: str = "memory",
    model: str,
    scope_clause: str,
    scope_params: Sequence[object],
    width: Optional[int] = None,
) -> list[tuple[str, tuple[float, ...]]]:
    """In-scope, live vectors for ``model``, of ``width`` when given.

    **Every read verifies the vector belongs to the text it says it does**:
    a memory row is only returned when its stored ``content_hash`` equals the
    memory's current one (an empty stored hash means "unverified" — the
    pre-EM-303 rows and test fixtures — and is kept for back-compat); an
    episode row is only returned when its stored stamp equals the episode's
    current ``updated_at``. An out-of-date vector is *excluded*, never mixed:
    coverage drops, the generator/read stops trusting it, and the queued
    re-embed job is what brings it back.

    ``width`` filters to vectors of the query's dimension, so a same-name
    model whose artifact changed dimension cannot crash the matrix path or
    silently pad/truncate. Rows of another width stay in the store untouched.

    One statement. A corrupt blob is omitted. The scope clause is the one
    ``scope_sql`` already built; this function does not invent a second rule.
    """
    if owner_type == "episode":
        sql = (
            "SELECT emb.owner_id AS owner_id, emb.vector AS vector"
            " FROM embeddings emb JOIN episodes e ON e.id = emb.owner_id"
            " WHERE emb.owner_type = 'episode' AND emb.model = ?"
            "   AND (emb.content_hash = '' OR emb.content_hash = e.updated_at)"
            "   AND " + scope_clause
        )
    else:
        sql = (
            "SELECT emb.owner_id AS owner_id, emb.vector AS vector"
            " FROM embeddings emb JOIN memories m ON m.id = emb.owner_id"
            " WHERE emb.owner_type = 'memory' AND emb.model = ?"
            "   AND m.status = 'active'"
            "   AND (emb.content_hash = '' OR emb.content_hash = m.content_hash)"
            "   AND " + scope_clause
        )
    rows = conn.execute(sql, (model, *scope_params)).fetchall()
    loaded: list[tuple[str, tuple[float, ...]]] = []
    for row in rows:
        vector = unpack_vector(row["vector"])
        if vector is None:
            continue
        if width is not None and len(vector) != width:
            continue
        loaded.append((str(row["owner_id"]), vector))
    return loaded


def load_memory_vectors(
    conn: sqlite3.Connection,
    *,
    model: str,
    scope_clause: str,
    scope_params: Sequence[object],
    width: Optional[int] = None,
) -> list[tuple[str, tuple[float, ...]]]:
    """The memory half of :func:`load_vectors` (kept as the long-standing name)."""
    return load_vectors(
        conn,
        owner_type="memory",
        model=model,
        scope_clause=scope_clause,
        scope_params=scope_params,
        width=width,
    )


def count_episodes(
    conn: sqlite3.Connection,
    *,
    scope_clause: str,
    scope_params: Sequence[object],
) -> int:
    """Episodes in the same scope the vector load uses. The episode denominator."""
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM episodes e WHERE " + scope_clause,
        tuple(scope_params),
    ).fetchone()
    if row is None:
        return 0
    return int(row["n"])


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


# --- model identity and the backfill worklist ------------------------------


def stored_model(conn: sqlite3.Connection) -> str:
    """The model recorded in ``meta.embedding_model``, or ``""``."""
    row = conn.execute("SELECT value FROM meta WHERE key=?", (EMBEDDING_MODEL_KEY,)).fetchone()
    return str(row["value"]) if row is not None and row["value"] else ""


def set_stored_model(conn: sqlite3.Connection, model: str) -> None:
    """Record the model a completed backfill has just filled the store for."""
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?)"
        " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (EMBEDDING_MODEL_KEY, str(model)),
    )


def pending_embed_texts(
    conn: sqlite3.Connection, *, model: str, limit: int = 64
) -> list[tuple[str, str, str, str, str]]:
    """Rows with **no** embedding for ``model``: ``(owner_type, id, a, b, hash)``.

    Memories yield ``(summary, content, content_hash)``; episodes
    ``(title, summary, updated_at)`` — the caller shapes the text per type and
    stores the hash/stamp on the vector. Rows with no text at all are skipped
    rather than spending a batch on an empty string. A row that carries a
    vector for a *different* model is still pending for this one — that is the
    model-switch case; a row whose vector is stale (hash/stamp mismatch) is
    **not** pending here, because it has a row; the fix for that is a re-embed
    on the write path (the update enqueues one).
    """
    if not model:
        return []
    rows = conn.execute(
        "SELECT 'memory' AS owner_type, m.id AS id, m.summary AS a, m.content AS b,"
        "       m.content_hash AS hash"
        " FROM memories m"
        " LEFT JOIN embeddings e ON e.owner_type = 'memory'"
        "   AND e.owner_id = m.id AND e.model = ?"
        " WHERE m.status = 'active' AND e.owner_id IS NULL"
        "   AND (TRIM(COALESCE(m.summary, '')) <> '' OR TRIM(COALESCE(m.content, '')) <> '')"
        " UNION ALL"
        " SELECT 'episode' AS owner_type, ep.id AS id, ep.title AS a, ep.summary AS b,"
        "       ep.updated_at AS hash"
        " FROM episodes ep"
        " LEFT JOIN embeddings e ON e.owner_type = 'episode'"
        "   AND e.owner_id = ep.id AND e.model = ?"
        " WHERE e.owner_id IS NULL"
        "   AND (TRIM(COALESCE(ep.title, '')) <> '' OR TRIM(COALESCE(ep.summary, '')) <> '')"
        " ORDER BY owner_type, id LIMIT ?",
        (model, model, int(limit)),
    ).fetchall()
    return [
        (
            str(row["owner_type"]),
            str(row["id"]),
            str(row["a"] or ""),
            str(row["b"] or ""),
            str(row["hash"] or ""),
        )
        for row in rows
    ]


def missing_memory_count(conn: sqlite3.Connection, *, model: str) -> int:
    """How many active memories still need a vector for ``model`` (episodes not counted)."""
    if not model:
        return 0
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM memories m"
        " LEFT JOIN embeddings e ON e.owner_type = 'memory'"
        "   AND e.owner_id = m.id AND e.model = ?"
        " WHERE m.status = 'active' AND e.owner_id IS NULL",
        (model,),
    ).fetchone()
    if row is None:
        return 0
    return int(row["n"])
