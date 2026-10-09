"""EM-303's query-embedding seam in the v3 eval adapter.

The frozen `ci`/`hard` suites pass `disable_embeddings=True` and stay lexical,
so their numbers cannot move. A custom suite — and these tests — pass `False`
and get the vector path: documents are embedded at `load`, the query is
embedded in `_run`, and the gate's cosine condition becomes reachable.

The backend is a deterministic fake, so nothing here downloads a model and CI
stays offline.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from evals.adapters import engine_v3  # noqa: E402
from evals.dataset import Memory, NoiseSpec, Scenario, Turn  # noqa: E402
from evals.runner import parse_injected_ids  # noqa: E402


def test_cross_mode_detection_is_exact_and_treats_unlabelled_as_unknown():
    from evals.runner import comparison_is_cross_mode

    assert comparison_is_cross_mode("lexical", "lexical") is False
    assert comparison_is_cross_mode("vector", "vector") is False
    assert comparison_is_cross_mode("vector", "lexical") is True
    assert comparison_is_cross_mode("VECTOR", "lexical") is True
    assert comparison_is_cross_mode("", None) is False  # both unknown: pre-label era
    assert comparison_is_cross_mode("lexical", None) is True  # a label vs no label

from em.embeddings.backends import NoneBackend  # noqa: E402
from em.embeddings.service import EmbeddingService  # noqa: E402

#: Named so the gate's per-model cosine threshold exists (§3.6 names it).
MODEL = "all-MiniLM-L6-v2"


class FakeBackend:
    """Aligned for anything about animals; orthogonal for everything else."""

    name = "fake"
    dim = 4
    default_model = MODEL

    def available(self) -> bool:
        return True

    def warm(self) -> None:
        pass

    def embed(self, texts):
        return [
            [1.0, 0.0, 0.0, 0.0]
            if any(word in t for word in ("alpacas", "animals", "raise"))
            else [0.0, 1.0, 0.0, 0.0]
            for t in texts
        ]


def _service(backend=None):
    return EmbeddingService(
        ":memory:", backend=backend or FakeBackend(), model=MODEL
    )


def _scenario(**kw) -> Scenario:
    return Scenario(
        scenario_id="adapter_v3_vectors_1",
        category="ageing",
        memories=[
            Memory(
                content="Acme keeps alpacas at the northern site",
                age_days=40,
                importance=0.8,
                domain="Knowledge",
                kind="fact",
            )
        ],
        noise=NoiseSpec(count=kw.get("noise", 0), seed=3),
        turns=[
            Turn(
                query="what animals do they raise?",
                expect_ids=["$0"],
                must_not=["$noise"],
            )
        ],
    )


@pytest.fixture()
def adapter():
    a = engine_v3.EngineV3Adapter(disable_embeddings=False, embedding_service=_service())
    yield a
    a.shutdown()


def _ref(adapter, scenario):
    handle = adapter.load(scenario)
    return handle, handle.ref_ids["$0"]


def test_a_paraphrase_with_no_shared_words_is_found_when_vectors_are_on(adapter):
    handle, memory_id = _ref(adapter, _scenario())
    try:
        block = adapter.prefetch(handle, "what animals do they raise?")
        assert parse_injected_ids(block) == [memory_id]
        assert block.startswith("- [")
        hits = adapter.search(handle, "what animals do they raise?", k=5)
        assert hits and hits[0].id == memory_id
    finally:
        adapter.finish(handle)


def test_the_frozen_suites_force_embeddings_off_and_still_abstain():
    a = engine_v3.EngineV3Adapter(disable_embeddings=True, embedding_service=_service())
    try:
        handle = a.load(_scenario())
        assert a.prefetch(handle, "what animals do they raise?") == ""
        assert parse_injected_ids("") == []
        a.finish(handle)
    finally:
        a.shutdown()


def test_a_none_backend_changes_nothing_even_when_embeddings_are_allowed():
    a = engine_v3.EngineV3Adapter(
        disable_embeddings=False,
        embedding_service=EmbeddingService(":memory:", backend=NoneBackend()),
    )
    try:
        handle = a.load(_scenario(noise=5))
        assert a.prefetch(handle, "what animals do they raise?") == ""
        # The lexical path still ranks: search without the gate returns order.
        assert a.search(handle, "what animals do they raise?", k=5)
        a.finish(handle)
    finally:
        a.shutdown()


def test_noise_with_orthogonal_vectors_does_not_leak_into_the_block(adapter):
    handle, memory_id = _ref(adapter, _scenario(noise=8))
    try:
        block = adapter.prefetch(handle, "what animals do they raise?")
        assert parse_injected_ids(block) == [memory_id]
    finally:
        adapter.finish(handle)


def test_the_adapter_label_says_what_will_actually_run():
    assert engine_v3.EngineV3Adapter(disable_embeddings=True).retrieval_mode == "lexical"
    assert (
        engine_v3.EngineV3Adapter(
            disable_embeddings=False, embedding_service=_service()
        ).retrieval_mode
        == "vector"
    )
    assert (
        engine_v3.EngineV3Adapter(
            disable_embeddings=False,
            embedding_service=EmbeddingService(":memory:", backend=NoneBackend()),
        ).retrieval_mode
        == "lexical"
    )
