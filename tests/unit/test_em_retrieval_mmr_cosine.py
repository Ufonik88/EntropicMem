"""EM-303 — MMR's embedding path: cosine when vectors are there, Jaccard otherwise.

§3.6's diversity step: "MMR with λ = 0.7 using embedding cosine (fallback: token
Jaccard) over the top 20." The pipeline supplies a pairwise similarity when the
caller gave it a query vector and a model; a pair with no stored vector on
either side falls back to token Jaccard. A negative cosine is clamped to 0 —
redundancy is a penalty, not a bonus. Nothing embeds.

The end-to-end test uses the two orders that disagree: three candidates whose
token sets make C look more diverse than B (Jaccard), while the stored vectors
make B maximally different from A and C identical to it (cosine).

Invented data only: Acme.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from em.clock import to_iso  # noqa: E402
from em.retrieval.candidates import OWNER_TYPE_MEMORY  # noqa: E402
from em.retrieval.diversity import mmr  # noqa: E402
from em.retrieval.fusion import Ranking  # noqa: E402
from em.retrieval.pipeline import _pairwise_similarity, retrieve  # noqa: E402
from em.store.db import Store  # noqa: E402
from em.store.embeddings import put_embedding  # noqa: E402
from em.store.memories import MemoryStore  # noqa: E402
from em.store.migrations import migrate  # noqa: E402
from em.store.types import MemoryDraft, Scope  # noqa: E402

OWNER = Scope(profile="default")
NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
MODEL = "all-MiniLM-L6-v2"

TEXTS = {"A": "staging port", "B": "port staging", "C": "staging port acme"}


def key(name: str):
    return (OWNER_TYPE_MEMORY, name)


def ranking(name: str, score: float) -> Ranking:
    return Ranking(
        owner_type=OWNER_TYPE_MEMORY,
        owner_id=name,
        score=score,
        rrf=0.0,
        rrf_n=0.0,
        recency=0.0,
        feedback=0.0,
        signals=(),
        why=(),
    )


def _texts() -> dict:
    return {key(name): text for name, text in TEXTS.items()}


def _items():
    # Ranked best-first; A is chosen first by MMR either way.
    return [ranking("A", 0.9), ranking("B", 0.85), ranking("C", 0.8)]


#: What the vectors below say: A~C identical, A~B orthogonal.
_COSINE = {
    (key("A"), key("B")): 0.0,
    (key("B"), key("A")): 0.0,
    (key("A"), key("C")): 1.0,
    (key("C"), key("A")): 1.0,
    (key("B"), key("C")): 0.0,
    (key("C"), key("B")): 0.0,
    (key("A"), key("A")): 1.0,
    (key("B"), key("B")): 1.0,
    (key("C"), key("C")): 1.0,
}


def test_mmr_defaults_to_jaccard_and_a_callable_overrides_it():
    """Jaccard sees B as a duplicate of A; the vectors say C is."""
    lexical = mmr(_items(), texts=_texts())
    assert [r.owner_id for r in lexical] == ["A", "C", "B"]

    seen: list = []

    def similarity(left, right):
        seen.append((left, right))
        return _COSINE[(left, right)]

    embedded = mmr(_items(), texts=_texts(), similarities=similarity)
    assert [r.owner_id for r in embedded] == ["A", "B", "C"]
    # The callable is asked about the candidate against the chosen key.
    assert (key("B"), key("A")) in seen
    assert (key("C"), key("B")) in seen


def test_mmr_without_a_callable_is_unchanged():
    assert [r.owner_id for r in mmr(_items(), texts=_texts(), similarities=None)] == [
        "A",
        "C",
        "B",
    ]


def test_pairwise_similarity_uses_cosine_caps_at_zero_and_falls_back():
    """The two branches, plus the clamp: a negative cosine is no bonus."""
    vectors = {
        key("A"): (1.0, 0.0),
        key("C"): (1.0, 0.0),
        key("D"): (-1.0, 0.0),
    }
    sim = _pairwise_similarity(vectors, _texts())
    assert sim(key("A"), key("C")) == pytest.approx(1.0)
    assert sim(key("A"), key("D")) == pytest.approx(0.0)
    # B has no vector, so its pairs are token Jaccard.
    assert sim(key("B"), key("C")) == pytest.approx(2 / 3)
    assert sim(key("A"), key("B")) == pytest.approx(1.0)


@pytest.fixture
def store(tmp_path):
    saved = Store(str(tmp_path / "memory.db"))
    with saved.writer() as conn:
        migrate(conn)
    yield saved
    saved.close()


def _seed(store):
    vectors = {"A": (1.0, 0.0), "B": (0.0, 1.0), "C": (1.0, 0.0)}
    ids = {}
    with store.transaction() as conn:
        memories = MemoryStore(conn)
        for name, text in TEXTS.items():
            result = memories.add(
                MemoryDraft(content=text, source="agent"),
                scope=OWNER,
                actor="tester",
            )
            assert result.ok, result
            ids[name] = result.id
            put_embedding(
                conn,
                owner_id=result.id,
                model=MODEL,
                vector=vectors[name],
                created_at=to_iso(NOW),
            )
    return ids


def test_the_pipeline_uses_cosine_for_mmr_when_it_has_vectors(store):
    ids = _seed(store)
    conn = store.reader()
    lexical = retrieve(conn, scope=OWNER, query="staging port", with_gate=True, now=NOW)
    assert [r.owner_id for r in lexical.rankings] == [ids["A"], ids["C"], ids["B"]]

    embedded = retrieve(
        conn,
        scope=OWNER,
        query="staging port",
        with_gate=True,
        now=NOW,
        query_vector=(1.0, 0.0),
        embedding_model=MODEL,
    )
    assert [r.owner_id for r in embedded.rankings] == [ids["A"], ids["B"], ids["C"]]
