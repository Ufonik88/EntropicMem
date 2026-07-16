# EntropicMem — Master Task Tracker

> **Rule:** Active tasks stay at the top. Completed tasks move to the bottom.
> **Source of truth for product direction:** `PROJECT_PLAN.md` (standalone replan, 2026-07-16).

---

## ACTIVE TASKS

| # | Phase | Task | Status | Notes for next agent |
|---|-------|------|--------|----------------------|
| 5.1 | 5 | **Product language freeze** | `in_progress` | PROJECT_PLAN rewritten for standalone. Finish README/SKILL/SETUP/RISKS/RELEASE alignment. |
| 5.2 | 5 | **CLI/template wording cleanup** | `not_started` | Remove remaining legacy help text (remember/forget still may say external names). |
| 5.3 | 5 | **Add `recall` + `memory list` CLI** | `not_started` | MemoryEngine already has `recall`/`list_facts`; expose via CLI for standalone completeness. |
| 5.4 | 5 | **Fill references/*.md (5 docs)** | `not_started` | MEMORY_MODEL, VAULT_SCHEMA, CLI_REFERENCE, VISUALIZER, HERMES_INTEGRATION — standalone only. |
| 5.5 | 5 | **Fill docs/* (7 docs)** | `not_started` | ARCHITECTURE, MEMORY_MODEL, CLI_REFERENCE, VISUALIZER, SELF_INSTALL, COMPARISON, COMPARISON_TABLE. |
| 5.6 | 5 | **SKILL.md operating contract** | `not_started` | Write/read policy, session pattern, promotion rules from chat → remember. |
| 5.7 | 5 | **/learn dry-run + SELF_INSTALL** | `not_started` | Prove bootstrap on clean profile. |
| 5.8 | 5 | **v1.0.0 release gate** | `not_started` | RELEASE-CHECKLIST green + tag + changelog. |

---

## COMPLETED TASKS

| # | Phase | Task | Completed | Notes |
|---|-------|------|-----------|-------|
| P0 | 0 | Planning skeleton + public repo | 2026-07-16 | GitHub: Ufonik88/EntropicMem |
| 1–6 | 1 | Core vault engine | 2026-07-16 | vault, index, retrieval, init/lint/hotcache/query/note |
| 7–17 | 2 | Knowledge loop | 2026-07-16 | ingest, pile, moc, research, open, etc. |
| 18–21 | 3 | Graph visualizer | 2026-07-16 | graph_export + D3 galaxy HTML + serve |
| 22–24 | 4 | Standalone MemoryEngine | 2026-07-16 | memory_engine.py, remember/forget dual-write, memory project/stats |
| R1 | — | Standalone refactor (code) | 2026-07-16 | Removed external bridge module; own SQLite memory store |
| R2 | — | **PROJECT_PLAN standalone replan** | 2026-07-16 | Companion framing abandoned; full product definition for replacement-class tool |

---

## HANDOFF — WHERE TO CONTINUE

### Product goal (locked)
EntropicMem is a **complete standalone memory tool** for Hermes Agent: store facts, build a linked Markdown vault, retrieve with citations, maintain hygiene, visualize knowledge. No runtime dependence on external memory applications.

### Current code state
- Scripts: `vault.py`, `index.py`, `retrieval.py`, `memory_engine.py`, `graph_export.py`, `entropicmem.py`
- Tests: **80 passing** (`pytest tests/ -q`)
- Commands: init, ingest, ingest-pile, query, note, research, lint, moc, hotcache, graph, remember, forget, memory, open

### Next implementation priority
1. Clean CLI help/docstrings still carrying legacy wording
2. Add `entropicmem recall` (and optional `memory list`)
3. Write full reference docs under `skills/entropicmem/references/`
4. Skill operating contract
5. `/learn` dry-run → tag v1.0.0

### Do not do
- Reintroduce bridges to external memory products as core architecture
- Present EntropicMem as a companion/sidecar to another system
- Start Phase 6 MemoryProvider until Phase 5 ship gate is green
