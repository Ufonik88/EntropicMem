# EntropicMem — Project Plan & Technical Specification

**Status:** Planning Phase (Research Complete)  
**Author:** Entropy (Hermes Agent)  
**Date:** 2026-07-16  
**Target:** Public GitHub repository installable via Hermes `/learn` command

---

## Executive Summary

EntropicMem is a **Hermes Agent skill with supporting scripts** that provides an agent-native, Obsidian-inspired second brain and memory system. It is **not** a replacement for Mnemosyne (which remains the primary working/episodic memory). Instead, EntropicMem is the **durable, linked, browsable knowledge layer** that compounds over time — the "fall back to Obsidian graph" that Ufonik's workflow already uses manually, now automated and agent-driveable.

**Deliverable Form (locked):**  
1. **Skill** at `skills/entropicmem/` — primary ship unit for `/learn`  
2. **Scripts** at `skills/entropicmem/scripts/` — deterministic vault ops, index, lint, graph export  
3. **Templates** at `skills/entropicmem/templates/vault/` — seed vault skeleton  
4. **Optional MemoryProvider bridge** (Phase 6+) — read/write hooks to Mnemosyne  
5. **Visual Graph** — single-file HTML (D3/canvas) + JSON export, works offline via `file://`

**Why this architecture:** Matches the existing Hermes extension model (`write-a-skill`, `hermes-plugin-management`, memory-provider ABC), makes `/learn` self-installing, keeps Mnemosyne as primary memory, and gives the visual component a stable home without a server dependency.

---

## 1. System Analysis — How the Relevant Systems Work

### 1.1 Obsidian Vault (Ufonik's Second Brain)

**Location:** `~/Documents/Obsidian Vault` (Syncthing-synced to Mac, git-auto-committed every 15min)

**Structure (472 active notes, 8 domains):**
```
Obsidian Vault/
├── AGENTS.md              # Boot file for any agent session
├── WIKI.md                # 6-command reference (wiki.py)
├── Wiki-Cache.md          # Hot cache: recent + high-value notes
├── Welcome.md             # MOC with domain links + cleanup stats
├── Projects.md            # GitHub repo index with wikilinks
├── .raw/                  # Web clipper landing (ingest input)
├── inbox/                 # Fleeting captures
├── Mnemosyne/             # READ-ONLY auto-export (mnemosyne_to_obsidian.py, 6h cron)
├── templates/             # Fleeting/literature/permanent note templates
├── _archive/              # 3,294 files (raw-exports, dupes, trash, leftover)
├── attachments/
├── Source/                # Source index by origin
├── Knowledge/             # 99 notes
├── Infrastructure/        # 92 notes
├── Ajax Systems/          # 147 notes
├── X-Growth/              # 35 notes
├── Finance/               # 23 notes
├── Workflows/             # 34 notes
├── People/                # 32 notes
├── Products-Research/     # 10 notes
└── Projects/              # 25 repos via MOCs
```

**Key Conventions (from AGENTS.md):**
- `[[wikilinks]]` — case-sensitive on Linux
- YAML frontmatter: `tags`, `created`, `source`, `aliases`
- Atomic notes: one idea per note, link liberally
- `inbox/` → domain folder promotion during `lint` or end-of-session
- `Mnemosyne/` is **read-only to humans** — regenerated every 6h
- Git = undo history (not for collaboration)

**Pipeline (WIKI.md — 6 commands via `wiki.py`):**
| Command | Purpose |
|---------|---------|
| `ingest <source>` | Read URL/file/stdin → 1 literature note + 8–15 atomic permanent notes |
| `ingest-pile <dir>` | Parallel ingest folder → cross-reference shared entities |
| `query "<q>"` | Scan cache+index → cited snippets |
| `note [title]` | Stdin → permanent note |
| `research "<q>"` | 3-round autonomous web research → literature + synthesis notes |
| `lint` | Orphans, dead links, stale (>90d), contradictions as `[!contradiction]` |
| `hotcache` | Rebuild `Wiki-Cache.md` (recent 14d + longest notes) |
| `moc` | Build/repair Maps of Content per domain (back-link every note to its Index) |

**Wiki-Cache.md Pattern:** Auto-refreshed index opened first each session — recent (14d) + high-value (longest) notes as wikilinks.

---

### 1.2 Mnemosyne (Primary Memory System)

**Location:** `~/.hermes/mnemosyne/` (SQLite + sqlite-vec)

**Architecture (BEAM — from `mnemosyne-cron-writes` skill):**
```
Mnemosyne (legacy class)          BeamMemory (core)
├── working_memory                ├── working_memory (hot context, auto-injected)
├── episodic_memory               ├── episodic_memory (long-term, sqlite-vec + FTS5)
└── scratchpad                    ├── scratchpad (temp reasoning workspace)
                                  └── memory_embeddings (FK → memories.id)
```

**Critical API (from `mnemosyne-cron-writes` skill):**
```python
# CORRECT — legacy Mnemosyne class (dual-writes working_memory + memories + embeddings)
from mnemosyne.core.memory import Mnemosyne
mem = Mnemosyne(db_path=Path("~/.hermes/mnemosyne/data/mnemosyne.db"))
mid = mem.remember(
    content="...concise durable fact...",
    source="notion|conversation|correction",
    importance=0.7,
    scope="global",              # REQUIRED for cross-session durability
    metadata={"notion_page": "Ajax SDK", "type": "product_knowledge"},
)
# mid = deterministic hash of content — re-call dedups + backfills embeddings
```

**MCP Server (`mnemosyne/mcp_server.py`):** 28 tools exposed (remember, recall, batch, shared, sleep, triples, canonical, graph, hygiene, import/export, diagnose). Auth via `MNEMOSYNE_MCP_TOKEN` for non-loopback SSE.

**Key Constraints:**
- Mnemosyne is **primary**; Obsidian is fallback for heavy tasks
- Never store raw credentials (skip `has_credentials` sources entirely)
- `BeamMemory.remember()` is **broken** — writes only to working_memory, FK fails silently on embeddings
- `self.beam` initialization bug (fixed 2026-07-16): must be in `__init__`, not `__del__`

---

### 1.3 Hermes Agent Extension Model

**Skill Format (from `write-a-skill`):**
```markdown
---
name: skill-name
description: One sentence <=60 chars. Use when [specific triggers].
platforms: [linux, macos, windows]
---
# Skill Name
## Quick start
## Workflows
## Advanced features → REFERENCE.md
```
- Description is the **only thing the agent sees** for routing (truncated at 60 chars in system prompt)
- `skill_manage create` writes `SKILL.md` + optional `scripts/`, `references/`, `templates/`
- Progressive disclosure: SKILL.md <100 lines, detail in `REFERENCE.md`

**Plugin System (from `hermes-plugin-management`):**
- Vendored: `~/.hermes/hermes-agent/plugins/<name>/`
- External: `~/.hermes/plugins/<name>/` (git clone)
- Enable: `hermes plugins enable <name>` → adds to `config.yaml`
- Dashboard restart required after enable/disable

**Memory Provider ABC (from `plugins/memory/__init__.py`):**
- Only **one** provider active at a time (`memory.provider` in config.yaml)
- 8 bundled providers: `honcho`, `holographic`, `mem0`, `openviking`, `hindsight`, `retaindb`, `supermemory`, `byterover`
- Interface: `is_available()`, `initialize()`, `system_prompt_block()`, `get_tool_schemas()`, `handle_tool_call()`, `prefetch()`, `sync_turn()`, `shutdown()`
- CLI commands via `discover_plugin_cli_commands()` → active provider only

