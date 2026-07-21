# Changelog

## [1.6.0] - 2026-07-21

### Added (M3: Intelligence & Resilience)
- **I1**: Fuzzy deduplication — Jaccard similarity >= 0.8 catches near-duplicate facts
- **I2**: DB error recovery — automatic FTS5 index rebuild on corruption
- **I3**: Memory consolidation — archive old, low-access facts to `facts_archive` table
- **I4**: Auto-backup — timestamped SQLite backups before destructive operations (forget, consolidate)

### Fixed
- **I5**: Reinforcement test now verifies `relevance_score` increases, not just `access_count`

## [1.5.0] - 2026-07-21

### Added (M2: Production Hardening)
- **H6**: `MemoryEngine` context manager (`__enter__`/`__exit__`) — all plugin callers updated

### Fixed
- **H1**: `_auto_extract` is now truly non-blocking — removed `t.join()`, added `_extract_lock`
- **H2**: `reinforce()` returns `True`/`False` based on fact existence (same class as A5)
- **H3**: `_recently_injected` guarded with `_prefetch_lock` for thread safety
- **H4**: `recall_with_relevance` multi-word FTS now searches title/tags fields (parity with `recall()`)
- **H5**: `cmd_patch_core` delegates to `CoreMemory` class — single source of truth

## [1.4.0] - 2026-07-21

### Fixed (M1 Correctness Phase)
- **A1:** `recall()` multi-word FTS query now splits into per-word OR terms instead of a single quoted phrase — matches `recall_with_relevance()` strategy, resolving 4/14 verification misses
- **A2:** `CoreMemory.injection_block()` frontmatter stripping now actually updates `persona`/`profile` variables (was a no-op loop reassignment)
- **A3:** `extract_and_store()` uses `re.finditer` + `group(0)` instead of `re.findall` — avoids garbage facts from multi-group tuple reconstruction
- **A4:** `_conversation_changed()` now hashes recent conversation and compares to previous hash — was returning `True` for any non-empty history, invalidating cache every turn
- **A5:** `forget()` returns `row is not None` instead of checking `SELECT changes()` after FTS delete — was returning `False` when FTS row was already missing

### Changed
- **E1:** `entropicmem_recall` tool now uses `recall_with_relevance()` with decay/reinforcement config instead of basic `recall()` — active tool recall now matches prefetch quality
- `entropicmem_recall` results include `relevance_score` field
- Version 1.4.0

### Verified
- 133 tests passing
- 14/14 verification queries return results (up from 10/14)

## [1.2.0] - 2026-07-17

### Added
- **Smart Context Management** for intelligent memory prefetch
- Relevance scoring with FTS5 bm25() ranking (0-1 normalized)
- Token budget enforcement (default: 1500 chars/turn)
- Turn-level deduplication (configurable window)
- Domain-aware filtering (optional domain list)
- Progressive disclosure (high → medium → low relevance tiers)
- Conversation context awareness (uses recent messages)
- Smart cache with conversation-aware invalidation
- 28 new unit tests for smart context features

### Changed
- `recall_with_relevance()` method added to MemoryEngine
- Plugin prefetch now uses intelligent filtering pipeline
- Configuration schema expanded with 11 new settings
- Version 1.2.0

### Performance
- Estimated 60-80% reduction in context injection token usage
- Only relevant, non-repeated facts injected per turn

## [1.1.0] - 2026-07-16

### Added
- Hermes MemoryProvider plugin (`plugins/entropicmem/`)
- Tools: `entropicmem_remember`, `entropicmem_recall`, `entropicmem_query`
- Memory write mirroring from built-in `memory` tool
- Phase 6 optional integration

### Changed
- Version 1.1.0

## [1.0.0] - 2026-07-16

### Added
- Standalone MemoryEngine (`memory.db`)
- CLI: `recall`, `memory list`
- Full reference and product documentation
- Phase 5 ship gate: standalone product framing

### Changed
- `remember`/`forget` dual memory engine + vault
- Seed vault AGENTS/SCHEMA (EntropicMem-only)
- Version 1.0.0

### Includes from prior releases
- Vault engine, ingest loop, graph visualizer, 80+ tests
