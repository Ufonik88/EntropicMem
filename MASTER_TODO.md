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

## Memvid Feature Analysis & Integration Plan

**Analyzed:** 2026-07-26 | **Source:** https://github.com/memvid/memvid (16K+ stars, Rust core, Apache 2.0)

### What Memvid Is

Memvid is a single-file memory layer for AI agents. It packages data, embeddings, search indices, and metadata into one portable `.mv2` file. No databases, no servers. Key concepts:

- **Smart Frames**: Immutable, append-only content units with checksums, timestamps, and metadata. Grouped into segments for compression and parallel reads.
- **Embedded WAL**: Write-ahead log inside the file for crash recovery. Checkpoints at 75% occupancy or every 1,000 transactions.
- **Feature-flag architecture**: `lex` (BM25/Tantivy FTS), `vec` (HNSW + ONNX embeddings), `clip` (visual), `whisper` (audio), `encryption`, `temporal_track`, `parallel_segments`.
- **Graph search**: Entity pattern matching, triple extraction, hybrid graph+vector retrieval.
- **Time-travel**: Replay engine can rewind, replay, or branch any memory state.
- **URI scheme**: Hierarchical paths (`mv2://meetings/2024-01-15`) for structured addressing.

### Gap Analysis: Memvid vs EntropicMem

| # | Feature | Memvid | EntropicMem | Gap? | Priority |
|---|---------|--------|-------------|------|----------|
| G1 | **Semantic/vector search** | HNSW + ONNX embeddings (384-dim BGE-small), cosine similarity | FTS5 keyword only | **YES** | **HIGH** |
| G2 | **Hybrid search** | BM25 + vector fusion ranking | FTS5 only | **YES** | **HIGH** |
| G3 | **Temporal queries** | Natural language date parsing ("last Tuesday"), time index | `created_at` column, no NL parsing | **YES** | MEDIUM |
| G4 | **PII detection** | Built-in PII scanner/redaction | None | **YES** | MEDIUM |
| G5 | **Graph/relational query** | Entity patterns, triple extraction, graph-filtered search | Vault wikilinks exist but not queryable as a graph | **YES** | MEDIUM |
| G6 | **Time-travel / replay** | Rewind, replay, branch memory states via replay engine | No temporal state queries | **YES** | LOW |
| G7 | **Append-only immutability** | Smart Frames are immutable with SHA-256 checksums | Facts are mutable (reinforce, patch_core) | Partial | LOW |
| G8 | **Single-file capsule** | Self-contained `.mv2` with rules, expiry, sharing | SQLite DB + vault directory (two artifacts) | Partial | LOW |
| G9 | **Compression** | Zstd / LZ4 per-frame compression | SQLite WAL (implicit) | Minimal | LOW |
| G10 | **Encryption at rest** | Password-based encrypted capsules (`.mv2e`) | None | **YES** | LOW |
| G11 | **Multi-modal ingestion** | PDF, CLIP images, Whisper audio | Text only | Out of scope | SKIP |
| G12 | **Predictive caching** | Sub-5ms recall with predictive cache | SQLite is already fast (~1ms) | Minimal | SKIP |

### Phased Implementation Plan

#### Phase 7: Semantic Search Foundation (HIGH)

**Goal:** Add vector embeddings and hybrid search to close the biggest capability gap.

- [ ] **7.1 — Embedding pipeline**
  - Add optional `sentence-transformers` dependency (already in pyproject.toml as optional)
  - Create `skills/entropicmem/scripts/embeddings.py`
  - Generate 384-dim embeddings on `remember()` when model available
  - Store embeddings in a new `embeddings` table (entropic_id TEXT PK, vector BLOB)
  - Graceful fallback: if no model, skip embedding (FTS5 still works)
  - **Acceptance:** `remember("test fact")` stores embedding; `recall("test")` uses vector similarity when available

- [ ] **7.2 — Vector search in recall**
  - Add cosine similarity search over embeddings table
  - Implement `recall_with_relevance()` hybrid mode: FTS5 score + vector score, weighted fusion
  - Configurable weights (default: 0.6 FTS + 0.4 vector)
  - **Acceptance:** `recall("what did I say about X")` returns semantically relevant results even without exact keyword match

- [ ] **7.3 — Embedding maintenance**
  - CLI command `entropicmem embed --rebuild` to regenerate all embeddings
  - Auto-embed on remember, lazy-embed on first recall miss
  - Health check reports embedding coverage (% of facts with vectors)
  - **Acceptance:** `entropicmem embed --rebuild` processes all facts; health check shows coverage

- **Dependencies:** `sentence-transformers` (optional), `numpy` (for cosine sim)
- **Risk:** Model download size (~90MB for BGE-small). Mitigate: cache in `~/.hermes/entropicmem/models/`

#### Phase 8: Temporal Intelligence (MEDIUM)

**Goal:** Natural language date queries and time-aware recall.

