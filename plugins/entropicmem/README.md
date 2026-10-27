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

Pip install (engine + provider in one distribution):

```bash
pip install entropicmem
```

The distribution declares the host's own `hermes_agent.memory_providers` entry point
(`entropicmem = entropicmem_plugin:register`) and ships the engine's flat modules, the
`em.*` packages and this whole plugin directory as the `entropicmem_plugin` package, so
`hermes memory setup` finds `entropicmem` exactly as a catalog install does — the
dashboard panel and `hermes entropicmem …` come from the shipped `config_schema.py` and
`cli.py`. It needs a host release that has `spawn_context_thread` and `RecallStatus`
(declared as `requires_hermes: ">=0.21.3"` in `plugin.yaml`).

Optional extras — the base install is stdlib-only, and every extra is opt-in:

| Extra | What it adds |
|---|---|
| `pip install "entropicmem[semantic]"` | `fastembed` — the ONNX embedding backend (no torch) behind `embeddings_enabled: true` |
| `pip install "entropicmem[semantic-st]"` | the v2 semantic re-ranker's stack: `sentence-transformers`, `numpy`, `scikit-learn` |
| `pip install "entropicmem[graph]"` | `graphviz`, for the DOT renderer (`graph export --format dot`) |
| `pip install "entropicmem[security]"` | `cryptography`, for the encrypted-store commands |
| `pip install "entropicmem[serve]"` | `fastapi` + `uvicorn`, for `graph serve` |
| `pip install "entropicmem[dev]"` | `pytest` + `ruff`, for working on this repo |

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
| `entropicmem_remember` | Store a durable memory (policy + PII sanitized) |
| `entropicmem_search` | Search memories/episodes/notes/shared facts by query or `ids`, `why` on every hit |
| `entropicmem_update` | Correct a stored memory in place (v3 store) |
| `entropicmem_forget` | Forget by id, or preview matching candidates and confirm with a token |
| `entropicmem_timeline` | Episodes by time window, optionally matched against a query |
| `entropicmem_entity` | Entity card: aliases, links and relations (v3 store) |
| `entropicmem_profile` | Read or patch Core Memory (Persona / User Profile; patching is opt-in via `core_memory_writable`) |
| `entropicmem_review` | Pending-item review: list/promote/discard, restore, and consolidate preview |
| `entropicmem_stats` | Memory statistics: fact count, domain distribution, DB path |

The legacy names (`recall`, `query`, `patch_core`, `get`, `consolidate`) route through an alias map for one minor version; their responses carry `deprecated_tool`.

## Hooks

`on_memory_write`, `on_session_switch`, `on_session_end`, `on_turn_start`, `on_pre_compress`, `on_delegation`. Behavior and config keys: [docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md).

## Memory-Context Injection (Critical)

When active, Hermes injects prefetched memories wrapped in `<memory-context>` tags at the start of each turn. These are system-injected context, not user input. The agent MUST:

- Use the facts silently to inform answers
- NEVER acknowledge the block itself
- NEVER say "thanks for sharing," "I notice you've shared," or similar
- NEVER ask "what do you want me to do with this context"
- If a memory-context block appears with no actual user message, ask the user what they need

## Smart Context Management

Prefetch relevance filtering, token budgets, and dedup windows optimize context injection. Configure under `plugins.entropicmem` in `~/.hermes/config.yaml` — the schema is `config_schema.py`, the defaults come from the typed model in `scripts/em/config.py` (EM-407). The full option list and behaviour notes are in [`skills/entropicmem/references/HERMES_INTEGRATION.md`](../../skills/entropicmem/references/HERMES_INTEGRATION.md).
