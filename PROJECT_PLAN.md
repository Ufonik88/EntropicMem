# EntropicMem — Project Plan & Technical Specification

**Status:** Active development (Phases 0–4 implemented; re-planned for standalone v1.0)  
**Date:** 2026-07-16  
**Repo:** https://github.com/Ufonik88/EntropicMem  
**Install:** `/learn https://github.com/Ufonik88/EntropicMem`

---

## 0. Product Definition (Locked)

### 0.1 What EntropicMem Is

**EntropicMem is a complete, standalone memory and knowledge system for Hermes Agent.**

It is the primary place the agent stores durable knowledge, retrieves linked context, maintains a human-readable archive, and visualizes relationships. It is not a companion to another memory product, not a bridge, and not a thin wrapper around an external second brain.

It ships as:

1. A **Hermes skill** (`skills/entropicmem/`) installable via `/learn`
2. A **stdlib-first CLI** (`entropicmem`) for deterministic operations
3. A **SQLite memory engine** for durable facts
4. A **Markdown vault** for browsable, linked notes
5. A **vault index** for FTS + graph edges
6. A **single-file visual graph** for knowledge exploration

### 0.2 What Success Looks Like

A correctly installed EntropicMem lets Hermes:

| Need | How EntropicMem covers it |
|------|----------------------------|
| Remember durable facts across sessions | `remember` → MemoryEngine + vault note |
| Forget or supersede facts | `forget` by `entropic_id` |
| Search knowledge with citations | `query` over vault index (+ optional semantic re-rank) |
| Capture sources into structured knowledge | `ingest` / `ingest-pile` / `research` / `note` |
| Maintain knowledge hygiene | `lint`, `moc`, `hotcache` |
| Browse and share structure with a human | plain Markdown vault + domain Indexes |
| See relationships | `graph export` / `graph serve` |
| Self-bootstrap | `init` + SETUP.md for `/learn` |

### 0.3 Non-Goals (v1.0)

- Replacing Hermes conversation context / prompt caching
- Being a multi-user collaborative wiki server
- Requiring cloud services, Electron, or a web backend
- Depending on any third-party memory product at runtime
- Shipping as Hermes `memory.provider` in v1.0 (optional post-v1)

### 0.4 Design Principles

1. **Self-contained.** All durable state lives under EntropicMem-owned paths.
2. **Stdlib-first.** Core path needs Python 3.10+ only; optional extras degrade gracefully.
3. **Agent-native.** CLI + skill instructions; Hermes uses `terminal` / file tools.
4. **Plain-text vault.** Markdown is source of human truth; DBs are indexes/engines.
5. **Deterministic identity.** `entropic_id = SHA256(content)[:16]` for dedup and recall.
6. **Surgical surface.** Prefer CLI commands + skill over new core Hermes tools.
7. **Verify before claim.** Every phase ends with automated tests + executable gates.

---

## 1. Problem Statement

Hermes agents need durable knowledge that:

- Survives session boundaries
- Can be searched and cited
- Compounds over time with links between concepts
- Is inspectable by both agent and human
- Can be installed and initialized without manual glue

Without a standalone system, agents either:

- Lose durable facts when conversation context compresses
- Scatter notes across ad-hoc files with no index/graph
- Rely on external products that the agent cannot fully own or ship

**EntropicMem solves this by owning the full stack:** write path, store, retrieve, maintain, visualize, install.

---

## 2. Target Users & Usage Modes

### 2.1 Primary User

Hermes Agent (any channel: CLI, Desktop, gateway), guided by the skill, executing `entropicmem` via the terminal tool.

### 2.2 Secondary User

The human operator who may browse the vault, open the graph, or run CLI commands manually.

### 2.3 Usage Modes

| Mode | Description |
|------|-------------|
| **Working memory promotion** | Agent promotes important chat conclusions via `remember` |
| **Source capture** | Agent ingests URLs/files into literature + atomic notes |
| **Retrieval** | Agent queries before answering long-horizon questions |
| **Hygiene** | Agent runs lint/moc/hotcache at session end or on schedule |
| **Human review** | Human opens vault or `graph.html` for inspection |

---

## 3. Architecture (Standalone)

### 3.1 Component Map