- [ ] **8.1 — Temporal query parser**
  - Create `skills/entropicmem/scripts/temporal.py`
  - Parse NL date expressions: "last Tuesday", "yesterday", "in March", "2 weeks ago"
  - Convert to SQL date range filters on `created_at` / `updated_at`
  - Integrate into `recall()` and `recall_with_relevance()`
  - **Acceptance:** `recall("meeting notes from last week")` filters by date range

- [ ] **8.2 — Time index**
  - Add `time_index` table for fast chronological range queries
  - Index on (created_at, domain) for filtered time scans
  - CLI: `entropicmem timeline --from 2026-01-01 --to 2026-07-01`
  - **Acceptance:** Timeline query returns facts in chronological order with domain filter

- **Dependencies:** None (stdlib `datetime` + `re` for parsing)

#### Phase 9: PII Detection & Redaction (MEDIUM)

**Goal:** Prevent sensitive data from persisting in memory.

- [ ] **9.1 — PII scanner**
  - Create `skills/entropicmem/scripts/pii.py`
  - Regex-based detection: emails, phone numbers, ID numbers, API keys, passwords
  - Optional: South African ID number pattern (13 digits), FNB account numbers
  - Scan on `remember()` — flag or redact before storage
  - Configurable: `warn` (log only), `redact` (replace with `[REDACTED]`), `block` (reject)
  - **Acceptance:** `remember("my password is hunter2")` triggers redaction/warning per config

- [ ] **9.2 — PII audit**
  - CLI: `entropicmem pii-scan` — scan all existing facts, report findings
  - Health check includes PII scan summary
  - **Acceptance:** `entropicmem pii-scan` reports any facts containing detected PII patterns

- **Dependencies:** None (stdlib `re`)

#### Phase 10: Graph Query Layer (MEDIUM)

**Goal:** Make vault wikilinks queryable as a knowledge graph.

- [ ] **10.1 — Link graph extraction**
  - Parse vault wikilinks into a `links` table (source_id, target_title, context)
  - Build on vault projection (already extracts wikilinks)
  - CLI: `entropicmem graph --show "Wedding"` — show connected notes
  - **Acceptance:** `entropicmem graph --show X` returns all notes linking to/from X

- [ ] **10.2 — Graph-aware recall**
  - When a recall hit has wikilinks, optionally expand to linked notes
  - `recall("wedding venue", expand_links=True)` returns the fact + linked context
  - **Acceptance:** Recall with link expansion returns related vault notes

- **Dependencies:** Phase 7 (vector search) for best results, but works standalone with FTS5

#### Phase 11: Security & Portability (LOW)

**Goal:** Encryption at rest and portable memory capsules.

- [ ] **11.1 — Encryption at rest**
  - Use SQLite's built-in encryption or `cryptography` Fernet for vault files
  - Optional passphrase stored in VaultKnox
  - CLI: `entropicmem encrypt --enable` / `--disable`
  - **Acceptance:** DB and vault files are encrypted; unreadable without passphrase

- [ ] **11.2 — Memory capsule export**
  - Single-file export: `entropicmem export capsule.mv2` (or `.tar.gz`)
  - Bundle: SQLite DB + vault notes + embeddings + metadata
  - Import: `entropicmem import capsule.mv2`
  - **Acceptance:** Export/import round-trip preserves all facts, vault notes, and embeddings

- [ ] **11.3 — Fact immutability option**
  - Optional append-only mode: updates create new versions, old versions retained
  - `versions` table tracks history (entropic_id, version, content, timestamp)
  - CLI: `entropicmem history <entropic_id>` — show version timeline
  - **Acceptance:** In append-only mode, `reinforce()` creates new version; `history` shows all versions

- **Dependencies:** `cryptography` (optional) for encryption

### What We're NOT Adopting (and Why)

| Memvid Feature | Why Skip |
|---------------|----------|
| Multi-modal (CLIP, Whisper, PDF) | EntropicMem is a text memory system for an AI agent. Multi-modal ingestion is out of scope. |
| Predictive caching | SQLite recall is already ~1ms. Predictive caching adds complexity for negligible gain. |
| Rust rewrite | EntropicMem's stdlib-Python approach is a feature, not a limitation. Hermes integration requires Python. |
| `.mv2` binary format | SQLite is already a single-file, portable, battle-tested format. No need for a custom binary. |
| Serverless architecture | EntropicMem is already serverless (embedded SQLite). No gap here. |

### Priority Summary

| Phase | Focus | Priority | Effort | Dependencies |
|-------|-------|----------|--------|--------------|
| **7** | Semantic/vector search | **HIGH** | Large | sentence-transformers (optional) |
| **8** | Temporal queries | MEDIUM | Medium | None |
| **9** | PII detection | MEDIUM | Small | None |
| **10** | Graph query layer | MEDIUM | Medium | Phase 7 (optional) |
| **11** | Security & portability | LOW | Medium | cryptography (optional) |

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