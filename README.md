# EntropicMem — Hermes Agent Second Brain

> **Build and maintain an agent-native Obsidian vault with Mnemosyne bridge, graph visualizer, and a 6-command knowledge loop.** Installed via Hermes `/learn` command.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Hermes Agent](https://img.shields.io/badge/Hermes-Agent-blue.svg)](https://hermes-agent.nousresearch.com)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)

---

## One-Line Description

A Hermes Agent **skill** that provides a durable, linked, browsable knowledge layer (Obsidian vault) on top of Mnemosyne working memory — with a galaxy-themed visual graph, Mnemosyne↔vault round-trip sync, and a Karpathy-style `ingest/query/lint/graph` workflow.

## Install via `/learn`

```bash
# Inside any Hermes conversation (CLI, Telegram, Discord, Desktop):
/learn https://github.com/Ufonik88/EntropicMem
```

The agent will:
1. Fetch this repo and read `skills/entropicmem/SKILL.md` + `SETUP.md`
2. Install the skill via `skill_manage create`
3. Run first-time bootstrap: `entropicmem init`
4. Run smoke tests: `lint` + `hotcache` + `graph export --format html`
5. Report the vault path and available commands

## Quickstart (After Install)

```bash
# Ingest a source (URL, file, or piped text)
entropicmem ingest "https://arxiv.org/abs/2301.00001"

# Query the vault (returns cited snippets)
entropicmem query "transformer attention mechanism"

# Create a permanent note from stdin
cat my-thoughts.md | entropicmem note "My Research"

# Lint the vault (orphans, dead links, stale notes, contradictions)
entropicmem lint

# Export a galaxy-themed visual graph
entropicmem graph export --format html
# Open file://.../export/graph.html in your browser

# Promote a durable fact to both vault AND Mnemosyne
entropicmem remember "VaultKnox evaluates policies at request time" --domain Infrastructure --tags vaultknox,policy
```

## Architecture at a Glance

```
Mnemosyne (Primary Working/Episodic Memory)
       │ remember/recall (Python API)
       ▼
EntropicMem Skill (This Repo)
├── skills/entropicmem/scripts/entropicmem.py      # CLI: init, ingest, query, note, lint, moc, hotcache, graph, remember, forget, bridge
├── skills/entropicmem/scripts/vault.py            # Vault ops (write, read, linkify, sanitize, search)
├── skills/entropicmem/scripts/index.py            # SQLite FTS5 index + graph edges
├── skills/entropicmem/scripts/graph_export.py     # JSON/DOT/HTML/Canvas export (galaxy theme)
├── skills/entropicmem/scripts/mnemosyne_bridge.py # Export (Mnemosyne→Vault) / Import (Vault→Mnemosyne) / Remember
├── skills/entropicmem/scripts/retrieval.py        # Composed stack: hot cache → FTS → wikilink expansion → optional semantic
└── skills/entropicmem/
    ├── SKILL.md                # Agent instructions (triggers, workflows, Hermes-tool framing)
    ├── SETUP.md                # First-run checklist (vault resolution, env vars, init, smoke test)
    └── templates/vault/        # Seed skeleton (AGENTS.md, SCHEMA.md, index.md, log.md, domains/, templates/)
```

## Memory Model (5 Layers)

| Layer | System | Purpose | Retention |
|-------|--------|---------|-----------|
| L1 Hot Context | Mnemosyne `working_memory` | Current conversation, auto-injected | Session |
| L2 Episodic | Mnemosyne `episodic_memory` | Cross-session facts, vector+FTS | Long-term |
| L3 Scratchpad | Mnemosyne `scratchpad` | Agent temp reasoning | Session |
| **L4 Durable Knowledge** | **EntropicMem Vault** (this skill) | **Compounded, linked, human-browsable** | **Permanent** |
| L5 Mnemosyne Mirror | Vault `Mnemosyne/` folder | Read-only projection of L2 | Sync'd (6h) |

**Round-trip identity:** `entropic_id = SHA256(content)[:16]` links vault note ↔ Mnemosyne row.

## Commands

| Command | Description |
|---------|-------------|
| `init [--vault PATH] [--force] [--dry-run]` | Bootstrap vault + index + env vars |
| `ingest <source> [--domain DOMAIN]` | URL/file/stdin → literature + 8-15 permanents |
| `ingest-pile <dir> [--domain DOMAIN]` | Batch ingest + cross-ref |
| `query "<q>" [--top-k N] [--semantic]` | Cited retrieval (FTS + wikilink expansion) |
| `note [title] [--domain DOMAIN]` | Stdin → permanent note |
| `research "<q>" [--rounds N]` | 3-round web research → inbox brief |
| `lint [--domain DOMAIN]` | Orphans, dead links, stale (>90d), contradictions |
| `moc [--domain DOMAIN]` | Build/repair domain Index.md + backlinks |
| `hotcache` | Refresh Wiki-Cache.md (recent + longest) |
| `graph export [--format json\|dot\|html\|canvas] [--max-nodes N] [--domain D]` | Visual graph export |
| `graph serve [--port N]` | Serve export dir via HTTP |
| `remember "fact" [--domain D] [--tags t1,t2]` | Vault note + Mnemosyne row (same entropic_id) |
| `forget <entropic_id>` | Delete both sides |
| `bridge export [--since DATETIME]` | Mnemosyne → Vault `Mnemosyne/` mirror |
| `bridge import [--folder Mnemosyne]` | Vault → Mnemosyne (agent=true notes) |
| `open <note_id>` | Open note in `$EDITOR` / VS Code |
| `--check-deps` | Print optional dependency status |

## Visual Graph (Galaxy Theme)

- **Single file** `graph.html` — works via `file://` or `python -m http.server`
- **D3 force-directed** (CDN + local fallback), dark galaxy aesthetic
- **Per-domain palette** (8 colorblind-safe colors from Ajax brand)
- **Node glow** (SVG filter), edge weight = thickness, node radius = log(importance)
- **Hover tooltip**, click → `entropicmem://open/<id>` (protocol handler documented in SETUP.md)
- **Filters:** domain checkboxes, tag search, importance slider

## Requirements

- Python 3.10+ (stdlib only for core)
- **Optional:** `pip install sentence-transformers` — enables `--semantic` re-rank
- **Optional:** `pip install graphviz` — enables `--format dot`
- Hermes Agent (for `/learn` install and skill execution)

## Documentation

- [`PROJECT_PLAN.md`](PROJECT_PLAN.md) — Full technical specification (all 10 sections)
- [`SETUP.md`](SETUP.md) — First-run checklist (agent reads this during `/learn`)
- [`RISKS.md`](RISKS.md) — Risk register with owners
- [`RELEASE-CHECKLIST.md`](RELEASE-CHECKLIST.md) — Ship-ready definition
- `skills/entropicmem/references/` — MEMORY_MODEL, VAULT_SCHEMA, HERMES_INTEGRATION, CLI_REFERENCE, VISUALIZER

## Comparison

| Feature | EntropicMem | `obsidian` skill | `llm-wiki` skill | Mnemosyne |
|---------|-------------|------------------|------------------|-----------|
| **Vault init + domain seeding** | ✅ | ❌ (raw FS ops) | ✅ (generic) | N/A |
| **6-command knowledge loop** | ✅ | ❌ | ✅ (similar) | N/A |
| **Mnemosyne bridge (round-trip)** | ✅ | ❌ | ❌ | Primary |
| **Galaxy graph visualizer** | ✅ | ❌ | ❌ | N/A |
| **`/learn` self-install** | ✅ | ✅ | ✅ | N/A |
| **Safe-mode existing vault bind** | ✅ | N/A | N/A | N/A |

## License

MIT — see [`LICENSE`](LICENSE).

---

**Built for Hermes Agent** — skill-first, stdlib-first, Mnemosyne-native.