```
┌─────────────────────────────────────────────────────────────┐
│                        HERMES AGENT                         │
│  skill_view(entropicmem) → terminal(entropicmem …)          │
└────────────────────────────┬────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────┐
│                     ENTROPICMEM CLI                         │
│  init · ingest · query · note · research · lint · moc       │
│  hotcache · graph · remember · forget · memory · open       │
└──────┬──────────────┬──────────────┬──────────────┬─────────┘
       │              │              │              │
       ▼              ▼              ▼              ▼
┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐
│  Memory    │ │   Vault    │ │   Index    │ │   Graph    │
│  Engine    │ │  (Markdown)│ │  (SQLite   │ │  Export    │
│  memory.db │ │  notes +   │ │   FTS5 +   │ │  HTML/JSON │
│  FTS facts │ │  domains)  │ │   edges)   │ │  DOT/Canvas│
└────────────┘ └────────────┘ └────────────┘ └────────────┘
```

### 3.2 Owned State Paths

| Artifact | Default path | Role |
|----------|--------------|------|
| Vault root | `~/.hermes/entropicmem/vault` | Human-readable Markdown source of structure |
| Vault index | `~/.hermes/entropicmem/index.db` | FTS over notes + graph edges |
| Memory engine | `~/.hermes/entropicmem/memory.db` | Durable fact store with FTS |
| Graph export | `./export/` (or user-chosen) | Generated visual artifacts |
| Env config | `~/.hermes/.env` | Path overrides |

Override env vars:

- `ENTROPICMEM_VAULT_PATH`
- `ENTROPICMEM_INDEX_DB`
- `ENTROPICMEM_MEMORY_DB`

### 3.3 Data Flow

**Remember (durable fact):**
```
fact text
  → MemoryEngine.remember()  → memory.db (id=entropic_id)
  → Vault.write_note()       → Domain/*.md
  → VaultIndex.upsert_note() → index.db + edges
```

**Ingest (source capture):**
```
URL|file|stdin
  → extract text + entities
  → inbox literature note
  → N atomic permanent notes
  → index upsert + edge extraction
```

**Query:**
```
query
  → hot cache (orientation)
  → index FTS
  → wikilink expansion
  → optional semantic re-rank
  → cited snippets
```

**Graph:**
```
index nodes/edges
  → graph.json
  → graph.html (embedded data, D3 force layout)
```

### 3.4 Memory Model (Internal Layers)

| Layer | Store | Lifetime | Primary API |
|-------|-------|----------|-------------|
| L1 Hot orientation | `Wiki-Cache.md` | Regenerated | `hotcache` |
| L2 Durable facts | `memory.db` | Permanent (until forget) | `remember` / `forget` / `memory stats` |
| L3 Structured knowledge | Vault Markdown | Permanent | `ingest` / `note` / `query` |
| L4 Relational index | `index.db` | Rebuilt from vault | rebuild on write / `moc` |
| L5 Visualization | export graph | Generated | `graph export` / `serve` |

L2 and L3 are both first-class. Memory engine optimizes fact recall; vault optimizes browsable linked knowledge. `memory project` can materialize L2 into L3.

---

## 4. Feature Catalog

### 4.1 Implemented (as of this replan)

| Area | Capability | Module / command |
|------|------------|------------------|
| Bootstrap | Seed vault + domains + env | `init` |
| Vault ops | write/read/linkify/sanitize/search | `vault.py` |
| Index | FTS5, metadata, graph edges | `index.py` |
| Retrieval | hot → FTS → links → optional semantic | `retrieval.py` + `query` |
| Capture | literature + atomics, pile, stdin notes | `ingest`, `ingest-pile`, `note` |
| Research brief | agent-driven inbox placeholder | `research` |
| Hygiene | orphans/dead links/stale/contradictions | `lint` |
| Structure | domain Index + backlinks | `moc` |
| Cache | recent + high-value links | `hotcache` |
| Durable memory | SQLite facts, FTS, dedup | `memory_engine.py`, `remember`, `forget` |
| Memory projection | facts → vault notes | `memory project` |
| Graph | JSON/DOT/HTML/Canvas + HTTP serve | `graph_export.py` |
| Tests | unit + CLI gates | 80 tests |

### 4.2 Required for True Standalone v1.0 (remaining)

These are not optional polish; they define whether the product is *shippable as a full replacement for external memory workflows*.

