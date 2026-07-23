# EntropicMem — Pre-Sole-Provider Gap Analysis

**Generated:** 2026-07-23
**Current state:** Tandem (EntropicMem sole provider, Mnemosyne disabled, some crons resumed)
**Goal:** Close all gaps so EntropicMem can run as the ONLY memory system with no Mnemosyne dependency.

---

## Current Architecture

```
memory.provider: entropicmem
Mnemosyne plugin: disabled (not removed)
Mnemosyne DB: ~/.hermes/mnemosyne/data/mnemosyne.db (~90MB, intact)

Active crons using EntropicMem:
  fa33fba0b03a  EntropicMem 12h monitoring cycle     (scheduled)
  bf428b0b2e05  EntropicMem Mnemosyne Sync            (scheduled, tandem bridge)

Resumed Mnemosyne crons (tandem safety nets):
  bacf5cca7c61  Mnemosyne Autonomous Memory Manager   (scheduled)
  11b5bbe1fc68  Mnemosyne → Google Drive Backup       (scheduled)
  f893e7549326  Mnemosyne → Notion Backup              (scheduled)

Still paused:
  dff8a6a72447  Notion Knowledge Sync                  (paused — needs rewrite)
  7cbacc0d9038  Mnemosyne → Logseq Sync                (paused — legacy)
  b20d38ad8edb  Mnemosyne → Obsidian Sync              (paused — legacy)

Rollback: bash ~/.hermes/entropicmem/cutover-2026-07-22/rollback.sh
```

---

## Gap 1: Cron Memory Path — `memory` Tool Unavailable

**Severity:** CRITICAL → **RESOLVED (by design)** — 2026-07-23
**What:** The Hermes `memory` tool returns `"Memory is not available"` in cron contexts when `provider=entropicmem`. The `entropicmem_*` tools are also unavailable.

**Root cause (confirmed):** Hermes core intentional design — NOT an EntropicMem bug.
- `cron/scheduler.py` constructs `AIAgent(skip_memory=True)` with comment:
  *"Cron system prompts would corrupt user representations"*
- `agent/agent_init.py`: when `skip_memory=True`, external MemoryProvider is not loaded
- Even if the `"memory"` toolset is forced on, only the file-backed MEMORY.md store is created — not EntropicMem

**Official permanent path (verified):**
```bash
python3 ~/.hermes/scripts/entropicmem_cron_remember.py "fact" --domain Knowledge --importance 0.7 --source cron
```
- Canonical repo copy: `scripts/entropicmem_cron_remember.py`
- Design doc: `docs/CRON_MEMORY_PATH.md` (+ `~/.hermes/entropicmem/CRON_MEMORY_PATH.md`)
- Skill: `entropicmem-cron-writes` (`skills/memory/entropicmem-cron-writes/`)

**Verification completed (2026-07-23):**
1. Helper `--self-test` → exit 0, `verified_recall: true`
2. Direct write+recall → exit 0
3. `no_agent` cron job `d299bfbdf578` ran script via scheduler → output `PHASE1_CRON_VERIFY_OK` (then job removed)

**Do not "fix" by forcing skip_memory=False** without upstream design for write-only provider loads that skip prompt injection.

---

## Gap 2: Rewrite Notion Knowledge Sync → EntropicMem

**Severity:** HIGH
**What:** Cron `dff8a6a72447` ("Notion Knowledge Sync") syncs Notion pages → Mnemosyne memory. Currently paused. Must be rewritten to target EntropicMem.

**Cron details:**
- Job ID: `dff8a6a72447`
- Schedule: `every 120m`
- Current prompt: "Sync Notion knowledge into Mnemosyne memory"
- Skills: none (no skill loaded)
- Model: `kilo-auto/free` / `kilocode`

