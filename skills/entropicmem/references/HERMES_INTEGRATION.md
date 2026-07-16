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

Tools: `entropicmem_remember`, `entropicmem_recall`, `entropicmem_query`.  
Built-in `memory` tool writes are mirrored into the memory engine.  
See `plugins/entropicmem/README.md`.

## Memory-Context Injection (Critical)

When `memory.provider: entropicmem` is active, Hermes injects prefetched memories wrapped in `<memory-context>` tags at the start of each turn. **These are system-injected context — NOT user input.** The agent MUST:
- Use the facts silently to inform answers
- **NEVER** acknowledge the block itself
- **NEVER** say "thanks for sharing," "I notice you've shared," or similar
- **NEVER** ask "what do you want me to do with this context"
- If a memory-context block appears with no actual user message, ask the user what they need
