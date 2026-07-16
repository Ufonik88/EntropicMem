# EntropicMem — Master Task Tracker

> **Rule:** Completed tasks move to the bottom section. Active and not-started tasks stay at the top.

---

## ACTIVE TASKS

| # | Phase | Task | Status |
|---|-------|------|--------|
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
| 1-6 | 1 | **Core Vault Engine** | 2026-07-16 | vault.py, index.py, retrieval.py, CLI skeleton, 30 tests. |
| 7-17 | 2 | **Knowledge Loop** | 2026-07-16 | ingest, ingest-pile, moc, research, remember, forget, open, note, lint, hotcache, check-deps, 50 tests. |
| 18-21 | 3 | **Graph Visualizer** | 2026-07-16 | graph_export.py (JSON/DOT/HTML/Canvas), D3 galaxy graph.html, graph serve, 64 total tests. |
| 22-24 | 4 | **Mnemosyne Bridge** | 2026-07-16 | mnemosyne_bridge.py (export 162 memories, dual remember), bridge CLI, 76 tests passing. entropic_id round-trip verified. |

---

## HANDOFF NOTES FOR NEXT AGENT (Phase 5)

### Where we are
Phases 0-4 complete. **76 tests passing.** All 15 commands implemented:
```
init | ingest | ingest-pile | query | note | research | lint | moc | hotcache |
graph export | graph serve | remember (dual) | forget | open | bridge export
```

### Phase 5 — Packaging & Polish
1. **Fill reference docs** (#25): `skills/entropicmem/references/` — MEMORY_MODEL, VAULT_SCHEMA, HERMES_INTEGRATION, CLI_REFERENCE, VISUALIZER
2. **Fill docs** (#26): `docs/` — ARCHITECTURE, MEMORY_MODEL, CLI_REFERENCE, VISUALIZER, SELF_INSTALL, COMPARISON, COMPARISON_TABLE
3. **SKILL.md review** (#27): Ensure <100 lines, triggers correct, tool framing accurate
4. **/learn dry-run** (#28): Test on fresh Hermes profile
5. **Phase 5 gate** (#29): Clean /learn install, init works, graph renders
6. **v1.0 release** (#30): Tag v1.0.0, changelog, announce

### Key facts
- Mnemosyne DB: ~240 memories, bridge successfully exports 162
- remember() writes to BOTH vault + Mnemosyne with matching entropic_id
- Bridge uses `_allow_protected=True` to write Mnemosyne/ folder
