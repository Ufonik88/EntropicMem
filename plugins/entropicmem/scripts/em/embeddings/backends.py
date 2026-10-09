"""Embedding backends and selection — EM-303 (plan §3.6/EM-303 card).

The card's four backends, behind one small protocol:

| name | stack | notes |
|---|---|---|
| ``fastembed`` | ONNX (no torch) | preferred; default model ``BAAI/bge-small-en-v1.5``, 384-d |
| ``sentence_transformers`` | torch | model configurable; default ``all-MiniLM-L6-v2`` |
| ``openai_compat`` | HTTP (stdlib ``urllib``) | for users with an embeddings endpoint |
| ``none`` | — | no embeddings; every caller must treat it as "not available" |

``select_backend("auto")`` picks the first available in the card's order.
An explicit name that is not available **falls back to ``none``** rather than
raising: an unreleased optional dependency must never break a session, and
``available()``/``name`` tell the caller what they got.

Nothing here embeds at import time and nothing here reads the live store. The
job handlers (``em.embeddings.jobs``) are the only callers of ``embed()``, and
they run off the write path in the worker thread — the card's hard rule that no
embedding call ever runs on the agent/prefetch thread.

Stdlib-only module: the optional packages are imported inside methods.
"""

from __future__ import annotations

import importlib.util
import json
import os
import urllib.error
import urllib.request
from typing import Dict, List, Optional, Sequence

__all__ = [
    "FastEmbedBackend",
    "NoneBackend",
    "OpenAICompatBackend",
    "SELECTION_ORDER",
    "SentenceTransformersBackend",
    "select_backend",
]

#: The card's ``auto`` order.
SELECTION_ORDER = ("fastembed", "sentence_transformers", "openai_compat")

FASTEMBED_MODEL = "BAAI/bge-small-en-v1.5"
SENTENCE_TRANSFORMERS_MODEL = "all-MiniLM-L6-v2"
OPENAI_COMPAT_MODEL = "text-embedding-3-small"


def _module_available(name: str) -> bool:
    """True when ``name`` can be imported. Never imports it (no side effects)."""
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _env(env: Optional[Dict[str, str]]) -> Dict[str, str]:
    return dict(os.environ) if env is None else dict(env)


class NoneBackend:
    """No embeddings. ``available()`` is False and ``embed`` is a caller bug."""

    name = "none"
    default_model = ""
    dim = 0

    def available(self) -> bool:
        return False

    def warm(self) -> None:
        return None

    def embed(self, texts: Sequence[str]) -> List[List[float]]:
        raise RuntimeError("no embedding backend selected; check embeddings.backend")


class FastEmbedBackend:
    """``fastembed`` — ONNX, no torch (the card's preferred backend)."""

    name = "fastembed"
    default_model = FASTEMBED_MODEL
    dim = 384

    def __init__(self, model: Optional[str] = None) -> None:
        self.model = model or self.default_model
        self._model = None

    def available(self) -> bool:
        return _module_available("fastembed")

    def warm(self) -> None:
        if self._model is None and self.available():
            from fastembed import TextEmbedding  # lazy: heavy, optional

            self._model = TextEmbedding(model_name=self.model)

    def embed(self, texts: Sequence[str]) -> List[List[float]]:
        if not self.available():
            raise RuntimeError("fastembed is not installed")
        self.warm()
        vectors = self._model.embed(list(texts))  # type: ignore[union-attr]
        return [[float(value) for value in vector] for vector in vectors]


