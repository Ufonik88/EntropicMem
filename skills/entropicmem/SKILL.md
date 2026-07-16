---
name: entropicmem
description: Hermes second brain: vault, Mnemosyne bridge, galaxy graph. Use for ingest, query, lint, graph.
version: 0.1.0
author: Hermes
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Vault, Memory, Graph, Mnemosyne, Knowledge-Base]
    category: memory
    related_skills: [obsidian, llm-wiki, mnemosyne-cron-writes]
---

# EntropicMem — Agent-Native Second Brain

Build and maintain an Obsidian-style vault on top of Mnemosyne working memory. Provides a 6-command knowledge loop, galaxy-themed visual graph, and explicit Mnemosyne↔vault round-trip sync.

## When to Use

- **Create/seed a vault** — `/learn` this skill, then `entropicmem init`
- **Ingest sources** — URL, file, or conversation → literature + atomic permanent notes
- **Query linked notes** — cited retrieval with wikilink expansion (not raw Mnemosyne recall)
- **Visualize knowledge** — export galaxy graph (`graph.html`) and serve locally
- **Promote durable facts** — `entropicmem remember "fact"` writes to vault + Mnemosyne
- **Maintain health** — `lint` finds orphans, dead links, stale notes, contradictions
- **Sync Mnemosyne mirror** — cron runs `bridge export` to project durable memories to `Mnemosyne/`

## Division of Labor

| Task | Use |
|------|-----|
| General chat, preferences, transient facts | Mnemosyne (`memory` tool) |
| Durable linked knowledge, graph, human-browsable vault | EntropicMem (`entropicmem` CLI) |

## Quick Start

```bash
# After /learn installs this skill:
entropicmem init                    # Bootstraps vault + index + env vars
entropicmem ingest "https://..."    # Ingest source → lit + permanents
entropicmem query "topic"           # Cited retrieval
entropicmem graph export --format html  # Galaxy graph
```

## Workflows

### 1. Bootstrap (first run after `/learn`)
See `SETUP.md` — resolves vault path, writes `.env`, seeds templates, runs smoke tests.

### 2. Ingest a Source
```bash
entropicmem ingest "https://arxiv.org/abs/2301.00001" --domain Knowledge
# Creates: inbox/Lit-*.md + Knowledge/* permanents with wikilinks
```

### 3. Query the Vault
```bash
entropicmem query "transformer attention" --top-k 10
# Returns: cited note paths + snippets + graph context
```

### 4. Lint & Maintain
```bash
entropicmem lint              # Orphans, dead links, >90d stale, contradictions
entropicmem moc               # Rebuilds domain Index.md + backlinks
entropicmem hotcache          # Refreshes Wiki-Cache.md
```

### 5. Visual Graph
```bash
entropicmem graph export --format html --max-nodes 500
entropicmem graph serve       # Opens http://localhost:8080/graph.html
```

### 6. Promote Durable Fact (Vault + Mnemosyne)
```bash
entropicmem remember "VaultKnox evaluates policies at request time" \
  --domain Infrastructure --tags vaultknox,policy
# Creates permanent note + Mnemosyne row with same entropic_id
```

### 7. Mnemosyne → Vault Mirror (Cron)
```bash
# In Hermes cron or systemd:
entropicmem bridge export --since "$(date -d '6 hours ago')"
# Projects scope=global memories to Mnemosyne/ as permanent notes
```

## Tool Framing

- **Vault ops** → invoke via `terminal` tool: `entropicmem <subcommand>`
- **File reads/writes** → `read_file` / `write_file` / `patch` on vault paths
- **Search** → `search_files` for content/filename patterns
- **Web sources** → `web_extract` for URLs, `web_search` for research
- **Mnemosyne** → `mnemosyne_remember` / `mnemosyne_recall` tools (via bridge)

## Prerequisites

- Python 3.10+ (stdlib + `jinja2`; `sentence-transformers` optional for semantic rerank)
- Mnemosyne DB at `~/.hermes/mnemosyne/data/mnemosyne.db`
- Existing Obsidian vault at `~/Documents/Obsidian Vault` (optional — safe-mode bind)

## Verification

```bash
entropicmem lint          # 0 errors on fresh vault
entropicmem --check-deps  # Reports optional dep status
entropicmem --version     # Prints version
```

## References

- `SETUP.md` — first-run checklist (vault resolution, env vars, init, smoke test)
- `references/MEMORY_MODEL.md` — 5-layer memory model, entropic_id round-trip
- `references/VAULT_SCHEMA.md` — frontmatter, domains, tag taxonomy, linking rules
- `references/CLI_REFERENCE.md` — every subcommand with examples
- `references/VISUALIZER.md` — D3 spec, node/edge schema, palette, physics
- `references/HERMES_INTEGRATION.md` — /learn flow, safe-mode guards, coexistence

## Pitfalls

- **Never write** `Mnemosyne/`, `.obsidian/`, `_archive/` — guarded in `vault.py`
- **Embeddings optional** — FTS5 is mandatory path; semantic rerank degrades gracefully
- **Graph caps at 500 nodes** — filter by domain/importance for large vaults
- **`/learn` cannot pip-install** — core runs stdlib-only; optional deps documented in SETUP.md

