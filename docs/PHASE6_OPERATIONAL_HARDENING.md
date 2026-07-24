# Phase 6 — Operational Hardening Documentation

## 6.7 Gateway/Telegram Context Memory Behavior

### Verified Behavior
- EntropicMem plugin registers 4 tools: `entropicmem_remember`, `entropicmem_recall`, `entropicmem_query`, `entropicmem_patch_core`
- Plugin tools are available in interactive sessions (main chat, desktop app)
- **Cron/subagent contexts**: `entropicmem_cron_remember.py` script must be used (Hermes core design: `skip_memory=True` in cron)

### Gateway Context Testing
Gateway contexts (Telegram, Discord) use the same Hermes Agent runtime as interactive sessions. Memory tools should work identically because:
1. Plugin registration happens at startup via `plugins/entropicmem/__init__.py`
2. `handle_tool_call()` dispatch is context-agnostic
3. No special gateway-specific code path exists

**Recommendation**: Run a manual test via Telegram gateway to confirm:
1. Send message via Telegram: "Store this test: gateway context memory test"
2. Verify fact appears in `entropicmem_remember` tool output
3. Verify recall works from Telegram context

### Status: **PENDING** — Manual verification required via Telegram gateway

---

## 6.8 Retention/GC Policy

### Current State
- No TTL or importance decay for stored facts
- Facts persist indefinitely in `memory.db`
- Vault notes persist indefinitely in `vault/`

### Proposed Policy

| Criterion | Action | Priority |
|-----------|--------|----------|
| Facts older than 90 days with access_count=0 | Archive to `facts_archive` table | P1 |
| Facts older than 180 days regardless of access | Move to `_archive/` vault folder | P2 |
| Facts with importance < 0.3 | Demote to `_archive/` | P2 |
| Vault notes without linked facts | Flag for review | P3 |

### Implementation Path
1. `entropicmem consolidate` command exists in `memory_engine.py`
2. Add CLI wrapper: `entropicmem gc --dry-run` (preview), `entropicmem gc` (execute)
3. Schedule via cron: weekly `entropicmem gc` job

### Status: **DESIGNED** — Implementation deferred to future sprint

---

## 6.9 Vector/Semantic Search Readiness Evaluation

### Current Search Capabilities
- **FTS5**: Fast full-text search via `recall()` and `recall_with_relevance()`
- **Hybrid**: Vault wikilinks + FTS5 via `retrieval.py`
- **BM25 Ranking**: Built into FTS5

### Vector Search Tradeoffs

| Aspect | Current (FTS5) | Vector Search |
|--------|----------------|---------------|
| **Latency** | ~1ms | ~10-50ms (embedding) |
| **Accuracy** | Keyword-based | Semantic similarity |
| **Storage** | ~1MB per 1000 facts | ~5-20MB per 1000 facts |
| **Dependencies** | None (stdlib) | sentence-transformers (~500MB) |
| **Setup** | Zero | Requires model download |

### Recommendation
Vector search is **not required** for current EntropicMem use cases:
1. User has < 1000 facts (keyword search sufficient)
2. FTS5 with porter stemming handles most queries
3. Zero-dependency is a feature for reliability

**Status**: Vector search deferred. Re-evaluate when fact count exceeds 5000 or semantic queries become frequent.

---

## 6.10 Sole Provider Promotion

### Gate Requirements (must ALL pass)
1. ✅ `entropicmem_remember` tool works in interactive context (6.1 fixed)
2. ✅ Documentation reconciled (6.2)
3. ⬜ 1-week stability gate: 7 consecutive OK health checks (6.3)
4. ✅ DB concurrency guard implemented (6.4)
5. ✅ Rollback script idempotent (6.5)
6. ✅ Backup restore tested (6.6)
7. ⬜ Manual gateway verification (6.7)
8. ✅ Retention/GC policy designed (6.8)
9. ✅ Vector search evaluated (6.9)

### Post-Gate Actions
1. Delete 6 paused Mnemosyne/tandem crons
2. Move `~/.hermes/mnemosyne/` to `~/.hermes/mnemosyne.archive/`
3. Remove old rollback script (keep new `entropicmem_rollback.sh`)
4. Update `SOLE_PROVIDER_CUTOVER.md` → mark FINAL

**Status**: **PENDING** — Awaiting 1-week stability gate + gateway verification

---

## Summary

| Sub-phase | Status | Action Required |
|-----------|--------|-----------------|
| 6.1 | ✅ Complete | None |
| 6.2 | ✅ Complete | None |
| 6.3 | ✅ Complete | Start 7-day tracking |
| 6.4 | ✅ Complete | None |
| 6.5 | ✅ Complete | None |
| 6.6 | ✅ Complete | None |
| 6.7 | ⬜ Pending | Manual Telegram test |
| 6.8 | ✅ Designed | Defer implementation |
| 6.9 | ✅ Evaluated | Defer vector search |
| 6.10 | ⬜ Pending | Awaiting 6.7 + 1-week gate |