**`/learn` Workflow (from `learn_prompt.py`):**
1. User: `/learn <free-text request>` (repo URL, directory, "what we just did", pasted notes)
2. Agent builds prompt via `build_learn_prompt()` → includes full authoring standards
3. Agent gathers sources (`read_file`/`search_files` for local, `web_extract` for URLs, conversation history)
4. Agent authors **one** `SKILL.md` + optional scripts/references via `skill_manage create`
5. Agent reports skill name, category, one-line summary

---

### 1.4 Existing Hermes Skills (Do Not Duplicate)

| Skill | Location | Purpose | What EntropicMem Adds |
|-------|----------|---------|----------------------|
| `obsidian` | `skills/note-taking/obsidian/` | Raw FS vault ops (read_file, search_files, write_file, patch) | **Orchestrates structure**: domains, MOCs, templates, hotcache, lint, graph — not "use read_file" |
| `llm-wiki` | `skills/research/llm-wiki/` | General Karpathy wiki pattern (raw/ + entities/concepts/comparisons/queries) | **Hermes-home + Ufonik-vault-aware**: Mnemosyne bridge, graph visualizer, `/learn` self-setup, agent-native workflows |
| `mnemosyne-cron-writes` | `skills/memory/mnemosyne-cron-writes/` | Durable writes from cron via Python API | EntropicMem **reads** Mnemosyne for vault projection; does not replace this |

---

### 1.5 Tencent/ByteDance Analogues (Ideas Only)

**OpenViking (ByteDance/Volcengine) — `plugins/memory/openviking/`:**
- URI-like addresses: `viking://user/peers/hermes/memories/...`
- Tiered read: abstract → overview → full with backlinks
- Filesystem-style browse: list/tree/stat
- Explicit `remember`/`forget` semantics
- **Takeaway for EntropicMem:** `vault://Domain/Note` URI scheme, tiered note views (title+summary / body / full+backlinks), explicit `entropicmem remember/forget` CLI

**Tencent Cloud VectorDB / Hunyuan long-context / markingmemory agentKB:**
- Context-engineering lineage (LangChain, LlamaIndex family)
- **Takeaway:** Hybrid FTS + vector retrieval; optional embeddings with FTS fallback; hygiene/consolidation jobs

---

## 2. Feature Selection — Replicate / Adapt / Improve

| Source Feature | Decision | EntropicMem Treatment |
|----------------|----------|----------------------|
| **Domain folders + MOCs** | **Replicate** | Core vault structure; `entropicmem init` seeds 8 Ufonik domains + `Projects` |
| **YAML frontmatter (tags, created, source, aliases)** | **Replicate + Extend** | Add `agent: true`, `entropic_id: <hash>` for Mnemosyne round-trip |
| **`[[wikilinks]]` (case-sensitive Linux)** | **Replicate** | Enforce via linter; `linkify()` auto-links known titles |
| **Atomic notes + inbox→domain promotion** | **Replicate** | `ingest` creates literature + permanents; `lint` promotes orphans |
| **6-command wiki.py loop** | **Lift + Port** | Become `entropicmem` subcommands with identical semantics |
| **Hot cache (Wiki-Cache.md)** | **Replicate** | `hotcache` subcommand; agent reads first each session |
| **Git auto-commit (15min cron)** | **Replicate** | Document in SETUP.md; vault is plain Markdown |
| **Mnemosyne export as read-only mirror** | **Replicate + Automate** | `mnemosyne_bridge.py export` → `Mnemosyne/` (cron or on-demand) |
| **Mnemosyne BEAM (working/episodic/scratchpad)** | **Bridge, Don't Fork** | Read-only access via `Mnemosyne` class; write via `remember()` |
| **OpenViking URI + tiered read** | **Adapt** | `vault://Domain/Note` URIs; `query` returns summary→body→full+backlinks |
| **OpenViking explicit remember/forget** | **Adapt** | `entropicmem remember "fact"` → creates vault note + Mnemosyne row |
| **Visual graph (Obsidian-style)** | **Build v1** | Force-directed D3/canvas HTML + JSON export; galaxy theme |
| **`/learn` self-install** | **Design Explicitly** | SKILL.md + SETUP.md drive `skill_manage create` → `entropicmem init` |
| **Syncthing + git coexistence** | **Guard** | Never write `Mnemosyne/`, `.obsidian/`, `_archive/`; vault = plain MD |

---

## 3. Architecture

### 3.1 High-Level Component Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              HERMES AGENT                                      │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────────────┐  │
│  │   Mnemosyne     │  │  EntropicMem    │  │  Existing Skills            │  │
│  │  (Primary Mem)  │  │  (Skill +       │  │  obsidian, llm-wiki,        │  │
│  │  working/       │  │   Scripts +     │  │  mnemosyne-cron-writes      │  │
│  │  episodic/      │  │   Templates)    │  │                             │  │
│  │  scratchpad     │  │                 │  │                             │  │
│  └────────┬────────┘  └────────┬────────┘  └─────────────────────────────┘  │
│           │                    │                                            │
│           │  remember/recall   │  query/ingest/lint/graph                  │
│           │  (Python API)      │  (CLI via terminal tool)                  │
│           ▼                    ▼                                            │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                     ENTROPICMEM MEMORY MODEL                          │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                │   │
│  │  │   VAULT      │  │   INDEX      │  │  MNEMOSYNE   │                │   │
│  │  │  (Source of  │  │  (SQLite     │  │  (Bridge)    │                │   │
│  │  │   Truth)     │  │   FTS +      │  │  read/write  │                │   │
│  │  │  Plain MD    │  │   metadata + │  │  hooks       │                │   │
│  │  │              │  │   graph edges)│  │              │                │   │
│  │  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘                │   │
│  └─────────│─────────────────│──────────────────│────────────────────────┘   │
│            │                 │                  │                            │
│            ▼                 ▼                  ▼                            │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                        RETRIEVAL STACK                                 │   │
│  │  1. Hot cache / index.md (orientation)  2. FTS over titles/tags/body  │   │
│  │  3. Wikilink expansion (1-2 hops)       4. Optional semantic re-rank │   │
│  │  5. Cited note paths + snippets → agent synthesizes answer            │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        EXTERNAL SYSTEMS                                      │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────────────┐   │
│  │  Obsidian App    │  │  Syncthing       │  │  Git (auto-commit)       │   │
│  │  (Human browse)  │  │  (Mac ↔ Linux)   │  │  (Undo history)          │   │
│  └──────────────────┘  └──────────────────┘  └──────────────────────────┘   │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  Visual Graph: file:///.../entropicmem/export/graph.html             │   │
│  │  (D3 force-directed, dark galaxy theme, click → entropicmem open)   │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Data Flow

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   SOURCE    │────▶│  INGEST     │────▶│   VAULT     │────▶│   INDEX     │
│  (URL/file/ │     │  (literature│     │  (MD files  │     │  (SQLite    │
│   conversation)   + atomic)   │     │   + wikilinks)     │   FTS + meta)│
└─────────────┘     └─────────────┘     └─────────────┘     └──────┬──────┘
                                                                      │
                    ┌─────────────┐     ┌─────────────┐               │
                    │  MNEMOSYNE  │◀───▶│  BRIDGE     │               │
                    │  (remember/ │     │  (export/   │               │
                    │   recall)   │     │   import)   │               │
                    └─────────────┘     └─────────────┘               │
                                                                      ▼
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   QUERY     │◀───│  RETRIEVAL  │◀───│   GRAPH     │◀───│  EXPORT     │
│  (agent)    │     │  (stack)    │     │  (JSON/     │     │  (HTML +    │
└─────────────┘     └─────────────┘     │   DOT)      │     │   JSON)     │
                                        └─────────────┘     └─────────────┘
