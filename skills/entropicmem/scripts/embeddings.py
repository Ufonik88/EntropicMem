"""
embeddings.py — Optional vector embedding pipeline for EntropicMem.

Provides:
  - Embedding generation via sentence-transformers (optional dep)
  - SQLite storage of 384-dim vectors in an `embeddings` table
  - Cosine similarity search over stored embeddings
  - Hybrid fusion: FTS5 BM25 + vector similarity with configurable weights

Graceful degradation: if sentence-transformers is not installed, all functions
return None/empty and the engine falls back to FTS5-only search.

Requires: `pip install entropicmem[semantic]` (sentence-transformers + numpy)
"""

import sqlite3
from pathlib import Path
from typing import List, Optional, Tuple

# ── optional dependency detection ───────────────────────────────────────────

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False

try:
    from sentence_transformers import SentenceTransformer
    EMBEDDER_AVAILABLE = True
except ImportError:
    EMBEDDER_AVAILABLE = False

# ── schema ──────────────────────────────────────────────────────────────────

EMBEDDINGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS embeddings (
    fact_id TEXT PRIMARY KEY,
    vector BLOB NOT NULL,
    model TEXT DEFAULT 'all-MiniLM-L6-v2',
    dim INTEGER DEFAULT 384,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (fact_id) REFERENCES facts(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_embeddings_model ON embeddings(model);
"""

# ── embedder ────────────────────────────────────────────────────────────────

_MODEL_NAME = "all-MiniLM-L6-v2"
_model_instance = None


def get_embedder():
    """Lazy-load the sentence-transformer model. Returns None if unavailable."""
    global _model_instance
    if not EMBEDDER_AVAILABLE:
        return None
    if _model_instance is None:
        _model_instance = SentenceTransformer(_MODEL_NAME)
    return _model_instance


def embed_text(text: str) -> Optional[List[float]]:
    """Generate a 384-dim embedding for text. Returns None if deps missing."""
    model = get_embedder()
    if model is None:
        return None
    vec = model.encode(text, normalize_embeddings=True)
    return vec.tolist()


def embed_batch(texts: List[str]) -> Optional[List[List[float]]]:
    """Batch-embed multiple texts. Returns None if deps missing."""
    model = get_embedder()
    if model is None:
        return None
    vecs = model.encode(texts, normalize_embeddings=True, batch_size=32)
    return [v.tolist() for v in vecs]


# ── storage ─────────────────────────────────────────────────────────────────

def _vec_to_blob(vec: List[float]) -> bytes:
    """Serialize a float vector to a compact binary blob."""
    if not NUMPY_AVAILABLE:
        import struct
        return struct.pack(f"{len(vec)}f", *vec)
    return np.array(vec, dtype=np.float32).tobytes()


def _blob_to_vec(blob: bytes) -> List[float]:
    """Deserialize a binary blob back to a float vector."""
    if not NUMPY_AVAILABLE:
        import struct
        n = len(blob) // 4
        return list(struct.unpack(f"{n}f", blob))
    return np.frombuffer(blob, dtype=np.float32).tolist()


def init_embeddings_schema(db: sqlite3.Connection) -> None:
    """Create the embeddings table if it doesn't exist."""
    db.executescript(EMBEDDINGS_SCHEMA)
    db.commit()


def store_embedding(db: sqlite3.Connection, fact_id: str, vector: List[float]) -> None:
    """Store or update an embedding for a fact."""
    blob = _vec_to_blob(vector)
    db.execute(
        """INSERT OR REPLACE INTO embeddings (fact_id, vector, model, dim)
           VALUES (?, ?, ?, ?)""",
        (fact_id, blob, _MODEL_NAME, len(vector)),
    )
    db.commit()


def delete_embedding(db: sqlite3.Connection, fact_id: str) -> None:
    """Remove an embedding when a fact is deleted."""
    db.execute("DELETE FROM embeddings WHERE fact_id = ?", (fact_id,))
    db.commit()


def get_embedding(db: sqlite3.Connection, fact_id: str) -> Optional[List[float]]:
    """Retrieve a stored embedding."""
    row = db.execute(
        "SELECT vector FROM embeddings WHERE fact_id = ?", (fact_id,)
    ).fetchone()
    if row is None:
        return None
    return _blob_to_vec(row[0])


def embedding_coverage(db: sqlite3.Connection) -> dict:
    """Report what fraction of facts have embeddings."""
    total = db.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
    embedded = db.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
    return {
        "total_facts": total,
        "embedded_facts": embedded,
        "coverage_pct": round(embedded / total * 100, 1) if total > 0 else 0.0,
        "model": _MODEL_NAME,
        "available": EMBEDDER_AVAILABLE,
    }


# ── similarity search ───────────────────────────────────────────────────────

def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Cosine similarity between two vectors."""
    if NUMPY_AVAILABLE:
        va, vb = np.array(a), np.array(b)
        denom = np.linalg.norm(va) * np.linalg.norm(vb)
        if denom == 0:
            return 0.0
        return float(np.dot(va, vb) / denom)
    # Pure-Python fallback
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def vector_search(
    db: sqlite3.Connection,
    query_vec: List[float],
    top_k: int = 10,
    domain: Optional[str] = None,
) -> List[Tuple[str, float]]:
    """
    Brute-force cosine similarity search over all stored embeddings.

    Returns list of (fact_id, similarity_score) sorted by score descending.
    For <10K facts this is fast enough; for larger sets, consider HNSW.
    """
    if domain:
        rows = db.execute(
            """SELECT e.fact_id, e.vector FROM embeddings e
               JOIN facts f ON e.fact_id = f.id
               WHERE f.domain = ?""",
            (domain,),
        ).fetchall()
    else:
        rows = db.execute("SELECT fact_id, vector FROM embeddings").fetchall()

    scored = []
    for row in rows:
        vec = _blob_to_vec(row[1])
        sim = cosine_similarity(query_vec, vec)
        scored.append((row[0], sim))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]


# ── hybrid fusion ───────────────────────────────────────────────────────────

def hybrid_rank(
    fts_results: List[Tuple[str, float]],
    vec_results: List[Tuple[str, float]],
    fts_weight: float = 0.6,
    vec_weight: float = 0.4,
) -> List[Tuple[str, float]]:
    """
    Fuse FTS5 BM25 scores and vector similarity scores.

    Both input lists are (fact_id, score) tuples, already normalized to 0-1.
    Returns fused (fact_id, combined_score) sorted descending.
    """
    scores: dict = {}

    for fid, score in fts_results:
        scores[fid] = scores.get(fid, 0.0) + fts_weight * score

    for fid, score in vec_results:
        scores[fid] = scores.get(fid, 0.0) + vec_weight * score

    fused = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return fused
