# Changelog

## [2.1.5] - 2026-07-23

### Added (Phase 5 — Polish + Final Validation)
- **docs/SOLE_PROVIDER_CUTOVER.md** — comprehensive cutover record (config, crons, data paths, rollback, deletion gate)
- **README.md** — sole-provider status section
- **Gap 8 RESOLVED** — all 8 gaps in gap analysis marked RESOLVED

### Documentation
- All gaps resolved: Gaps 1-8 complete
- Vault dual-write decision: NO (documented in SOLE_PROVIDER_CUTOVER.md)
- Final E2E validation: all write paths, CLI tools, 135 tests passed

## [2.1.4] - 2026-07-23

### Added (Phase 4 — Cleanup)
- **scripts/entropicmem_health_check.py** — pure EntropicMem health check
  - DB integrity, fact count, vault note count, index freshness, FTS health, backup recency
  - JSON output for cron consumption
- **Gap 5 RESOLVED** — all 6 Mnemosyne/tandem crons paused (not deleted — pending 1-week stability)
- **Gap 6 RESOLVED** — v1.3.1 skill copy deleted, only v2.1.0 remains

### Changed
- 12h monitoring cron (`fa33fba0b03a`) redesigned as "EntropicMem 12h Health Check"
- All Mnemosyne/tandem crons paused: `bf428b0b2e05`, `bacf5cca7c61`, `7cbacc0d9038`, `b20d38ad8edb`, `11b5bbe1fc68`, `f893e7549326`

## [2.1.3] - 2026-07-23

### Added (Phase 3 — Safety Nets)
- **scripts/entropicmem_backup.sh** — daily EntropicMem backup to Google Drive via rclone
  - Tar+gzip: memory.db, index.db, vault/
  - /tmp staging to avoid rclone .db bug
  - 7-day local retention, HERMES_HOME-aware
- **Gap 7 RESOLVED** — EntropicMem scheduled backup (`4ec76cbf8193`, daily 02:00)
- **Gap 4 RESOLVED** — Mnemosyne backup crons paused (`11b5bbe1fc68`, `f893e7549326`)

### Changed
- Weekly Full Backup (`8883bbe4bab3`) now includes EntropicMem backup step

## [2.1.2] - 2026-07-23

### Added (Phase 2 — Data Flow)
- **scripts/notion_entropicmem_sync.py** — consolidated Notion → EntropicMem cron script
  - `--mode fetch`: direct Notion API fetch + ingest
  - `--mode json`: read existing sync JSON
  - `--self-test`, `--dry-run` supported
  - Blocklist + sensitive-keyword guards preserved
- **Gap 2 RESOLVED** — Notion Knowledge Sync (`dff8a6a72447`) retargeted to EntropicMem
- **Gap 3 RESOLVED** — second-brain-capture-review (`9483533865f1`) uses `entropicmem_cron_remember.py`

### Changed
- `docs/ENTROPICMEM_GAP_ANALYSIS.md` — Gaps 2/3 marked RESOLVED
- `README.md` — added Notion→EntropicMem script note

## [2.1.1] - 2026-07-23

### Added (Phase 1 — Cron Memory Path)
- **docs/CRON_MEMORY_PATH.md** — root-cause analysis of Hermes cron `skip_memory=True` and the official durable-write path
- **scripts/entropicmem_cron_remember.py** — cron-safe helper (write + verified recall); no LLM required
- **skills/memory/entropicmem-cron-writes/** — skill for agent-driven crons that must persist facts
- **docs/ENTROPICMEM_GAP_ANALYSIS.md** — Gap 1 marked RESOLVED (by design)

### Fixed / Documented
- Cron interactive `memory` / `entropicmem_*` tools unavailable is **Hermes intentional design**, not an EntropicMem provider bug
- Downstream crons must use the helper (or MemoryEngine API), never interactive memory tools

## [2.1.0] - 2026-07-21

### Fixed (Graph Visualizer — P0)
- **GV-1**: Fixed two top-level JS `SyntaxError`s (duplicate `let currentNodeData`, duplicate `const body` in `openModal`) that blanked the entire visualizer — the `<script>` block never parsed.
- **GV-2**: Fixed `export_html` node-body lookup — guarded on `node["id"]` (was `node_id`, which never matched), so every modal now shows real note content instead of "No content available".
- **GV-3**: Removed an unreachable second `return html` in `export_html`.
- **GV-4**: `export_html` now accepts `vault_root` and the CLI passes it, so full note bodies embed reliably (env-resolution fallback retained).

### Added (Graph Visualizer — P1/P2/P3)
- **GV-5**: Real per-type node shapes (circle/square/diamond/triangle) rendered from `TYPE_SHAPES` — previously all nodes drew as circles despite the legend.
- **GV-6**: Focus mode — clicking a node dims non-neighbors to ~12% opacity; click empty canvas to release. Banner shows the focused note.
- **GV-7**: Title search with zoom-to-node (`Enter` jumps + focuses the best match).
- **GV-8**: Edge encoding — solid lines for wikilinks, dashed for tag co-occurrence; stroke width scales with edge weight; hover tooltip on nodes.
- **GV-9**: Wikilink navigation — `[[Target]]` in the modal body becomes a clickable link that opens the target note; unresolved links flagged `.broken`.
- **GV-10**: Tag chips in the modal frontmatter filter the graph on click.
- **GV-11**: Minimap with live viewport rectangle; PNG export button; "Copy link" (deep-link `#note=Title`).
- **GV-12**: Accessibility — nodes are focusable (`tabindex`, `role=button`), Enter/Space opens, modal is `role=dialog`/`aria-modal` with focus return on close, Escape closes.
- **GV-13**: Performance — node positions persist across filter re-renders (no full re-scatter); single group transform for zoom.
- **GV-14**: Typography — Space Grotesk display font for headings/panel; improved modal markdown styling (tables, code, blockquotes).

### Changed
- **GV-15**: `test_export_html` no longer asserts `"galaxy" not in html` — that was a change-detector that broke once real note bodies (which may contain the word) are embedded.

## [2.0.0] - 2026-07-21

### Added (M4: Release & CI Expansion)
- **M4.1**: `pyproject.toml` — project metadata, optional deps (`semantic`, `graph`, `dev`), pytest/ruff config
- **M4.2**: CI expanded — multi-Python matrix (3.10, 3.11, 3.12) + ruff lint job
- **M4.3**: README updated with v1.5.0/v1.6.0 feature sections
- **M4.4**: `docs/IMPROVEMENT_PLAN.md` — all milestones (M1-M4) marked complete

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
