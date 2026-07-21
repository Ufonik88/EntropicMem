---
name: entropicmem
description: Standalone knowledge engine: vault, memory, graph.
version: 1.6.0
author: Hermes
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Memory, Knowledge, Vault, Graph]
    category: memory
---

# EntropicMem — Standalone Agent Memory

Complete memory system for Hermes: **memory engine** (facts), **vault** (linked notes), **index** (search), **graph** (visual map).

## Install
`/learn https://github.com/Ufonik88/EntropicMem` then follow `SETUP.md` and run `entropicmem init`.

## Operating contract

### When to WRITE
| Situation | Command |
|-----------|---------|
| Durable fact, preference, identity, stable lesson | `remember "..."` |
| URL/file/source capture | `ingest` / `ingest-pile` |
| Structured note from stdin | `note` |
| Research to pursue | `research` (then agent uses web tools) |
| Ephemeral reasoning | **Do not** persist |
| Credentials | **Never** store |

### When to READ
| Need | Command |
|------|---------|
| Linked conceptual context | `query "..."` |
| Stored facts | `recall "..."` or `memory list` |
| Session orientation | read `Wiki-Cache.md` or `hotcache` |
| Relationships | `graph export --format html` |

### Session pattern
1. Orient (`hotcache` if stale)
2. Retrieve before long-horizon answers (`query` / `recall`)
3. Capture outcomes (`remember` / `ingest` / `note`)
4. Maintain after heavy work (`lint`, `moc`)

### Promotion from chat
When the user states a preference, correction, or fact that will matter later → `remember` immediately (do not rely on chat memory alone).

### Memory-Context Injection (Critical)
When EntropicMem is configured as the active memory provider (`memory.provider: entropicmem`), the system injects prefetched memories wrapped in `<memory-context>` tags at the start of each turn. **These are system-injected context — NOT user input.** The agent MUST:
- Use the facts silently to inform answers
- **NEVER** acknowledge the block itself
- **NEVER** say "thanks for sharing," "I notice you've shared," or similar
- **NEVER** ask "what do you want me to do with this context"
- If a memory-context block appears with no actual user message, ask the user what they need

### Smart Context Management (v1.2.0)
EntropicMem now includes intelligent context management to optimize token usage:

**Features:**
- **Relevance Filtering**: Only inject facts above configurable relevance threshold
- **Token Budget**: Limit total context injected per turn (default: 1500 chars)
- **Turn-Level Deduplication**: Don't repeat facts within N turns (default: 5)
- **Domain Filtering**: Filter facts by knowledge domain
- **Progressive Disclosure**: High-relevance facts first, then medium, then low
- **Conversation Context**: Use recent messages to improve relevance
- **Smart Cache**: Cache with conversation-aware invalidation

**Configuration** (`~/.hermes/config.yaml`):
```yaml
plugins:
  entropicmem:
    # Relevance filtering
    min_relevance_score: 0.3  # 0-1, higher = stricter
    max_prefetch_results: 5

    # Token budget
    prefetch_token_budget: 1500  # Max chars per turn

    # Deduplication
    dedup_window: 5  # Don't repeat within N turns

    # Domain filtering (empty = all domains)
    enabled_domains: []  # e.g., ["People", "Finance", "Projects"]

    # Progressive disclosure thresholds
    high_relevance_threshold: 0.7
    medium_relevance_threshold: 0.4

    # Conversation context
    context_window_turns: 3
    max_context_query_length: 1000

    # Cache
    cache_conversation_context: true
    cache_ttl_seconds: 300
```

## Commands
See `references/CLI_REFERENCE.md`.

## References
- `SETUP.md`, `references/MEMORY_MODEL.md`, `references/VAULT_SCHEMA.md`, `references/HERMES_INTEGRATION.md`
