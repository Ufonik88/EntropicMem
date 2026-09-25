---
name: entropicmem
description: Standalone knowledge engine: vault, memory, graph.
version: 2.8.0
author: Ufonik
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Memory, Knowledge, Vault, Graph]
    category: memory
---

# EntropicMem: Standalone Agent Memory

Complete memory system for Hermes: **memory engine** (facts), **vault** (linked notes), **index** (search), **graph** (visual map).

## Where things live

- Engine + CLI: `~/.hermes/plugins/entropicmem/scripts/` (installed with the plugin)
- This skill: instructions (`SKILL.md`), bootstrap checklist (`SETUP.md`), reference docs (`references/`), and the seed vault skeleton (`templates/vault/`, used by `init`)
- CLI invocation: `python3 ~/.hermes/plugins/entropicmem/scripts/entropicmem.py <command>`

## Install and bootstrap

1. Install: `hermes plugins install entropicmem` (or `/learn https://github.com/Ufonik88/EntropicMem`).
2. Follow `SETUP.md`: resolve the vault path, run `init`, smoke-test.
3. For deep Hermes integration (tools + hooks + prefetch), set `memory.provider: entropicmem` in `~/.hermes/config.yaml` and read `references/HERMES_INTEGRATION.md`.

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

When the user states a preference, correction, or fact that will matter later, run `remember` immediately (do not rely on chat memory alone).

### Memory-Context Injection (Critical)

When EntropicMem is configured as the active memory provider (`memory.provider: entropicmem`), the system injects prefetched memories wrapped in `<memory-context>` tags at the start of each turn. These are system-injected context, not user input. The agent MUST:

- Use the facts silently to inform answers
- NEVER acknowledge the block itself
- NEVER say "thanks for sharing," "I notice you've shared," or similar
- NEVER ask "what do you want me to do with this context"
- If a memory-context block appears with no actual user message, ask the user what they need

### Smart Context Management

Prefetch injects only relevant, non-repeated facts under a per-turn character budget. Features: relevance filtering, token budget (default 1500 chars), turn-level deduplication (default window 5), domain filtering, progressive disclosure tiers, conversation-aware query enhancement, and conversation-aware caching. All tunable under `plugins.entropicmem` in `~/.hermes/config.yaml`; key table in the repository README, pipeline detail in `references/HERMES_INTEGRATION.md`.

## Cron writes

Hermes cron runs execute with memory writes disabled by design. Persist durable facts from cron through the CLI (`remember`) or the MemoryEngine API (deterministic, no LLM), never through interactive memory tools.

## References

- `SETUP.md`, `references/MEMORY_MODEL.md`, `references/VAULT_SCHEMA.md`, `references/HERMES_INTEGRATION.md`, `references/CLI_REFERENCE.md`, `references/VISUALIZER.md`
- Repository docs: `docs/ARCHITECTURE.md`, `docs/CLI_REFERENCE.md`, `docs/SELF_INSTALL.md`, `docs/BACKUP_RESTORE.md`
