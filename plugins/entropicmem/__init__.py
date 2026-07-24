"""EntropicMem Hermes MemoryProvider plugin.

Install:
  ln -s /path/to/EntropicMem/plugins/entropicmem ~/.hermes/plugins/entropicmem

Prerequisites:
  /learn https://github.com/Ufonik88/EntropicMem
  entropicmem init

Config (~/.hermes/config.yaml):
  memory:
    provider: entropicmem
  plugins:
    entropicmem:
      vault_path: ~/.hermes/entropicmem/vault
      index_db: ~/.hermes/entropicmem/index.db
      memory_db: ~/.hermes/entropicmem/memory.db
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.memory_provider import MemoryProvider

from ._backend import (
    ensure_scripts_on_path,
    hermes_home_from_kwargs,
    load_plugin_config,
    resolve_paths,
    resolve_scripts_dir,
)

logger = logging.getLogger(__name__)

REMEMBER_SCHEMA = {
    "name": "entropicmem_remember",
    "description": "Store a durable fact in EntropicMem (memory engine + vault projection).",
    "parameters": {
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "Fact to remember."},
            "domain": {"type": "string", "description": "Vault domain (default: Knowledge)."},
            "importance": {"type": "number", "description": "0.0–1.0 (default 0.7)."},
        },
        "required": ["content"],
    },
}

RECALL_SCHEMA = {
    "name": "entropicmem_recall",
    "description": "Search EntropicMem durable facts (FTS5 memory engine).",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query."},
            "limit": {"type": "integer", "description": "Max results (default 8)."},
            "domain": {"type": "string", "description": "Filter by domain (optional)."},
        },
        "required": ["query"],
    },
}

QUERY_SCHEMA = {
    "name": "entropicmem_query",
    "description": "Hybrid vault retrieval with citations (wikilinks + FTS).",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Topic or question."},
            "top_k": {"type": "integer", "description": "Max notes (default 5)."},
        },
        "required": ["query"],
    },
}

PATCH_CORE_SCHEMA = {
    "name": "entropicmem_patch_core",
    "description": "Surgically update Core Memory (Persona or User Profile). Use for permanent changes to agent guidelines or user facts.",
    "parameters": {
        "type": "object",
        "properties": {
            "target": {"type": "string", "enum": ["persona", "user_profile"], "description": "Which core memory to update."},
            "old_text": {"type": "string", "description": "Exact text to find and replace."},
            "new_text": {"type": "string", "description": "Replacement text (empty = delete matched text)."},
        },
        "required": ["target", "old_text"],
    },
}

STATS_SCHEMA = {
    "name": "entropicmem_stats",
    "description": "Return EntropicMem memory statistics: fact count, domain distribution, DB path.",
    "parameters": {
        "type": "object",
        "properties": {},
    },
}

GET_SCHEMA = {
    "name": "entropicmem_get",
    "description": "Retrieve a single stored fact by its entropic_id.",
    "parameters": {
        "type": "object",
        "properties": {
            "entropic_id": {"type": "string", "description": "The entropic_id of the fact to retrieve."},
        },
        "required": ["entropic_id"],
    },
}

# ── Smart Context Management Defaults ────────────────────────────────────────

SMART_CONTEXT_DEFAULTS = {
    # Relevance filtering
    "min_relevance_score": 0.3,
    "max_prefetch_results": 5,

    # Token budget (max characters per prefetch turn)
    "prefetch_token_budget": 1500,

    # Deduplication (don't repeat facts within N turns)
    "dedup_window": 5,

    # Domain filtering (empty = all domains)
    "enabled_domains": [],

    # Progressive disclosure thresholds
    "high_relevance_threshold": 0.7,
    "medium_relevance_threshold": 0.4,

    # Conversation context awareness
    "context_window_turns": 3,
    "max_context_query_length": 1000,

    # Cache behavior
    "cache_conversation_context": True,
    "cache_ttl_seconds": 300,
}


def _tool_error(msg: str) -> str:
    try:
        from tools.registry import tool_error

        return tool_error(msg)
    except Exception:
        return json.dumps({"error": msg})


class EntropicMemMemoryProvider(MemoryProvider):
    """Hermes MemoryProvider backed by EntropicMem MemoryEngine + vault."""

    def __init__(self, config: Optional[dict] = None):
        self._config = {**SMART_CONTEXT_DEFAULTS, **(config or {})}
        self._scripts_dir: Optional[Path] = None
        self._hermes_home: Optional[Path] = None
        self._vault_path: Optional[Path] = None
        self._index_db: Optional[Path] = None
        self._memory_db: Optional[Path] = None
        self._session_id = ""
        self._prefetch_lock = threading.Lock()
        self._prefetch_cache: str = ""
        self._last_query: str = ""
        self._conversation_history: List[Dict[str, Any]] = []

        # Smart context tracking
        self._recently_injected: Dict[str, int] = {}  # fact_id -> turn_count
        self._turn_counter: int = 0
        self._cache_timestamp: float = 0.0
        self._last_conversation_hash: str = ""
        self._extract_lock = threading.Lock()

    @property
    def name(self) -> str:
        return "entropicmem"

    def is_available(self) -> bool:
        try:
            hh = Path.home() / ".hermes"
            scripts = resolve_scripts_dir(hh)
            return scripts is not None
        except Exception:
            return False

    def get_config_schema(self) -> List[Dict[str, Any]]:
        return [
            {
                "key": "vault_path",
                "description": "EntropicMem vault directory",
                "default": "~/.hermes/entropicmem/vault",
            },
            {
                "key": "index_db",
                "description": "Vault index SQLite path",
                "default": "~/.hermes/entropicmem/index.db",
            },
            {
                "key": "memory_db",
                "description": "Memory engine SQLite path",
                "default": "~/.hermes/entropicmem/memory.db",
            },
            # Smart Context Management
            {
                "key": "min_relevance_score",
                "description": "Minimum FTS5 relevance score for prefetch (0.0-1.0)",
                "default": 0.3,
            },
            {
                "key": "max_prefetch_results",
                "description": "Maximum facts to inject per turn",
                "default": 5,
            },
            {
                "key": "prefetch_token_budget",
                "description": "Maximum characters for prefetch context per turn",
                "default": 1500,
            },
            {
                "key": "dedup_window",
                "description": "Don't repeat facts within N turns",
                "default": 5,
            },
            {
                "key": "enabled_domains",
                "description": "List of domains to filter (empty = all)",
                "default": [],
            },
            {
                "key": "high_relevance_threshold",
                "description": "Threshold for high-relevance facts (progressive disclosure)",
                "default": 0.7,
            },
            {
                "key": "medium_relevance_threshold",
                "description": "Threshold for medium-relevance facts",
                "default": 0.4,
            },
            {
                "key": "context_window_turns",
                "description": "Number of recent turns to consider for context",
                "default": 3,
            },
            {
                "key": "max_context_query_length",
                "description": "Maximum length of context-enhanced query",
                "default": 1000,
            },
            {
                "key": "cache_conversation_context",
                "description": "Cache prefetch results with conversation awareness",
                "default": True,
            },
            {
                "key": "cache_ttl_seconds",
                "description": "Cache TTL in seconds",
                "default": 300,
            },
            # Phase 8: Auto-extraction
            {
                "key": "auto_extract_enabled",
                "description": "Enable background fact extraction from conversation (regex-based, no LLM)",
                "default": True,
            },
            {
                "key": "extraction_timeout",
                "description": "Maximum seconds for background extraction per turn",
                "default": 5.0,
            },
            # Phase 8: Core Memory
            {
                "key": "core_memory_enabled",
                "description": "Enable Core Memory (Persona/User Profile) injection in prefetch",
                "default": True,
            },
            # Phase 8: Temporal Decay
            {
                "key": "decay_enabled",
                "description": "Enable temporal decay scoring for memory recall",
                "default": True,
            },
            {
                "key": "decay_half_life_days",
                "description": "Half-life for memory decay in days",
                "default": 30,
            },
            {
                "key": "reinforcement_boost",
                "description": "Score boost per fact access (capped)",
                "default": 0.1,
            },
        ]

    def save_config(self, values: Dict[str, Any], hermes_home: str) -> None:
        config_path = Path(hermes_home) / "config.yaml"
        try:
            import yaml

            existing: dict = {}
            if config_path.exists():
                with open(config_path, encoding="utf-8-sig") as f:
                    existing = yaml.safe_load(f) or {}
            existing.setdefault("plugins", {})
            existing["plugins"]["entropicmem"] = values
            with open(config_path, "w", encoding="utf-8") as f:
                yaml.dump(existing, f, default_flow_style=False)
        except Exception as e:
            logger.debug("entropicmem save_config failed: %s", e)

    def initialize(self, session_id: str, **kwargs) -> None:
        self._session_id = session_id
        self._hermes_home = hermes_home_from_kwargs(kwargs)
        self._config = {**load_plugin_config(self._hermes_home), **self._config}
        self._scripts_dir = resolve_scripts_dir(self._hermes_home)
        if not self._scripts_dir:
            logger.warning("EntropicMem skill scripts not found — run /learn EntropicMem")
            return
        ensure_scripts_on_path(self._scripts_dir)
        self._vault_path, self._index_db, self._memory_db = resolve_paths(
            self._hermes_home, self._config
        )
        self._memory_db.parent.mkdir(parents=True, exist_ok=True)

    def system_prompt_block(self) -> str:
        if not self._scripts_dir:
            return (
                "# EntropicMem\n"
                "Skill not installed. Run `/learn https://github.com/Ufonik88/EntropicMem` "
                "then `entropicmem init`.\n"
            )
        return (
            "# EntropicMem (active)\n"
            "Standalone memory: use `entropicmem_remember` for durable facts, "
            "`entropicmem_recall` for fact search, `entropicmem_query` for cited vault notes.\n"
            "CLI: `entropicmem lint`, `hotcache`, `graph export` for maintenance.\n"
        )

    def queue_prefetch(self, query: str, *, session_id: str = "") -> None:
        if query:
            self._last_query = query[:2000]

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        """Smart prefetch with relevance filtering, core memory, temporal decay, and deduplication."""
        q = (query or self._last_query or "").strip()
        if not q or not self._scripts_dir or not self._memory_db:
            return ""

        self._turn_counter += 1
        blocks: List[str] = []

        # Phase 8: Core Memory always injected first
        if self._config.get("core_memory_enabled", True) and self._vault_path and self._vault_path.is_dir():
            try:
                ensure_scripts_on_path(self._scripts_dir)
                from vault import CoreMemory
                core = CoreMemory(Path(self._vault_path))
                core_block = core.injection_block()
                if core_block:
                    blocks.append(core_block)
            except Exception as e:
                logger.debug("EntropicMem core memory failed: %s", e)

        # Check cache first (with conversation awareness)
        if self._config.get("cache_conversation_context", True) and not blocks:
            cached = self._check_cache(q)
            if cached is not None:
                # Inject core memory above cached prefetch
                if blocks:
                    return "\n\n".join(blocks + [cached])
                return cached

        try:
            from memory_engine import MemoryEngine

            engine = MemoryEngine(self._memory_db)

            # Phase 2.3: Build context-aware query
            enhanced_query = self._build_context_query(q)

            # Phase 1.2 & 2.2: Get candidates with relevance scoring and domain filtering
            # Pass decay config from plugin settings
            candidates = self._get_candidates(engine, enhanced_query)

            # Phase 2.1: Apply deduplication
            deduplicated = self._apply_deduplication(candidates)

            # Phase 3.1: Apply progressive disclosure
            selected = self._apply_progressive_disclosure(deduplicated)

            # Phase 1.3: Apply token budget
            budgeted = self._apply_token_budget(selected)

            engine.close()

            if budgeted:
                block = self._format_block(budgeted)
                blocks.append(block)

                # Track injected facts for deduplication
                self._track_injected(budgeted)

            result = "\n\n".join(blocks) if blocks else ""

            # Cache result
            with self._prefetch_lock:
                self._prefetch_cache = result
                self._cache_timestamp = self._get_timestamp()

            return result

        except Exception as e:
            logger.debug("EntropicMem prefetch failed: %s", e)
            return ""

    def sync_turn(
        self,
        user_content: str,
        assistant_content: str,
        *,
        session_id: str = "",
        messages: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Update conversation history and run background auto-extraction."""
        if messages:
            self._conversation_history = messages[-(self._config.get("context_window_turns", 3) * 2):]

        # Auto-extract facts from conversation (non-blocking, regex-based)
        if self._config.get("auto_extract_enabled", True) and self._memory_db and self._scripts_dir:
            try:
                self._auto_extract(user_content, assistant_content, session_id or self._session_id)
            except Exception as e:
                logger.debug("EntropicMem auto-extract failed: %s", e)

    def _auto_extract(self, user_content: str, assistant_content: str, session_id: str) -> None:
        """Background auto-extraction of durable facts from conversation text.

        Fire-and-forget: skips if an extraction is already running.
        """
        if not self._extract_lock.acquire(blocking=False):
            return  # Another extraction is in progress — skip

        def _run():
            try:
                ensure_scripts_on_path(self._scripts_dir)
                from memory_engine import MemoryEngine
                with MemoryEngine(self._memory_db) as engine:
                    engine.extract_and_store(
                        user_text=user_content,
                        assistant_text=assistant_content,
                        session_id=session_id,
                        source="auto_extracted",
                        min_confidence=0.4,
                    )
            except Exception:
                pass  # Non-blocking; failures are silent
            finally:
                self._extract_lock.release()

        t = threading.Thread(target=_run, daemon=True)
        t.start()

    # ── Smart Context Helpers ─────────────────────────────────────────────

    def _check_cache(self, query: str) -> Optional[str]:
        """Check cache with conversation context awareness."""
        with self._prefetch_lock:
            if not self._prefetch_cache:
                return None

            # Check TTL
            ttl = self._config.get("cache_ttl_seconds", 300)
            if self._get_timestamp() - self._cache_timestamp > ttl:
                self._prefetch_cache = ""
                return None

            # Check if query matches (simple cache)
            if query == self._last_query:
                return self._prefetch_cache

            # Conversation-aware cache invalidation
            if self._conversation_changed():
                self._prefetch_cache = ""
                return None

            return None

    def _conversation_changed(self) -> bool:
        """Detect if conversation has changed significantly."""
        if not self._conversation_history:
            return False

        # Hash recent conversation and compare to previous
        import hashlib
        recent_content = " ".join(
            msg.get("content", "")[:100]
            for msg in self._conversation_history[-4:]
        )
        current_hash = hashlib.sha256(recent_content.encode()).hexdigest()[:16]
        changed = current_hash != self._last_conversation_hash
        self._last_conversation_hash = current_hash
        return changed

    def _build_context_query(self, query: str) -> str:
        """Build enhanced query using conversation context."""
        if not self._conversation_history:
            return query

        # Extract recent user messages
        max_turns = self._config.get("context_window_turns", 3)
        recent_user_msgs = [
            msg.get("content", "")[:200]
            for msg in self._conversation_history[-(max_turns * 2):]
            if msg.get("role") == "user"
        ]

        # Combine with current query
        context_parts = [query] + recent_user_msgs

        # Remove duplicates while preserving order
        seen = set()
        unique_parts = []
        for part in context_parts:
            if part not in seen:
                seen.add(part)
                unique_parts.append(part)

        # Truncate to max length
        max_len = self._config.get("max_context_query_length", 1000)
        combined = " ".join(unique_parts)[:max_len]

        return combined

    def _get_candidates(self, engine, query: str) -> list:
        """Get candidate facts with relevance scoring, domain filtering, and temporal decay."""
        min_relevance = self._config.get("min_relevance_score", 0.3)
        max_results = self._config.get("max_prefetch_results", 5)
        enabled_domains = self._config.get("enabled_domains", [])

        # Get more candidates than needed for filtering
        candidates = engine.recall_with_relevance(
            query,
            top_k=max_results * 2,
            min_relevance=min_relevance,
            decay_enabled=self._config.get("decay_enabled", True),
            decay_half_life_days=self._config.get("decay_half_life_days", 30.0),
            reinforcement_boost=self._config.get("reinforcement_boost", 0.1),
        )

        # Apply domain filtering if configured
        if enabled_domains:
            candidates = [f for f in candidates if f.domain in enabled_domains]

        return candidates[:max_results]

    def _apply_deduplication(self, facts: list) -> list:
        """Remove recently injected facts (thread-safe)."""
        dedup_window = self._config.get("dedup_window", 5)

        with self._prefetch_lock:
            fresh = [
                f for f in facts
                if f.id not in self._recently_injected
                or self._turn_counter - self._recently_injected[f.id] > dedup_window
            ]

            # If all facts are duplicates, allow repeats but with penalty
            if not fresh and facts:
                # Sort by recency (prefer facts not seen recently)
                facts.sort(
                    key=lambda f: self._recently_injected.get(f.id, 0)
                )
                return facts[:2]  # Allow max 2 repeats

        return fresh

    def _apply_progressive_disclosure(self, facts: list) -> list:
        """Apply tiered relevance filtering."""
        if not facts:
            return []

        high_threshold = self._config.get("high_relevance_threshold", 0.7)
        medium_threshold = self._config.get("medium_relevance_threshold", 0.4)

        # Tier 1: High relevance (max 2)
        high_relevance = [f for f in facts if f.relevance_score >= high_threshold]
        if high_relevance:
            return high_relevance[:2]

        # Tier 2: Medium relevance (max 3)
        medium_relevance = [f for f in facts if f.relevance_score >= medium_threshold]
        if medium_relevance:
            return medium_relevance[:3]

        # Tier 3: Low relevance (max 5)
        return facts[:5]

    def _apply_token_budget(self, facts: list) -> list:
        """Apply token budget constraint."""
        budget = self._config.get("prefetch_token_budget", 1500)

        selected = []
        char_count = 0

        # Sort by importance to keep most important facts
        sorted_facts = sorted(facts, key=lambda f: f.importance, reverse=True)

        for fact in sorted_facts:
            fact_chars = len(fact.content)

            if char_count + fact_chars <= budget:
                selected.append(fact)
                char_count += fact_chars
            else:
                # Try truncated version
                remaining = budget - char_count
                if remaining >= 100:  # Minimum useful size
                    # Create a simple object with truncated content
                    truncated = type(fact)(
                        id=fact.id,
                        content=fact.content[:remaining] + "...",
                        title=fact.title,
                        source=fact.source,
                        importance=fact.importance,
                        domain=fact.domain,
                        tags=fact.tags,
                        created_at=fact.created_at,
                        updated_at=fact.updated_at,
                        relevance_score=fact.relevance_score,
                    )
                    selected.append(truncated)
                break

        return selected

    def _track_injected(self, facts: list) -> None:
        """Track injected facts for deduplication (thread-safe)."""
        with self._prefetch_lock:
            for fact in facts:
                self._recently_injected[fact.id] = self._turn_counter

            # Cleanup old entries
            dedup_window = self._config.get("dedup_window", 5)
            cutoff = self._turn_counter - dedup_window
            self._recently_injected = {
                fid: turn for fid, turn in self._recently_injected.items()
                if turn > cutoff
            }

    def _format_block(self, facts: list) -> str:
        """Format facts into injection block."""
        if not facts:
            return ""

        lines = ["## EntropicMem recall"]
        for fact in facts:
            # Include relevance score in output for debugging
            score_str = f" [score:{fact.relevance_score:.2f}]" if fact.relevance_score > 0 else ""
            content_preview = fact.content[:300]
            if len(fact.content) > 300:
                content_preview += "..."
            lines.append(f"- [{fact.id}] {content_preview}{score_str}")

        return "\n".join(lines)

    def _get_timestamp(self) -> float:
        """Get current timestamp."""
        return time.time()

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        return [REMEMBER_SCHEMA, RECALL_SCHEMA, QUERY_SCHEMA, PATCH_CORE_SCHEMA, STATS_SCHEMA, GET_SCHEMA]

    def handle_tool_call(self, tool_name: str, args: Dict[str, Any], **kwargs) -> str:
        if tool_name == "entropicmem_remember":
            return self._remember(args)
        if tool_name == "entropicmem_recall":
            return self._recall(args)
        if tool_name == "entropicmem_query":
            return self._query(args)
        if tool_name == "entropicmem_patch_core":
            return self._patch_core(args)
        if tool_name == "entropicmem_stats":
            return self._stats(args)
        if tool_name == "entropicmem_get":
            return self._get(args)
        return _tool_error(f"Unknown tool: {tool_name}")

    def on_memory_write(
        self,
        action: str,
        target: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        if action != "add" or not content or not self._memory_db or not self._scripts_dir:
            return
        try:
            ensure_scripts_on_path(self._scripts_dir)
            from memory_engine import MemoryEngine

            domain = "People" if target == "user" else "Knowledge"
            with MemoryEngine(self._memory_db) as engine:
                engine.remember(
                    content=content,
                    title=content[:60],
                    domain=domain,
                    tags=["mirrored", target],
                    source="built_in_memory",
                    importance=0.75 if target == "user" else 0.6,
                )
        except Exception as e:
            logger.debug("EntropicMem on_memory_write mirror failed: %s", e)

    def on_session_switch(
        self,
        new_session_id: str,
        *,
        parent_session_id: str = "",
        reset: bool = False,
        rewound: bool = False,
        **kwargs,
    ) -> None:
        self._session_id = new_session_id
        if reset:
            with self._prefetch_lock:
                self._prefetch_cache = ""
                self._last_query = ""

    def backup_paths(self) -> List[str]:
        paths = []
        for p in (self._vault_path, self._index_db, self._memory_db):
            if p:
                paths.append(str(p))
        return paths

    def shutdown(self) -> None:
        with self._prefetch_lock:
            self._prefetch_cache = ""

    def _remember(self, args: dict) -> str:
        if not self._scripts_dir or not self._memory_db:
            return _tool_error("EntropicMem not initialized")
        content = (args.get("content") or "").strip()
        if not content:
            return _tool_error("content required")
        domain = args.get("domain") or "Knowledge"
        importance = float(args.get("importance") or 0.7)
        try:
            ensure_scripts_on_path(self._scripts_dir)
            from index import VaultIndex
            from memory_engine import MemoryEngine
            from vault import Vault

            with MemoryEngine(self._memory_db) as engine:
                eid = engine.remember(
                    content=content,
                    title=content[:60],
                    domain=domain,
                    source="agent_tool",
                    importance=importance,
                )
            vault_note = None
            if self._vault_path and self._vault_path.is_dir():
                vault = Vault(self._vault_path)
                body = (
                    f"## Fact\n{content}\n\n## Source\n- entropicmem_remember\n\n"
                    f"## Links\n- [[{domain}/Index]]\n"
                )
                # write_note returns Path; keep as Path for read_note
                vault_note = vault.write_note(
                    domain,
                    f"Fact - {content[:50]}",
                    body,
                    tags=["durable", "agent"],
                    domain=domain,
                    frontmatter={"entropic_id": eid},
                )
                if self._index_db:
                    idx = VaultIndex(self._index_db)
                    note = vault.read_note(vault_note)
                    idx.upsert_note(note)
                    idx.upsert_edges_for_note(vault, note)
                    idx.close()
                # Convert to string for JSON serialization
                vault_note = str(vault_note)
            return json.dumps({"ok": True, "entropic_id": eid, "vault_note": vault_note})
        except Exception as e:
            logger.exception("entropicmem_remember failed")
            return _tool_error(str(e))

    def _recall(self, args: dict) -> str:
        if not self._memory_db or not self._scripts_dir:
            return _tool_error("EntropicMem not initialized")
        query = (args.get("query") or "").strip()
        if not query:
            return _tool_error("query required")
        limit = int(args.get("limit") or 8)
        try:
            ensure_scripts_on_path(self._scripts_dir)
            from memory_engine import MemoryEngine

            with MemoryEngine(self._memory_db) as engine:
                rows = engine.recall_with_relevance(
                    query,
                    top_k=limit,
                    decay_enabled=self._config.get("decay_enabled", True),
                    decay_half_life_days=self._config.get("decay_half_life_days", 30.0),
                    reinforcement_boost=self._config.get("reinforcement_boost", 0.1),
                )
            payload = [
                {
                    "id": r.id,
                    "domain": r.domain,
                    "importance": r.importance,
                    "content": r.content,
                    "relevance_score": round(r.relevance_score, 3),
                }
                for r in rows
            ]
            return json.dumps({"results": payload})
        except Exception as e:
            return _tool_error(str(e))

    def _query(self, args: dict) -> str:
        if not self._scripts_dir or not self._vault_path or not self._index_db:
            return _tool_error("Vault not initialized — run entropicmem init")
        query = (args.get("query") or "").strip()
        if not query:
            return _tool_error("query required")
        top_k = int(args.get("top_k") or 5)
        try:
            ensure_scripts_on_path(self._scripts_dir)
            from index import VaultIndex
            from retrieval import retrieve
            from vault import Vault

            vault = Vault(self._vault_path)
            index = VaultIndex(self._index_db)
            results = retrieve(vault, index, query, top_k=top_k)
            index.close()
            return json.dumps({"results": results})
        except Exception as e:
            return _tool_error(str(e))

    def _patch_core(self, args: dict) -> str:
        """Handle entropicmem_patch_core tool call."""
        target = args.get("target", "")
        old_text = args.get("old_text", "")
        new_text = args.get("new_text", "")

        if not target or not old_text:
            return _tool_error("target and old_text required")

        if target not in ("persona", "user_profile"):
            return _tool_error("target must be 'persona' or 'user_profile'")

        if not self._vault_path or not self._vault_path.is_dir() or not self._scripts_dir:
            return _tool_error("Vault not initialized — run entropicmem init")

        try:
            ensure_scripts_on_path(self._scripts_dir)
            from vault import CoreMemory

            core = CoreMemory(self._vault_path)
            success = core.patch(target=target, old_text=old_text, new_text=new_text)

            if success:
                return json.dumps({"ok": True, "target": target, "patched": True})
            else:
                return _tool_error(f"Patch text not found in {target} core memory")
        except Exception as e:
            logger.exception("entropicmem_patch_core failed")
            return _tool_error(str(e))


    def _memory_engine(self):
        """Shared helper: ensure scripts on path and open a MemoryEngine context.

        Returns (engine, None) on success, or (None, error_json) on failure.
        The caller must check the second element before using engine.

        Usage:
            engine, error = self._memory_engine()
            if error:
                return error
            with engine:
                ...
        """
        if not self._memory_db or not self._scripts_dir:
            return None, _tool_error("EntropicMem not initialized")
        ensure_scripts_on_path(self._scripts_dir)
        from memory_engine import MemoryEngine
        engine = MemoryEngine(self._memory_db)
        return engine, None

    def _stats(self, args: dict) -> str:
        """Return EntropicMem memory statistics."""
        engine, error = self._memory_engine()
        if error:
            return error
        try:
            with engine:
                s = engine.stats()
            return json.dumps(s)
        except Exception as e:
            return _tool_error(str(e))

    def _get(self, args: dict) -> str:
        """Retrieve a single fact by entropic_id."""
        engine, error = self._memory_engine()
        if error:
            return error
        # Accept both 'entropic_id' (canonical) and 'id' (backward compat)
        if "id" in args and "entropic_id" not in args:
            logger.warning("entropicmem_get: deprecated 'id' argument, use 'entropic_id' instead")
        entropic_id = (args.get("entropic_id") or args.get("id") or "").strip()
        if not entropic_id:
            return _tool_error("entropic_id required")
        try:
            with engine:
                fact = engine.get_fact(entropic_id)
            if fact is None:
                return _tool_error(f"Fact not found: {entropic_id}")
            return json.dumps({
                "id": fact.id,
                "domain": fact.domain,
                "importance": fact.importance,
                "content": fact.content,
                "source": fact.source,
                "tags": fact.tags,
                "created_at": fact.created_at,
                "updated_at": fact.updated_at,
                "access_count": fact.access_count,
            })
        except Exception as e:
            return _tool_error(str(e))


def register_memory_provider(ctx) -> None:
    """Memory provider discovery entry point."""
    cfg = {}
    try:
        from hermes_constants import get_hermes_home

        cfg = load_plugin_config(get_hermes_home())
    except Exception:
        pass
    ctx.register_memory_provider(EntropicMemMemoryProvider(config=cfg))


def register(ctx) -> None:
    """General plugin loader entry point."""
    register_memory_provider(ctx)
