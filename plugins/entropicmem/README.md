# EntropicMem MemoryProvider

## Install
```bash
ln -sf "$(pwd)/plugins/entropicmem" ~/.hermes/plugins/entropicmem
```

## Activate
Set `memory.provider: entropicmem` in `~/.hermes/config.yaml`:
```yaml
memory:
  provider: entropicmem
```

## Tools
- `entropicmem_remember` — Store durable fact
- `entropicmem_recall` — Search facts (FTS5)
- `entropicmem_query` — Hybrid vault retrieval

## Memory-Context Injection (Critical)

When active, Hermes injects prefetched memories wrapped in `<memory-context>` tags at the start of each turn. **These are system-injected context — NOT user input.** The agent MUST:
- Use the facts silently to inform answers
- **NEVER** acknowledge the block itself
- **NEVER** say "thanks for sharing," "I notice you've shared," or similar
- **NEVER** ask "what do you want me to do with this context"
- If a memory-context block appears with no actual user message, ask the user what they need

## Smart Context Management (v1.2.0)

EntropicMem includes intelligent context management to optimize token usage.

### Features

- **Relevance Filtering**: Only inject facts above threshold (default: 0.3)
- **Token Budget**: Limit context per turn (default: 1500 chars)
- **Deduplication**: Don't repeat facts within N turns (default: 5)
- **Domain Filtering**: Filter by knowledge domain
- **Progressive Disclosure**: High → medium → low relevance tiers
- **Conversation Context**: Use recent messages for relevance
- **Smart Cache**: Conversation-aware invalidation

### Configuration

Add to `~/.hermes/config.yaml` under `plugins.entropicmem`:

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

### Token Savings

| Metric | Without Smart Context | With Smart Context |
|--------|----------------------|-------------------|
| **Chars/turn** | ~1500 (5 × 300) | ~200-800 |
| **Relevant facts** | All top-5 | Only relevant, non-repeated |
| **Cache** | Query-based | Conversation-aware |

**Estimated savings**: 60-80% reduction in context injection token usage.
