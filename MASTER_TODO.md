# EntropicMem — Master Task Tracker

> **Rule:** Completed tasks move to the bottom section. Active and not-started tasks stay at the top.
> **Handoff:** Each task block includes enough context for a different agent/model to continue where the last one left off.

---

## ACTIVE TASKS

| # | Phase | Task | Status | Assigned To | Started | Completed |
|---|-------|------|--------|-------------|---------|-----------|
| 7 | 2 | **ingest subcommand (URL → lit + permanents)** | `not_started` | — | — | — |
| 8 | 2 | **ingest-pile subcommand (batch + cross-ref)** | `not_started` | — | — | — |
| 9 | 2 | **note subcommand (stdin → permanent note)** | `not_started` | — | — | — |
| 10 | 2 | **research subcommand (3-round web research → inbox)** | `not_started` | — | — | — |
| 11 | 2 | **remember / forget subcommands (vault + Mnemosyne)** | `not_started` | — | — | — |
| 13 | 2 | **moc subcommand (rebuild domain Index.md + backlinks)** | `not_started` | — | — | — |
| 15 | 2 | **open subcommand (open note in $EDITOR / VS Code)** | `not_started` | — | — | — |
| 16 | 2 | **--check-deps (print optional dep status)** | `not_started` | — | — | — |
| 17 | 2 | **Phase 2 gate: 10/10 test queries return correct citations** | `not_started` | — | — | — |
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
| P1 | 0 | **README.md** | 2026-07-16 | /learn install command, architecture diagram, quickstart, comparison table. |
| P2 | 0 | **SETUP.md** | 2026-07-16 | Agent-facing bootstrap checklist. |
| P3 | 0 | **RISKS.md** | 2026-07-16 | 12-item risk register with owners. |
| P4 | 0 | **RELEASE-CHECKLIST.md** | 2026-07-16 | Ship-ready definition. |
| P5 | 0 | **skills/entropicmem/SKILL.md** | 2026-07-16 | Agent instructions (56-char desc, 7 workflows). |
| P6 | 0 | **skills/entropicmem/SETUP.md** | 2026-07-16 | Mirror of root SETUP.md. |
| P7 | 0 | **skills/entropicmem/templates/vault/** | 2026-07-16 | Seed skeleton: AGENTS, SCHEMA, index, log + 9 domains. |
| P8 | 0 | **skills/entropicmem/references/*.md** | 2026-07-16 | 5 stub reference docs. |
| P9 | 0 | **docs/*.md** | 2026-07-16 | 7 stub documentation docs. |
| P10 | 0 | **LICENSE (MIT)** | 2026-07-16 | Standard MIT license. |
| P11 | 0 | **.gitignore** | 2026-07-16 | Excludes DBs, exports, env, build artifacts. |
| P12 | 0 | **.github/workflows/test.yml** | 2026-07-16 | CI stub. |
| P13 | 0 | **Git init + commits** | 2026-07-16 | Repo pushed to github.com/Ufonik88/EntropicMem. |
| P14 | 0 | **MASTER_TODO.md** | 2026-07-16 | This file. |
| **1** | **1** | **vault.py** | **2026-07-16** | Core vault operations: resolve, write, read, linkify, sanitize, search, list_notes, open_note, extract_wikilinks. Write guards for Mnemosyne/, .obsidian/, _archive/. Safe mode detection. Note dataclass with YAML frontmatter round-trip. |
| **2** | **1** | **index.py** | **2026-07-16** | SQLite FTS5 index: rebuild, upsert, delete, search_fts, search_by_title, get_backlinks, get_outlinks, get_graph_edges, get_graph_nodes, get_stats. Graph edge table with weight tracking, upsert_edges_for_note. |
| **3** | **1** | **retrieval.py** | **2026-07-16** | Composed 5-layer search: hot_cache → FTS → wikilink expansion → optional semantic re-rank → cited snippets. Domain filtering. Graceful optional dep degradation. RetrievalResult with to_text(). |
| **4** | **1** | **entropicmem CLI skeleton** | **2026-07-16** | argparse CLI with all subcommands. Phase 1 implemented: init, lint, hotcache, query, note, --version, --check-deps. Phase 2-5 stubs: ingest, ingest-pile, research, moc, graph, remember, forget, open, bridge. Seed vault templates with 9 domains. |
| **5** | **1** | **Unit tests** | **2026-07-16** | 30 tests passing: TestVault (13), TestIndex (8), TestRetrieval (6), TestCLI (3). Covers write/read/sanitize/protected/linkify/frontmatter/FTS/search/backlinks/graph/retrieval/domain-filter/lint-init. |
| **6** | **1** | **Phase 1 gate** | **2026-07-16** | ✅ init creates valid vault. ✅ lint finds 0 issues on clean vault. ✅ hotcache produces Wiki-Cache.md. ✅ query returns ranked cited results. ✅ 30 pytest pass. |

---

## HANDOFF NOTES FOR NEXT AGENT (Phase 2)

### Where we are
Phase 1 (Core Vault Engine) is **complete**. The four core modules are implemented and tested:
- `skills/entropicmem/scripts/vault.py` — 500+ lines, all vault operations
- `skills/entropicmem/scripts/index.py` — 430+ lines, FTS5 + graph edges
- `skills/entropicmem/scripts/retrieval.py` — 250+ lines, composed search stack
- `skills/entropicmem/scripts/entropicmem.py` — 500+ lines, CLI with working init/lint/hotcache/query/note

### What needs to happen next
**Phase 2 — Retrieval & Knowledge Loop.** See `PROJECT_PLAN.md` §7.2.

The CLI already has stubs for all Phase 2 subcommands. The next agent should:

1. **Implement `ingest`** (Task #7): Fetch URL/file → extract entities → create literature note + 8-15 permanent notes with cross-links. Uses `vault.write_note()` + `index.upsert_note()` + `index.upsert_edges_for_note()`. See `wiki.py` in `~/.hermes/scripts/wiki.py` for the reference implementation pattern.

2. **Implement `ingest-pile`** (Task #8): Parallel batch ingest of a directory. Cross-reference shared entities across notes.

3. **Implement `research`** (Task #10): 3-round web search → inbox brief. Uses `web_search` + `web_extract` Hermes tools.

4. **Implement `moc`** (Task #13): Rebuild domain Index.md files — list all notes in domain, add backlinks section to each note pointing to domain Index.

5. **Implement `remember`/`forget`** (Task #11): These require Mnemosyne bridge (Phase 4) so they can remain stubs for now, or implement vault-only versions.

6. **Implement `open`** (Task #15): Wire up `vault.open_note()` — already implemented in vault.py, just needs the CLI handler.

7. **`note` subcommand is already implemented** — stdin → permanent note. Works. Mark Task #9 as done.

8. **`lint` and `hotcache` are already implemented** — Tasks #12 and #14 done. Mark as completed.

9. **Write Phase 2 tests** and verify the gate: 10/10 test queries return correct citations.

### Key constraints (same as Phase 1)
- Stdlib-first. `string.Template` for templates.
- All scripts in `skills/entropicmem/scripts/`.
- Tests: `python3 -m pytest tests/ -q`. Use temp dirs.
- Update this file after each completed task.
- Never write Mnemosyne/, .obsidian/, _archive/.

### Working commands (Phase 1)
```bash
cd ~/Documents/Coding\ Projects/EntropicMem
python3 skills/entropicmem/scripts/entropicmem.py init --vault /tmp/test-vault
python3 skills/entropicmem/scripts/entropicmem.py lint
python3 skills/entropicmem/scripts/entropicmem.py hotcache
python3 skills/entropicmem/scripts/entropicmem.py query "search terms" --top-k 10
python3 skills/entropicmem/scripts/entropicmem.py note "My Title" --domain Knowledge < input.txt
python3 -m pytest tests/ -q
```