```

---

## 4. What Must Be Designed, Written, Coded, Tested, Documented, Packaged

### 4.1 Core Modules (Scripts)

| Module | Responsibility | Key Functions |
|--------|----------------|---------------|
| `entropicmem.py` | Main CLI entry | `init`, `ingest`, `query`, `note`, `research`, `lint`, `moc`, `hotcache`, `graph`, `remember`, `forget`, `open`, `export`, `serve` |
| `vault.py` | Vault operations | `resolve_path()`, `write_note()`, `read_note()`, `append_note()`, `linkify()`, `sanitize()`, `list_notes()`, `search_notes()` |
| `index.py` | SQLite FTS index | `rebuild()`, `upsert_note()`, `delete_note()`, `search()`, `get_backlinks()`, `get_graph_edges()` |
| `graph_export.py` | Graph visualization | `export_json()`, `export_dot()`, `export_html()`, `export_canvas()` |
| `mnemosyne_bridge.py` | Mnemosyne ↔ Vault | `export_to_vault()`, `import_from_vault()`, `sync_durable_facts()` |
| `templates.py` | Template rendering | `render(template_name, context)` for literature/permanent/MOC |

### 4.2 Vault Schema (Source of Truth)

**Frontmatter (every note):**
```yaml
---
title: "Note Title"
type: "literature|permanent|moc|index|log"
tags: ["tag1", "tag2"]
created: "2026-07-16"
updated: "2026-07-16"
source: "url|file|conversation|agent"
source_url: "https://..."  # if applicable
aliases: ["Alt Name"]
agent: true                # created by EntropicMem agent
entropic_id: "sha256[:16]" # deterministic content hash for Mnemosyne round-trip
domain: "Infrastructure"   # one of the 8+1 domains
---
```

**Domain Folders (seeded at init):**
```
vault/
├── AGENTS.md
├── SCHEMA.md           # Domain config, tag taxonomy, conventions
├── index.md            # Sectioned catalog with one-line summaries
├── log.md              # Append-only action log (rotated yearly)
├── inbox/              # Fleeting captures
├── .raw/               # Web clipper landing
├── Mnemosyne/          # READ-ONLY mirror (gitignored or tracked with warning)
├── templates/
│   ├── literature.md
│   ├── permanent.md
│   ├── moc.md
│   └── index.md
├── Infrastructure/
├── Ajax Systems/
├── X-Growth/
├── Finance/
├── Workflows/
├── People/
├── Knowledge/
├── Products-Research/
└── Projects/
```

### 4.3 Retrieval Stack (Composable Functions)

```python
# Each layer is a standalone function; agent can call individually or composed

def retrieve_hot_cache(vault_path: Path) -> str:
    """Read Wiki-Cache.md — orientation layer."""
    ...

def retrieve_fts(index_db: Path, query: str, top_k: int = 10) -> List[SearchHit]:
    """SQLite FTS5 over title + tags + body."""
    ...

def retrieve_wikilink_expansion(index_db: Path, seed_notes: List[str], hops: int = 2) -> List[SearchHit]:
    """Follow [[wikilinks]] outbound/inbound up to N hops."""
    ...

def retrieve_semantic_rerank(hits: List[SearchHit], query: str, embedder) -> List[SearchHit]:
    """Optional: sentence-transformers re-rank. Degrades to FTS-only if unavailable."""
    ...

def retrieve_composed(query: str, vault_path: Path, index_db: Path, 
                       use_semantic: bool = False) -> RetrievalResult:
    """Full stack: hot_cache → fts → wikilink_expansion → optional_rerank → cited snippets."""
    ...
```

### 4.4 Visual Graph Component

**Export Formats:**
- `graph.json` — nodes + edges (primary for HTML)
- `graph.dot` — Graphviz for static renders
- `graph.canvas` — Obsidian JSON Canvas (optional)

**HTML Visualizer (`graph.html`):**
- Single file, no build step, works via `file://`
- D3 force-directed or pure Canvas (simpler, no npm)
- **Galaxy theme:** Dark background, per-domain color palette, node glow (`feGaussianBlur`), edge thickness = link count, node radius = `log(importance) * scale`
- Physics: repulsion tuned for "web/galaxy" feel (not hairball)
- Interaction: hover → tooltip (title, type, tags), click → `entropicmem open <id>` (via custom protocol or file watcher)
- Seed: fixed for reproducibility

**Node Schema:**
```json
{
  "id": "Infrastructure/entropicmem-architecture",
  "title": "EntropicMem Architecture",
  "type": "permanent",
  "domain": "Infrastructure",
  "importance": 0.85,
  "tags": ["architecture", "memory", "hermes"],
  "color": "#1DCF8E"  // per-domain palette
}
```

**Edge Schema:**
```json
{
  "source": "Infrastructure/entropicmem-architecture",
  "target": "Infrastructure/Mnemosyne-BEAM",
  "weight": 3,
  "kind": "wikilink|tag|semantic"
}
```

### 4.5 Mnemosyne Bridge (Read/Write Hooks)

| Direction | Operation | Implementation |
|-----------|-----------|----------------|
| **Mnemosyne → Vault** | Cron (6h) or on-demand | `mnemosyne_bridge.export_to_vault()` reads `Mnemosyne.remember()` rows with `scope=global`, creates/updates permanent notes in `Mnemosyne/` folder with `entropic_id` = memory_id |
| **Vault → Mnemosyne** | Explicit `remember` CLI | `entropicmem remember "fact"` → creates vault note + calls `Mnemosyne.remember()` with same `entropic_id` |
| **Dedup** | Content hash | `entropic_id = sha256(content)[:16]` — identical content = same ID both sides |

---

## 5. `/learn` Workflow, Self-Setup, Installation, Initialization

### 5.1 End-to-End `/learn` Flow

```
User: /learn https://github.com/Ufonik88/EntropicMem
       │
       ▼
Hermes fetches repo → reads SKILL.md + SETUP.md
       │
       ▼
Agent calls: skill_manage create (name="entropicmem", category="memory", content=SKILL.md)
       │
       ▼
Skill installed at ~/.hermes/skills/entropicmem/
       │
       ▼
SETUP.md instructs agent to run first-time bootstrap:
       │
       ▼
Agent runs: python3 ~/.hermes/skills/entropicmem/scripts/entropicmem.py init
       │
       ├── Resolves vault path (existing Obsidian OR new ~/.hermes/entropicmem/vault)
       ├── Creates vault skeleton from templates/vault/
       ├── Initializes SQLite index at ~/.hermes/entropicmem/index.db
       ├── Writes ~/.hermes/.env entries: ENTROPICMEM_VAULT_PATH, ENTROPICMEM_INDEX_DB
       ├── Runs: entropicmem lint + hotcache + graph export (smoke test)
       └── Opens graph.html in default browser (optional)
       │
       ▼
Agent reports: "EntropicMem installed. Vault: ~/Documents/Obsidian Vault (bound). 
   Commands: entropicmem ingest|query|note|lint|graph|hotcache. Graph: file://..."
```

### 5.2 SKILL.md Triggers (Description ≤60 chars)

> **Builds and maintains an agent-native Obsidian vault with Mnemosyne bridge, graph visualizer, and 6-command knowledge loop. Use when creating a second brain, ingesting sources, querying linked notes, or visualizing knowledge graph.**

