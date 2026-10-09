"""The embedding service: one backend, one model name, batched text — EM-303.

``EmbeddingService`` is what the job handlers talk to. It owns:

* the selected backend (``select_backend``'s silent ``none`` fallback included),
* the **model name** that gets written into ``meta.embedding_model`` and into
  every ``embeddings`` row, so a model switch can be detected and backfilled,
* batching (§3.6: up to 64 texts per call),
* the text shapes the card fixes: memories embed ``summary or content``
  (≤ 2,000 chars), episodes embed ``title + summary``.

No prefetch path may call this: ``embed_texts`` is only invoked from the
worker's job handlers.
"""

from __future__ import annotations

import os
from typing import Dict, Iterable, List, Optional, Sequence

from .backends import select_backend

__all__ = [
    "BATCH_SIZE",
    "MAX_TEXT_CHARS",
    "EmbeddingService",
    "batches",
    "episode_text",
    "memory_text",
]

#: The card's batch cap.
BATCH_SIZE = 64

#: The card's per-text cap.
MAX_TEXT_CHARS = 2_000


def batches(items: Sequence[str], size: int = BATCH_SIZE) -> Iterable[Sequence[str]]:
    """Yield ``items`` in chunks of at most ``size``."""
    if size < 1:
        raise ValueError("batch size must be >= 1")
    for start in range(0, len(items), size):
        yield items[start : start + size]


def memory_text(summary: str, content: str) -> str:
    """§3.6/EM-303: ``summary or content``, stripped, capped at 2,000 chars."""
    text = (summary or "").strip() or (content or "").strip()
    return text[:MAX_TEXT_CHARS]


def episode_text(title: str, summary: str) -> str:
    """An episode embeds its ``title + summary`` (card EM-303)."""
    parts = [(title or "").strip(), (summary or "").strip()]
    return "\n".join(part for part in parts if part)[:MAX_TEXT_CHARS]


class EmbeddingService:
    """Backend + model + batching. Construct once per process/worker."""

    def __init__(
        self,
        db_path: str,
        *,
        backend=None,
        preference: Optional[str] = None,
        model: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> None:
        self.db_path = str(db_path)
        if backend is None:
            environ = dict(os.environ) if env is None else dict(env)
            backend = select_backend(
                preference or environ.get("ENTROPICMEM_EMBEDDINGS_BACKEND", "auto"),
                model=model,
                env=environ,
            )
        self.backend = backend
        self.model = model or getattr(backend, "default_model", "") or ""
        self._warm = False

    @property
    def available(self) -> bool:
        return bool(self.backend.available())

    @property
    def is_warm(self) -> bool:
        """True once the backend has loaded (or served) this process."""
        return self._warm and self.available

    def warm(self) -> None:
        """Load the model. Idempotent; safe to call from the worker thread."""
        if not self.available or self._warm:
            return
        self.backend.warm()
        self._warm = True

    def embed_texts(self, texts: Sequence[str]) -> List[List[float]]:
        """Embed ``texts`` in batches. Raises when no backend is selected."""
        if not texts:
            return []
        if not self.available:
            raise RuntimeError("no embedding backend selected; check embeddings.backend")
        self.warm()
        vectors: List[List[float]] = []
        for batch in batches(list(texts)):
            vectors.extend(self.backend.embed(list(batch)))
        if len(vectors) != len(texts):
            raise RuntimeError(
                f"backend {self.backend.name!r} returned {len(vectors)} vectors "
                f"for {len(texts)} texts"
            )
        return vectors

    def embed_query(self, text: str) -> Optional[List[float]]:
        """One query's vector, or ``None`` when no backend is selected.

        This is the query half the search path needs; until the provider cards
        wire it, the eval adapter is the caller (offline, not the prefetch
        thread). Empty text and a ``none`` backend both return ``None``.
        """
        query = (text or "").strip()
        if not query or not self.available:
            return None
        vectors = self.embed_texts([query])
        return vectors[0] if vectors else None