| # | Requirement | Why it matters |
|---|-------------|----------------|
| S1 | Complete skill docs (SETUP + 5 references) | Agent self-configures without external tribal knowledge |
| S2 | Complete product docs (`docs/*`, CLI_REFERENCE) | Humans and agents can operate without reading source |
| S3 | Accurate CLI help/strings (no legacy wording) | Trust + correct routing |
| S4 | `recall` CLI over MemoryEngine | Agents need fact-store search, not only vault FTS |
| S5 | Unified search strategy in skill | When to use `query` vs `memory`/`recall` |
| S6 | Session-end / promotion workflow in SKILL.md | Makes EntropicMem the default durable write path |
| S7 | `/learn` dry-run acceptance on clean profile | Proves installability |
| S8 | RELEASE-CHECKLIST all green + tag `v1.0.0` | Ship definition |
| S9 | Optional Hermes MemoryProvider adapter (post-v1) | Deeper Hermes integration without becoming required for core use |

### 4.3 v1.1 / Post-v1 Enhancements

- Automatic session-turn hooks (if/when Hermes provider surface is adopted)
- Semantic embeddings pack as first-class install path
- Import adapters for foreign archives (generic Markdown dump, not product-specific branding)
- Multi-profile vault isolation helpers
- Incremental index watch mode

---

## 5. Module Spec (Current + Target)

### 5.1 `memory_engine.py` — Durable Fact Store

**Responsibility:** Own the agent’s long-term fact memory.

**API:**
- `remember(content, title?, source?, importance?, domain?, tags?) -> entropic_id`
- `forget(entropic_id) -> bool`
- `recall(query, top_k?, domain?) -> list[StoredFact]`
- `get_fact(entropic_id)`
- `list_facts(domain?, limit?)`
- `stats()`
- `project_to_vault(vault, index, limit?)`

**Invariants:**
- Same content → same `entropic_id`
- Re-remember updates existing row, does not duplicate
- Core path uses only stdlib + sqlite3

**Gaps to close for v1.0:**
- Expose `recall` via CLI
- Document importance/tag conventions in skill
- Harden FTS delete/upsert edge cases under concurrent use

### 5.2 `vault.py` — Markdown Knowledge Archive

**Responsibility:** Durable structured notes humans and agents can read.

**Key ops:** write/read/append/patch/delete, list/search, linkify, extract wikilinks, open editor.

**Vault layout (seeded by `init`):**
```
vault/
├── AGENTS.md
├── SCHEMA.md
├── index.md
├── log.md
├── Wiki-Cache.md
├── inbox/
├── .raw/
├── templates/
├── _archive/          # write-protected
└── <Domain>/          # Infrastructure, Knowledge, etc.
```

**Frontmatter (required fields):**
```yaml
title: "..."
type: literature|permanent|moc|index|log
tags: [...]
created: YYYY-MM-DD
updated: YYYY-MM-DD
source: agent|url|file|conversation
entropic_id: "<16 hex>"
domain: "..."
agent: true|false
```

### 5.3 `index.py` — Retrieval + Graph Index

**Responsibility:** Fast search and relationship graph over vault notes.

**Tables:** `notes_meta`, `notes_fts`, `graph_edges`

**Ops:** rebuild, upsert, delete, search_fts, backlinks/outlinks, graph nodes/edges, stats

### 5.4 `retrieval.py` — Composed Query Stack

Order:
1. Hot cache orientation
2. FTS hits
3. Wikilink expansion
4. Optional semantic re-rank (if installed)
5. Cited snippets + graph neighborhood

### 5.5 `graph_export.py` — Visual Knowledge Map

Formats: `json`, `dot`, `html`, `canvas`  
HTML is the primary human deliverable: single file, embedded data, D3 force layout, domain colors, filters, tooltips.

### 5.6 `entropicmem.py` — CLI Surface

All agent capability must remain reachable as CLI subcommands so Hermes needs no special core tools.

---

## 6. Agent Operating Contract

### 6.1 Write Policy

| Content type | Destination |
|--------------|-------------|
| Stable identity/preferences/facts | `remember` (MemoryEngine + vault note) |
| Source-derived knowledge | `ingest` / `research` then `lint`/`moc` |
| Ephemeral reasoning | Do **not** write to EntropicMem |
| Secrets/credentials | Never store |

### 6.2 Read Policy

| Need | Command |
|------|---------|
| Linked conceptual context | `query "..."` |
| Exact durable facts | `memory stats` + (v1) `recall` / remember IDs |
| Structure overview | `hotcache`, domain `Index.md` |
| Relationship map | `graph export --format html` |

### 6.3 Default Session Pattern

1. Orient: read `Wiki-Cache.md` or run `hotcache` if stale  
2. Retrieve: `query` before long answers that need prior knowledge  
3. Capture: `ingest` / `note` / `remember` as outcomes solidify  
4. Maintain: `lint` + `moc` before ending heavy knowledge sessions  

---

## 7. Revised Implementation Phases

