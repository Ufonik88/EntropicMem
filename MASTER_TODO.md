# EntropicMem — MASTER TODO

**Last updated:** 2026-08-08
**Active track:** Contextual parity — G1–G10 gap closure (v2.2.0)
**Plan doc:** `docs/SECURITY_HARDENING_PLAN.md`
**Release:** v2.2.0 (contextual parity); v2.1.9 (`.env` re-poisoning fix); v2.1.8 (index maintenance); v2.1.7 (docs/metadata); v2.1.6 (security hardening)

---

## Security Hardening (2026-07-28 audit) — COMPLETE

### Phase 1 — Immediate / Critical

- [x] **1.1** Graph server bind `127.0.0.1`; require token on `POST /refresh`
- [x] **1.2** Default HTML export omits `full_body` (opt-in `--include-bodies`)
- [x] **1.3** Harden FS modes: DBs/backups `600`, dirs `700`; engine secure create
- [x] **1.4** Encrypt backup archives (OpenSSL AES-256-CBC) before rclone
- [x] **1.5** `auto_extract_enabled` default **false**
- [x] **1.6** Gate `patch_core` via `core_memory_writable` (default false)
- [x] **1.7** Prefetch source denylist + strip instruction markers on `remember`
- [x] **1.8** Fix LIKE domain filter parentheses in `memory_engine.recall`
- [x] **1.9** Verify listeners/perms; run targeted tests; update health notes

### Phase 2 — Architectural

- [x] Sensitivity tiers + write policy (`policy.py`)
- [x] `audit_log` table + CLI `audit`
- [x] Privileged-tool confirm gates (consolidate/forget)
- [x] Pending-facts quarantine for auto-extract + CLI `pending`
- [x] Pin plugin vault/index/memory paths (no Obsidian fallback)
- [x] SSRF DNS resolve + private IP recheck
- [x] Reinforce decoupling (`auto_reinforce=False` default)
- [x] Encrypted backup standard + restore drill docs
- [x] Runtime encryption design spike (`docs/SQLCIPHER_SPIKE.md`)
- [x] Merge-safe `save_config`

### Phase 3 — Testing & validation

- [x] Security pytest pack (`test_phase1_security`, `test_security_phase2`)
- [x] Adversarial poisoned-fact / SSRF / secret-block tests
- [x] Health check: bind address, perms, backup ciphertext, audit_log
- [x] Backup restore game day documented
- [x] Full pytest suite green pre-release

### Progress log

