"""``em.embeddings`` — EM-303's backends, service and vector cache.

Stdlib-only (plan §3.2). The optional stacks (``fastembed``,
``sentence-transformers``) are imported lazily inside the backend that needs
them, never at module import, so a missing package degrades to the ``none``
backend instead of breaking every import of ``em``.
"""
