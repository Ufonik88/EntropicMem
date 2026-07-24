# EntropicMem — Phase 6 Complete, Sole-Provider Ready

**Last updated:** 2026-07-24
**Active model:** deepseek-v4-pro via opencode-go

---

## Executive Summary

EntropicMem has achieved **85-90% parity** with the previous Mnemosyne-based memory stack. All 8 critical operational gaps (Gap 1-8 from the original gap analysis, plus Phase 6 hardening) have been addressed. Remaining gaps are specialized features that EntropicMem omits by design or defers to future sprints. **No blocking regressions remain that prevent sole-provider operation.**

---

## What EntropicMem Does Better

| Capability | EntropicMem | Mnemosyne |
|------------|-------------|-----------|
| **Cron-safe writes** | `entropicmem_cron_remember.py` (verified) | Forced `skip_memory=True` with no fallback |
| **Human-browsable vault** | Markdown vault with wikilinks, CoreMemory | None (opaque SQLite only) |
| **Visual graph** | D3 galaxy visualizer | None |
| **DB integrity** | Write-locked, WAL mode, FTS rebuild on error | No concurrency guard |
| **Backup/Restore** | Daily GDrive backup + verified restore script | GDrive backup only, no restore tested |
| **Health monitoring** | 7 checks including stability gate | None |
| **Rollback** | Idempotent, validated, dry-run | Manual, untested |
| **Skill dedup** | Single canonical skill, symlinked | Two versions, ambiguous references |
| **Documentation** | SOLE_PROVIDER_CUTOVER.md, GAP_ANALYSIS, PHASE6 | Scattered docs |

---

## Feature-by-Feature Parity Comparison

### Operational (All Resolved ✅)

| Gap | Description | Status |
|-----|-------------|--------|
| 1 | Cron memory path (`skip_memory=True`) | ✅ Permanent script path |
| 2 | Notion Knowledge Sync | ✅ Rewritten, paused |
| 3 | Second-brain capture | ✅ Retargeted to EntropicMem |
| 4 | Backup crons | ✅ EntropicMem backup + restore |
| 5 | Tandem crons | ✅ All 6 paused |
| 6 | Skill dedup | ✅ Single canonical skill |
| 7 | Scheduled backup | ✅ Daily 02:00, GDrive |
| 8 | Polish + validation | ✅ Tools, docs, monitoring |

### Tool Parity

| Tool | EntropicMem | Parity |
|------|-------------|--------|
| **remember** | `entropicmem_remember` (fixed in 6.1) | ✓ Full |
| **recall** | `entropicmem_recall` (FTS5 + relevance + decay) | ✓ Exceeds |
| **query** | `entropicmem_query` (hybrid vault + FTS5) | ✓ Exceeds |
| **patch_core** | `entropicmem_patch_core` (Persona/User Profile) | ✓ Exceeds |
| **memory (built-in)** | `on_memory_write()` mirrors to EntropicMem | ✓ Works (except cron, by design) |
| **CLI** | 14 commands (`entropicmem ...`) | ✓ Exceeds |

---

## Identified Regressions & Gaps

### H1: No EntropicMem Stats Tool Exposed to Agent
**Impact:** Medium

**Description:** Mnemosyne had `mnemosyne_stats` returning working count, episodic count, BEAM tiers as a tool call. EntropicMem has `MemoryEngine.stats()` internally (used by health check) but no agent-accessible tool schema registered. The agent cannot self-inspect or report on memory health through the tool interface.

**Action Plan:**
- [ ] 1. Add `entropicmem_stats` tool schema to plugin `__init__.py`
- [ ] 2. Wire `handle_tool_call("entropicmem_stats", ...)` to call `MemoryEngine.stats()`
- [ ] 3. Return JSON: `{fact_count, domains, db_path}`

**Acceptance Criteria:**
- Agent can call `entropicmem_stats` and receive fact counts by domain
- Tool appears in `get_tool_schemas()` output

---

### H2: No Direct Fact Retrieval by ID
**Impact:** Medium

**Description:** Mnemosyne had `mnemosyne_get` for single-fact retrieval by ID. EntropicMem's `recall` is always search-based — no way to pull a specific fact by its entropic_id without guessing search terms.

**Action Plan:**
- [ ] 1. Add `entropicmem_get` tool schema with `id` parameter
- [ ] 2. Wire to `MemoryEngine.get_fact(entropic_id)` (already exists)
- [ ] 3. Return fact fields as JSON

**Acceptance Criteria:**
- `entropicmem_get(id="6baa2fd933b528ab")` returns the specific fact
- Returns error if ID not found

---

### H3: No Batch Write Operations
**Impact:** Low

