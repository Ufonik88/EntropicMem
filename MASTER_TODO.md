# EntropicMem — MASTER TODO

**Last updated:** 2026-07-28
**Active track:** Security Hardening COMPLETE (v2.1.6)
**Plan doc:** `docs/SECURITY_HARDENING_PLAN.md`
**Release:** v2.1.6

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

**Action Plan:**
- [x] 1. Add optional `batch` mode to `entropicmem_cron_remember.py` with `--json` input *(already existed)*
- [x] 2. (Optional) Add `operations` parameter to `entropicmem_remember` if needed *(not needed — cron `--json` covers batch use case)*

**Acceptance Criteria:**
- Can write multiple facts in a single `--json` pipe or tool call
- Each fact independently verified with round-trip recall

---

### M1: No Graph Relationship Tool Exposed
**Impact:** Low

**Description:** Mnemosyne had `mnemosyne_triple_add/end/query` for subject-predicate-object relationship triples. EntropicMem has vault wikilinks for graph edges but no dedicated triple API exposed as a tool.

**Action Plan:**
- [x] 1. Document that vault wikilinks serve as graph edges (e.g., `[[Domain/Note]]` syntax) *(Phase 10: graph_query.py)*
- [x] 2. If needed: add `entropicmem_link` tool to create wikilink edges between facts *(Phase 10: `graph show` CLI + `_expand_with_links`)*

**Acceptance Criteria:**
- Agent can create and query relationships between stored facts
- Graph export visualizes these relationships

---

### M2: No Agent-Triggered Consolidation
**Impact:** Low

**Description:** Mnemosyne had `mnemosyne_sleep` for periodic memory consolidation. EntropicMem has `MemoryEngine.consolidate()` (archives old, low-value facts) but no tool to trigger it from the agent.

**Action Plan:**
- [x] 1. Add `entropicmem_consolidate` tool schema with `max_age_days`, `min_access_count` params
- [x] 2. Wire to `MemoryEngine.consolidate()` with `dry_run` support
- [x] 3. Return `{archived, cutoff_days}` (or `{would_archive, cutoff_days, dry_run}` in dry-run mode)

**Acceptance Criteria:**
- Agent can trigger consolidation on demand
- `--dry-run` mode shows what would be archived

---

### M3: No Write Approval Gate
**Impact:** Low

**Description:** Mnemosyne supported `memory.write_approval: true` — writes were staged as pending JSON files for human review before committing. EntropicMem has no equivalent. Writes are immediate.

**Action Plan:**
- [x] 1. Assess whether write approval is needed (currently no complaints about automatic writes) — **Assessed: not needed.** Cron `--dry-run` already provides pre-write review. No user complaints about automatic writes. Adding a full staging/approval workflow would be over-engineering.
- [x] 2. If needed: add `--stage` flag to `entropicmem_cron_remember.py` that writes to pending dir — **Deferred: not needed per assessment above.**

**Acceptance Criteria:**
- Pending writes can be reviewed before commit *(covered by `--dry-run`)*
- Toggle via config or CLI flag *(not implemented — deemed unnecessary)*

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

## Memvid Integration Plan (Phases 7–11)

> **Full analysis:** `docs/MEMVID_ANALYSIS.md` — deep dive on Memvid architecture, MV2 format, feature flags, and per-feature gap rationale.

**Gap summary (Memvid vs EntropicMem):**
| Priority | Gap | Phase | Dependencies |
|----------|-----|-------|--------------|
| HIGH | Semantic/vector search (HNSW embeddings) | 7 | `semantic` extra |
| HIGH | Hybrid search (FTS5 + vector fusion) | 7 | `semantic` extra |
| MEDIUM | Temporal queries (NL date parsing) | 8 | None |
| MEDIUM | PII detection & redaction | 9 | None |
| MEDIUM | Graph/relational query over wikilinks | 10 | Phase 7 (optional) |
| LOW | Encryption at rest + capsule export + versioning | 11 | `security` extra |

### Phase 7: Semantic Search Foundation (HIGH) — `semantic` extra required

- [x] **7.1 — Embedding pipeline**
  - Add `embeddings.py`: generate 384-dim vectors on `remember()`, store in `embeddings` table
  - Graceful fallback: if no model, skip embedding (FTS5 still works)
  - **Acceptance:** `remember("test")` stores embedding; `recall("test")` uses vector similarity when available

- [x] **7.2 — Hybrid search in recall**
  - `recall_hybrid()`: FTS5 score + cosine similarity, weighted fusion (default 0.6 FTS + 0.4 vector)
  - **Acceptance:** Semantic recall returns relevant results without exact keyword match

- [x] **7.3 — Embedding maintenance**
  - CLI: `entropicmem embed --rebuild` regenerates all embeddings
  - Health check reports embedding coverage %
  - **Acceptance:** Full rebuild works; health check shows % coverage

