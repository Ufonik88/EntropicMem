# EntropicMem — Standalone Agent Memory System

> **A self-contained knowledge engine for Hermes Agent.** SQLite memory, Markdown vault, visual graph, and a 30-command knowledge loop. Installed via `/learn`.

> **⚠️ Public repo.** This project is public-facing. Never commit personal
> data — real names, home paths, emails, IPs, employer/client details, or
> memory/graph exports. See [CONTRIBUTING.md](CONTRIBUTING.md) for the rule
> and the pre-commit checklist.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Hermes Agent](https://img.shields.io/badge/Hermes-Agent-blue.svg)](https://hermes-agent.nousresearch.com)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![CI](https://github.com/Ufonik88/EntropicMem/actions/workflows/test.yml/badge.svg)](https://github.com/Ufonik88/EntropicMem/actions/workflows/test.yml)

---

## What It Is

A Hermes Agent **memory provider + skill** delivering a complete, standalone knowledge system:

| Component | What it does |
|-----------|--------------|
| **Memory engine** | Durable facts with FTS5 search, dedup, versioning, audit log, quarantine |
| **Episodic memory** | Session summaries with time-windowed recall |
| **Knowledge triples** | Subject–predicate–object graph with neighbors, paths, inconsistency checks |
| **Embeddings** | BGE-small vectors with hybrid FTS+vector recall (optional dep) |
| **Vault** | Human-browsable, linked, domain-organized Markdown notes |
| **Index** | Vault FTS5 + graph edges powering cited retrieval |
| **Visual graph** | Self-contained D3 galaxy HTML export with lazy wikilink resolution |
| **MemoryProvider plugin** | 7 `entropicmem_*` tools wired into Hermes' memory system |

## Install via `/learn`

```bash
/learn https://github.com/Ufonik88/EntropicMem
```

The agent will fetch, install, bootstrap, and smoke-test in one pass.

## Quickstart

```bash
entropicmem init                         # Bootstrap vault + memory engine
entropicmem ingest "https://..."         # Source → notes
entropicmem query "topic" --top-k 10     # Cited vault search
entropicmem recall "durable fact"        # Memory engine search
entropicmem remember "durable fact"      # Store in memory engine
entropicmem graph export --format html   # Galaxy graph (./export/graph.html)
```

## Repository Layout

```
EntropicMem/
├── skills/entropicmem/
│   ├── SKILL.md                 # Agent instructions (loaded by /learn)
│   ├── SETUP.md                 # First-run bootstrap checklist
│   ├── scripts/                 # Engine + CLI (stdlib-only core)
│   │   ├── memory_engine.py     # SQLite FTS5 memory engine
│   │   ├── vault.py             # Markdown vault operations
│   │   ├── index.py             # Vault FTS5 index + graph edges
│   │   ├── retrieval.py         # Composed retrieval stack
│   │   ├── graph_export.py      # D3 galaxy visual graph
│   │   ├── policy.py / pii.py   # Write policy + PII redaction
│   │   ├── embeddings.py        # Vector search (optional)
│   │   └── entropicmem.py       # CLI
│   ├── references/              # Agent-facing docs (memory model, integration)
│   └── templates/vault/         # Seed vault skeleton
├── plugins/entropicmem/         # Hermes MemoryProvider (7 tools)
├── scripts/graph_server/        # FastAPI graph server (token-gated)
├── benchmarks/                  # Frozen recall benchmark (corpus, probes, runner)
├── docs/                        # User-facing docs (see index below)
├── tests/                       # 300+ tests
└── .github/workflows/test.yml   # CI: pytest (3.10–3.12) + ruff
```

## Memory Model

Five cooperating layers — see [docs/MEMORY_MODEL.md](docs/MEMORY_MODEL.md) for the full model:

| Layer | Where | Purpose |
|-------|-------|---------|
| **Hot cache** | `Wiki-Cache.md` | Instant orientation each session |
| **Facts** | `~/.hermes/entropicmem/memory.db` | Durable facts, episodes, triples, embeddings |
| **Vault** | Markdown files | Human-browsable, linked, domain-organized |
| **Index** | `~/.hermes/entropicmem/index.db` | Vault FTS5 + graph edges for retrieval |
| **Graph** | `export/graph.html` | D3 galaxy visualizer |

**Explainable recall (D1):** Every `recall()` / `recall_with_relevance()` / `recall_hybrid()` hit carries a `why_retrieved` field — a deterministic list of reason tokens (`exact`, `fts`, `vector`, `recency`, `importance`, `triple`, `domain`; the LIKE-fallback path also reports `fts`) so you can audit why a fact surfaced. The plugin's `entropicmem_recall` tool exposes it in its JSON output.

**Recall benchmark (D2):** Run `PYTHONPATH="skills/entropicmem/scripts" python3 benchmarks/run_recall_bench.py` to measure `precision@5` and `MRR` against a frozen 98-fact corpus with 20 probes. CI enforces a floor (`precision@5 >= 0.50`, `MRR >= 0.50`); first run: `precision@5 = 0.98`, `MRR = 0.975`.

## Commands

30 top-level commands in 8 groups. Full reference: [docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md).

| Group | Commands |
|-------|----------|
| Vault & knowledge | `init`, `ingest`, `ingest-pile`, `query`, `note`, `research`, `lint`, `moc`, `hotcache`, `open` |
| Memory engine | `remember`, `recall`, `forget --confirm`, `memory stats/list/project/reindex`, `extract`, `reinforce`, `history`, `consolidate --confirm` |
| Episodic & triples | `episode add/list/stats`, `triple extract/list/stats/neighbors/path/inconsistencies` |
| Index & graph | `index rebuild/status`, `graph export/serve/show` |
| Vectors & time | `embed --rebuild`, `timeline` |
| Security | `security enable/disable/status`, `patch-core` |
| Portability | `export`, `import` |
| Governance | `audit`, `pending list/promote/discard` |

## Hermes Integration (sole memory provider)

```yaml
memory:
  provider: entropicmem
```

- **Interactive tools:** `entropicmem_remember`, `entropicmem_recall`, `entropicmem_query`, `entropicmem_patch_core`, `entropicmem_stats`, `entropicmem_get`, `entropicmem_consolidate` — plus the built-in `memory` tool.
- **Prefetch injection:** relevant facts are prefetched into `<memory-context>` each turn. These are system-injected context, not user input.
- **Lifecycle hooks:** `on_session_end` writes an extractive session digest episode (idempotent per session) and runs quarantine-first extraction; `on_turn_start` flushes a partial digest every N turns for always-on sessions; `on_pre_compress` feeds a standing-constraints digest into the compression summary prompt and persists it. Config under `plugins.entropicmem` (`session_end_capture`, `turn_cadence_flush_turns`, `turn_cadence_min_interval_sec`, `session_extract_pending`) — see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
- **Cron:** Hermes cron runs use `skip_memory=True`; durable writes go through a deterministic helper script (no LLM).
- **Full integration guide:** [skills/entropicmem/references/HERMES_INTEGRATION.md](skills/entropicmem/references/HERMES_INTEGRATION.md)

## Security

- **Write policy** — secrets and credentials are blocked; auto-extracted facts are quarantined as pending; PII is redacted.
- **Destructive gates** — `forget` and `consolidate` require `--confirm`; both auto-backup before running.
- **Audit log** — every write is append-only audited.
- **Graph server** — localhost bind + token-gated refresh; note bodies embedded by default, `--no-bodies` for shareable lean shells.
- **Backups** — AES-256-CBC encrypted before cloud upload. See [docs/BACKUP_RESTORE.md](docs/BACKUP_RESTORE.md).

## Smart Context Management

Prefetch relevance filtering, per-turn token budgets, dedup windows, and progressive disclosure — defaults tuned to cut context-injection usage 60–80%. Configuration lives under `plugins.entropicmem` in `~/.hermes/config.yaml`. Details in [HERMES_INTEGRATION.md](skills/entropicmem/references/HERMES_INTEGRATION.md).

## Documentation

| Doc | Content |
|-----|---------|
| [docs/MEMORY_MODEL.md](docs/MEMORY_MODEL.md) | The five-layer memory model + write policy |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Component architecture, storage layout, data flow |
| [docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md) | All commands and subcommands |
| [docs/VISUALIZER.md](docs/VISUALIZER.md) | Graph UI: zoom, overlays, wikilink resolution, shortcuts |
| [docs/BACKUP_RESTORE.md](docs/BACKUP_RESTORE.md) | Encrypted backup + restore drill |
| [docs/SELF_INSTALL.md](docs/SELF_INSTALL.md) | `/learn` install flow |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Public-repo rules + commit checklist |
| [CHANGELOG.md](CHANGELOG.md) | Release history |
| [benchmarks/run_recall_bench.py](benchmarks/run_recall_bench.py) | Recall benchmark runner (precision@5 / MRR) |

## Requirements

- Python 3.10+ (stdlib only for the core path)
- Optional: `sentence-transformers` for semantic search, `graphviz` for DOT export

## License

MIT
