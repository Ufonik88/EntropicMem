# EntropicMem — Master Task Tracker

> **Rule:** Completed tasks move to the bottom section. Active and not-started tasks stay at the top.

---

## ACTIVE TASKS

| # | Phase | Task | Status |
|---|-------|------|--------|
| 22 | 4 | **mnemosyne_bridge.py** | `not_started` |
| 23 | 4 | **bridge export/import subcommands** | `not_started` |
| 24 | 4 | **Phase 4 gate: round-trip remember** | `not_started` |
| 25 | 5 | **references/*.md — 5 full docs** | `not_started` |
| 26 | 5 | **docs/*.md — 7 full docs** | `not_started` |
| 27 | 5 | **SKILL.md final review** | `not_started` |
| 28 | 5 | **/learn dry-run** | `not_started` |
| 29 | 5 | **Phase 5 gate** | `not_started` |
| 30 | 5 | **GitHub release v1.0.0** | `not_started` |

---

## COMPLETED TASKS

| # | Phase | Task | Completed | Notes |
|---|-------|------|-----------|-------|
| P0-P8 | 0 | **Planning + Repo** | 2026-07-16 | PROJECT_PLAN, README, SETUP, RISKS, RELEASE-CHECKLIST, SKILL, templates, LICENSE, CI, GitHub push. |
| 1-6 | 1 | **Core Vault Engine** | 2026-07-16 | vault.py, index.py, retrieval.py, CLI skeleton, 30 tests, Phase 1 gate. |
| 7-17 | 2 | **Knowledge Loop** | 2026-07-16 | ingest, ingest-pile, moc, research, remember, forget, open, note, lint, hotcache, check-deps, 50 tests, Phase 2 gate. |
| 18-21 | 3 | **Graph Visualizer** | 2026-07-16 | graph_export.py (JSON/DOT/HTML/Canvas), D3 galaxy graph.html, graph serve, 14 tests, Phase 3 gate. 64 total tests passing. |

---

## HANDOFF NOTES FOR NEXT AGENT (Phase 4)

### Where we are
Phases 0-3 complete. **64 tests passing.** All 13 subcommands + graph export/serve are functional.

### Phase 4 — Mnemosyne Bridge
See `PROJECT_PLAN.md` §7.4.

1. **`mnemosyne_bridge.py`** (#22):
   - `export_to_vault()`: Read Mnemosyne working_memory + memories (scope=global), write as permanent notes in `Mnemosyne/` folder with `entropic_id`.
   - `remember()`: Write to vault + Mnemosyne with same `entropic_id`.
   - Uses public `Mnemosyne` class API from `mnemosyne.core.memory`.

2. **`bridge export`/`bridge import`** (#23): Wire to CLI.

3. **Phase 4 gate** (#24): Round-trip remember → vault note + Mnemosyne row with same entropic_id. Dedup works.

### Key constraints
- Bridge uses ONLY public Mnemosyne class API (no direct SQL).
- `remember` creates both vault note + Mnemosyne memory with same entropic_id.
- Cron recipe documented in SETUP.md, not auto-installed.

### Working commands (Phases 1-3)
```bash
entropicmem init --vault /tmp/test
entropicmem ingest test.md --domain Knowledge
entropicmem query "search" --top-k 10
entropicmem moc && entropicmem lint
entropicmem graph export --format html
entropicmem graph serve --port 8080
python3 -m pytest tests/ -q
```
