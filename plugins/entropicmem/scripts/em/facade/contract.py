"""The provider-facing engine contract (foundation for card EM-211).

The Hermes provider (``plugins/entropicmem/__init__.py``) talks to storage only
through the v2 ``memory_engine.MemoryEngine`` API. The v3 cutover replaces the
engine *behind* that API with a facade over ``em.store``. The provider itself
is not rewritten in S2. This module pins down exactly what "that API" is, so
the facade has a precise target and nobody can widen or narrow it by accident.

Three parts, each kept honest by a test (``tests/unit/test_em_facade_contract.py``):

1. ``PROVIDER_CALLS``: every engine method the provider calls, with the
   keyword arguments it passes and how many positional ones. The test derives
   this table from the provider's source (AST scan) and fails when they differ.
   A new call site in the provider therefore changes the contract visibly.
2. ``LegacyEngine`` / ``FactView``: the typed shape. The test checks that every
   registered implementation (today ``MemoryEngine``, later the v3 facade)
   accepts every recorded call.
3. ``BEHAVIOURS``: the semantics the provider relies on that no signature
   shows. ``tests/parity/`` exercises them against each implementation.

Stdlib-only (plan §3.2); imports nothing from the provider or the v2 engine.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, Sequence, runtime_checkable

#: method -> (keyword arguments the provider passes, positional-arg counts seen).
#: Generated from the provider source; see the module docstring.
PROVIDER_CALLS: Dict[str, tuple[frozenset[str], frozenset[int]]] = {
    "add_episode": (
        frozenset({"end_ts", "episode_id", "importance", "source", "source_session", "start_ts", "summary", "title"}),
        frozenset({0}),
    ),
    "close": (frozenset(), frozenset({0})),
    "consolidate": (
        frozenset({"confirm", "dry_run", "evergreen_domains", "max_age_days", "min_access_count"}),
        frozenset({0}),
    ),
    "extract_and_store": (
        frozenset({"assistant_text", "min_confidence", "promote", "session_id", "source", "user_text"}),
        frozenset({0}),
    ),
    "forget": (frozenset({"confirm"}), frozenset({1})),
    "get_fact": (frozenset(), frozenset({1})),
    "next_episode_wave": (frozenset(), frozenset({1})),
    "prune_pending": (frozenset({"older_than_days"}), frozenset({0})),
    "recall_hybrid": (
        frozenset({"auto_reinforce", "expand_links", "fts_weight", "top_k", "vec_weight"}),
        frozenset({1}),
    ),
    "recall_with_relevance": (
        frozenset(
            {
                "auto_reinforce",
                "decay_enabled",
                "decay_floor",
                "decay_half_life_days",
                "evergreen_domains",
                "min_relevance",
                "reinforcement_boost",
                "top_k",
            }
        ),
        frozenset({1}),
    ),
    "remember": (
        frozenset({"actor", "content", "domain", "importance", "sensitivity", "session_id", "source", "tags", "title"}),
        frozenset({0}),
    ),
    "stats": (frozenset(), frozenset({0})),
    "touch": (frozenset(), frozenset({1})),
}

#: Engine attributes the provider reads that are not method calls. ``db`` is the
#: raw v2 ``sqlite3.Connection``: ``_locate_mirror`` runs
#: ``SELECT id, content, tags FROM facts`` on it. A v3 facade cannot offer a v2
#: ``facts`` table. Before cutover, this access must be replaced by an engine
#: method (see ``BEHAVIOURS["mirror-scan"]``) and removed from this set.
PROVIDER_ATTRIBUTES: frozenset[str] = frozenset({"db"})

#: Semantics the provider depends on. Keys are stable ids that the parity
#: scenarios cite.
BEHAVIOURS: Dict[str, str] = {
    "id-from-content": (
        "get_fact(StoredFact.make_id(content)) finds what remember(content) stored. "
        "make_id is sha256(content)[:16]. _locate_mirror uses it to find the mirror row "
        "for a built-in memory replace/remove. v3 ids are ULIDs, so the facade must keep "
        "this lookup working, e.g. by storing make_id(content) as legacy_id on remember, "
        "which MemoryStore.get already resolves."
    ),
    "remember-idempotent": (
        "remember() of content that is already stored returns the existing id and adds "
        "no second row."
    ),
    "forget-needs-confirm": (
        "forget(id) without confirm=True raises ValueError and deletes nothing; "
        "forget(id, confirm=True) returns True if a row went, False if there was none."
    ),
    "tags-are-a-list": "FactView.tags is a list[str] (v3 stores JSON; v2 stored CSV).",
    "scores-in-unit-range": (
        "recall results carry relevance_score in [0, 1], sorted best first, all >= "
        "min_relevance, with why_retrieved a list."
    ),
    "touch-counts": (
        "touch(ids) returns how many ids matched and refreshes last_accessed on each (the "
        "decay clock). v2 does not change access_count here, and the provider relies only "
        "on last_accessed."
    ),
    "episode-waves-monotonic": (
        "next_episode_wave(base) is max(existing base_wN) + 1, starting at 1, and never "
        "reuses a wave after deletion."
    ),
    "context-manager-releases": (
        "'with Engine(...) as e:' closes and releases the write lock on exit, even on error."
    ),
    "mirror-scan": (
        "OPEN (EM-211): _locate_mirror's fallback reads engine.db directly. Add an engine "
        "method, find_mirrored(needle) -> Optional[str], to BOTH engines, switch the "
        "provider to it, and drop 'db' from PROVIDER_ATTRIBUTES."
    ),
}


@runtime_checkable
class FactView(Protocol):
    """What the provider reads from a stored or recalled fact."""

    id: str
    content: str
    title: str
    source: str
    importance: float
    domain: str
    tags: List[str]
    created_at: str
    updated_at: str
    last_accessed: str
    access_count: int
    sensitivity: str
    relevance_score: float
    decay_score: float
    why_retrieved: List[Any]


class LegacyEngine(Protocol):
    """The v2 engine API as the provider uses it. The v3 facade implements this."""

    def __enter__(self) -> "LegacyEngine": ...
    def __exit__(self, exc_type, exc_val, exc_tb) -> None: ...
    def close(self) -> None: ...

    def remember(
        self,
        content: str,
        title: str = "",
        source: str = "agent",
        importance: float = 0.5,
        domain: str = "Knowledge",
        tags: Optional[List[str]] = None,
        session_id: str = "",
        sensitivity: Optional[str] = None,
        actor: Optional[str] = None,
    ) -> str: ...

    def get_fact(self, entropic_id: str) -> Optional[FactView]: ...
    def forget(self, entropic_id: str, *, confirm: bool = False) -> bool: ...
    def touch(self, fact_ids: Sequence[str]) -> int: ...
    def stats(self) -> dict: ...

    def recall_with_relevance(
        self,
        query: str,
        top_k: int = 10,
        domain: Optional[str] = None,
        min_relevance: float = 0.0,
        decay_enabled: bool = True,
        decay_half_life_days: float = 90.0,
        decay_floor: float = 0.5,
        evergreen_domains: Optional[Sequence[str]] = None,
        reinforcement_boost: float = 0.1,
        auto_reinforce: bool = False,
    ) -> List[FactView]: ...

    def recall_hybrid(
        self,
        query: str,
        top_k: int = 10,
        domain: Optional[str] = None,
        fts_weight: float = 0.6,
        vec_weight: float = 0.4,
        expand_links: bool = False,
        auto_reinforce: bool = False,
    ) -> List[FactView]: ...

    def extract_and_store(
        self,
        user_text: str,
        assistant_text: str = "",
        session_id: str = "",
        source: str = "auto_extracted",
        min_confidence: float = 0.4,
        promote: bool = True,
    ) -> List[Dict[str, Any]]: ...

    def prune_pending(self, older_than_days: int = 30) -> int: ...

    def add_episode(
        self,
        title: str,
        summary: str,
        *,
        start_ts: Optional[str] = None,
        end_ts: Optional[str] = None,
        source_session: str = "",
        linked_fact_ids: Optional[List[str]] = None,
        importance: float = 0.5,
        domain: str = "Knowledge",
        source: str = "agent",
        episode_id: Optional[str] = None,
    ) -> str: ...

    def next_episode_wave(self, episode_base: str) -> int: ...

    def consolidate(
        self,
        max_age_days: int = 90,
        min_access_count: int = 0,
        dry_run: bool = True,
        confirm: bool = False,
        evergreen_domains: Optional[Sequence[str]] = None,
    ) -> dict: ...


__all__ = ["BEHAVIOURS", "FactView", "LegacyEngine", "PROVIDER_ATTRIBUTES", "PROVIDER_CALLS"]
