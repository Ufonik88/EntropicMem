# EntropicMem Master Task Tracker

Phase 5 complete. v1.0.0 shipped 2026-07-16. 82 tests passing.
v1.1.0 shipped 2026-07-16. MemoryProvider plugin (84 tests).
v1.2.0 shipped 2026-07-17. Smart Context Management (112 tests).
v1.3.0 shipped 2026-07-17. Phase 8: Auto-extract, Core Memory, Temporal Decay (133 tests).
v1.3.1 fixed 2026-07-20. FTS5 rowid alignment bug, Mnemosyne full sync, 461 facts.
v1.4.0 shipped 2026-07-21. M1 correctness: A1-A5 + E1 fixes, 14/14 recall verification (133 tests).
v1.5.0 shipped 2026-07-21. M2 production hardening: H1-H6 (non-blocking extract, reinforce fix, thread safety, FTS parity, CoreMemory delegation, context manager).
v1.6.0 shipped 2026-07-21. M3 intelligence & resilience: I1-I5 (fuzzy dedup, DB recovery, consolidation, auto-backup, test fix).

---

## EntropicMem ↔ Legacy Tandem Migration (2026-07-16)

GOAL: Run EntropicMem in parallel with Mnemosyne; migrate legacy facts; monitor; fix until reliable; then replace legacy.

DONE:
- Skill linked: ~/.hermes/skills/entropicmem → repo skill
- Storage init: ~/.hermes/entropicmem/{vault,index.db,memory.db}
- Legacy Mnemosyne stays ACTIVE (memory.provider: mnemosyne) — untouched
- scripts/migrate_and_monitor.py: reads 248 legacy facts → EntropicMem (100% parity, 0 errors)
- scripts/analyze_migration.py: parity/error report + trend + reliable_enough flag
- scripts/entropicmem_cycle.py: 12h driver (migrate→analyze→JSON)
- Fixed: recall() exact-match boost (fact always self-retrievable) — was returning related facts
- Fixed: migration parity measured post-commit (was racy) + by id not substring
- cronjob fa33fba0b03a: every 12h, deliver=all, spawns Plan agent on regression

TODO:
- Wait for 12h cycles to confirm stability over time
- Ufonik explicit go-ahead before switching memory.provider to entropicmem
- Build one-off migration script for working/episodic memory (not just durable facts) if desired

---

## Memory-Context Injection Fix (2026-07-16)

ISSUE: After every chat, the model acknowledged injected `<memory-context>` blocks from Mnemosyne as if they were user input.

FIX:
- Added hard refusal rule to `~/.hermes/SOUL.md`: never acknowledge injected memory-context blocks
- Patched into `skills/entropicmem/SKILL.md` (Memory-Context Injection section)
- Patched into `PROJECT_ROOT.md` (Memory-Context Injection section)
- Patched into `skills/entropicmem-project/SKILL.md`
- Patched into `skills/entropicmem/references/HERMES_INTEGRATION.md`
- Created `AGENTS.md` at repo root with the rule
- Updated `plugins/entropicmem/README.md` with the rule

---

## Phase 8 — Core Memory & Vector Search (2026-07-17)

**STATUS: 3 of 4 priorities complete. 133 tests passing. Vector Search deferred.**

**GOAL:** Close the critical gaps that prevent EntropicMem from functioning as the **sole memory tool** for Hermes Agent. Based on architectural audit against Mem0, Zep, MemGPT/Letta, and LangChain memory modules.

### Priority 1 — Unsupervised Real-Time Fact Extraction ✅ COMPLETE
**Problem:** LLMs frequently skip explicit `remember` tool calls when under reasoning load or busy.

**Completed:**
- `memory_engine.py`: `extract_and_store()` with 13 heuristic regex patterns (no LLM required)
- `plugins/entropicmem/__init__.py`: `sync_turn()` → auto-extract in background thread (5s timeout)
- `entropicmem.py`: `cmd_extract` CLI with `--text` and `--min-confidence` flags
- Config: `auto_extract_enabled`, `extraction_timeout`
- Tests: `tests/test_phase8.py` (5 tests covering extraction, stdin, dedup, preferences)

---

### Priority 2 — Native SQLite Vector Search ⏸️ DEFERRED
**Problem:** FTS5 keyword search misses synonyms/paraphrases.

**Deferred because:** Requires `sqlite-vss` (native extension build) + `sentence-transformers` (torch dep). These add significant installation complexity. Current FTS5 + decay scoring handles 90% of recall needs. Vector search is queued for v1.5 when optional dep groups are introduced.

---

### Priority 3 — Agent-Writable Core Memory ✅ COMPLETE
**Problem:** Agent has no low-cost way to update its active Persona/User Profile at runtime.