| When | Change |
|------|--------|
| 2026-07-28 | Phase 1 implemented and verified |
| 2026-07-28 | Phase 2–3 implemented; version bumped to 2.1.6; docs + vault updated |
| 2026-07-28 | Tag+release v2.1.6 published at c145dc9; PR #37 open — main merge needs second approving review (branch protection) |
| 2026-07-30 | Docs refresh + repo maintenance → v2.1.7: version refs aligned, MASTER_TODO/README/CHANGELOG updated, test count corrected to 201 |
| 2026-08-04 | Index maintenance → v2.1.8: `index rebuild|status` + `memory reindex` CLI, silent 6h watchdog, FTS-orphan detection in health check, current-streak stability gate in both health check and gate script, graph server `/refresh` rebuilds index first + canonical repo copy, 214 tests passing. Live remediation complete: scripts deployed, DBs rebuilt (1001 notes, 0 FTS orphans), `.env` de-poisoned, watchdog cron live (PR #41 hard-pin fix), health back to overall OK |
| 2026-08-07 | `.env` re-poisoning fix → v2.1.9: `_append_env` guard only checked `ENTROPICMEM_VAULT_PATH`, so the next `init` after the v2.1.8 cleanup re-appended fresh `/tmp` entries (tmpzjok → tmpn2gh3ds5). Now block-level idempotent + refuses temp-dir paths. Live `.env` cleaned to one canonical block. Untracked generated `graph_export/`. 5 new tests (223 green). PR #47 merged; tag+release v2.1.9 |
| 2026-08-08 | Contextual parity → v2.2.0 (G1–G10): episodic store (376 legacy imported + 12h capture cron), knowledge triples (4,938 legacy + 2,053 fact-triples + rule-based extractor + split-brain edge sync), full embedding coverage (885/885, hybrid recall live, venv re-exec for cron/Notion writes), cron-helper vault dual-write, Obsidian export mirror + AGENTS.md fix, canonical domain cleanup (11 remapped), CLI on PATH, parity audit PASS (0 missing). Notion sync resumed. 19 new tests (271 green). G7 cron deletion pending explicit user approval |
| 2026-08-08 | v2.2.0 follow-up fix (PR #53): graph refresh cron now syncs triples AFTER the server refresh (rebuild() deletes graph_edges — previous order wiped synced edges, split-brain WARN); added `rebuild_episodes_fts()` for delete-orphan repair. Live: overall OK, edges 979=979 both DBs, 272 tests green |

---

## Index Maintenance (2026-08-04 review) — COMPLETE (v2.1.8)

Live review found a causal chain: `index.db` permanently stale (rebuild only
reachable via `init`) → health WARN every cycle → stability gate cron in
daily error state → gate stuck at 2/7. Plus a correctness bug (gate counted
the longest historical streak, not the current one), an orphan `facts_fts`
row, and stale `/tmp` env entries in `~/.hermes/.env` poisoning
`resolve_vault_path()`.

### Shipped

- [x] CLI `entropicmem index rebuild|status` — periodic vault index refresh
- [x] CLI `entropicmem memory reindex` + public `MemoryEngine.rebuild_fts()` (audit-trailed)
- [x] Health check: FTS orphan WARN + repair hint; `current_consecutive_ok` field
- [x] Gate semantics: current streak decides the gate (health check + gate script); log gaps break streaks
- [x] Graph server: `/refresh` rebuilds the index first; canonical copy at `scripts/graph_server/`
- [x] Silent watchdog `scripts/entropicmem_index_refresh.sh` (pins env paths; cron every 6h)
- [x] 13 new tests (`tests/test_v2_1_8.py`), 214 total green

### Live remediation (post-merge) — DONE (2026-08-04)

- [x] Deploy updated `entropicmem_health_check.py` + `daily_stability_gate.py` to `~/.hermes/scripts/` (byte-identical, verified by diff)
- [x] Graph server canonical copy synced + unit restarted; `/health` OK on loopback and Tailscale (`tailscale+local`)
- [x] Live `index rebuild`: 1001 notes, 0.0h age; vault `.md` count == `notes_meta` count
- [x] Live `memory reindex`: 844 → 843 FTS rows; orphan count now 0
- [x] Removed stale `ENTROPICMEM_VAULT_PATH`/`ENTROPICMEM_INDEX_DB` `/tmp` entries from `~/.hermes/.env` (backup: `.env.bak-20260804-v218`)
- [x] Watchdog cron `e9365690a702` installed (`0 */6 * * *`, no_agent, silent when fresh); first run failed on poisoned env still in gateway memory → hard-pinned paths in PR #41, re-run ok
- [x] Health check returns overall **OK**: memory_db/vault/index/fts/backup/security/audit all OK; stability gate correctly PENDING 0/7 (current-streak semantics restart the count; ~2026-08-11 to pass)

---

## `.env` Re-poisoning Fix (2026-08-07 verification) — COMPLETE (v2.1.9)

During v2.1.8 live verification the health check was green, but the audit of
`~/.hermes/.env` found the cutover-artifact problem had **returned**: the
v2.1.8 cleanup removed `ENTROPICMEM_VAULT_PATH` (the one key `_append_env`
guarded on), so the next `entropicmem init` run re-appended a fresh
`/tmp/tmpn2gh3ds5` block — a different dead temp dir than the original
`/tmp/tmpzjok_s0t`. The class of bug is a re-poisoning loop: single-key guard,
blind full-block re-append.

### Shipped (PR #47, tag v2.1.9)

- [x] `_append_env` rewritten: block-level idempotency (skip when ANY of the
  three `ENTROPICMEM_*` keys exists) + temp-dir refusal (never persist
  vault/index paths under `/tmp/`, `/var/tmp/`, `/private/tmp/`)
- [x] Live `~/.hermes/.env` cleaned to exactly one canonical block pointing at
  `~/.hermes/entropicmem/{vault,index.db,memory.db}` (backup:
  `.env.bak-<ts>-v219`; no duplicates, no `/tmp` references)
- [x] Untracked generated `graph_export/` (daily cron artifact → permanently
  dirty tree); added to `.gitignore`
- [x] 5 regression tests (`tests/test_v2_1_9.py`), 223 total green
- [x] Version 2.1.8 → 2.1.9 (pyproject, CLI `__version__`, SKILL.md, plugin.yaml)

### Verification (2026-08-07)

- [x] Full pytest suite: **223 passed**
- [x] Health check: overall **OK** (index 0.0h behind, FTS 875=875, backups 7/7 encrypted)
- [x] Stability gate: **PENDING 3/7 current consecutive OK days** — correct
  current-streak semantics; ~2026-08-11 to pass (no action needed)
- [x] Runtime symlinks pick up v2.1.9 automatically (plugin.yaml, SKILL.md, CLI)
- [x] Watchdog cron `e9365690a702` active; graph server unit active

---

## Contextual Parity (2026-08-08 gap closure) — COMPLETE (v2.2.0)

Closed the six gaps from the EntropicMem vs Mnemosyne gap analysis
(`docs/ENTROPICMEM_GAP_ANALYSIS.md`-style audit of 2026-08-08) to reach
**contextual parity**, not just operational parity. Verified against live
stores: 885 facts, 1,003+ vault notes, full embedding coverage, episodic
timeline, relational triple store.

### G1 — Episodic memory (CRITICAL)
- [x] `episodes` table + `episodes_fts` in the engine (title, summary,
  start_ts/end_ts, source_session, linked_fact_ids, importance, domain)
- [x] Engine API: `add_episode`, `list_episodes`, `recall_episodes`, `episode_stats`
- [x] CLI: `episode add|list|stats`; `recall --type episodic --since --until`
- [x] Backfill: **376/376** legacy Mnemosyne episodic entries (mne_ ids)
- [x] 12h capture cron `b2618ec5b973` (`entropicmem_episodic_capture.py`,
  reads live `state.db`, distills interactive sessions, skips cron noise)

### G2 — Knowledge triples (CRITICAL)
- [x] `triples` table (UNIQUE subject/predicate/object, validity, confidence, source)
- [x] Engine: `upsert_triple`, `list_triples`, `triple_neighbors`, `triple_path`,
  `triple_inconsistencies`, `triple_stats`
- [x] CLI: `triple extract|list|stats|neighbors|path|inconsistencies`
- [x] Rule-based extractor `triple_extract.py` (entity dict + relation patterns)
- [x] Split-brain fixed: `triples_sync.py` mirrors triples → `graph_edges` in
  BOTH memory.db and index.db (health check verifies parity)
- [x] Backfill: **4,938 distinct** legacy triples + **2,053** legacy
  triple-shaped facts (the analysis's "12,579" was the raw row count —
  316k rows deduplicate to 4,938 distinct)
- [x] Graph refresh cron runs extract + sync before server refresh

### G3 — Embedding coverage (HIGH)
- [x] Backfill: **885/885 facts embedded, 0 errors** (Hermes venv python)
- [x] Write-path: `remember()` embeds on insert; cron helper + Notion sync
  re-exec via venv when embedder missing
- [x] Hybrid retrieval: plugin `_recall` + CLI `recall` use `recall_hybrid`
- [x] Health check `embeddings` (coverage + orphan rows)

### G4 — Cron memory path (MEDIUM, by design)
- [x] `entropicmem_cron_remember.py --write-vault` (vault dual-write from cron)

### G5 — Notion sync (MEDIUM)
- [x] Test ingestion verified (11 facts → recall, security OK)
- [x] Cron `dff8a6a72447` **resumed** (every 120m)

### G6 — Obsidian second-brain (MEDIUM)
- [x] `entropicmem_obsidian_export.sh`: engine vault → `Obsidian Vault/EntropicMem/`
  (6h cron `1ce003b785d8`), 1,004 notes mirrored
- [x] Obsidian `AGENTS.md` rewritten (0 Mnemosyne refs)
- [x] Stale `Mnemosyne/` export folder retired to `_archive/`

### G7 — Legacy cron cleanup (LOW) — **PENDING USER APPROVAL**
- [ ] 6 paused Mnemosyne crons + `mnemosyne` plugin entry retained (deliberate:
  destructive op requires explicit approval; jobs are disabled so no runtime risk)

### G8 — Domains (LOW)
- [x] Canonical list defined; `domain_cleanup.py` (dry-run default);
  **11 stray facts remapped** (Test→Knowledge, Wedding→Projects,
  Preference/Preferences→People, Operations/Security→Infrastructure)

### G9 — CLI packaging (LOW)
- [x] `~/.local/bin/entropicmem` symlink; verified in fresh shell

### G10 — Parity audit (VERIFICATION)
- [x] `entropicmem_parity_audit.py` — **PASS**: 0/2,053 facts, 0/376 episodes,
  0/4,938 triples, 0/885 embeddings missing
- [ ] Mnemosyne data dir preserved (94 MB) — deletion awaits explicit approval

### Release state
- [x] 271 tests green (19 new in `tests/test_v2_2_0.py`)
- [x] Version 2.1.9 → 2.2.0; docs + skill updated
- [x] PR #51 (visual graph UX) merged into this release line

---

## Prior status (pre-security-track)

# EntropicMem — Phase 6 Complete, Sole-Provider Ready

**Last updated:** 2026-07-24
**Active model:** deepseek-v4-pro via opencode-go

---

## Executive Summary

EntropicMem has achieved **85-90% parity** with the previous Mnemosyne-based memory stack. All 8 critical operational gaps (Gaps 1–8 from the original gap analysis, plus Phase 6 hardening) have been addressed. Remaining gaps are specialized features that EntropicMem omits by design or defers to future sprints. **No blocking regressions remain that prevent sole-provider operation.**

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
- [x] 1. Add `entropicmem_stats` tool schema to plugin `__init__.py` *(PR #24)*
- [x] 2. Wire `handle_tool_call("entropicmem_stats", ...)` to call `MemoryEngine.stats()` *(PR #24)*
- [x] 3. Return JSON: `{fact_count, domains, db_path}` *(PR #24)*

**Acceptance Criteria:**
- Agent can call `entropicmem_stats` and receive fact counts by domain
- Tool appears in `get_tool_schemas()` output

---

### H2: No Direct Fact Retrieval by ID
**Impact:** Medium

**Description:** Mnemosyne had `mnemosyne_get` for single-fact retrieval by ID. EntropicMem's `recall` is always search-based — no way to pull a specific fact by its entropic_id without guessing search terms.

**Action Plan:**
- [x] 1. Add `entropicmem_get` tool schema with `id` parameter *(PR #24)*
- [x] 2. Wire to `MemoryEngine.get_fact(entropic_id)` (already exists) *(PR #24)*
- [x] 3. Return fact fields as JSON *(PR #24)*

**Acceptance Criteria:**
- `entropicmem_get(id="6baa2fd933b528ab")` returns the specific fact
- Returns error if ID not found

---

### H3: No Batch Write Operations
**Impact:** Low

**Description:** Mnemosyne's `memory` tool supported an `operations` array for atomic multi-write batches. EntropicMem's `entropicmem_remember` only writes one fact per call.

---

## Current State Summary

```
EntropicMem: ACTIVE PROVIDER  (full parity)
Mnemosyne:   PAUSED           (~90MB data, 6 crons paused)
Gap status:  8/8 resolved     (operational gaps)
Tool parity: 10/14 matched    (4 specialized tools omitted by design)
Phase 6:     Complete          (6.10 pending 1-week gate)
Phases 7-11: Complete          (all Memvid-inspired features)
Tests:       223 passing
```

## Priority Roadmap for Full Parity

| Priority | Item | Effort | Status |
|----------|------|--------|--------|
| P1 | H1: Stats tool | ~30 min | Done (PR #24) |
| P2 | H2: Get-by-ID tool | ~20 min | Done (PR #24) |
| P3 | H3: Batch writes | ~1 hr | Done (cron `--json` already existed) |
| — | L1-3: Specialized tools | N/A | Omitted by design |

**All parity gaps resolved.** All critical operational gaps (1-8), production hardening (Phase 6), Memvid phases (7-11), and roadmap items (H1-H3) are complete.

## Verification Checklist

- [x] All 8 original operational gaps resolved
- [x] Phase 6 production hardening complete (6.1-6.9)
- [x] 223 tests passing (v2.1.9 pack: +5 `_append_env` regression; v2.1.8: +13 index-maintenance)
- [x] Health check with stability gate functional
- [x] Backup + restore tested end-to-end
- [x] Rollback idempotent + validated
- [x] DB concurrency guard implemented
- [x] Gateway context verified (Telegram working)
- [x] Phases 7-11 implemented (semantic, temporal, PII, graph, security, capsule, versioning)
- [ ] 1-week stability gate PASS — **in progress: 3/7 consecutive OK days as of 2026-08-07** (gate log: OK 08-05, 08-06, 08-07 after the v2.1.8 index fix); expected pass ~2026-08-11 if health stays OK; current-streak semantics (v2.1.8) mean the count restarts on any WARN/FAIL
- [ ] 6.10 Sole provider promotion — **blocked on the gate above**; EntropicMem is already the live sole provider (memory.provider: entropicmem), this checkbox closes out the formal Phase-6 gate record once 7 consecutive OK days accumulate

---

## Visual Vault Graph — Comprehensive UI/UX & GUI Overhaul (v2.2.0 — Phase 1 COMPLETE)

**Track owner:** GUI/Visual layer (`skills/entropicmem/scripts/graph_export.py` + embedded HTML/SVG single-page app)  
**Dependencies:** graph server v2.1.9 runtime, index rebuild contract (`index.db`), exported `graph.json` schema  
**Goal:** Transform the EntropicMem visual vault graph from a basic functional SVG layout into an Obsidian-grade, polished, professional knowledge canvas featuring stable physical simulation, wispy dynamic node styling, buttery-smooth zooming, and rich contextual markdown inspection.

**Phase 1 Status (2026-08-07):** Phases B, C, D, E, F, G4 implemented and verified. 247 tests green (+24 new in `tests/test_graph_ux.py`). Live graph server serving updated HTML at `http://127.0.0.1:8075/`. All 14 feature checks pass on the live page.

---

### Executive UX Critique & Gap Analysis vs Obsidian Canvas / Graph

| Aspect | Current EntropicMem Graph (`graph.html`) | Target Standard (Obsidian / Professional Canvas) |
|---|---|---|
| **Visual Styling** | Basic dark circles/shapes, flat hex colors, heavy hardcoded rgba borders | Unified design tokens, glassmorphism panels, glowing halos, layered gradients, depth cues |
| **Node Representation** | Static shapes (circle, square, diamond, triangle) with static radius | Motion-aware icons, velocity halos, domain-coded type glyphs, pulsing activity indicators |
| **Physics & Stability** | High jitter, perpetual movement, bounce on filter, loose collision | Damped velocity decay, auto-cooldown alpha settle, freeze non-focused subgraphs during hover/focus |
| **Zoom & Scale** | Basic D3 zoom [0.1, 5], jumpy scaling of labels at extreme zooms | Inertial wheel zoom, semantic zoom LOD (level-of-detail label culling), synchronized minimap viewport |
| **Node Inspection** | Simple modal with basic markdown render, static text | Obsidian-grade markdown renderer, live wikilink auto-resolution, tag chips, backlink panel, copy tools |
| **Performance** | O(N) re-render on filter, DOM recreation overhead | Spatial indexing, requestAnimationFrame throttling, view culling for 500+ nodes |

---

### Phase A — Baseline Audit & Simulation Telemetry (1 task)

- [ ] **A1 — Simulation Jitter & Frame-Rate Profiling**
  - **Action:** Instrument `graph_export.py` template with a lightweight performance HUD (frame delta, active alpha, simulated node movement delta per frame).
  - **Metrics:** Measure average node drift per second at rest, time to alpha-decay stabilization, and DOM reflow cost during hover/focus transitions.
  - **Acceptance:** Quantitative baseline established; target <0.5px/sec average node drift at rest after 3s cooldown.

---

### Phase B — Design System & Visual Polish (4 tasks) — COMPLETE

- [x] **B1 — CSS Design Token Architecture**
  - **Action:** Consolidate all colors, fonts, shadows, and spacing in `_HTML_TEMPLATE` into CSS custom properties (`:root`).
  - **Acceptance:** Zero ad-hoc hex codes in SVG elements or JS styles; easy theme tuning via CSS variables.

- [x] **B2 — Glassmorphism UI Chrome**
  - **Action:** Rework panel, legend, minimap, stats, and focus banner with frosted glass styling (`backdrop-filter: blur(12px)`), refined border radios, and micro-borders (`1px solid var(--border-subtle)`).
  - **Acceptance:** Clean visual hierarchy at 100%, 125%, and 150% browser zoom; no text clipping.

- [x] **B3 — Typography & Scale Hierarchy**
  - **Action:** Standardize font weights and sizes using `Space Grotesk` for headers/labels and system sans-serif for UI body text.
  - **Acceptance:** Consistent readability across dense and sparse domain views.

- [x] **B4 — Unified Accent Palette & Glow System**
  - **Action:** Centralize the Ajax brand palette (`#1DCF8E`, `#5AE4AA`, `#FFB800`, etc.) with matching subtle drop-shadows and SVG glow filters (`<filter id="glow">`).
  - **Acceptance:** Active/hover nodes emit a clean, non-distracting halo matching their domain color.

---

### Phase C — Wispy, Motion-Like, Dynamic Node Icons (4 tasks) — COMPLETE

- [x] **C1 — Layered SVG Icon Definitions**
  - **Action:** Replace flat shapes with multi-layer SVG group definitions (`<defs>`) combining a core node geometry, an inner translucent gradient fill, and a delicate outer halo ring.
  - **Acceptance:** Visual distinction between permanent notes (pulsing circle), literature notes (rounded card), MOCs (diamond cluster), and indexes/logs (triangle beacon).

- [x] **C2 — Velocity-Responsive Halo Rings**
  - **Action:** Bind node SVG halo opacity and scale dynamically to simulation velocity (`d.vx`, `d.vy`) during movement, fading out to a stable soft ring at rest.
  - **Acceptance:** Moving nodes show a subtle trailing "wisp" effect; resting nodes remain crisp and motionless.

- [x] **C3 — Interactive State Transitions**
  - **Action:** Add CSS transitions for hover enlargement, focus ring illumination, and dimming of unrelated subgraphs.
  - **Acceptance:** Smooth 150ms ease-out transitions on pointer enter/leave.

- [x] **C4 — Offline Fallback Iconography**
  - **Action:** Ensure pure SVG rendering without dependency on external icon fonts or sprite sheets.
  - **Acceptance:** Works instantly over `file://` or isolated local network.

---

### Phase D — Physics Stability: Eliminating Jitter (5 tasks) — COMPLETE

- [x] **D1 — Force Simulation Parameter Tuning**
  - **Action:** Calibrate D3 force parameters: increase velocity damping (`alphaDecay: 0.035`), refine many-body strength (`strength: -180`), tune collision radius with padding (`radius: nodeRadius + 12`), and set optimal link distance (`distance: 110`).
  - **Acceptance:** Simulation settles naturally within 2.5 seconds without perpetual oscillation.

- [x] **D2 — Intelligent Alpha Settle Strategy**
  - **Action:** Implement automatic cooling: pause simulation ticks (`simulation.stop()`) once `simulation.alpha() < 0.005`, re-enabling only on drag, zoom, or filter changes.
  - **Acceptance:** Zero CPU burn from background physics ticks when the user is not interacting.

- [x] **D3 — Edge Anti-Wobble Interpolation**
  - **Action:** Clean up link coordinate bindings to update directly via integer-rounded or cleanly interpolated tick coordinates, eliminating sub-pixel line shimmer.
  - **Acceptance:** Zero perceived edge crawl or line jitter at rest.

- [x] **D4 — Subgraph Isolation on Focus**
  - **Action:** When a node is focused, pin or damp non-adjacent nodes so they do not exert repulsive forces that jitter the active cluster.
  - **Acceptance:** Clicking a node locks the surrounding neighborhood instantly without shifting distant nodes.

- [x] **D5 — State-Preserving Re-filtering**
  - **Action:** In `render()`, reuse existing simulation node objects and coordinates (`d.x`, `d.y`) when applying domain/tag filters, avoiding full re-randomization.
  - **Acceptance:** Toggling a filter does not scatter the graph layout; visible nodes stay anchored.

---

### Phase E — Smooth Zoom, Semantic Scaling, and Viewport Behavior (4 tasks) — COMPLETE

- [x] **E1 — Inertial Zoom & Extent Tuning**
  - **Action:** Configure D3 zoom behavior with optimized scale extent `[0.05, 8.0]`, wheel damping, and keyboard zoom multipliers (`+` / `-` keys).
  - **Acceptance:** Zoom feels buttery smooth on trackpads and mouse wheels.

- [x] **E2 — Semantic Level-of-Detail (LOD) Culling**
  - **Action:** Implement scale-aware label rendering: hide note labels when zoom scale drops below `0.35` (showing only nodes/halos), show full titles at normal scale, and display badges/tags at high zoom (`> 2.5`).
  - **Acceptance:** Dense 500-node graphs never suffer from overlapping unreadable text when zoomed out.

- [x] **E3 — Bi-directional Minimap Sync**
  - **Action:** Ensure the minimap viewport rectangle accurately mirrors pan/zoom transformations in real-time, supporting click-to-teleport and drag-to-pan.
  - **Acceptance:** Minimap acts as a robust navigation overview at any zoom level.

- [x] **E4 — Responsive Viewport Resize Handling**
  - **Action:** Handle window resize events by recalculating center forces and canvas bounds smoothly without resetting zoom or throwing simulation positions.
  - **Acceptance:** Resizing browser window preserves current zoom level and center point.

---

### Phase F — Rich Node Interaction & Obsidian-Grade Markdown Modal (4 tasks) — F1, F2, F4 COMPLETE

- [x] **F1 — Robust Hit-Testing & Multi-Modal Triggers**
  - **Action:** Expand invisible pointer-event radius around nodes (`circle` / `path` hit-areas) to ensure effortless clicking even for small nodes.
  - **Acceptance:** Zero missed clicks; instant modal opening on first click.

- [x] **F2 — Obsidian-Grade Markdown Modal Renderer**
  - **Action:** Enhance `modal-body` rendering via `marked.js` with custom syntax extensions: callout boxes, syntax-highlighted code blocks with one-click copy buttons, styled tables, and metadata frontmatter badges.
  - **Acceptance:** Notes render with identical fidelity to Obsidian preview mode.

- [ ] **F3 — Interactive Wikilink & Tag Resolution**
  - **Action:** Make `[[Target]]` wikilinks clickable inside the modal, instantly jumping the graph and opening the target note. Unresolved wikilinks render with a distinct red badge and tooltip.
  - **Acceptance:** Clicking any wikilink traverses the knowledge graph seamlessly.

- [x] **F4 — Deep-Link & Clipboard Sharing**
  - **Action:** Update URL hash (`#note=Title`) dynamically when opening notes in the modal; support "Copy Link" button that copies the shareable graph URL.
  - **Acceptance:** Pasting a graph URL with `#note=...` automatically opens the correct note modal on load.

---

### Phase G — Performance Budget, Accessibility, and Offline Resilience (4 tasks) — G4 COMPLETE

- [ ] **G1 — Performance Budget Verification**
  - **Action:** Audit memory and CPU footprint for 500-node exports; ensure DOM element count remains lean and garbage collection is unhindered.
  - **Acceptance:** Maintains steady 60 FPS during pan/zoom operations on standard hardware.

- [ ] **G2 — WCAG Accessibility & Keyboard Navigation**
  - **Action:** Ensure full keyboard traversal (`Tab` to navigate nodes, `Enter`/`Space` to open modal, arrow keys to pan, `Esc` to close modal), with correct ARIA attributes and focus trapping.
  - **Acceptance:** Fully operable without a mouse or trackpad.

- [ ] **G3 — Offline Resilience (Vendored Assets)**
  - **Action:** Check for local vendored copies of D3 and marked next to `graph.html`, falling back gracefully to CDN if offline and vendored assets are absent.
  - **Acceptance:** Works seamlessly in air-gapped environments when assets are vendored.

- [x] **G4 — Automated Regression & Schema Tests**
  - **Action:** Add pytest coverage (`tests/test_graph_ux.py`) validating graph export payload structure, HTML template validity, and script syntax (`node --check`).
  - **Acceptance:** CI test suite catches any malformed HTML or broken D3 wiring instantly. 24 new tests across 7 test classes covering physics, SVG glow, LOD, zoom, minimap, modal, design tokens, JS syntax, and schema stability.

---

### Phase H — Rollout, Live Verification, and Documentation (3 tasks)

- [ ] **H1 — Staged Rollout via Feature Flags**
  - **Action:** Introduce optional query parameters (`?v2=1`) for testing new visual layers before full promotion.
  - **Acceptance:** Zero risk of breaking existing shared exports during iterative styling.

- [ ] **H2 — Multi-Environment Live Verification**
  - **Action:** Test graph export and graph server `/refresh` across local browser, Hermes Desktop GUI, and Tailscale remote access (`100.67.179.69:8075`).
  - **Acceptance:** Verified working across all target endpoints.

- [ ] **H3 — Documentation & User Guide Update**
  - **Action:** Update `README.md`, `docs/VISUALIZER.md`, and `docs/CLI_REFERENCE.md` with details on the new visual features, shortcut keys, and LOD behaviors.
  - **Acceptance:** Documentation accurately reflects the overhauled GUI capabilities.

---

### Deliverables Summary
1. **Overhauled `graph_export.py`** containing the next-generation self-contained `_HTML_TEMPLATE` (glassmorphic UI, wispy SVG halos, physics auto-settle, LOD scaling, Obsidian markdown modal).
2. **Automated test suite extensions** (`tests/test_graph_ux.py`) ensuring zero regression in graph generation or syntax. 24 new tests, 247 total green.
3. **Verified deployment** on the active EntropicMem graph server instance (`entropicmem-graph-server.service`) serving at `http://127.0.0.1:8075/`.

### Implementation Summary (2026-08-07)

| Phase | Tasks Done | What Changed |
|-------|-----------|--------------|
| **B** Design Tokens | 4/4 | CSS `:root` custom properties (`--blur`, `--radius`, `--transition`, `--accent-glow`, `--text-bright`, `--border-subtle`), glassmorphic backdrop blur on all panels, radial gradient body bg, hover glow on nodes |
| **C** Dynamic Icons | 4/4 | SVG `<defs>` with `feGaussianBlur` glow filters (`node-glow`, `node-glow-strong`), radial `halo-grad` gradient, per-node `.node-halo` circle bound to velocity via `updateNodeHalos()`, glow filter applied to core shapes |
| **D** Physics Stability | 5/5 | `alphaDecay(0.035)`, `alphaMin(0.005)`, charge `-180`, collision `+12`, link distance `110`, drag `alphaTarget(0.15)`, `Math.round()` on tick coords, `simulation.on("end")` auto-stop |
| **E** Zoom & Viewport | 4/4 | `scaleExtent([0.05, 8])`, wheel damping (`wheelDelta`), keyboard zoom (`+`/`-`), LOD label culling (`updateLOD()`: hide <0.35x, fade <0.6x, badges >2.5x), minimap click-to-pan, resize no longer re-renders |
| **F** Modal Polish | 3/4 | Code block copy buttons (hover-reveal), frontmatter badges, wikilink navigation (existing), deep-link `#note=` (existing). F3 (wikilink auto-jump from graph) deferred. |
| **G4** Tests | 1/4 | 24 new tests in `tests/test_graph_ux.py`: physics params, SVG defs, LOD, zoom, minimap, modal, design tokens, JS syntax (`node --check`), schema stability |

**Remaining for Phase 2:** A1 (baseline metrics), F3 (wikilink auto-jump), G1 (perf budget), G2 (a11y audit), G3 (vendored assets), H1-H3 (rollout/docs).
