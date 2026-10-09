"""EM-303 — embedding backends, selection, batching, and text shaping.

The optional stacks (fastembed, sentence-transformers) are never imported at
module import: `em` is stdlib-only, and a missing package must degrade to
`none`, never to an error. Selection is `auto` → first available in the card's
order, or an explicit name with the same fallback.

No embedding call runs on the agent/prefetch thread here — this module only
provides the backends; the job handlers (tested in `test_em_embed_jobs.py`)
are what call them, off the write path.

Invented data only: Acme.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from em.embeddings import backends  # noqa: E402
from em.embeddings.backends import (  # noqa: E402
    FastEmbedBackend,
    NoneBackend,
    OpenAICompatBackend,
    SentenceTransformersBackend,
    select_backend,
)
from em.embeddings.service import (  # noqa: E402
    EmbeddingService,
    episode_text,
    memory_text,
)


class FakeBackend:
    """A tiny deterministic backend for the tests that need one."""

    name = "fake"
    dim = 4

    def __init__(self):
        self.warm_calls = 0
        self.embed_calls: list[int] = []
        self.available_value = True

    def available(self) -> bool:
        return self.available_value

    def warm(self) -> None:
        self.warm_calls += 1

    def embed(self, texts):
        self.embed_calls.append(len(texts))
        return [[float(len(t) % 7), 1.0, 0.0, 0.0] for t in texts]


# --- selection -------------------------------------------------------------


def _specs(*present: str):
    def find(name: str):
        return object() if name in present else None

    return find


def test_auto_selects_the_first_available_in_the_cards_order(monkeypatch):
    monkeypatch.setattr(backends, "_module_available", _specs("fastembed", "sentence_transformers"))
    assert select_backend("auto", env={}).name == "fastembed"
    monkeypatch.setattr(backends, "_module_available", _specs("sentence_transformers"))
    assert select_backend("auto", env={}).name == "sentence_transformers"
    monkeypatch.setattr(backends, "_module_available", _specs())
    assert select_backend("auto", env={}).name == "none"


def test_openai_compat_is_selected_when_it_is_the_first_available(monkeypatch):
    monkeypatch.setattr(backends, "_module_available", _specs())
    env = {"ENTROPICMEM_EMBEDDINGS_BASE_URL": "http://127.0.0.1:8080/v1"}
    assert select_backend("auto", env=env).name == "openai_compat"


def test_an_explicit_preference_that_is_unavailable_falls_back_to_none(monkeypatch):
    monkeypatch.setattr(backends, "_module_available", _specs())
    backend = select_backend("fastembed", env={})
    assert backend.name == "none"
    assert not backend.available()


def test_the_none_backend_does_not_pretend_to_embed():
    backend = NoneBackend()
    assert backend.name == "none"
    assert not backend.available()
    with pytest.raises(RuntimeError):
        backend.embed(["anything"])


def test_optional_backends_report_unavailable_without_their_package(monkeypatch):
    monkeypatch.setattr(backends, "_module_available", _specs())
    assert not FastEmbedBackend().available()
    assert not SentenceTransformersBackend().available()
    with pytest.raises(RuntimeError):
        FastEmbedBackend().embed(["x"])


def test_each_backend_carries_the_cards_shapes():
    assert FastEmbedBackend.default_model == "BAAI/bge-small-en-v1.5"
    assert FastEmbedBackend().dim == 384
    assert SentenceTransformersBackend().dim == 384
    assert OpenAICompatBackend(base_url="").available() is False


# --- openai_compat ---------------------------------------------------------


def test_openai_compat_posts_batches_and_parses_vectors(monkeypatch):
    calls = []

    def fake_post(url, payload, headers, timeout):
        calls.append((url, payload, headers))
        return {"data": [{"embedding": [0.25, 0.5]} for _ in payload["input"]]}

    monkeypatch.setattr(backends, "_post_json", fake_post)
    backend = OpenAICompatBackend(
        base_url="http://127.0.0.1:9/v1",
        api_key="test-key",
        model="acme-embed",
        env={},
    )
    assert backend.available() is True
    vectors = backend.embed(["one", "two"])
    assert vectors == [[0.25, 0.5], [0.25, 0.5]]
    url, payload, headers = calls[0]
    assert url.endswith("/embeddings")
    assert payload == {"model": "acme-embed", "input": ["one", "two"]}
    assert headers["Authorization"] == "Bearer test-key"
    assert backend.dim == 2  # learned from the response


def test_openai_compat_refuses_a_short_response(monkeypatch):
    monkeypatch.setattr(
        backends, "_post_json", lambda *a, **k: {"data": [{"embedding": [1.0]}]}
    )
    backend = OpenAICompatBackend(base_url="http://x/v1", model="m", env={})
    with pytest.raises(RuntimeError):
        backend.embed(["one", "two"])


# --- the service -----------------------------------------------------------


def test_the_service_batches_at_sixty_four_and_warms_once():
    backend = FakeBackend()
    service = EmbeddingService(":memory:", backend=backend, model="fake-1")
    vectors = service.embed_texts([f"t{i}" for i in range(150)])
    assert backend.embed_calls == [64, 64, 22]
    assert len(vectors) == 150
    assert backend.warm_calls == 1
    assert service.is_warm


def test_the_service_reports_a_missing_backend_as_unavailable():
    service = EmbeddingService(":memory:", backend=NoneBackend())
    assert service.available is False
    assert service.is_warm is False
    # embed_texts on the none backend is the caller's bug, not a silent [].
    with pytest.raises(RuntimeError):
        service.embed_texts(["x"])


def test_memory_text_prefers_the_summary_and_caps_at_two_thousand():
    assert memory_text("short summary", "long content") == "short summary"
    assert memory_text("", "only content") == "only content"
    long = "z" * 2_500
    assert memory_text("", long) == "z" * 2_000
    assert memory_text("", "") == ""


def test_episode_text_is_title_plus_summary():
    assert episode_text("Acme cutover", "the summary") == "Acme cutover\nthe summary"
    assert episode_text("Acme cutover", "") == "Acme cutover"
