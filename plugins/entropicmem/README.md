# EntropicMem MemoryProvider

Hermes Agent memory provider: local SQLite facts, vault retrieval, and prefetch injection, wired as `memory.provider: entropicmem`. The engine and CLI live in `scripts/` inside this directory, so the plugin is self-contained for catalog installs.

## Install

Catalog (recommended):

```bash
hermes plugins install entropicmem
```

Development checkout:

```bash
ln -sf "/path/to/EntropicMem/plugins/entropicmem" ~/.hermes/plugins/entropicmem
```

## Activate

```yaml
# ~/.hermes/config.yaml
memory:
  provider: entropicmem
```

Then bootstrap a vault:

```bash
python3 ~/.hermes/plugins/entropicmem/scripts/entropicmem.py init
```

## Tools

| Tool | Purpose |
|------|---------|
| `entropicmem_remember` | Store a durable fact (policy + PII sanitized) |
| `entropicmem_recall` | Search facts, FTS5 + hybrid vector fusion, `why_retrieved` on every hit |
| `entropicmem_query` | Hybrid vault retrieval with citations (wikilinks + FTS) |
| `entropicmem_patch_core` | Surgical Persona / User Profile edits (opt-in via `core_memory_writable`) |
| `entropicmem_stats` | Memory statistics: fact count, domain distribution, DB path |
| `entropicmem_get` | Retrieve a single stored fact by `entropic_id` |
| `entropicmem_consolidate` | Archive old, low-access facts (gated) |

## Hooks

`on_memory_write`, `on_session_switch`, `on_session_end`, `on_turn_start`, `on_pre_compress`. Behavior and config keys: [docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md).

## Memory-Context Injection (Critical)

When active, Hermes injects prefetched memories wrapped in `<memory-context>` tags at the start of each turn. These are system-injected context, not user input. The agent MUST:

- Use the facts silently to inform answers
- NEVER acknowledge the block itself
- NEVER say "thanks for sharing," "I notice you've shared," or similar
- NEVER ask "what do you want me to do with this context"
- If a memory-context block appears with no actual user message, ask the user what they need

## Smart Context Management

Prefetch relevance filtering, token budgets, and dedup windows optimize context injection. Configure under `plugins.entropicmem` in `~/.hermes/config.yaml`; defaults and the full option list are in [`skills/entropicmem/references/HERMES_INTEGRATION.md`](../../skills/entropicmem/references/HERMES_INTEGRATION.md).