**When to Use (explicit triggers in SKILL.md):**
- "create a vault" / "start a second brain" / "set up Obsidian for Hermes"
- "ingest this URL/paper/conversation into my vault"
- "query my vault for X" / "search my notes about Y"
- "build a knowledge graph" / "visualize my vault connections"
- "lint my vault" / "find orphan notes" / "fix dead links"
- "sync Mnemosyne memories to vault" / "promote durable fact to vault"

### 5.3 SETUP.md (First-Run Checklist)

```markdown
# EntropicMem First-Run Setup

## 1. Resolve Vault Path
- If `~/Documents/Obsidian Vault` exists AND has AGENTS.md → bind to it (SAFE MODE: never write Mnemosyne/, .obsidian/, _archive/)
- Else → create new vault at `~/.hermes/entropicmem/vault`

## 2. Install Dependencies
- Stdlib only for core (Python 3.10+)
- Optional: `pip install sentence-transformers` for semantic re-rank; `pip install graphviz` for DOT export. v1 uses stdlib templates only.
- Optional: `pip install graphviz` for DOT export

## 3. Environment Variables (append to ~/.hermes/.env)
ENTROPICMEM_VAULT_PATH="/home/ufonik/Documents/Obsidian Vault"
ENTROPICMEM_INDEX_DB="/home/ufonik/.hermes/entropicmem/index.db"
ENTROPICMEM_MNEMOSYNE_DB="/home/ufonik/.hermes/mnemosyne/data/mnemosyne.db"

## 4. Initialize
python3 ~/.hermes/skills/entropicmem/scripts/entropicmem.py init --vault "$ENTROPICMEM_VAULT_PATH"

## 5. Smoke Test
entropicmem lint
entropicmem hotcache
entropicmem graph export --format html
# Open graph.html in browser

## 6. Register Cron (optional)
# Add to Hermes cron: "0 */6 * * * entropicmem bridge export"
```

### 5.4 Initialization Command

```bash
entropicmem init [--vault PATH] [--force] [--dry-run]
```

- `--vault`: Explicit path (overrides env var)
- `--force`: Re-initialize existing vault (backs up AGENTS.md, SCHEMA.md, index.md, log.md)
- `--dry-run`: Print actions without writing

---

## 6. Memory Model, Vault Structure, Linking, Retrieval, Visual Graph

### 6.1 Memory Model (Layered)

| Layer | System | Purpose | Retention | Access Pattern |
|-------|--------|---------|-----------|----------------|
| **L1: Hot Context** | Mnemosyne `working_memory` | Current conversation, auto-injected | Session | Automatic (system prompt) |
| **L2: Episodic** | Mnemosyne `episodic_memory` | Cross-session facts, vector+FTS recall | Long-term | `mnemosyne_recall()` tool |
| **L3: Scratchpad** | Mnemosyne `scratchpad` | Agent temp reasoning | Session | `mnemosyne_scratchpad_*` tools |
| **L4: Durable Knowledge** | **EntropicMem Vault** | Compounded, linked, browsable, human-owned | Permanent | `entropicmem query/ingest/graph` |
| **L5: Mnemosyne Mirror** | Vault `Mnemosyne/` folder | Read-only projection of L2 | Sync'd (6h) | Human browse in Obsidian |

**Round-Trip Identity:** `entropic_id` (SHA256(content)[:16]) links vault note ↔ Mnemosyne row.

### 6.2 Vault Structure (Reiterated)

See Section 4.2. Key additions:
- `SCHEMA.md` — domain list, tag taxonomy, conventions (agent reads on every session)
- `index.md` — sectioned catalog (auto-maintained by `moc` command)
- `log.md` — append-only: `2026-07-16 14:32 | ingest | Lit - Karpathy LLM Wiki | 12 notes`
- `templates/` — string.Template templates for consistent note creation

### 6.3 Linking System

1. **Wikilinks** — `[[Note Title]]` (case-sensitive, Linux). Auto-generated notes)
2. **Frontmatter tags** — `#tag` in YAML, queryable via index
3. **MOC backlinks** — Every note gets `- [[Domain/Index]]` in `## Links` section
4. **Mnemosyne cross-ref** — `[[Mnemosyne Dashboard]]` in literature notes
5. **Semantic edges (optional)** — Embedding similarity >0.85 added as `graph_edges` in index (kind=semantic)

**Link Validation:** `lint` checks dead links; `moc` repairs orphans by back-linking to domain Index.

### 6.4 Retrieval Mechanisms (Detailed)

```python
# retrieval.py — composed stack

def retrieve(query: str, vault: Path, index_db: Path, 
             mnemosyne: Optional[Mnemosyne] = None,
             use_semantic: bool = False) -> RetrievalResult:
    """
    Returns: {notes: [NoteRef], snippets: [Snippet], graph_context: GraphContext}
    """
    # 1. Orientation — hot cache (instant)
    hot = retrieve_hot_cache(vault)
    
    # 2. FTS — primary recall
    fts_hits = retrieve_fts(index_db, query, top_k=20)
    
    # 3. Wikilink expansion — context
    seed_ids = [h.note_id for h in fts_hits[:5]]
    link_hits = retrieve_wikilink_expansion(index_db, seed_ids, hops=2)
    
    # 4. Merge + dedup by note_id
    all_hits = merge_dedup(fts_hits + link_hits)
    
    # 5. Optional semantic re-rank
    if use_semantic and EMBEDDER_AVAILABLE:
        all_hits = retrieve_semantic_rerank(all_hits, query, EMBEDDER)
    
    # 6. Build cited snippets
    snippets = build_snippets(all_hits[:10], query)
    
    # 7. Graph context for visualizer
    graph_ctx = build_graph_context(index_db, [h.note_id for h in all_hits[:10]])
    
    return RetrievalResult(notes=all_hits[:10], snippets=snippets, graph_context=graph_ctx)
```

**Agent Usage Pattern (in SKILL.md):**
```python
# General chat → Mnemosyne only (saves tokens)
# Heavy/durable/linked work → EntropicMem
result = entropicmem.query("VaultKnox policy engine")
# Returns cited notes + snippets → agent synthesizes answer
```

### 6.5 Visual Graph (Detailed Spec)

**Export Command:**
```bash
entropicmem graph export --format json|dot|html|canvas --output-dir ./export
entropicmem graph serve --port 8080  # python -m http.server on export dir
```

**HTML Visualizer Requirements:**
- Single `graph.html` (self-contained, ~300 lines JS + CSS)
- Loads `graph.json` via `fetch()`
- D3 v7 (CDN) or pure Canvas force-directed
- **Galaxy Aesthetic:**
  - Background: `#0a0a0f` (near-black)
  - Node glow: SVG filter `feGaussianBlur` stdDeviation="2.5"
  - Domain palette (8 colors, colorblind-safe):
    - Infrastructure: `#1DCF8E` (Brand Green)
    - Ajax Systems: `#5AE4AA` (Light Mint)
    - X-Growth: `#00AD74` (Deep Green)
    - Finance: `#FFB800` (Gold)
    - Workflows: `#7C4DFF` (Deep Purple)
    - People: `#FF6B6B` (Coral)
    - Knowledge: `#4FC3F7` (Sky Blue)
    - Products-Research: `#FF9800` (Orange)
    - Projects: `#9CCC65` (Light Green)
  - Node radius: `max(4, min(24, log(importance * 100) * 6))`
  - Edge width: `0.5 + weight * 1.2`
  - Physics: `linkDistance = 80`, `charge = -120`, `collision radius = 8`
