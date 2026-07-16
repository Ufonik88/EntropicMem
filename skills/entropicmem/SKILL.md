---
name: entropicmem
description: Standalone knowledge engine: vault, memory, graph. Use for ingest, query, remember.
version: 0.5.0
author: Hermes
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Memory, Knowledge, Vault, Graph]
    category: memory
---

# EntropicMem — Standalone Agent Memory

A self-contained knowledge engine for Hermes Agent. Own SQLite memory, Markdown vault, visual graph, and full ingest/query/workflow loop.

## Quick Start

```bash
entropicmem init                    # Bootstrap vault + memory engine
entropicmem ingest "https://..."    # Source → literature + atomic notes
entropicmem query "topic"           # Full-text search with citations
entropicmem remember "durable fact" # Store in memory engine
entropicmem graph export --format html  # Galaxy graph
```

## When to Use

- Creating or seeding a knowledge vault
- Ingesting web sources, files, or conversation into durable notes
- Querying linked notes with cited results
- Storing durable facts in the memory engine
- Visualizing knowledge as a galaxy graph
- Maintaining vault health (lint, moc, hotcache)

## Workflows

### 1. Bootstrap
```bash
entropicmem init [--vault PATH]
```

### 2. Ingest
```bash
entropicmem ingest <url|file|-> [--domain DOMAIN]
```

### 3. Query
```bash
entropicmem query "<query>" [--top-k N] [--domain DOMAIN] [--semantic]
```

### 4. Store Durable Facts
```bash
entropicmem remember "fact" [--domain DOMAIN] [--tags t1,t2]
entropicmem forget <entropic_id>
```

### 5. Visual Graph
```bash
entropicmem graph export --format html
entropicmem graph serve --port 8080
```

### 6. Maintain
```bash
entropicmem lint          # Orphans, dead links, stale
entropicmem moc           # Rebuild domain indexes
entropicmem hotcache      # Refresh Wiki-Cache.md
entropicmem memory stats  # Engine statistics
```

## Prerequisites

- Python 3.10+ (stdlib only for core)
- Optional: `sentence-transformers` for semantic re-rank

## References

- `SETUP.md` — first-run checklist
- `references/MEMORY_MODEL.md` — architecture
- `references/VAULT_SCHEMA.md` — structure
- `references/CLI_REFERENCE.md` — every subcommand
- `references/VISUALIZER.md` — graph spec
EOF