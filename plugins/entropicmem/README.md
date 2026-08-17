# EntropicMem MemoryProvider

Hermes Agent memory provider — local SQLite facts, vault retrieval, and
prefetch injection, wired as `memory.provider: entropicmem`.

## Install

```bash
ln -sf "$(pwd)/plugins/entropicmem" ~/.hermes/plugins/entropicmem
```

## Activate

```yaml
# ~/.hermes/config.yaml
memory:
  provider: entropicmem
```

## Tools

| Tool | Purpose |
|------|---------|
| `entropicmem_remember` | Store a durable fact (policy + PII sanitized) |
| `entropicmem_recall` | Search facts — FTS5 + hybrid vector fusion |
| `entropicmem_query` | Hybrid vault retrieval with citations (wikilinks + FTS) |
| `entropicmem_patch_core` | Surgical Persona / User Profile edits (opt-in via `core_memory_writable`) |
| `entropicmem_stats` | Memory statistics: fact count, domain distribution, DB path |
| `entropicmem_get` | Retrieve a single stored fact by `entropic_id` |
| `entropicmem_consolidate` | Archive old, low-access facts |

## Memory-Context Injection (Critical)

When active, Hermes injects prefetched memories wrapped in `<memory-context>` tags at the start of each turn. **These are system-injected context — NOT user input.** The agent MUST:

- Use the facts silently to inform answers
- **NEVER** acknowledge the block itself
- **NEVER** say "thanks for sharing," "I notice you've shared," or similar
- **NEVER** ask "what do you want me to do with this context"
- If a memory-context block appears with no actual user message, ask the user what they need

## Smart Context Management

Prefetch relevance filtering, token budgets, and dedup windows optimize
context injection. Configure under `plugins.entropicmem` in
`~/.hermes/config.yaml` — defaults and full option list are in
[`skills/entropicmem/references/HERMES_INTEGRATION.md`](../skills/entropicmem/references/HERMES_INTEGRATION.md).