- **Interactions:**
  - Hover → tooltip (title, type, tags, domain)
  - Click → `navigator.sendBeacon('/entropicmem/open', {id})` + fallback to `window.location = 'entropicmem://open/' + id`
  - Filter panel: domain checkboxes, tag search, importance slider
  - Legend: domain colors + node type shapes (circle=permanent, square=literature, diamond=MOC, triangle=index)

**Custom Protocol Handler (Optional v1.1):**
- Register `entropicmem://` → `entropicmem open %1` for click-to-open from browser

---

## 7. Implementation Phases & Milestones

| Phase | Name | Duration | Deliverables | Exit Criteria |
|-------|------|----------|--------------|---------------|
| **0** | **Plan Freeze** | Now | `PROJECT_PLAN.md`, `README.md`, `RISKS.md`, `RELEASE-CHECKLIST.md` | All 10 plan sections complete; open decisions resolved in text |
| **1** | **Core Vault Engine** | 2-3 weeks | `init`, `write_note`, `read_note`, `linkify`, `sanitize`, `domains`, `MOC`, `hotcache`, `lint`, `templates/vault/` | `entropicmem init` creates valid vault; `lint` finds 0 orphans in fresh vault; `hotcache` produces Wiki-Cache.md |
| **2** | **Retrieval & Knowledge Loop** | 2-3 weeks | SQLite FTS index, `query`, `ingest`, `ingest-pile`, `note`, `research`, `search` | `ingest URL` → literature + 8-15 permanents; `query` returns cited snippets; `research` creates research brief |
| **3** | **Graph Visualizer** | 1-2 weeks | `graph export` (json/dot/html/canvas), `graph serve`, `graph.html` (galaxy theme) | `graph export --format html` produces viewable `graph.html`; click-to-open works via custom protocol or file watcher |
| **4** | **Mnemosyne Bridge** | 1-2 weeks | `bridge export` (Mnemosyne→Vault), `bridge import` (Vault→Mnemosyne), `remember` CLI, cron recipe | `bridge export` creates/updates `Mnemosyne/` notes with `entropic_id`; `remember "fact"` writes both sides; dedup via content hash works |
| **5** | **Packaging & `/learn` Polish** | 1 week | `SKILL.md` (triggers, workflows), `SETUP.md`, `README.md`, public GitHub repo, `/learn` dry-run, tests | `/learn https://github.com/...` installs skill → runs `init` → smoke test passes; repo has clear README, license, contributing |
| **6** | **Future (Post-v1)** | — | MemoryProvider adapter, Dataview-like queries, real-time graph server, Obsidian plugin sync | — |

**Milestone Gates (must pass before next phase):**
- Phase 1: `pytest tests/test_vault.py` + `entropicmem lint` on 100-note test vault = 0 errors
- Phase 2: `entropicmem query` on seeded vault returns correct citations for 10/10 test queries
- Phase 3: `graph.html` opens in browser, shows >50 nodes, click opens note in editor (via protocol)
- Phase 4: Round-trip `remember` → vault note + Mnemosyne row with same `entropic_id`; re-run = no dup
- Phase 5: Clean `/learn` install on fresh Hermes profile; skill loads, `init` works, graph renders

---

## 8. Repository Structure, Core Modules, Interfaces, Dependencies, Data Flows

### 8.1 Repository Structure

```
EntropicMem/
├── README.md                    # Public: install via /learn, quickstart, architecture
├── LICENSE                      # MIT
├── PROJECT_PLAN.md              # This document
├── RISKS.md                     # Open questions, decisions, mitigations
├── RELEASE-CHECKLIST.md         # Ship-ready definition
├── SETUP.md                     # First-run bootstrap (agent reads this)
├── pyproject.toml               # Optional: if packaged as pip installable
├── requirements.txt             # Optional deps (sentence-transformers, graphviz)
├── .gitignore
├── .github/
│   └── workflows/
│       └── test.yml             # CI: lint, type-check, test on PR
├── skills/
│   └── entropicmem/
│       ├── SKILL.md             # Agent instructions (triggers, workflows, tool framing)
│       ├── SETUP.md             # First-run checklist (copied from root)
│       ├── references/
│       │   ├── MEMORY_MODEL.md
│       │   ├── VAULT_SCHEMA.md
│       │   ├── HERMES_INTEGRATION.md
│       │   ├── CLI_REFERENCE.md
│       │   └── VISUALIZER.md
│       └── templates/
│           └── vault/           # Seed vault skeleton (copied at init)
│               ├── AGENTS.md
│               ├── SCHEMA.md
│               ├── index.md
│               ├── log.md
│               ├── inbox/.gitkeep
│               ├── .raw/.gitkeep
│               ├── Mnemosyne/.gitkeep
│               ├── templates/
│               │   ├── literature.md
│               │   ├── permanent.md
│               │   ├── moc.md
│               │   └── index.md
│               └── domains/
│                   ├── Infrastructure/.gitkeep
│                   ├── Ajax Systems/.gitkeep
│                   ├── X-Growth/.gitkeep
│                   ├── Finance/.gitkeep
│                   ├── Workflows/.gitkeep
│                   ├── People/.gitkeep
│                   ├── Knowledge/.gitkeep
│                   ├── Products-Research/.gitkeep
│                   └── Projects/.gitkeep
├── scripts/
│   ├── entropicmem.py           # Main CLI (click/argparse)
│   ├── vault.py                 # Vault operations library
│   ├── index.py                 # SQLite FTS + metadata + graph edges
│   ├── graph_export.py          # JSON/DOT/HTML/Canvas export
│   ├── mnemosyne_bridge.py      # Mnemosyne read/write hooks
│   ├── retrieval.py             # Composed retrieval stack
│   └── templates.py             # string.Template template rendering
├── tests/
│   ├── test_vault.py
│   ├── test_index.py
│   ├── test_retrieval.py
│   ├── test_graph.py
│   ├── test_bridge.py
│   └── fixtures/
│       └── sample_vault/        # 20-note test vault
└── docs/
    ├── ARCHITECTURE.md
    ├── MEMORY_MODEL.md
    ├── CLI_REFERENCE.md
    ├── VISUALIZER.md
    ├── SELF_INSTALL.md
    ├── COMPARISON.md
    └── COMPARISON_TABLE.md
```

### 8.2 Core Interfaces (Python)

```python
# vault.py
class Vault:
    def __init__(self, root: Path):
        self.root = root
    
    def resolve_path(self, relative: str) -> Path: ...
    def write_note(self, folder: str, title: str, body: str, 
                   tags: List[str], frontmatter: Dict = None) -> Path: ...
    def read_note(self, path: Path) -> Note: ...
    def append_note(self, path: Path, content: str, anchor: str = None) -> None: ...
    def linkify(self, text: str, known_titles: Set[str]) -> str: ...
    def sanitize(self, name: str) -> str: ...
    def list_notes(self, folder: str = None) -> List[Path]: ...
    def search_notes(self, pattern: str, folder: str = None) -> List[SearchHit]: ...

# index.py
class VaultIndex:
    def __init__(self, db_path: Path):
        self.db = sqlite3.connect(db_path)
        self._init_schema()
    
    def rebuild(self, vault: Vault) -> None: ...
    def upsert_note(self, note: Note) -> None: ...
    def delete_note(self, note_id: str) -> None: ...
    def search_fts(self, query: str, top_k: int = 10) -> List[SearchHit]: ...
    def get_backlinks(self, note_id: str) -> List[str]: ...
    def get_graph_edges(self) -> List[GraphEdge]: ...
    def get_note(self, note_id: str) -> Optional[Note]: ...

# retrieval.py
def retrieve_composed(query: str, vault: Vault, index: VaultIndex,
                      mnemosyne: Mnemosyne = None,
                      use_semantic: bool = False) -> RetrievalResult: ...

# mnemosyne_bridge.py
class MnemosyneBridge:
    def __init__(self, vault: Vault, index: VaultIndex, mnemosyne_db: Path):
        self.vault = vault
        self.index = index
        self.mnemosyne = Mnemosyne(db_path=mnemosyne_db)
    
    def export_to_vault(self, since: datetime = None) -> ExportResult: ...
    def import_from_vault(self, folder: str = "Mnemosyne") -> ImportResult: ...
    def remember_fact(self, content: str, domain: str, tags: List[str]) -> str: ...
```

