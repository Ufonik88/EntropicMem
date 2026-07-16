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