### Phase Status Summary

| Phase | Name | Status |
|-------|------|--------|
| 0 | Plan & packaging skeleton | Done (replan supersedes companion framing) |
| 1 | Core vault engine | Done |
| 2 | Knowledge loop | Done |
| 3 | Graph visualizer | Done |
| 4 | Standalone memory engine | Done (replaces external-bridge design) |
| **5** | **Standalone product completion** | **Active** |
| 6 | Optional Hermes provider adapter | Future |

### Phase 5 — Standalone Product Completion (Current)

**Goal:** EntropicMem is a shippable, self-explanatory, installable full memory tool.

#### 5.1 Documentation rewrite (must complete)

- [ ] `PROJECT_PLAN.md` — this document (standalone target)
- [ ] `README.md` — product face, no companion framing
- [ ] `SETUP.md` + skill SETUP mirror
- [ ] `SKILL.md` — operating contract, write/read policy
- [ ] `RISKS.md` — standalone risks only
- [ ] `RELEASE-CHECKLIST.md` — standalone ship gate
- [ ] `MASTER_TODO.md` — current/next handoff
- [ ] `references/MEMORY_MODEL.md`
- [ ] `references/VAULT_SCHEMA.md`
- [ ] `references/CLI_REFERENCE.md`
- [ ] `references/VISUALIZER.md`
- [ ] `references/HERMES_INTEGRATION.md` (skill + `/learn` only)
- [ ] `docs/*` full versions (or thin wrappers pointing to references if duplicated)

#### 5.2 Product surface cleanup

- [ ] CLI help text has zero legacy external-product wording
- [ ] Seed templates (`AGENTS.md`, `SCHEMA.md`) describe EntropicMem-only workflow
- [ ] Remove dead modules/names (`mnemosyne_bridge` already removed)
- [ ] Ensure env docs only list EntropicMem vars

#### 5.3 Capability gaps for standalone completeness

- [ ] Add `entropicmem recall "<q>"` CLI over MemoryEngine
- [ ] Optionally add `entropicmem memory list [--domain]`
- [ ] Skill documents promotion rules from chat → `remember`
- [ ] Cron recipe for optional maintenance (`lint`/`hotcache`/`memory project`) owned by EntropicMem

#### 5.4 Quality gate

- [ ] `pytest` green (currently 80+)
- [ ] Fresh temp vault: init → ingest → remember → query → recall → graph export
- [ ] `/learn` dry-run transcript recorded in `docs/SELF_INSTALL.md`
- [ ] Tag `v1.0.0`

**Exit criteria for Phase 5 / v1.0:**
1. New Hermes profile can install via `/learn` and reach working `init`
2. Agent can store and retrieve durable facts without any external memory system
3. Vault + graph + memory engine all function offline with stdlib
4. Docs explain only EntropicMem concepts
5. Release checklist 100% for required items

### Phase 6 — Optional Deep Hermes Integration

**Not required for v1.0.** Only after standalone CLI/skill product is solid:

- Implement `MemoryProvider` adapter under a future plugin path
- Keep MemoryEngine as backend (do not reintroduce foreign stores)
- Provider remains optional; CLI skill remains primary

---

## 8. Repository Structure (Target)

```
EntropicMem/
├── README.md
├── LICENSE
├── PROJECT_PLAN.md
├── MASTER_TODO.md
├── SETUP.md
├── RISKS.md
├── RELEASE-CHECKLIST.md
├── .gitignore
├── .github/workflows/test.yml
├── skills/entropicmem/
│   ├── SKILL.md
│   ├── SETUP.md
│   ├── references/
│   │   ├── MEMORY_MODEL.md
│   │   ├── VAULT_SCHEMA.md
│   │   ├── CLI_REFERENCE.md
│   │   ├── VISUALIZER.md
│   │   └── HERMES_INTEGRATION.md
│   ├── scripts/
│   │   ├── entropicmem.py
│   │   ├── vault.py
│   │   ├── index.py
│   │   ├── retrieval.py
│   │   ├── memory_engine.py
│   │   └── graph_export.py
│   └── templates/vault/
├── tests/
│   ├── test_vault.py
│   ├── test_phase2.py
│   ├── test_phase3.py
│   └── test_phase4.py
└── docs/
    ├── ARCHITECTURE.md
    ├── MEMORY_MODEL.md
    ├── CLI_REFERENCE.md
    ├── VISUALIZER.md
    ├── SELF_INSTALL.md
    ├── COMPARISON.md          # capability comparison vs generic classes of tools (no brand dependency claims)
    └── COMPARISON_TABLE.md
```