### 8.3 Dependencies

| Dependency | Purpose | Required? |
|------------|---------|-----------|
| Python 3.10+ | Runtime | ✅ |
| `sqlite3` (stdlib) | FTS index, graph edges | ✅ |
| `pathlib`, `json`, `hashlib`, `datetime`, `re` | Core ops | ✅ |
| `string.Template` (stdlib) | Template rendering | ✅ stdlib |
| `click` or `argparse` | CLI | ✅ (stdlib argparse OK) |
| `sentence-transformers` | Semantic re-rank | ❌ Optional |
| `graphviz` (pygraphviz or `dot` binary) | DOT export | ❌ Optional |
| `d3` (CDN) | HTML visualizer | ✅ (via CDN in HTML) |

**No heavy ML deps in core.** Embeddings are optional degraded path.

### 8.4 Data Flows (Sequence)

**Ingest Flow:**
```
User: entropicmem ingest "https://arxiv.org/abs/2301.00001"
    │
    ▼
fetch_url() → raw text
    │
    ▼
extract_entities() → [entities]
    │
    ▼
vault.write_note("inbox", "Lit - ...", literature_template, tags=["literature"])
    │
    ▼
for entity in entities[:15]:
    vault.write_note("Knowledge", entity, permanent_template, tags=["permanent"])
    linkify(entity_note, all_titles)
    │
    ▼
index.upsert_note() for each new note
    │
    ▼
index.rebuild() or incremental upsert
    │
    ▼
hotcache rebuild (optional)
```

**Query Flow:**
```
User: entropicmem query "VaultKnox policy engine"
    │
    ▼
retrieve_composed(query, vault, index, mnemosyne=None, use_semantic=False)
    │
    ├── retrieve_hot_cache() → orientation string
    ├── retrieve_fts() → 20 hits
    ├── retrieve_wikilink_expansion() → +15 contextual hits
    ├── merge_dedup() → 25 unique
    └── build_snippets(top 10) → cited context
    │
    ▼
Print: note paths + snippets + graph_context
```

**Graph Export Flow:**
```
entropicmem graph export --format html
    │
    ▼
index.get_graph_edges() → [GraphEdge]
    │
    ▼
Build nodes from index (all notes with type, domain, importance, tags)
    │
    ▼
graph_export.export_json(nodes, edges) → export/graph.json
graph_export.export_html(nodes, edges) → export/graph.html (embeds graph.json fetch)
graph_export.export_dot(nodes, edges) → export/graph.dot
graph_export.export_canvas(nodes, edges) → export/graph.canvas
    │
    ▼
entropicmem graph serve → python -m http.server export/
```

---

## 9. Technical Risks, Open Questions, Decisions

| # | Risk / Question | Decision (Written in Plan) | Mitigation |
|---|-----------------|----------------------------|------------|
| 1 | **Mnemosyne as primary vs EntropicMem as replacement** | **EntropicMem is additive browser/authoring layer. Mnemosyne remains primary working/episodic memory.** | SKILL.md explicitly states: "General chat → Mnemosyne. Heavy/durable/linked → EntropicMem." |
| 2 | **Collision with bundled `obsidian` / `llm-wiki` skills** | **EntropicMem = structured second-brain + graph + init + Mnemosyne bridge. Complementary, not competitive.** | SKILL.md `related_skills: [obsidian, llm-wiki]`. `COMPARISON.md` documents differentiation. |
| 3 | **User's live vault is large (3K archived + 472 active) + Syncthing + Git** | **Default: index only non-archive domains. Never write `Mnemosyne/`, `.obsidian/`, `_archive/`. Safe mode binds to existing vault with write guards.** | `init --vault` with `--safe-mode` (default when AGENTS.md exists). `lint`/`moc` skip excluded folders. |
| 4 | **Embeddings optional — FTS required path** | **FTS5 is mandatory. `sentence-transformers` is `extras_require["semantic"]`. Degrade gracefully.** | `retrieve_composed` checks `EMBEDDER_AVAILABLE` flag; `use_semantic=False` by default. |
| 5 | **Graph performance on 3K+ notes** | **Cap nodes at 500 for visual export. Filter by domain/tags. Archive excluded by default.** | `graph export --max-nodes 500 --domain Infrastructure --min-importance 0.3` |
| 6 | **`/learn` doesn't install Python deps** | **SETUP.md uses stdlib-first CLI. Optional deps documented; agent prompts user to `pip install` if they want semantic/graphviz.** | `entropicmem --check-deps` prints status. `requirements-optional.txt` listed in SETUP.md. |
| 7 | **Packaging location — skill vs plugin vs both** | **Skill-first (user-installed via `/learn`). MemoryProvider adapter = Phase 6+.** | Repo root = skill folder for `/learn`. `plugins/memory/entropicmem/` = future adapter (Phase 6). |
| 8 | **Tencent vs ByteDance confusion** | **Clarify: OpenViking = ByteDance/Volcengine. Tencent analogues = Hunyuan long-context, VectorDB, markingmemory. Plan cites OpenViking as "Tencent/ByteDance-style context engineering lineage" — not a substitution.** | `COMPARISON.md` has "Lineage" column. |
| 9 | **Visual graph must work offline + in Docker/remote** | **Single `graph.html` + `graph.json` via `file://` or `python -m http.server`. No Electron, no WebGL, no build step.** | `graph serve` starts HTTP server. `graph.html` uses CDN D3 (with local fallback copy in `templates/`). |
| 10 | **Mnemosyne schema changes break bridge** | **Bridge uses ONLY public `Mnemosyne` class API (`remember`, `recall`, `get_stats`). No direct SQL.** | `mnemosyne_bridge.py` imports `Mnemosyne` from `mnemosyne.core.memory`. Unit tests mock the class. |
| 11 | **Bridge cron not enforced** | **Provide recipe in SETUP.md; user chooses frequency (6h matches existing).** | `entropicmem bridge export --since $(date -d '6 hours ago')` |
| 12 | **entropic_id collision** | **SHA256[:16] = 64-bit space. Negligible for <10M notes. Log warning on collision.** | `entropic_id = hashlib.sha256(content.encode()).hexdigest()[:16]` |

---

## 10. Ship-Ready Definition — What v1.0 Must Include

### 10.1 Repository (Public GitHub)

- [ ] `README.md` with: one-line description, `/learn` install command, architecture diagram, quickstart, license
- [ ] `LICENSE` (MIT)
- [ ] `PROJECT_PLAN.md` (this document)
- [ ] `RISKS.md`, `RELEASE-CHECKLIST.md`
- [ ] `.github/workflows/test.yml` passing (lint + unit tests)
- [ ] Tagged release `v1.0.0` with changelog

### 10.2 Skill Package (`skills/entropicmem/`)

