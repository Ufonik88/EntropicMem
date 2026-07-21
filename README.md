# EntropicMem — Standalone Agent Memory System

> **A self-contained knowledge engine for Hermes Agent.** Own SQLite memory, Markdown vault, visual graph, and 14-command knowledge loop. Installed via `/learn`.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Hermes Agent](https://img.shields.io/badge/Hermes-Agent-blue.svg)](https://hermes-agent.nousresearch.com)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)

---

## One-Line Description

A Hermes Agent **skill** providing a complete, standalone knowledge system — memory engine, Markdown vault, visual graph, and full ingest/query/workflow loop.

## Install via `/learn`

```bash
/learn https://github.com/Ufonik88/EntropicMem
```

The agent will fetch, install, bootstrap, and smoke-test in one pass.

## Quickstart

```bash
entropicmem init                         # Bootstrap vault + memory engine
entropicmem ingest "https://..."         # Source → notes
entropicmem query "topic" --top-k 10     # Full-text search
entropicmem remember "durable fact"      # Store in memory engine
entropicmem graph export --format html   # Galaxy graph
```

## Architecture

```
EntropicMem (This Repo)
├── memory_engine.py     # SQLite FTS5 memory engine (standalone)
├── vault.py             # Markdown vault operations
├── index.py             # Vault FTS5 index + graph edges
├── retrieval.py         # Composed search stack
├── graph_export.py      # D3 galaxy visual graph
├── entropicmem.py       # CLI: 14 commands
└── skills/entropicmem/
    ├── SKILL.md         # Agent instructions
    ├── SETUP.md         # Bootstrap checklist
    └── templates/vault/ # Seed skeleton
```

## Memory Model

| Layer | Where | Purpose |
|-------|-------|---------|
| **Memory Engine** | `~/.hermes/entropicmem/memory.db` | Durable facts with FTS5, entropic_id dedup |
| **Vault** | Markdown files | Human-browsable, linked, domain-organized |
| **Index** | `~/.hermes/entropicmem/index.db` | Vault FTS5 + graph edges for retrieval |
| **Graph** | `graph.html` | D3 galaxy visualizer |

## Commands

| Command | Description |
|---------|-------------|
| `init [--vault PATH]` | Bootstrap vault + memory engine |
| `ingest <source>` | URL/file/stdin → literature + atomic notes |
| `ingest-pile <dir>` | Batch directory ingest |
| `query "<q>"` | Cited retrieval |
| `note [title]` | Stdin → permanent note |
| `research "<q>"` | Agent-driven research brief |
| `lint` | Orphans, dead links, stale, contradictions |
| `moc` | Rebuild domain maps of content |
| `hotcache` | Refresh cache |
| `graph export --format html` | D3 galaxy graph |
| `graph serve` | Serve graph via HTTP |
| `remember "fact"` | Store in memory engine |
| `forget <id>` | Delete from memory engine |
| `memory project` | Project memory facts to vault |
| `memory stats` | Memory engine statistics |

## Visual Graph (v2.1.0)

Single-file `graph.html` — D3 force-directed, dark galaxy theme. Self-contained: full note bodies are embedded so it works offline via `file://` or `graph serve`.

- **Per-domain colors** (Ajax brand palette) + **per-type shapes** (circle=permanent, square=literature, diamond=moc, triangle=index/log).
- **Click a node** → modal renders the note's Markdown (tables, code, blockquotes) with frontmatter (domain, type, importance, tags).
- **Wikilink navigation** — `[[Target]]` in a note opens the linked note; unresolved links are flagged. Tag chips filter the graph.
- **Focus mode** — clicking a node dims everything except its direct neighbors; click empty space to release.
- **Search** — type a title and press Enter to zoom to and focus that note.
- **Filters** — domain checkboxes, tag filter, min-importance slider; node positions persist across re-filters.
- **Edge encoding** — solid = wikilink, dashed = tag co-occurrence; width scales with weight.
- **Minimap** with live viewport, **PNG export**, **Copy link** (deep-link `#note=Title`).
- **Accessible** — keyboard-focusable nodes (Enter/Space to open), `role=dialog` modal with focus return, Escape to close.

## Smart Context Management (v1.2.0)

EntropicMem now includes **intelligent context management** to optimize token usage:

### Features

- **Relevance Filtering**: Only inject facts above configurable threshold (default: 0.3)
- **Token Budget**: Limit context per turn (default: 1500 chars)
- **Deduplication**: Don't repeat facts within N turns (default: 5)
- **Domain Filtering**: Filter by knowledge domain
- **Progressive Disclosure**: High → medium → low relevance tiers
- **Conversation Context**: Use recent messages for relevance
- **Smart Cache**: Conversation-aware invalidation

### Token Savings

| Metric | Without Smart Context | With Smart Context |
|--------|----------------------|-------------------|
| **Chars/turn** | ~1500 (5 × 300) | ~200-800 |
| **Relevant facts** | All top-5 | Only relevant, non-repeated |
| **Cache** | Query-based | Conversation-aware |

**Estimated savings**: 60-80% reduction in context injection token usage.

### Configuration

```yaml
plugins:
  entropicmem:
    min_relevance_score: 0.3
    prefetch_token_budget: 1500
    dedup_window: 5
    enabled_domains: []
    high_relevance_threshold: 0.7
    medium_relevance_threshold: 0.4
    context_window_turns: 3
    cache_conversation_context: true
    cache_ttl_seconds: 300
```

See `skills/entropicmem/references/HERMES_INTEGRATION.md` for full documentation.

## Production Hardening (v1.5.0)

- **Non-blocking extraction** — `_auto_extract` runs fire-and-forget with a lock guard
- **Thread-safe injection** — `_recently_injected` guarded with `_prefetch_lock`
- **FTS parity** — `recall_with_relevance` multi-word queries search title/tags fields
- **CoreMemory delegation** — CLI `patch-core` uses `CoreMemory` class (single source of truth)
- **Context manager** — `MemoryEngine` supports `with` statements for safe cleanup

## Intelligence & Resilience (v1.6.0)

- **Fuzzy deduplication** — Jaccard similarity ≥ 0.8 catches near-duplicate facts
- **DB error recovery** — automatic FTS5 index rebuild on corruption
- **Memory consolidation** — archive old, low-access facts to `facts_archive` table
- **Auto-backup** — timestamped SQLite backups before destructive operations

## Requirements

- Python 3.10+ (stdlib only for core)
- Optional: `sentence-transformers` for semantic re-rank, `graphviz` for DOT export

## License

MIT