---

## 9. Testing Strategy

### 9.1 Automated (required)

| Suite | Covers |
|-------|--------|
| `test_vault.py` | vault ops, protection, frontmatter |
| `test_phase2.py` | ingest/moc/research/query gate |
| `test_phase3.py` | graph export formats + CLI |
| `test_phase4.py` | MemoryEngine remember/forget/recall/project |

Run: `python3 -m pytest tests/ -q`

### 9.2 Manual / agent acceptance

1. Clean temp vault init  
2. Ingest a sample markdown file  
3. Remember two facts  
4. Query + recall  
5. Graph HTML opens and shows nodes  
6. Forget one fact and verify removal  

### 9.3 `/learn` acceptance

On a profile without EntropicMem:

```
/learn https://github.com/Ufonik88/EntropicMem
```

Expect: skill installed → SETUP followed → `init` succeeds → smoke commands pass → agent reports vault/memory paths.

---

## 10. Risks (Standalone Framing)

| Risk | Impact | Mitigation |
|------|--------|------------|
| Agents keep writing only to chat context | Knowledge never compounds | SKILL.md write policy + session-end checklist |
| Dual stores (memory.db + vault) drift | Confusing truth | Document L2 vs L3; `memory project` + remember dual-write |
| FTS quality without embeddings | Misses paraphrases | Optional semantic re-rank; good titles/tags guidance |
| Large vaults slow graph | Unusable visualization | Default max 500 nodes + domain/importance filters |
| `/learn` cannot pip install | Missing optional deps | Stdlib core; `--check-deps` honesty |
| Legacy wording confuses users | Product looks incomplete | Doc/CLI purge (this replan) |

---

## 11. Ship Definition — v1.0 Standalone

A v1.0 release is valid only if EntropicMem can be described truthfully as:

> “A complete memory system for Hermes Agent: store facts, build a linked vault, retrieve with citations, maintain hygiene, and visualize knowledge — without depending on any external memory application.”

### Must include

- [x] MemoryEngine (standalone SQLite)
- [x] Vault + index + retrieval
- [x] Knowledge loop commands
- [x] Graph visualizer
- [x] Public GitHub repo + MIT license
- [ ] Fully rewritten product docs (standalone)
- [ ] Skill operating contract complete
- [ ] CLI wording cleaned
- [ ] `recall` CLI (recommended for v1.0 completeness)
- [ ] `/learn` dry-run proof
- [ ] Tag `v1.0.0` + changelog

---

## 12. Immediate Next Actions (Execution Order)

1. **Freeze product language** in README/SKILL/SETUP/RISKS/RELEASE/MASTER_TODO (this replan is the source of truth).  
2. **Clean remaining CLI/help/template strings** that still imply external companions.  
3. **Implement `recall` + `memory list`** CLI for MemoryEngine completeness.  
4. **Write full reference docs** under `skills/entropicmem/references/`.  
5. **Fill `docs/`** (or generate from references to avoid drift).  
6. **Run full test suite + end-to-end standalone smoke**.  
7. **`/learn` dry-run** and capture SELF_INSTALL.  
8. **Tag v1.0.0**.

---

## 13. Decision Log (Revised)

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-07-16 | Standalone product, not companion | User goal: full replacement for external memory workflows |
| 2026-07-16 | Own MemoryEngine instead of foreign bridge | Runtime independence; hermetic installs |
| 2026-07-16 | Keep Markdown vault + SQLite engine dual model | Agent retrieval + human browsability |
| 2026-07-16 | Skill + CLI first; MemoryProvider later | Matches Hermes extension ladder; avoids core coupling |
| 2026-07-16 | Stdlib-first | `/learn` reliability |
| 2026-07-16 | Graph as single HTML file | Offline, no build, works in agent/remote environments |

---

## 14. Glossary

| Term | Meaning |
|------|---------|
| **Vault** | Directory of Markdown notes organized by domain |
| **Memory engine** | SQLite fact store (`memory.db`) |
| **Index** | SQLite FTS + edge DB over vault notes (`index.db`) |
| **entropic_id** | Deterministic 16-hex content identity |
| **MOC** | Map of Content domain index page |
| **Hot cache** | Regenerated orientation note of recent/high-value links |
| **Galaxy graph** | Force-directed HTML visualization of note relationships |

---

**End of replan.**  
This document supersedes earlier companion-oriented planning. Implementation work proceeds from **Phase 5 — Standalone Product Completion**.