- [ ] `SKILL.md` — description ≤60 chars, triggers, workflows, tool framing (Hermes tools only)
- [ ] `SETUP.md` — first-run checklist (vault resolution, env vars, init, smoke test)
- [ ] `references/` — 5 docs (MEMORY_MODEL, VAULT_SCHEMA, HERMES_INTEGRATION, CLI_REFERENCE, VISUALIZER)
- [ ] `templates/vault/` — complete seed skeleton (AGENTS.md, SCHEMA.md, index.md, log.md, templates/, domains/)
- [ ] Progressive disclosure: SKILL.md <100 lines, detail in references

### 10.3 CLI (`skills/entropicmem/scripts/entropicmem.py`)

| Subcommand | Status | Test |
|------------|--------|------|
| `init [--vault PATH] [--force] [--dry-run]` | ✅ Required | Creates valid vault, writes env vars |
| `ingest <source> [--domain DOMAIN]` | ✅ Required | URL/file/stdin → lit + 8-15 permanents |
| `ingest-pile <dir> [--domain DOMAIN]` | ✅ Required | Parallel + cross-ref |
| `query "<q>" [--top-k N] [--semantic]` | ✅ Required | Returns cited snippets |
| `note [title] [--domain DOMAIN]` | ✅ Required | Stdin → permanent note |
| `research "<q>" [--rounds N]` | ✅ Required | Research brief in inbox |
| `lint [--domain DOMAIN]` | ✅ Required | Orphans, dead links, stale, contradictions |
| `moc [--domain DOMAIN]` | ✅ Required | Builds Index.md + backlinks |
| `hotcache` | ✅ Required | Rebuilds Wiki-Cache.md |
| `graph export [--format json|dot|html|canvas] [--output-dir DIR] [--max-nodes N] [--domain D] [--min-imp F]` | ✅ Required | Viewable graph.html |
| `graph serve [--port N] [--dir DIR]` | ✅ Required | Serves export dir |
| `remember "fact" [--domain D] [--tags t1,t2]` | ✅ Required | Vault note + Mnemosyne row (same entropic_id) |
| `forget <entropic_id>` | ✅ Required | Deletes both sides |
| `open <note_id>` | ✅ Required | Opens note in $EDITOR / VS Code |
| `bridge export [--since DATETIME]` | ✅ Required | Mnemosyne → Vault Mnemosyne/ |
| `bridge import [--folder Mnemosyne]` | ⏳ Optional v1.1 | Vault → Mnemosyne |
| `--check-deps` | ✅ Required | Prints optional dep status |
| `--version` | ✅ Required | Prints version |

### 10.4 Core Library Modules

- [ ] `vault.py` — all ops tested (path resolution, write, read, linkify, sanitize, search)
- [ ] `index.py` — FTS5 schema, rebuild, upsert, delete, search, backlinks, graph edges
- [ ] `graph_export.py` — JSON, DOT, HTML (galaxy), Canvas
- [ ] `mnemosyne_bridge.py` — export, import, remember, dedup via content hash
- [ ] `retrieval.py` — composed stack with optional semantic
- [ ] `templates.py` — string.Template rendering for all note types

### 10.5 Visual Graph (`graph.html`)

- [ ] Single file, works via `file://` and `http://localhost:8080/`
- [ ] D3 v7 (CDN) + local fallback copy
- [ ] Galaxy theme: dark bg, per-domain palette, node glow, edge weight = thickness
- [ ] Physics tuned for web/galaxy (not hairball)
- [ ] Hover tooltip, click → `entropicmem://open/<id>` (protocol handler documented)
- [ ] Filter panel: domain, tags, importance slider
- [ ] Legend: domain colors + node type shapes
- [ ] Fixed seed for reproducibility

### 10.6 Tests (pytest)

| Test Module | Coverage Target |
|-------------|-----------------|
| `test_vault.py` | write/read/linkify/sanitize/search, path-with-spaces |
| `test_index.py` | rebuild, upsert, delete, FTS search, backlinks, graph edges |
| `test_retrieval.py` | composed stack returns correct citations for 10 fixture queries |
| `test_graph.py` | JSON/DOT/HTML/Canvas export valid; node/edge counts match |
| `test_bridge.py` | Round-trip remember → vault + Mnemosyne same entropic_id; dedup works |

### 10.7 `/learn` Dry-Run (Acceptance Test)

On a **fresh Hermes profile** (no EntropicMem):
```bash
# User action:
/learn https://github.com/Ufonik88/EntropicMem

# Expected agent behavior:
1. Fetches repo, reads SKILL.md + SETUP.md
2. skill_manage create name=entropicmem category=memory
3. Runs: python3 ~/.hermes/skills/entropicmem/scripts/entropicmem.py init
4. Runs: entropicmem lint && entropicmem hotcache && entropicmem graph export --format html
5. Opens graph.html (or reports path)
6. Reports: "EntropicMem installed. Vault: ~/Documents/Obsidian Vault. Commands: entropicmem ingest|query|graph..."
```

**Pass Criteria:** All steps complete without manual intervention; vault is valid; graph renders; no errors in Hermes logs.

### 10.8 Coexistence Guarantees

- [ ] Never writes to `Mnemosyne/`, `.obsidian/`, `_archive/` (guarded in `vault.py`)
- [ ] Respects existing `AGENTS.md`, `SCHEMA.md`, `index.md`, `log.md` (backs up on `--force`)
- [ ] Works with Syncthing (plain Markdown, no DB in vault)
- [ ] Works with git auto-commit (no binary files in vault)
- [ ] `obsidian` and `llm-wiki` skills remain functional

### 10.9 Documentation Suite (`docs/`)

- [ ] `ARCHITECTURE.md` — module diagram, data flows, why skill+scripts+MCP
- [ ] `MEMORY_MODEL.md` — 5-layer table, entropic_id round-trip, Mnemosyne bridge
- [ ] `CLI_REFERENCE.md` — every subcommand with examples
- [ ] `VISUALIZER.md` — D3 spec, node/edge schema, color palettes, physics params
- [ ] `SELF_INSTALL.md` — `/learn` walkthrough transcript, troubleshooting
- [ ] `COMPARISON.md` — vs obsidian skill, llm-wiki skill, Mnemosyne, OpenViking, Mem0, Tencent lineage
- [ ] `COMPARISON_TABLE.md` — machine-readable CSV for automated checks

---

## Appendix A: Key File Templates (Reference)

### A.1 `templates/vault/AGENTS.md`
```markdown
# AGENTS.md — EntropicMem Vault Boot File

> Boot instructions for any Hermes/agent session reading this vault.

## What This Vault Is
A personal knowledge base that compounds. Mnemosyne is working memory; this vault is the durable, linked, open-Markdown archive.

## Architecture
[vault root]/
├── AGENTS.md           # this file
├── SCHEMA.md           # domain config, tag taxonomy, conventions
├── index.md            # sectioned content catalog
├── log.md              # append-only action log
├── inbox/              # fleeting captures
├── .raw/               # web clipper landing
├── Mnemosyne/          # READ-ONLY Mnemosyne mirror (6h cron)
├── templates/          # note templates
└── <Domain>/           # Infrastructure, Ajax Systems, X-Growth, Finance, Workflows, People, Knowledge, Products-Research, Projects

## The Loop (6+ commands via `entropicmem`)
| Command | Purpose |
|---------|---------|
| `ingest <source>` | Literature + atomic permanents |
| `ingest-pile <dir>` | Batch + cross-ref |
| `query "<q>"` | Cited retrieval |
| `note [title]` | Stdin → permanent |
| `research "<q>"` | 3-round web research |
| `lint` | Orphans, dead links, stale, contradictions |
| `moc` | Build/repair domain Index + backlinks |
| `hotcache` | Refresh Wiki-Cache.md |
| `graph export` | JSON/DOT/HTML/Canvas visualizer |
| `remember "fact"` | Vault note + Mnemosyne row |

## Linking Conventions
- `[[wikilinks]]` — case-sensitive on Linux
- YAML frontmatter: tags, created, source, aliases, agent, entropic_id, domain
- Atomic notes, link liberally
- Promote `inbox/` → domain via `lint` or session end
- Cross-ref Mnemosyne via `[[Mnemosyne Dashboard]]`

## Git & Sync
- Auto-commit cron every 15 min (git history = undo)
- Syncthing syncs `.git/` to Mac — intentional
- Revert: `git log --oneline && git checkout <SHA> -- <path>`

## Safety
- Never edit `.obsidian/`, `Mnemosyne/`, `_archive/`
- Quote paths with spaces in shell
- Run `lint` weekly; resolves `[!contradiction]` callouts
```

