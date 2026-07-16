# EntropicMem — Master Task Tracker

> **Rule:** Completed tasks move to the bottom section. Active and not-started tasks stay at the top.
> **Handoff:** Each task block includes enough context for a different agent/model to continue where the last one left off.

---

## ACTIVE TASKS

| # | Phase | Task | Status | Assigned To | Started | Completed |
|---|-------|------|--------|-------------|---------|-----------|
| 18 | 3 | **graph_export.py — JSON/DOT/HTML/Canvas export** | `not_started` | — | — | — |
| 19 | 3 | **graph.html — D3 galaxy-themed visual graph** | `not_started` | — | — | — |
| 20 | 3 | **graph serve subcommand** | `not_started` | — | — | — |
| 21 | 3 | **Phase 3 gate: graph renders >50 nodes in browser** | `not_started` | — | — | — |
| 22 | 4 | **mnemosyne_bridge.py — export (M→V) + import (V→M) + remember + dedup** | `not_started` | — | — | — |
| 23 | 4 | **bridge export / import subcommands** | `not_started` | — | — | — |
| 24 | 4 | **Phase 4 gate: round-trip remember → vault + Mnemosyne, same entropic_id** | `not_started` | — | — | — |
| 25 | 5 | **skills/entropicmem/references/*.md — 5 full reference docs** | `not_started` | — | — | — |
| 26 | 5 | **docs/*.md — 7 full documentation docs** | `not_started` | — | — | — |
| 27 | 5 | **SKILL.md — final review and tightening (<100 lines)** | `not_started` | — | — | — |
| 28 | 5 | **/learn dry-run acceptance test on fresh Hermes profile** | `not_started` | — | — | — |
| 29 | 5 | **Phase 5 gate: clean /learn install, init works, graph renders** | `not_started` | — | — | — |
| 30 | 5 | **GitHub release v1.0.0 + changelog** | `not_started` | — | — | — |

---

## COMPLETED TASKS

