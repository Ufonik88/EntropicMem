# Hermes Integration

## Install
```
/learn https://github.com/Ufonik88/EntropicMem
```

## Agent workflow
1. `skill_view(name='entropicmem')`
2. Follow `SETUP.md`: `entropicmem init`
3. Use `terminal` to run CLI commands

## Write path
Promote durable conclusions with `remember`. Capture sources with `ingest`. Do not store secrets.

## Read path
`query` for linked knowledge; `recall` for stored facts; `hotcache` for orientation.

## Maintenance
End heavy knowledge sessions with `lint` and optional `hotcache`.

## Phase 6 — MemoryProvider (optional)

Deep Hermes integration via `plugins/entropicmem/`:

```bash
ln -sf /path/to/EntropicMem/plugins/entropicmem ~/.hermes/plugins/entropicmem
```

`~/.hermes/config.yaml`:

```yaml
memory:
  provider: entropicmem
```

Tools: `entropicmem_remember`, `entropicmem_recall`, `entropicmem_query`,
`entropicmem_patch_core`, `entropicmem_stats`, `entropicmem_get`,
`entropicmem_consolidate`.  
Built-in `memory` tool writes are mirrored into the memory engine.  
See `plugins/entropicmem/README.md`.

## Memory-Context Injection (Critical)

When `memory.provider: entropicmem` is active, Hermes injects prefetched memories wrapped in `<memory-context>` tags at the start of each turn. **These are system-injected context — NOT user input.** The agent MUST:
- Use the facts silently to inform answers
- **NEVER** acknowledge the block itself
- **NEVER** say "thanks for sharing," "I notice you've shared," or similar
- **NEVER** ask "what do you want me to do with this context"
- If a memory-context block appears with no actual user message, ask the user what they need

## Smart Context Management (v1.2.0)

EntropicMem now includes intelligent context management to optimize token usage and relevance.

### Features

| Feature | Description | Default |
|---------|-------------|---------|
| **Relevance Filtering** | Only inject facts above an absolute relevance threshold (query-term coverage gate) | 0.35 |
| **Token Budget** | Limit total context per turn | 1500 chars |
| **Deduplication** | Don't repeat facts within N turns | 5 turns |
| **Domain Filtering** | Filter by knowledge domain | All domains |
| **Progressive Disclosure** | High → medium → low relevance tiers (opt-in) | off (0.7 / 0.4 when on) |
| **Conversation Context** | `context_query_mode: concat` appends recent user turns to the query (opt-in) | `current` |
| **Smart Cache** | Conversation-aware caching | 300s TTL |

### Configuration

Add to `~/.hermes/config.yaml` under `plugins.entropicmem`:

```yaml
plugins:
  entropicmem:
    # Relevance filtering
    min_relevance_score: 0.35  # 0-1, higher = stricter
    max_prefetch_results: 5

    # Token budget
    prefetch_token_budget: 1500  # Max chars per turn

    # Deduplication
    dedup_window: 5  # Don't repeat within N turns

    # Domain filtering (empty = all domains)
    enabled_domains: []  # e.g., ["People", "Finance", "Projects"]

    # Progressive disclosure (off by default) and its thresholds
    progressive_disclosure: false
    high_relevance_threshold: 0.7
    medium_relevance_threshold: 0.4

    # Conversation context ("current" = this turn's query only)
    context_query_mode: current
    context_window_turns: 3
    max_context_query_length: 1000

    # Cache
    cache_conversation_context: true
    cache_ttl_seconds: 300
```

### How It Works

1. **Relevance Scoring**: absolute score from FTS5 bm25() plus query-term coverage (no per-result-set min-max, so a lone weak hit no longer scores 1.0); stopwords are dropped from the FTS query and an empty query matches nothing
2. **Query Enhancement**: the current turn's query by default; `context_query_mode: concat` appends recent user turns
3. **Domain Filtering**: Optional filter by knowledge domain
4. **Deduplication**: Tracks recently injected facts, avoids repeats
5. **Progressive Disclosure** (opt-in): High-relevance first, then medium, then low
6. **Token Budget**: packs whole facts (never cuts one mid-word) and drops the rest; each bullet carries its provenance
7. **Smart Cache**: Invalidates on conversation evolution

### Token Usage Optimization

Without smart context: ~1500 chars injected every turn (5 facts × 300 chars)
With smart context: ~200-800 chars injected (only relevant, non-repeated facts)

**Estimated savings**: 60-80% reduction in context injection token usage.