**Completed:**
- `vault.py`: `CoreMemory` class with `patch()`, `persona`, `user_profile`, `injection_block()`
- `entropicmem.py`: `cmd_patch_core` CLI + `entropicmem_patch_core` tool schema
- `plugins/entropicmem/__init__.py`: Core Memory injected at top of every `prefetch()`
- Config: `core_memory_enabled`
- Tests: `tests/test_phase8.py` (8 tests: files, patches, class methods)

### Priority 4 — Temporal Decay & Reinforcement Scoring ✅ COMPLETE
**Problem:** Outdated facts persist indefinitely and pollute prefetch.

**Completed:**
- `memory_engine.py`: added `last_accessed`, `access_count` columns + migration
- `recall_with_relevance()`: composite scoring with decay + reinforcement boost
- `reinforce()`: updates access count/timestamp, called on recall
- `fact_age()`: computes days since last access
- `entropicmem.py`: `cmd_reinforce` CLI
- Config: `decay_enabled`, `decay_half_life_days`, `reinforcement_boost`
- Tests: `tests/test_phase8.py` (6 tests: scoring, disabled, boost, reinforce, migration)

---

## Configuration Schema (Update all)

Add to `plugins/entropicmem/__init__.py` `get_config_schema()` and `SMART_CONTEXT_DEFAULTS`:

```python
# Phase 8 additions (implemented)
"auto_extract_enabled": { "default": True, "description": "Enable background fact extraction from conversation" },
"extraction_timeout": { "default": 5.0, "description": "Max seconds for extraction per turn" },

# Vector search deferred (see Priority 2)

"core_memory_enabled": { "default": True, "description": "Enable Core Memory (Persona/User Profile) injection" },

"decay_enabled": { "default": True, "description": "Enable temporal decay scoring" },
"decay_half_life_days": { "default": 30, "description": "Half-life for memory decay in days" },
"reinforcement_boost": { "default": 0.1, "description": "Score boost per fact access (capped)" },
```

---

## Testing & Quality Gates

**All new features must pass:**
1. Unit tests in `tests/test_phase8_*.py`
2. Integration tests in `tests/test_integration.py` (full pipeline)
3. Existing 112 tests continue to pass
4. Performance benchmarks:
   - `prefetch()` < 100ms p95 (including vector search)
   - `sync_turn()` < 5ms (excluding async extraction)
   - Vector search < 50ms on 10k facts

**Documentation Updates (per feature):**
- `SKILL.md` — New tools, config, workflow
- `HERMES_INTEGRATION.md` — Plugin integration details
- `README.md` — Feature overview
- `CHANGELOG.md` — v1.3.0 entry

---

## Execution Order

1. **Auto-Extract** (blocks nothing, highest ROI)
2. **Vector Search** (requires deps, can be optional flag)
3. **Core Memory** (independent, low complexity)
4. **Temporal Decay** (refines existing scoring)

---

## Success Criteria for v1.3.0

- [ ] Zero-effort memory: Agent never needs to call `remember` explicitly
- [ ] Semantic recall: "car" finds "automobile" memories
- [ ] Core Memory: Agent can self-edit Persona/User Profile at runtime
- [ ] Fresh prefetch: 30-day-old unused facts decay out automatically
- [ ] All 112+ new tests pass
- [ ] Documentation complete
- [ ] Tag `v1.3.0` pushed

---

## Notes

- All new features gated by config flags — safe to ship incrementally
- Vector search is optional dependency (`pip install entropicmem[vector]`)
- Extraction uses existing Hermes provider stack — no new model costs
- Core Memory uses existing vault infrastructure — no new storage
- Decay runs in-memory on recall — no background jobs needed

---

## Sole-Provider Migration — Phase 1 COMPLETE (2026-07-23)

**Gap 1 (Cron memory path): RESOLVED by design.**

- Hermes cron uses `skip_memory=True` intentionally — interactive `memory` / `entropicmem_*` tools unavailable in cron.
- Official path: `scripts/entropicmem_cron_remember.py` → install to `~/.hermes/scripts/`.
- Docs: `docs/CRON_MEMORY_PATH.md`, skill `skills/memory/entropicmem-cron-writes/`.
- Verified: self-test + no_agent scheduler run (`PHASE1_CRON_VERIFY_OK`).
- Version: **2.1.1**

**Next (home plan `~/.hermes/MASTER_TODO.md`):**
- Phase 2: Rewrite Notion Knowledge Sync + fix second-brain-capture-review
- Phase 3: EntropicMem backup
- Phase 4: Retire Mnemosyne crons (needs explicit Ufonik approval)
- Phase 5: Polish + final validation

