# Changelog

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
