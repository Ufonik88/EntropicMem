# EntropicMem Improvement Plan

> Reconstructed 2026-07-21 from architectural review + Sourcery PR #3 findings.
> M1 completed and merged as v1.4.0 (PR #3).

## Milestone Overview

| Milestone | Label | Version | Status |
|-----------|-------|---------|--------|
| M1 | Correctness (A1–A5 + E1) | v1.4.0 | ✅ Merged |
| M2 | Production Hardening | v1.5.0 | 🔨 In Progress |
| M3 | Intelligence & Resilience | v1.6.0 | ⏳ Pending |
| M4 | Release & CI Expansion | v2.0.0 | ⏳ Future |
| P2 | Vector Search (sentence-transformers) | — | Deferred (optional dep) |

---

## M2 — Production Hardening (v1.5.0)

Make EntropicMem robust under real production conditions: thread safety,
non-blocking extraction, correct return values, and code deduplication.

### H1: Make `_auto_extract` truly non-blocking
- **File:** `plugins/entropicmem/__init__.py` (line ~437-441)
- **Problem:** `t.join(timeout=5.0)` blocks `sync_turn` for up to 5s per turn.
  Sourcery flagged this as a performance issue.
- **Fix:** Remove `t.join()`. Daemon thread runs fire-and-forget. Add a
  `_extract_lock` to prevent concurrent extraction runs (skip if one is
  already running).

### H2: Fix `reinforce()` return value
- **File:** `skills/entropicmem/scripts/memory_engine.py` (line ~422-434)
- **Problem:** Same bug class as A5. Uses `SELECT changes()` after `commit()`,
  which may return 0 if another statement ran between UPDATE and SELECT.
- **Fix:** Fetch the row first (`SELECT id FROM facts WHERE id = ?`), then
  UPDATE, then return `row is not None`.

### H3: Thread safety for `_recently_injected`
- **File:** `plugins/entropicmem/__init__.py` (lines ~536-626)
- **Problem:** `_recently_injected` dict is read/written from `prefetch()`
  (main thread) and `_auto_extract` (background thread) without locking.
- **Fix:** Guard all `_recently_injected` access with `_prefetch_lock`.

### H4: `recall_with_relevance` multi-word FTS parity
- **File:** `skills/entropicmem/scripts/memory_engine.py` (line ~460-465)
- **Problem:** Multi-word queries only search `content:` field, while
  `recall()` searches `content:`, `title:`, and `tags:`. Sourcery flagged
  this parity gap.
- **Fix:** Extend multi-word branch to include `title:` and `tags:` fields,
  matching `recall()`.

### H5: Delegate `cmd_patch_core` to CoreMemory
- **File:** `skills/entropicmem/scripts/entropicmem.py`
- **Problem:** CLI `cmd_patch_core` reimplements Core/Persona/User_Profile
  creation and patching logic that already exists in `CoreMemory` (vault.py).
  Sourcery flagged the duplication/divergence risk.
- **Fix:** Replace inline logic with `CoreMemory(vault_path).patch(...)` call.

### H6: MemoryEngine context manager
- **File:** `skills/entropicmem/scripts/memory_engine.py`
- **Problem:** Every caller does `engine = MemoryEngine(db); ...; engine.close()`.
  Missing `close()` on exception leaks connections.
- **Fix:** Add `__enter__`/`__exit__` methods. Update plugin callers to use
  `with MemoryEngine(db) as engine:`.

---

## M3 — Intelligence & Resilience (v1.6.0)

Make EntropicMem smarter about what it stores and resilient against failure.

### I1: Fuzzy deduplication
- **File:** `skills/entropicmem/scripts/memory_engine.py`
- **Problem:** Dedup is exact-hash only. Near-identical facts ("User prefers
  concise replies" vs "User prefers concise responses") create duplicates.
- **Fix:** Add `_is_near_duplicate(content)` using token-overlap (Jaccard
  similarity ≥ 0.8 on word sets). Check before `remember()` insert. If
  near-dup found, update existing fact instead of inserting new one.

### I2: DB error recovery
- **File:** `skills/entropicmem/scripts/memory_engine.py`
- **Problem:** `sqlite3.OperationalError` (database locked, disk I/O error,
  corrupt FTS) crashes the caller with no recovery path.
- **Fix:** Wrap critical DB operations in retry logic (3 attempts, 100ms
  backoff). On FTS corruption, rebuild `facts_fts` from `facts` table
  automatically. Log warnings instead of crashing.

### I3: Memory consolidation
- **File:** `skills/entropicmem/scripts/memory_engine.py`
- **Problem:** Facts accumulate indefinitely. Old, low-access, low-importance
  facts dilute recall quality.
- **Fix:** Add `consolidate(max_age_days=90, min_access=1, min_importance=0.3)`
  method. Facts older than `max_age_days` with fewer than `min_access` accesses
  and importance below `min_importance` are archived (moved to `facts_archive`
  table) rather than deleted. Returns count of archived facts.

### I4: Auto-backup before destructive operations
- **File:** `skills/entropicmem/scripts/memory_engine.py`
- **Problem:** `forget()` and `consolidate()` are destructive with no safety net.
- **Fix:** Add `_backup_db()` that copies the DB file to `<db_path>.bak`
  (single rotating backup). Call before `forget()` and `consolidate()`.
  Skip if backup is < 5 minutes old (avoid I/O spam).

### I5: Fix reinforcement test to verify score
- **File:** `tests/test_phase8.py`
- **Problem:** `test_reinforce_boosts_score` only asserts `access_count`
  increases, not that the combined relevance score actually improves.
  Sourcery flagged this as a testing gap.
- **Fix:** Capture `relevance_score` before and after `reinforce()`, assert
  the score increases (or at minimum doesn't decrease).

---

## Constraints (apply to all milestones)

- **Stdlib-only** for core path. No new hard dependencies.
- **sentence-transformers** remains optional (P2 deferred).
- **Backward compatible** — existing DB schema, config keys, and tool schemas
  must not break.
- **Tests must pass** — 133+ tests green after each milestone.
- **No new HERMES_* env vars** — all config via config.yaml plugin keys.
