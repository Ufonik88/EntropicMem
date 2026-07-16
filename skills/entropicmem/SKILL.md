---
name: entropicmem
description: Standalone knowledge engine: vault, memory, graph.
version: 1.0.0
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

## Commands
See `references/CLI_REFERENCE.md`.

## References
- `SETUP.md`, `references/MEMORY_MODEL.md`, `references/VAULT_SCHEMA.md`, `references/HERMES_INTEGRATION.md`