**What needs to happen:**
1. Load the existing prompt (check if there's a script backing it)
2. Rewrite to use `entropicmem_cron_remember.py` or `entropicmem remember` CLI
3. Test with a single Notion page
4. Update cron job prompt + pin model/provider
5. Resume the cron

**Dependencies:** Gap 1 (cron memory path) — if `memory` tool works after fix, can use it directly; otherwise use helper script.

---

## Gap 3: Audit `second-brain-capture-review` Cron

**Severity:** MEDIUM
**What:** Cron `9483533865f1` ("second-brain-capture-review") runs every 12h, reviews recent sessions, and stores durable facts. Last run (2026-07-23 01:25) attempted to use `memory` tool with `operations` (batch writes) and hit failures.

**Cron details:**
- Job ID: `9483533865f1`
- Schedule: `every 720m`
- Active: YES (scheduled)
- Prompt: "store valuable findings using mnemosyne_remember" ← **STILL REFERENCES MNEMOSYNE**

**What needs to happen:**
1. Read the full cron prompt
2. Check if it's still trying to call `mnemosyne_remember`
3. Rewrite to use EntropicMem (either `memory` tool if Gap 1 fixed, or helper script)
4. Update cron job prompt
5. Verify with a manual run

---

## Gap 4: Replace Mnemosyne Backup/Export Crons

**Severity:** MEDIUM → **RESOLVED (2026-07-23)**
**What:** When Mnemosyne is fully removed, these crons become dead weight. Need EntropicMem equivalents or explicit retirement.

**Current state:**

| Job ID | Name | Status | Action |
|--------|------|--------|--------|
| `11b5bbe1fc68` | Mnemosyne → Google Drive Backup | Resumed (tandem) | Create EntropicMem equivalent |
| `f893e7549326` | Mnemosyne → Notion Backup | Resumed (tandem) | Create EntropicMem equivalent |
| `7cbacc0d9038` | Mnemosyne → Logseq Sync | Paused | Retire (Obsidian second-brain is active) |
| `b20d38ad8edb` | Mnemosyne → Obsidian Sync | Paused | Retire (Obsidian pipeline is git-native) |

**What needs to happen:**
1. Create `entropicmem_backup.sh` — backs up `memory.db`, `index.db`, `vault/` to Google Drive
2. Create `entropicmem_to_notion_backup.py` — or decide if Notion backup is still needed
3. Explicitly retire Logseq + Obsidian sync crons (delete them, not just pause)
4. Update the Weekly Full Backup cron (`8883bbe4bab3`) to include EntropicMem backup

**Dependencies:** Gap 1 (for cron scripts)

---

## Gap 5: Retire or Redesign Tandem-Only Crons

**Severity:** MEDIUM → **RESOLVED (2026-07-23, paused not deleted)**
**What:** Two crons exist only because of the tandem setup. When Mnemosyne is removed, they become unnecessary.

| Job ID | Name | Status | Post-Mnemosyne Fate |
|--------|------|--------|---------------------|
| `bf428b0b2e05` | EntropicMem Mnemosyne Sync | Resumed (tandem) | **DELETE** — no Mnemosyne to sync from |
| `bacf5cca7c61` | Mnemosyne Autonomous Memory Manager | Resumed (tandem) | **DELETE** — no Mnemosyne to manage |

**What needs to happen:**
1. After all other gaps are closed and Mnemosyne removal is approved
2. Delete both crons (not pause — delete)
3. Verify EntropicMem 12h monitoring cycle (`fa33fba0b03a`) handles all maintenance

---

## Gap 6: Skill Deduplication

**Severity:** LOW → **RESOLVED (2026-07-23)** (but confusing)
**What:** Two copies of the `entropicmem` skill exist:

| Path | Version | Referenced By |
|------|---------|---------------|
| `~/.hermes/skills/entropicmem/SKILL.md` | v2.1.0 | Standalone (newer) |
| `~/.hermes/skills/memory/entropicmem/SKILL.md` | v1.3.1 | Cron `bf428b0b2e05` (as `memory/entropicmem`) |

**What needs to happen:**
1. Compare both versions, merge any unique content from v1.3.1 into v2.1.0
2. Delete `~/.hermes/skills/memory/entropicmem/`
3. Update cron `bf428b0b2e05` to reference the standalone `entropicmem` skill
4. (If Gap 5 deletes that cron, step 3 is moot)

---

## Gap 7: EntropicMem Scheduled Backup

**Severity:** MEDIUM → **RESOLVED (2026-07-23)**
**What:** No automated backup of EntropicMem's own data. Mnemosyne had Google Drive + Notion backups. EntropicMem needs at least one.

**Data to back up:**
- `~/.hermes/entropicmem/memory.db` — fact engine
- `~/.hermes/entropicmem/index.db` — search index
- `~/.hermes/entropicmem/vault/` — markdown notes

**What needs to happen:**
1. Create `~/.hermes/scripts/entropicmem_backup.sh`:
   - Tar+gzip the three paths
   - Upload to Google Drive via `gdrive` or `rclone`
   - Keep last 7 daily backups
2. Create a cron job (daily, off-peak) to run it
3. Add to Weekly Full Backup cron (`8883bbe4bab3`)

**Dependencies:** Gap 1, gdrive/rclone configuration

---

## Gap 8: Optional Polish

**Severity:** LOW → **IN PROGRESS (Phase 5)**
**What:** Quality-of-life improvements for production-hard status.

**Items:**
1. **Confirm `entropicmem_*` tools in all contexts** — interactive, cron, delegation, gateway
2. **Vault dual-write on cron helper** — currently `entropicmem_cron_remember.py` only writes to memory engine. Should it also create vault notes?
3. **Monitoring** — 12h tandem cycle (`fa33fba0b03a`) currently monitors Mnemosyne parity. After Mnemosyne removal, redesign as pure EntropicMem health check
4. **Documentation** — Update `SOLE_PROVIDER_CUTOVER.md` with final state after all gaps closed

---

## Execution Order (Recommended)

```
Phase 1 — Foundation:
  Gap 1: Fix cron memory path (blocks Gaps 2, 3, 4, 7)

Phase 2 — Data Flow:
  Gap 2: Rewrite Notion Knowledge Sync
  Gap 3: Audit second-brain-capture-review

Phase 3 — Safety Nets:
  Gap 7: EntropicMem scheduled backup
  Gap 4: Replace Mnemosyne backup crons

Phase 4 — Cleanup:
  Gap 6: Skill deduplication
  Gap 5: Retire tandem crons (LAST — only after Mnemosyne removal approved)

Phase 5 — Polish:
  Gap 8: Optional polish items
```

---

## Key Paths

| Artifact | Path |
|----------|------|
| EntropicMem data | `~/.hermes/entropicmem/{memory.db,index.db,vault/}` |
| Cron helper | `~/.hermes/scripts/entropicmem_cron_remember.py` |
| Skills (standalone) | `~/.hermes/skills/entropicmem/` |
| Skills (categorized) | `~/.hermes/skills/memory/entropicmem/` |
| Cron writes skill | `~/.hermes/skills/memory/entropicmem-cron-writes/` |
| Cutover docs | `~/.hermes/entropicmem/cutover-2026-07-22/` |
| Rollback | `bash ~/.hermes/entropicmem/cutover-2026-07-22/rollback.sh` |
| EntropicMem repo | `~/Documents/Coding Projects/EntropicMem` |

---

## Guardrails

- **Do NOT delete Mnemosyne** until all gaps closed AND Ufonik explicitly approves
- **Do NOT delete the rollback package** (`cutover-2026-07-22/`)
- **Always pin model+provider** on any new/updated cron jobs (prevents config drift)
- **Verify before reporting success** — subagent claims must be independently checked
- **Credentials never in chat** — Signal DM only