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


def _tool_error(msg: str) -> str:
    try:
        from tools.registry import tool_error

        return tool_error(msg)
    except Exception:
        return json.dumps({"error": msg})


class EntropicMemMemoryProvider(MemoryProvider):
    """Hermes MemoryProvider backed by EntropicMem MemoryEngine + vault."""

    def __init__(self, config: Optional[dict] = None):
        self._config = config or {}
        self._scripts_dir: Optional[Path] = None
        self._hermes_home: Optional[Path] = None
        self._vault_path: Optional[Path] = None
        self._index_db: Optional[Path] = None
        self._memory_db: Optional[Path] = None
        self._session_id = ""
        self._prefetch_lock = threading.Lock()
        self._prefetch_cache: str = ""
        self._last_query: str = ""

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
        q = (query or self._last_query or "").strip()
        if not q or not self._scripts_dir or not self._memory_db:
            return ""
        with self._prefetch_lock:
            if self._prefetch_cache and q == self._last_query:
                return self._prefetch_cache
        try:
            from memory_engine import MemoryEngine

            engine = MemoryEngine(self._memory_db)
            rows = engine.recall(q, top_k=5)
            engine.close()
            if not rows:
                return ""
            lines = [f"- [{r.id}] {r.content[:300]}" for r in rows]
            block = "## EntropicMem recall\n" + "\n".join(lines)
            with self._prefetch_lock:
                self._prefetch_cache = block
            return block
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
        # Explicit tools + on_memory_write mirror; no silent auto-ingest in v1.1.
        pass

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        return [REMEMBER_SCHEMA, RECALL_SCHEMA, QUERY_SCHEMA]

    def handle_tool_call(self, tool_name: str, args: Dict[str, Any], **kwargs) -> str:
        if tool_name == "entropicmem_remember":
            return self._remember(args)
        if tool_name == "entropicmem_recall":
            return self._recall(args)
        if tool_name == "entropicmem_query":
            return self._query(args)
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
            engine = MemoryEngine(self._memory_db)
            engine.remember(
                content=content,
                title=content[:60],
                domain=domain,
                tags=["mirrored", target],
                source="built_in_memory",
                importance=0.75 if target == "user" else 0.6,
            )
            engine.close()
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
            from memory_engine import MemoryEngine
            from vault import Vault
            from index import VaultIndex

            engine = MemoryEngine(self._memory_db)
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
                vault_note = str(
                    vault.write_note(
                        domain,
                        f"Fact - {content[:50]}",
                        body,
                        tags=["durable", "agent"],
                        domain=domain,
                        frontmatter={"entropic_id": eid},
                    )
                )
                if self._index_db:
                    idx = VaultIndex(self._index_db)
                    note = vault.read_note(vault_note)
                    idx.upsert_note(note)
                    idx.upsert_edges_for_note(vault, note)
                    idx.close()
            engine.close()
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

            engine = MemoryEngine(self._memory_db)
            rows = engine.recall(query, top_k=limit)
            engine.close()
            payload = [
                {
                    "id": r.id,
                    "domain": r.domain,
                    "importance": r.importance,
                    "content": r.content,
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
            from vault import Vault
            from index import VaultIndex
            from retrieval import retrieve

            vault = Vault(self._vault_path)
            index = VaultIndex(self._index_db)
            results = retrieve(vault, index, query, top_k=top_k)
            index.close()
            return json.dumps({"results": results})
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