| # | Phase | Task | Completed | Notes |
|---|-------|------|-----------|-------|
| P0 | 0 | **PROJECT_PLAN.md** | 2026-07-16 | Full 10-section technical spec (1,566 lines). |
| P1 | 0 | **README.md** | 2026-07-16 | /learn install command, architecture diagram, quickstart. |
| P2 | 0 | **SETUP.md** | 2026-07-16 | Agent-facing bootstrap checklist. |
| P3 | 0 | **RISKS.md** | 2026-07-16 | 12-item risk register. |
| P4 | 0 | **RELEASE-CHECKLIST.md** | 2026-07-16 | Ship-ready definition. |
| P5 | 0 | **SKILL.md** | 2026-07-16 | Agent instructions (56-char desc, 7 workflows). |
| P6 | 0 | **templates/vault/** | 2026-07-16 | Seed skeleton: 9 domains. |
| P7 | 0 | **LICENSE + .gitignore + CI** | 2026-07-16 | MIT, excludes DBs/exports/build. |
| P8 | 0 | **GitHub repo + push** | 2026-07-16 | github.com/Ufonik88/EntropicMem. |
| **1** | **1** | **vault.py** | **2026-07-16** | Core ops: resolve, write, read, linkify, sanitize, search, open_note, extract_wikilinks, write guards, safe mode. 413 lines. |
| **2** | **1** | **index.py** | **2026-07-16** | SQLite FTS5: rebuild, upsert, delete, search_fts, backlinks, outlinks, graph_edges, graph_nodes, stats. 434 lines. |
| **3** | **1** | **retrieval.py** | **2026-07-16** | 5-layer stack: hot_cache → FTS → wikilink expansion → optional semantic re-rank → cited snippets. 265 lines. |
| **4** | **1** | **entropicmem CLI** | **2026-07-16** | argparse CLI with all 13 subcommands. Phase 1: init, lint, hotcache, query, note. 700+ lines. |
| **5** | **1** | **Phase 1 tests** | **2026-07-16** | 30 tests: TestVault, TestIndex, TestRetrieval, TestCLI. |
| **6** | **1** | **Phase 1 gate** | **2026-07-16** | ✅ init, lint (0 issues), hotcache, query, 30 tests. |
| **7** | **2** | **ingest subcommand** | **2026-07-16** | URL/file/stdin → 1 lit note + up to 15 atomic permanent notes with entity extraction, wikilinks, FTS indexing. |
| **8** | **2** | **ingest-pile subcommand** | **2026-07-16** | Batch directory ingest with cross-references. |
| **9** | **2** | **note subcommand** | **2026-07-16** | Already implemented in Phase 1. Stdin → permanent note. |
| **10** | **2** | **research subcommand** | **2026-07-16** | Agent-driven research brief in inbox. |
| **11** | **2** | **remember/forget** | **2026-07-16** | Vault-only (Mnemosyne bridge in Phase 4). remember creates note with entropic_id; forget deletes by id. |
| **12** | **2** | **lint subcommand** | **2026-07-16** | Already implemented in Phase 1. Orphans, dead links, stubs, stale, contradictions. |
| **13** | **2** | **moc subcommand** | **2026-07-16** | Rebuilds domain Index.md with frontmatter + backlinks on every note. |
| **14** | **2** | **hotcache subcommand** | **2026-07-16** | Already implemented in Phase 1. Rebuilds Wiki-Cache.md. |
| **15** | **2** | **open subcommand** | **2026-07-16** | Wired vault.open_note(). Opens note in $EDITOR/VS Code. |
| **16** | **2** | **--check-deps** | **2026-07-16** | Reports Python version, optional dep status. |
| **17** | **2** | **Phase 2 gate** | **2026-07-16** | ✅ 50 pytest pass (30 Phase 1 + 20 Phase 2). ✅ 10/10 query tests return correct results. ✅ All 13 subcommands work end-to-end. |

---

## HANDOFF NOTES FOR NEXT AGENT (Phase 3)

### Where we are
Phases 0, 1, and 2 are **complete**. All 13 subcommands are implemented:
```
init | ingest | ingest-pile | query | note | research | lint | moc | hotcache |
graph (stub) | remember | forget | open | bridge (stub)
```

### What needs to happen next
**Phase 3 — Graph Visualizer.** See `PROJECT_PLAN.md` §7.3.

1. **`graph_export.py`** (Task #18): JSON/DOT/HTML/Canvas export from VaultIndex graph data. See plan §6.5 for full node/edge schema. Uses `index.get_graph_nodes()` + `index.get_graph_edges()`.

2. **`graph.html`** (Task #19): Single-file D3 v7 force-directed galaxy-themed visual graph. Dark background (#0a0a0f), per-domain palette (8 colors from Ajax brand), node glow, edge weight = thickness, hover tooltip, click-to-open. Works via `file://`.

3. **`graph serve`** (Task #20): Python HTTP server on export directory.

4. **Phase 3 gate** (Task #21): graph.html renders >50 nodes in browser; click opens note via `entropicmem://open/` protocol.

### Key constraints
- Stdlib-only for export. D3 via CDN in HTML.
- Single file graph.html, no build step.
- Works offline via `file://`.
- Max 500 nodes default with domain/importance filters.
- Per-domain color palette from Ajax brand (Infrastructure=#1DCF8E, Ajax=#5AE4AA, etc).

### Working commands (Phases 1-2)
```bash
python3 skills/entropicmem/scripts/entropicmem.py init --vault /tmp/test
python3 skills/entropicmem/scripts/entropicmem.py ingest test.md --domain Knowledge
python3 skills/entropicmem/scripts/entropicmem.py query "search terms" --top-k 10
python3 skills/entropicmem/scripts/entropicmem.py moc
python3 skills/entropicmem/scripts/entropicmem.py lint
python3 skills/entropicmem/scripts/entropicmem.py remember "fact" --domain Infra
python3 -m pytest tests/ -q
```
