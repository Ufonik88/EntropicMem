# EntropicMem — Master Task Tracker

> **Rule:** Completed tasks move to the bottom section. Active and not-started tasks stay at the top.
> **Handoff:** Each task block includes enough context for a different agent/model to continue where the last one left off.

---

## ACTIVE TASKS

<!--
  INSTRUCTIONS FOR AGENTS:
  - Only ONE task in_progress at a time.
  - When you start a task, move it here and set status: in_progress.
  - When you finish a task, move it to COMPLETED section at the bottom.
  - Before starting any task, read SETUP.md and PROJECT_PLAN.md §7 (Phases).
  - Tests go in tests/; run them with `python3 -m pytest tests/ -q`.
  - Use stdlib only for core. Optional deps: sentence-transformers, graphviz.
-->

| # | Phase | Task | Status | Assigned To | Started | Completed |
|---|-------|------|--------|-------------|---------|-----------|
| 1 | 1 | **vault.py — Core vault operations** | `not_started` | — | — | — |
| 2 | 1 | **index.py — SQLite FTS5 index + graph edges** | `not_started` | — | — | — |
| 3 | 1 | **retrieval.py — Composed search stack** | `not_started` | — | — | — |
| 4 | 1 | **entropicmem CLI skeleton** | `not_started` | — | — | — |
| 5 | 1 | **Unit tests for vault + index + retrieval** | `not_started` | — | — | — |
| 6 | 1 | **Phase 1 gate: lint on 100-note test vault = 0 errors** | `not_started` | — | — | — |
| 7 | 2 | **ingest subcommand (URL → lit + permanents)** | `not_started` | — | — | — |
| 8 | 2 | **ingest-pile subcommand (batch + cross-ref)** | `not_started` | — | — | — |
| 9 | 2 | **note subcommand (stdin → permanent note)** | `not_started` | — | — | — |
| 10 | 2 | **research subcommand (3-round web research → inbox)** | `not_started` | — | — | — |
| 11 | 2 | **remember / forget subcommands (vault + Mnemosyne)** | `not_started` | — | — | — |
| 12 | 2 | **lint subcommand (orphans, dead links, stale, contradictions)** | `not_started` | — | — | — |
| 13 | 2 | **moc subcommand (rebuild domain Index.md + backlinks)** | `not_started` | — | — | — |
| 14 | 2 | **hotcache subcommand (refresh Wiki-Cache.md)** | `not_started` | — | — | — |
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
| P0 | 0 | **PROJECT_PLAN.md** | 2026-07-16 | Full 10-section technical spec (1,566 lines). Covers all architecture, memory model, phases, risks, ship definition. |
| P1 | 0 | **README.md** | 2026-07-16 | /learn install command, architecture diagram, quickstart, comparison table. |
| P2 | 0 | **SETUP.md** | 2026-07-16 | Agent-facing bootstrap checklist: vault resolution, env vars, init, smoke test, write guards, optional deps, cron recipe, click-to-open. |
| P3 | 0 | **RISKS.md** | 2026-07-16 | 12-item risk register with owners, severity, mitigation, decision log. |
| P4 | 0 | **RELEASE-CHECKLIST.md** | 2026-07-16 | Ship-ready definition: repo, skill, CLI, modules, graph, tests, /learn acceptance, coexistence, docs, phase gates. |
| P5 | 0 | **skills/entropicmem/SKILL.md** | 2026-07-16 | Agent instructions: triggers, division of labor, 7 workflows, tool framing, pitfalls. |
| P6 | 0 | **skills/entropicmem/SETUP.md** | 2026-07-16 | Mirror of root SETUP.md for /learn consumption. |
| P7 | 0 | **skills/entropicmem/templates/vault/** | 2026-07-16 | Seed skeleton: AGENTS, SCHEMA, index, log.md + 9 domain folders + inbox/.raw/Mnemosyne/templates. |
| P8 | 0 | **skills/entropicmem/references/*.md** | 2026-07-16 | 5 stub docs (MEMORY_MODEL, VAULT_SCHEMA, HERMES_INTEGRATION, CLI_REFERENCE, VISUALIZER). |
| P9 | 0 | **docs/*.md** | 2026-07-16 | 7 stub docs (ARCHITECTURE, MEMORY_MODEL, CLI_REFERENCE, VISUALIZER, SELF_INSTALL, COMPARISON, COMPARISON_TABLE). |
| P10 | 0 | **LICENSE (MIT)** | 2026-07-16 | Standard MIT license. |
| P11 | 0 | **.gitignore** | 2026-07-16 | Excludes DBs, exports, env, build artifacts, IDE files. |
| P12 | 0 | **.github/workflows/test.yml** | 2026-07-16 | CI stub: lint + pytest on push/PR. |
| P13 | 0 | **Git init + local commits** | 2026-07-16 | Two commits on branch main. |
| P14 | 0 | **MASTER_TODO.md** | 2026-07-16 | This file. Tracks all tasks, phases, handoff context. |

---

## HANDOFF NOTES FOR NEXT AGENT

### Where we are
Phase 0 (Planning) is **complete**. All research, documentation, risk analysis, and project structure is in place. The repo lives at `/home/ufonik/Documents/Coding Projects/EntropicMem/` with 2 git commits on branch `main`.

### What needs to happen next
**Phase 1 — Vault + Index + Retrieval Core.** See `PROJECT_PLAN.md` §7.1 for full spec. The next agent should:

1. Read `PROJECT_PLAN.md` thoroughly (especially §3-7).
2. Read `SETUP.md` for the bootstrap flow.
3. Read `skills/entropicmem/SKILL.md` for agent constraints.
4. Start with Task #1 in the ACTIVE table above: `vault.py` (see §4.1 in the plan).
5. Use Python 3.10+ stdlib only.
6. Write tests alongside implementation (TDD).
7. Test against a temporary vault, NOT the live `~/Documents/Obsidian Vault`.

### Key constraints
- **Stdlib-first.** `string.Template` for templates, not jinja2. Only `sentence-transformers` and `graphviz` are optional extras.
- **Path layout.** All scripts go in `skills/entropicmem/scripts/`. After `/learn` install, they resolve to `~/.hermes/skills/entropicmem/scripts/`.
- **Safe mode.** Never write `Mnemosyne/`, `.obsidian/`, `_archive/`. Guarded in `vault.py`.
- **Tests.** Run with `python3 -m pytest tests/ -q`. Use temp dirs, never the live vault.
- **Git.** Commit after each completed task with descriptive messages. Use `--author="Ufonik <Ufonik88@users.noreply.github.com>"`.
- **Update this file.** After each completed task, move it to the COMPLETED section.

### Project structure (post-/learn)
```
~/.hermes/skills/entropicmem/
├── SKILL.md
├── SETUP.md
├── references/
├── templates/vault/
└── scripts/
    ├── entropicmem.py          # CLI entry point
    ├── vault.py                # Core vault operations
    ├── index.py                # SQLite FTS5 index
    ├── retrieval.py            # Composed search stack
    ├── graph_export.py         # Visual graph export
    ├── mnemosyne_bridge.py     # Mnemosyne ↔ Vault bridge
    └── templates.py            # Note template rendering
```

### Expected v1.0 directory after full implementation
```
~/Documents/Coding Projects/EntropicMem/
├── .github/workflows/test.yml
├── .gitignore
├── LICENSE
├── MASTER_TODO.md
├── PROJECT_PLAN.md
├── README.md
├── RELEASE-CHECKLIST.md
├── RISKS.md
├── SETUP.md
├── skills/
│   └── entropicmem/
│       ├── SKILL.md
│       ├── SETUP.md
│       ├── references/
│       │   ├── CLI_REFERENCE.md
│       │   ├── HERMES_INTEGRATION.md
│       │   ├── MEMORY_MODEL.md
│       │   ├── VAULT_SCHEMA.md
│       │   └── VISUALIZER.md
│       ├── scripts/
│       │   ├── entropicmem.py
│       │   ├── graph_export.py
│       │   ├── index.py
│       │   ├── mnemosyne_bridge.py
│       │   ├── retrieval.py
│       │   ├── templates.py
│       │   └── vault.py
│       └── templates/
│           └── vault/
│               └── ... (seed skeleton)
├── tests/
│   ├── test_vault.py
│   ├── test_index.py
│   ├── test_retrieval.py
│   ├── test_graph.py
│   └── test_bridge.py
└── docs/
    ├── ARCHITECTURE.md
    ├── CLI_REFERENCE.md
    ├── COMPARISON.md
    ├── COMPARISON_TABLE.md
    ├── MEMORY_MODEL.md
    ├── SELF_INSTALL.md
    └── VISUALIZER.md
```
