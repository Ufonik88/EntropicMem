"""Entity linking entry point (v3 §3.6, card EM-208).

The plan puts the linker here and the store in ``em/store/entities.py``. This
module is the small, importable surface the formation pipeline uses:

    linker = EntityLinker(conn, scope)
    linked = linker.link(memory_dict)

``link`` must be cheap enough to run inline on the write path (the p95 budget
is 2 ms per memory at 10k entities), which is why alias resolution is an exact
indexed probe per n-gram rather than a scan.
"""

from __future__ import annotations

import sqlite3

from ..store.entities import (
    MAX_NGRAM,
    EntityStore,
    candidate_phrases,
    ngrams,
    normalise,
    time_link,
)
from ..store.types import Scope

__all__ = [
    "EntityLinker",
    "EntityStore",
    "MAX_NGRAM",
    "candidate_phrases",
    "ngrams",
    "normalise",
    "time_link",
]


class EntityLinker:
    """Bind a scope once, then link memory dicts.

    The plan's API is ``EntityLinker.link(memory)``, so the scope is a
    constructor argument rather than a per-call one.
    """

    def __init__(self, conn: sqlite3.Connection, scope: Scope) -> None:
        self._conn = conn
        self._scope = scope
        self._store = EntityStore(conn)

    @property
    def store(self) -> EntityStore:
        return self._store

    def link(self, memory: dict) -> list[str]:
        """Link one memory to entities. Returns the entity ids now linked."""
        return self._store.link(memory["id"], memory.get("content", ""), scope=self._scope)