### A.2 `templates/vault/SCHEMA.md`
```markdown
# Vault Schema — EntropicMem Configuration

## Domain
Hermes Agent second brain for Ufonik (Pre-Sales Manager, Ajax Systems, Sub-Saharan Africa)

## Conventions
- File names: lowercase, hyphens, no spaces (`transformer-architecture.md`)
- Every note: YAML frontmatter (see below)
- `[[wikilinks]]` minimum 2 outbound per permanent note
- Update `updated` date on every edit
- Every new note added to `index.md` under correct section
- Every action appended to `log.md`
- Provenance: `^[.raw/articles/source.md]` on synthesized paragraphs (3+ sources)

## Frontmatter Schema
```yaml
title: "Note Title"
type: "literature|permanent|moc|index|log"
tags: ["tag1", "tag2"]
created: "2026-07-16"
updated: "2026-07-16"
source: "url|file|conversation|agent"
source_url: "https://..."
aliases: ["Alt Name"]
agent: true
entropic_id: "a1b2c3d4e5f6g7h8"
domain: "Infrastructure"
```

## Tag Taxonomy (Capitalized, Relevant)
#Infrastructure #Hermes #VaultKnox #Mnemosyne #AjaxSystems #XGrowth #Finance #Workflows #People #Knowledge #ProductsResearch #Projects

## Domain List (Seeded at Init)
1. Infrastructure — Hermes, VaultKnox, Mnemosyne, models, servers, signal-cli
2. Ajax Systems — Products, APIs, migration paths, client notes, integrations
3. X-Growth — X/Twitter growth engine, xurl CLI, posting strategy
4. Finance — Wedding, FNB, budget, invoices
5. Workflows — Cron patterns, skill library updates, automation
6. People — Ufonik, family, Pami, relationships
7. Knowledge — General facts, research, techniques
8. Products-Research — External tools, GitHub repos, third-party products
9. Projects — 25 GitHub repos organized by domain

## Linking Rules
- Literature notes → `[[Domain/Entity]]` for every extracted entity
- Permanent notes → minimum 2 `[[wikilinks]]` to other permanents or MOCs
- MOCs (`Index.md`) → list ALL notes in domain as wikilinks
- Every note → `## Links` section with `- [[Domain/Index]]` backlink
```

### A.3 `templates/vault/templates/permanent.md`
```markdown
# {{ title }}

## Context
{{ context }}

## Source
- {{ source_link }}

## Links
- [[{{ domain }}/Index]]
- [[Mnemosyne Dashboard]]
{% for tag in tags %}
- #{{ tag }}
{% endfor %}
```

### A.4 `templates/vault/templates/literature.md`
```markdown
# Lit - {{ title }}

**Source:** {{ source_url }}

## Key Points
{% for point in key_points %}
- {{ point }}
{% endfor %}

## Extracted Entities
{% for entity in entities %}
- [[{{ entity }}]]
{% endfor %}

## Links
- [[Mnemosyne Dashboard]]
```

---

## Appendix B: Mnemosyne Bridge — Export/Import Detail

### Export (Mnemosyne → Vault)
```python
def export_to_vault(self, since: datetime = None) -> ExportResult:
    """
    Reads Mnemosyne working_memory + memories where scope=global.
    For each memory:
      - entropic_id = memory.id (or hash(content)[:16] for legacy)
      - Check if note exists in vault/Mnemosyne/ with same entropic_id
      - If not exists: create permanent note in Mnemosyne/ folder
      - If exists: update if content changed (compare hash)
      - Frontmatter: type=permanent, source=mnemosyne, agent=true, entropic_id=...
    """
```

### Import (Vault → Mnemosyne)
```python
def import_from_vault(self, folder: str = "Mnemosyne") -> ImportResult:
    """
    Reads vault/folder/*.md where frontmatter.agent=true.
    For each note:
      - entropic_id = frontmatter.entropic_id or hash(content)[:16]
      - Mnemosyne.remember(content, source="vault", importance=frontmatter.importance or 0.5,
                           scope="global", metadata={"vault_path": str(path), "tags": tags},
                           memory_id=entropic_id)  # explicit ID for dedup
    """
```

### Remember CLI (User-Facing)
```bash
entropicmem remember "VaultKnox policy engine evaluates rules at request time, not config load" \
  --domain Infrastructure \
  --tags vaultknox,policy,engine
```
- Creates permanent note in `Infrastructure/` with frontmatter
- Calls `Mnemosyne.remember()` with same `entropic_id`
- Returns `entropic_id` for future `forget`

---

## Appendix C: Graph Export — Node/Edge Schema (JSON)

```json
{
  "nodes": [
    {
      "id": "Infrastructure/entropicmem-architecture",
      "title": "EntropicMem Architecture",
      "type": "permanent",
      "domain": "Infrastructure",
      "importance": 0.85,
      "tags": ["architecture", "memory", "hermes"],
      "color": "#1DCF8E",
      "shape": "circle",
      "x": null,
      "y": null
    }
  ],
  "edges": [
    {
      "source": "Infrastructure/entropicmem-architecture",
      "target": "Infrastructure/Mnemosyne-BEAM",
      "weight": 3,
      "kind": "wikilink"
    }
  ],
  "meta": {
    "generated": "2026-07-16T14:32:00Z",
    "node_count": 342,
    "edge_count": 1287,
    "domains": ["Infrastructure", "Ajax Systems", "..."],
    "max_importance": 0.95
  }
}
```

---

## Appendix D: Decision Log (For Reviewers)

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-07-16 | Skill-first, not MemoryProvider | Only one provider active; replacing Mnemosyne breaks current stack |
| 2026-07-16 | Stdlib-first CLI, optional deps | `/learn` can't install pip deps; FTS required, embeddings optional |
| 2026-07-16 | `entropic_id` = SHA256(content)[:16] | Deterministic round-trip key; no UUID service needed |
| 2026-07-16 | Galaxy visualizer = single HTML + D3 CDN | Works offline via file://, no build, no Electron |
| 2026-07-16 | 8 Ufonik domains seeded at init | Matches existing vault; agent knows them from AGENTS.md |
| 2026-07-16 | `Mnemosyne/` folder = read-only mirror | Matches existing 6h cron pattern; human safety |
| 2026-07-16 | Never write `.obsidian/`, `_archive/` | Syncthing + git + user safety |
| 2026-07-16 | `/learn` installs skill → skill runs `init` | Matches `learn_prompt.py` flow; no plugin enable needed |

---

**End of Project Plan.**  
This document is the single source of truth for EntropicMem v1. Implementation follows the phased milestones in Section 7. All open questions are resolved in Section 9. Ship criteria are explicit in Section 10.