### Phase 8: Temporal Intelligence (MEDIUM) — no deps

- [x] **8.1 — Temporal query parser**
  - Parse NL dates: "last Tuesday", "in March", "2 weeks ago" → SQL range filters
  - Integrate into `recall()` and `recall_with_relevance()`
  - **Acceptance:** `recall("meeting notes from last week")` filters by date

- [x] **8.2 — Time index**
  - `timeline()` method on (created_at, domain) for fast chronological scans
  - CLI: `entropicmem timeline --from 2026-01-01 --to 2026-07-01`
  - **Acceptance:** Timeline query returns facts in chronological order

### Phase 9: PII Detection (MEDIUM) — no deps

- [x] **9.1 — PII scanner**
  - Regex detection: emails, phones, ID numbers, API keys, passwords
  - Configurable mode: `warn` / `redact` / `block`
  - Integrated into `remember()`: auto-redacts PII before storage
  - **Acceptance:** `remember("password is hunter2")` triggers redaction per config

- [x] **9.2 — PII audit**
  - CLI: `entropicmem lint --pii` — scan all facts, report findings
  - **Acceptance:** PII scan reports facts with detected patterns

### Phase 10: Graph Query Layer (MEDIUM) — Phase 7 optional

- [x] **10.1 — Link graph**
  - `links` table from vault wikilink extraction (source_path, target_title, context)
  - CLI: `entropicmem graph show "Wedding"` — connected notes
  - **Acceptance:** Graph show displays all notes linking to/from target

- [x] **10.2 — Graph-aware recall**
  - `recall_hybrid("wedding venue", expand_links=True)` returns fact + linked notes
  - `_expand_with_links()` traverses link graph, appends connected facts at 0.5x score
  - **Acceptance:** Recall with link expansion returns related vault context

### Phase 11: Security & Portability (LOW) — `security` extra required

- [x] **11.1 — Encryption at rest**
  - `security.py`: Fernet + PBKDF2 (480K iterations), passphrase-based
  - CLI: `entropicmem security enable|disable|status`
  - Encrypts DB + WAL/SHM + vault .md files; marker + salt files
  - **Acceptance:** DB/vault unreadable without passphrase; wrong passphrase raises ValueError

- [x] **11.2 — Memory capsule export**
  - `entropicmem export capsule.tar.gz` — bundles DB + vault + manifest.json
  - `entropicmem import capsule.tar.gz` — restores with overwrite confirmation
  - **Acceptance:** Export/import round-trip preserves all data

- [x] **11.3 — Fact versioning (append-only mode)**
  - `fact_versions` table: snapshots on dedup update and fuzzy dedup
  - `snapshot_version()` + `get_versions()` engine methods
  - CLI: `entropicmem history <entropic_id>` — version timeline (newest first)
  - **Acceptance:** Updates create version snapshots; `history` shows all versions

---

## Current State Summary

```
EntropicMem: ACTIVE PROVIDER  (full parity)
Mnemosyne:   PAUSED           (~90MB data, 6 crons paused)
Gap status:  8/8 resolved     (operational gaps)
Tool parity: 10/14 matched    (4 specialized tools omitted by design)
Phase 6:     Complete          (6.10 pending 1-week gate)
Phases 7-11: Complete          (all Memvid-inspired features)
Tests:       185 passing
```

## Priority Roadmap for Full Parity

| Priority | Item | Effort | Status |
|----------|------|--------|--------|
| P1 | H1: Stats tool | ~30 min | Done (PR #24) |
| P1 | H2: Get-by-ID tool | ~20 min | Done (PR #24) |
| P2 | H3: Batch writes | ~1 hr | Done (cron `--json` already existed) |
| P3 | M1: Graph relationships | ~2 hrs | Done (Phase 10) |
| P3 | M2: Consolidation trigger | ~30 min | Done (this PR) |
| P4 | M3: Write approval gate | ~2 hrs | Assessed: not needed |
| — | L1-3: Specialized tools | N/A | Omitted by design |

**All parity gaps resolved.** All critical operational gaps (1-8), production hardening (Phase 6), Memvid phases (7-11), and roadmap items (H1-M3) are complete.

## Verification Checklist

- [x] All 8 original operational gaps resolved
- [x] Phase 6 production hardening complete (6.1-6.9)
- [x] 185 tests passing (135 original + 35 Memvid phases + 15 Phase 11)
- [x] Health check with stability gate functional
- [x] Backup + restore tested end-to-end
- [x] Rollback idempotent + validated
- [x] DB concurrency guard implemented
- [x] Gateway context verified (Telegram working)
- [x] Phases 7-11 implemented (semantic, temporal, PII, graph, security, capsule, versioning)
- [ ] 1-week stability gate PASS (pending)
- [ ] 6.10 Sole provider promotion (pending gate)
