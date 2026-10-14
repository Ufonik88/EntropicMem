"""Tool schemas live here (EM-404 slice 1).

Split out of ``em.provider.provider`` so the tool surface and its validation
can evolve independently of the hook/state scaffolding. This slice moves the
schema constants verbatim and re-exports them; behaviour is unchanged and
``get_tool_schemas``/``handle_tool_call`` keep their signatures.
"""

from __future__ import annotations

REMEMBER_SCHEMA = {
    "name": "entropicmem_remember",
    "description": "Store a durable fact in EntropicMem (memory engine + vault projection).",
    "parameters": {
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "Fact to remember."},
            "domain": {"type": "string", "description": "Vault domain (default: Knowledge)."},
            "importance": {"type": "number", "description": "0.0–1.0 (default 0.7)."},
            "sensitivity": {
                "type": "string",
                "description": "public|internal|sensitive|secret (secret is rejected).",
            },
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

CONSOLIDATE_SCHEMA = {
    "name": "entropicmem_consolidate",
    "description": "Archive old, low-access facts to free up active memory. Returns count of archived facts.",
    "parameters": {
        "type": "object",
        "properties": {
            "max_age_days": {"type": "integer", "description": "Archive facts older than this many days (default: 90)."},
            "min_access_count": {"type": "integer", "description": "Only archive facts accessed this many times or fewer (default: 0)."},
            "dry_run": {"type": "boolean", "description": "If true (default), report only without archiving."},
            "confirm": {"type": "boolean", "description": "Must be true with dry_run=false to archive."},
        },
    },
}


__all__ = [
    "REMEMBER_SCHEMA", "RECALL_SCHEMA", "QUERY_SCHEMA", "PATCH_CORE_SCHEMA",
    "STATS_SCHEMA", "GET_SCHEMA", "CONSOLIDATE_SCHEMA",
]