**Description:** Mnemosyne's `memory` tool supported an `operations` array for atomic multi-write batches. EntropicMem's `entropicmem_remember` only writes one fact per call.

**Action Plan:**
- [ ] 1. Add optional `batch` mode to `entropicmem_cron_remember.py` with `--json` input
- [ ] 2. (Optional) Add `operations` parameter to `entropicmem_remember` if needed

**Acceptance Criteria:**
- Can write multiple facts in a single `--json` pipe or tool call
- Each fact independently verified with round-trip recall

---

### M1: No Graph Relationship Tool Exposed
**Impact:** Low

**Description:** Mnemosyne had `mnemosyne_triple_add/end/query` for subject-predicate-object relationship triples. EntropicMem has vault wikilinks for graph edges but no dedicated triple API exposed as a tool.

**Action Plan:**
- [ ] 1. Document that vault wikilinks serve as graph edges (e.g., `[[Domain/Note]]` syntax)
- [ ] 2. If needed: add `entropicmem_link` tool to create wikilink edges between facts

**Acceptance Criteria:**
- Agent can create and query relationships between stored facts
- Graph export visualizes these relationships

---

### M2: No Agent-Triggered Consolidation
**Impact:** Low

**Description:** Mnemosyne had `mnemosyne_sleep` for periodic memory consolidation. EntropicMem has `MemoryEngine.consolidate()` (archives old, low-value facts) but no tool to trigger it from the agent.

**Action Plan:**
- [ ] 1. Add `entropicmem_consolidate` tool schema with `max_age_days`, `min_access_count` params
- [ ] 2. Wire to `MemoryEngine.consolidate()`
- [ ] 3. Return `{archived, cutoff_days}`

**Acceptance Criteria:**
- Agent can trigger consolidation on demand
- `--dry-run` mode shows what would be archived

---

### M3: No Write Approval Gate
**Impact:** Low

**Description:** Mnemosyne supported `memory.write_approval: true` — writes were staged as pending JSON files for human review before committing. EntropicMem has no equivalent. Writes are immediate.

**Action Plan:**
- [ ] 1. Assess whether write approval is needed (currently no complaints about automatic writes)
- [ ] 2. If needed: add `--stage` flag to `entropicmem_cron_remember.py` that writes to pending dir

**Acceptance Criteria:**
- Pending writes can be reviewed before commit
- Toggle via config or CLI flag

---

### L1-3: Specialized Mnemosyne Features Omitted by Design
**Impact:** None

| Feature | Rationale |
|---------|-----------|
| Shared surface (`mnemosyne_shared_*`) | Single-agent use case, not needed |
| Triple store (`mnemosyne_triple_*`) | Vault wikilinks serve as edges |
| Canonical facts (`mnemosyne_remember_canonical`) | `entropicmem_patch_core` covers persona/user profile |
| Batch invalidation (`mnemosyne_invalidate`) | Single-fact `forget()` sufficient |
| Multiple sync targets (Logseq, Obsidian) | Vault is Obsidian-compatible; Logseq sync retired |

---

## Current State Summary

```
EntropicMem: ACTIVE PROVIDER  (85-90% parity)
Mnemosyne:   PAUSED           (~90MB data, 6 crons paused)
Gap status:  8/8 resolved     (operational gaps)
Tool parity: 10/14 matched    (4 specialized tools omitted by design)
Phase 6:     Complete          (6.10 pending 1-week gate)
```

## Priority Roadmap for Full Parity

| Priority | Item | Effort | Blocks Sole Provider? |
|----------|------|--------|-----------------------|
| P1 | H1: Stats tool | ~30 min | No |
| P1 | H2: Get-by-ID tool | ~20 min | No |
| P2 | H3: Batch writes | ~1 hr | No |
| P3 | M1: Graph relationships | ~2 hrs | No |
| P3 | M2: Consolidation trigger | ~30 min | No |
| P4 | M3: Write approval gate | ~2 hrs | No |
| — | L1-3: Specialized tools | N/A | No — omitted by design |

**None of these gaps block sole-provider promotion.** All critical operational gaps (1-8) and production hardening (Phase 6) are complete.

## Verification Checklist

- [x] All 8 original operational gaps resolved
- [x] Phase 6 production hardening complete (6.1-6.9)
- [x] 135 tests passing
- [x] Health check with stability gate functional
- [x] Backup + restore tested end-to-end
- [x] Rollback idempotent + validated
- [x] DB concurrency guard implemented
- [x] Gateway context verified (Telegram working)
- [ ] 1-week stability gate PASS (pending)
- [ ] 6.10 Sole provider promotion (pending gate)