class SentenceTransformersBackend:
    """``sentence-transformers`` — torch, model configurable."""

    name = "sentence_transformers"
    default_model = SENTENCE_TRANSFORMERS_MODEL
    dim = 384

    def __init__(self, model: Optional[str] = None) -> None:
        self.model = model or self.default_model
        self._model = None

    def available(self) -> bool:
        return _module_available("sentence_transformers")

    def warm(self) -> None:
        if self._model is None and self.available():
            from sentence_transformers import SentenceTransformer  # lazy

            self._model = SentenceTransformer(self.model)

    def embed(self, texts: Sequence[str]) -> List[List[float]]:
        if not self.available():
            raise RuntimeError("sentence-transformers is not installed")
        self.warm()
        encoded = self._model.encode(  # type: ignore[union-attr]
            list(texts), normalize_embeddings=True
        )
        return [[float(value) for value in vector] for vector in encoded]


def _post_json(url: str, payload: dict, headers: dict, timeout: float):
    """POST JSON and parse the response. Separated so tests can stub the wire."""
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - user-configured endpoint
        body = response.read().decode("utf-8")
    return json.loads(body)


class OpenAICompatBackend:
    """An OpenAI-compatible ``/embeddings`` endpoint, over stdlib urllib.

    Configuration precedence: constructor, then environment
    (``ENTROPICMEM_EMBEDDINGS_BASE_URL`` / ``_API_KEY`` / ``_MODEL``). No base
    URL means not available. ``dim`` is 0 until the first response teaches the
    width.
    """

    name = "openai_compat"
    default_model = OPENAI_COMPAT_MODEL
    dim = 0

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        *,
        env: Optional[Dict[str, str]] = None,
        timeout: float = 20.0,
    ) -> None:
        environ = _env(env)
        self.base_url = (
            base_url if base_url is not None else environ.get("ENTROPICMEM_EMBEDDINGS_BASE_URL", "")
        ).rstrip("/")
        self.api_key = (
            api_key if api_key is not None else environ.get("ENTROPICMEM_EMBEDDINGS_API_KEY", "")
        )
        self.model = (
            model if model is not None else environ.get("ENTROPICMEM_EMBEDDINGS_MODEL", "")
        ) or self.default_model
        self.timeout = float(timeout)

    def available(self) -> bool:
        return bool(self.base_url)

    def warm(self) -> None:
        return None  # nothing to load; the first request is the warm-up

    def embed(self, texts: Sequence[str]) -> List[List[float]]:
        if not self.available():
            raise RuntimeError("openai_compat has no base_url configured")
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        body = _post_json(
            f"{self.base_url}/embeddings",
            {"model": self.model, "input": list(texts)},
            headers,
            self.timeout,
        )
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, list) or len(data) != len(texts):
            raise RuntimeError(
                f"embeddings endpoint returned {_count(data)} vectors for {len(texts)} texts"
            )
        vectors: List[List[float]] = []
        for entry in data:
            vector = entry.get("embedding") if isinstance(entry, dict) else None
            if not isinstance(vector, list) or not vector:
                raise RuntimeError("embeddings endpoint returned a malformed vector")
            vectors.append([float(value) for value in vector])
        self.dim = len(vectors[0])
        return vectors


def _count(data) -> str:
    return str(len(data)) if isinstance(data, list) else "no"


def select_backend(
    preference: str = "auto",
    *,
    model: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
) -> object:
    """The card's selection, with a silent fall back to ``none``.

    ``auto`` tries fastembed → sentence_transformers → openai_compat. An
    explicit name builds just that backend; if it is not available the result
    is ``NoneBackend`` whose ``name`` says ``"none"``.
    """
    choose = (preference or "auto").strip().lower()
    if choose == "none":
        return NoneBackend()
    if choose not in ("auto", *SELECTION_ORDER):
        raise ValueError(f"unknown embeddings backend {preference!r}")

    def build(name: str):
        if name == "fastembed":
            return FastEmbedBackend(model)
        if name == "sentence_transformers":
            return SentenceTransformersBackend(model)
        return OpenAICompatBackend(model=model, env=env)

    names = SELECTION_ORDER if choose == "auto" else (choose,)
    for name in names:
        backend = build(name)
        if backend.available():
            return backend
    return NoneBackend()
