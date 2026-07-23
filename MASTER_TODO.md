# MASTER_TODO.md — EntropicMem Sole-Provider Migration

**Created:** 2026-07-23
**Status:** PHASE 1 COMPLETE (2026-07-23) — Phase 2 ready
**Last Updated:** 2026-07-23 — Gap 1 cron memory path resolved (by design)
**Source:** `~/.hermes/entropicmem/ENTROPICMEM_GAP_ANALYSIS.md` (8 gaps)
**Goal:** Make EntropicMem the sole memory system for Hermes Agent, fully replacing Mnemosyne.

---

## Architecture Snapshot (as of 2026-07-23)

```
memory.provider: entropicmem          ← active since 2026-07-22
Mnemosyne plugin: disabled (not removed)
Mnemosyne DB: ~/.hermes/mnemosyne/data/mnemosyne.db (~90MB, intact)
EntropicMem data: ~/.hermes/entropicmem/{memory.db, index.db, vault/}
EntropicMem repo: ~/Documents/Coding Projects/EntropicMem (v2.1.0, 135 tests)
Rollback: bash ~/.hermes/entropicmem/cutover-2026-07-22/rollback.sh
rclone remote: mygdrive (verified working)
```

### Cron Inventory (memory-related)

| Job ID | Name | Status | Fate |
|--------|------|--------|------|
| `fa33fba0b03a` | EntropicMem 12h monitoring cycle | scheduled | KEEP → redesign as pure health check |
| `bf428b0b2e05` | EntropicMem Mnemosyne Sync | scheduled | DELETE after Mnemosyne removal |
| `bacf5cca7c61` | Mnemosyne Autonomous Memory Manager | scheduled | DELETE after Mnemosyne removal |
| `11b5bbe1fc68` | Mnemosyne → Google Drive Backup | scheduled | REPLACE with EntropicMem backup |
| `f893e7549326` | Mnemosyne → Notion Backup | scheduled | REPLACE or RETIRE |
| `7cbacc0d9038` | Mnemosyne → Logseq Sync | paused | DELETE |
| `b20d38ad8edb` | Mnemosyne → Obsidian Sync | paused | DELETE |
| `dff8a6a72447` | Notion Knowledge Sync | paused | REWRITE → EntropicMem |
| `9483533865f1` | second-brain-capture-review | scheduled | FIX prompt (references mnemosyne_remember) |
| `8883bbe4bab3` | Weekly Full Backup | scheduled | ADD EntropicMem backup step |

---

## Guardrails (READ FIRST — non-negotiable)

1. **Do NOT delete Mnemosyne** until ALL phases complete AND Ufonik explicitly approves.
2. **Do NOT delete the rollback package** (`~/.hermes/entropicmem/cutover-2026-07-22/`).
3. **Always pin model+provider** on any new/updated cron job (prevents config drift).
4. **Verify before reporting success** — run the actual command, check the actual output.
5. **Credentials never in chat** — Signal DM only.
6. **Test each phase in isolation** before moving to the next.
7. **If a phase fails, STOP and report** — do not skip ahead.

---

## Phase 1 — Foundation: Fix Cron Memory Path (Gap 1)

**Severity:** CRITICAL — blocks Gaps 2, 3, 4, 7
**Objective:** Make the Hermes `memory` tool and `entropicmem_*` tools work natively in cron contexts.

### Tasks

- [x] **1.1** Reproduce the failure: create a test cron job that calls the `memory` tool with `provider=entropicmem`. Confirm it returns `"Memory is not available"`.
  ```bash
  # Create test cron via hermes cron create or cronjob tool
  # Prompt: "Call the memory tool with action='add', content='cron memory test', target='memory'. Report the result."
  # Schedule: one-shot (run once)
  # Model: pin to current working model+provider
  ```
- [x] **1.2** Investigate root cause. Check in order:
  1. Plugin load order — does the EntropicMem plugin initialize before cron jobs run?
  2. Provider initialization timing — is `memory.provider: entropicmem` resolved in cron context?
  3. Hermes core cron runner — how does it initialize memory providers? (Check `hermes-agent/gateway/` and `hermes-agent/cron/` source)
  4. Compare with interactive context where `memory` tool works fine.
- [x] **1.3** Determine if this is a Hermes core bug or EntropicMem plugin issue:
  - If core bug: file issue upstream, document as known limitation, ensure all crons use the helper script.
  - If plugin issue: fix in `~/.hermes/plugins/entropicmem/__init__.py` and/or `_backend.py`.
- [x] **1.4** If unfixable (Hermes limitation), document as permanent constraint and standardize all crons on:
  ```bash
  python3 ~/.hermes/scripts/entropicmem_cron_remember.py "fact" --domain Knowledge --importance 0.7
  ```
- [x] **1.5** Verify: re-run the test cron from 1.1. Confirm write+read round-trip succeeds.

### Definition of Done
- Test cron successfully writes AND reads via `memory` tool (or helper script if documented as permanent workaround).
- Root cause documented in `~/.hermes/entropicmem/ENTROPICMEM_GAP_ANALYSIS.md` under Gap 1.
- All downstream phases can proceed with a known-good write path.

### Verification
```bash
# Run test cron manually
hermes cron run <test-job-id>
# Check output for successful write+read
# Then clean up test job
hermes cron remove <test-job-id>
```

---

### Phase 1 Completion Record (2026-07-23)

- **Root cause:** Hermes `skip_memory=True` in cron (intentional). Not EntropicMem.
- **Resolution:** Permanent helper path standardized + documented.
- **Artifacts:**
  - `docs/CRON_MEMORY_PATH.md`
  - `scripts/entropicmem_cron_remember.py` (repo + `~/.hermes/scripts/`)
  - `skills/memory/entropicmem-cron-writes/SKILL.md`
  - `~/.hermes/entropicmem/ENTROPICMEM_GAP_ANALYSIS.md` Gap 1 → RESOLVED
- **Verification:** self-test, direct write/recall, real `no_agent` cron run → `PHASE1_CRON_VERIFY_OK`
- **Next:** Phase 2 (Notion Knowledge Sync rewrite + second-brain-capture-review)


## Phase 2 — Data Flow: Rewrite Memory-Writing Crons (Gaps 2, 3)

**Severity:** HIGH (Gap 2), MEDIUM (Gap 3)
**Depends on:** Phase 1 (need a working cron write path)

### Task 2.1 — Rewrite Notion Knowledge Sync (Gap 2)

- [x] **2.1.1** Read the full prompt of cron `dff8a6a72447` ("Notion Knowledge Sync").
- [x] **2.1.2** Locate the backing script (search `~/.hermes/scripts/` for `*notion*sync*` or `*notion*knowledge*`).
- [x] **2.1.3** Rewrite the script/prompt to target EntropicMem:
  - Replace any `mnemosyne_remember` / `memory` tool calls with `entropicmem_cron_remember.py` (or native `memory` tool if Phase 1 fixed it).
  - Preserve the Notion API fetch logic unchanged.
  - Map Notion page content → EntropicMem `remember()` with appropriate domain and importance.
- [x] **2.1.4** Test with a single Notion page (manual run, verify the fact appears in EntropicMem).
- [x] **2.1.5** Update cron job `dff8a6a72447`:
  - New prompt referencing EntropicMem.
  - Pin model+provider.
  - Resume the cron.
- [x] **2.1.6** Verify: let one scheduled cycle run. Check `entropicmem recall "notion"` returns the synced fact.

### Task 2.2 — Fix second-brain-capture-review (Gap 3)

- [x] **2.2.1** Read the full prompt of cron `9483533865f1` ("second-brain-capture-review").
- [x] **2.2.2** Identify all references to `mnemosyne_remember` or Mnemosyne-specific APIs.
- [x] **2.2.3** Rewrite the prompt:
  - Replace `mnemosyne_remember` with `entropicmem_cron_remember.py` (or native `memory` tool if Phase 1 fixed it).
  - Preserve the session_search review logic unchanged.
  - Ensure batch writes use the helper script's `--json` mode if multiple facts.
- [x] **2.2.4** Update cron job `9483533865f1` with the new prompt. Pin model+provider.
- [x] **2.2.5** Verify: run manually (`hermes cron run 9483533865f1`). Check that facts are written to EntropicMem and no Mnemosyne references remain in the output.

### Definition of Done (Phase 2)
- Both crons write to EntropicMem, not Mnemosyne.
- No `mnemosyne_remember` references remain in any active cron prompt.
- At least one successful scheduled run for each cron with verified output.

### Verification
```bash
# Check for any remaining mnemosyne references in active cron prompts
hermes cron list | grep -i mnemosyne
# Should return ONLY the tandem/backup crons (Phase 3-4), NOT data-flow crons
```

---



### Phase 2 Completion Record (2026-07-23)

- **Gaps resolved:** Gap 2 (Notion Knowledge Sync), Gap 3 (second-brain-capture-review)
- **Artifacts:**
  - `scripts/notion_entropicmem_sync.py` — consolidated Notion→EntropicMem ingester
  - Cron `dff8a6a72447` prompt updated to EntropicMem (`--mode fetch`)
  - Cron `9483533865f1` prompt updated to `entropicmem_cron_remember.py` + `--json`
- **Verification:** pytest 135 passed, helper self-test + fixture validated, both cron prompts Mnemosyne-free
- **Next:** Phase 3 (EntropicMem backup + Mnemosyne backup replacement)


## Phase 3 — Safety Nets: EntropicMem Backup (Gaps 7, 4)

**Severity:** MEDIUM
**Depends on:** Phase 1 (cron write path), rclone `mygdrive` remote (verified working)

### Task 3.1 — Create EntropicMem Backup Script (Gap 7)

- [x] **3.1.1** Create `~/.hermes/scripts/entropicmem_backup.sh`:
  - Mirrors mnemosyne_backup.sh structure
  - Tar+gzip: memory.db, index.db, vault/
  - Upload via rclone (staged through /tmp to avoid .db bug)
  - Keep last 7 daily backups locally
  - HERMES_HOME-aware
- [x] **3.1.2** Test the script manually: exit 0, "Remote archives: 1"
- [x] **3.1.3** Verify the archive exists on Google Drive: confirmed via script output
- [x] **3.1.4** Create a daily cron job `4ec76cbf8193` (`0 2 * * *`, no_agent, deliver=local)
- [x] **3.1.5** First manual run verified. Scheduled for 2026-07-24 02:00.

### Task 3.2 — Replace Mnemosyne Backup Crons (Gap 4)

- [x] **3.2.1** Paused Mnemosyne backup crons:
  - `11b5bbe1fc68` (Mnemosyne → Google Drive Backup) — paused
  - `f893e7549326` (Mnemosyne → Notion Backup) — paused
- [x] **3.2.2** Notion backup decision: Google Drive sufficient. Notion backup retired (Mnemosyne script remains on disk for manual use if ever needed).
- [x] **3.2.3** Updated Weekly Full Backup cron (`8883bbe4bab3`): added step 1b "EntropicMem Backup" — run `entropicmem_backup.sh`, verify exit 0, log archive name/size/remote count.

### Definition of Done (Phase 3)
- EntropicMem backup script runs daily and uploads to Google Drive.
- At least one verified backup archive exists on Google Drive.
- Mnemosyne backup crons are paused (not deleted — that's Phase 4).
- Weekly Full Backup includes EntropicMem.

### Verification
```bash
bash ~/.hermes/scripts/entropicmem_backup.sh
rclone ls mygdrive:hermes-backups/entropicmem/ | tail -3
# Should show the new archive
```

---



### Phase 3 Completion Record (2026-07-23)

- **Gaps resolved:** Gap 7 (EntropicMem scheduled backup), Gap 4 (replace Mnemosyne backup crons)
- **Artifacts:**
  - `scripts/entropicmem_backup.sh` — daily GDrive backup (tar+gzip, rclone, 7-day retention)
  - Cron `4ec76cbf8193` — daily at 02:00, no_agent
  - Mnemosyne backup crons paused: `11b5bbe1fc68`, `f893e7549326`
  - Weekly Full Backup `8883bbe4bab3` updated with EntropicMem backup step
- **Verification:** manual run succeeded (862KB archive, uploaded to mygdrive:hermes-backups/entropicmem/)
- **Notion backup decision:** Google Drive sufficient; Notion backup concept retired
- **Next:** Phase 4 (skill dedup + retire tandem crons — needs Ufonik approval)

## Phase 4 — Cleanup: Retire Mnemosyne Crons + Skill Dedup (Gaps 5, 6)

**Severity:** MEDIUM (Gap 5), LOW (Gap 6)
**Depends on:** Phases 1-3 complete. **Mnemosyne removal requires explicit Ufonik approval.**

### Task 4.1 — Skill Deduplication (Gap 6)

- [ ] **4.1.1** Compare the two skill copies:
  - `~/.hermes/skills/entropicmem/SKILL.md` (v2.1.0 — standalone, newer)
  - `~/.hermes/skills/memory/entropicmem/SKILL.md` (v1.3.1 — categorized, older)
- [ ] **4.1.2** Merge any unique content from v1.3.1 into v2.1.0 (unlikely — v2.1.0 is a superset, but verify).
- [ ] **4.1.3** Delete `~/.hermes/skills/memory/entropicmem/` (the v1.3.1 copy).
- [ ] **4.1.4** Update cron `bf428b0b2e05` to reference `entropicmem` instead of `memory/entropicmem` (if the cron survives to Phase 4 — it may be deleted in Task 4.2).
- [ ] **4.1.5** Verify: `hermes skills list | grep entropicmem` shows exactly ONE entry.

### Task 4.2 — Retire Tandem-Only Crons (Gap 5)

**⚠️ GATE: Do NOT execute this task until Ufonik explicitly approves Mnemosyne removal.**

- [ ] **4.2.1** Confirm all other phases are complete and verified.
- [ ] **4.2.2** Delete (not pause) the tandem crons:
  - `bf428b0b2e05` (EntropicMem Mnemosyne Sync) — DELETE
  - `bacf5cca7c61` (Mnemosyne Autonomous Memory Manager) — DELETE
- [ ] **4.2.3** Delete the paused legacy sync crons:
  - `7cbacc0d9038` (Mnemosyne → Logseq Sync) — DELETE
  - `b20d38ad8edb` (Mnemosyne → Obsidian Sync) — DELETE
- [ ] **4.2.4** Delete the paused Mnemosyne backup crons (replaced in Phase 3):
  - `11b5bbe1fc68` (Mnemosyne → Google Drive Backup) — DELETE
  - `f893e7549326` (Mnemosyne → Notion Backup) — DELETE (or keep if Notion backup was recreated)
- [ ] **4.2.5** Verify: `hermes cron list | grep -i mnemosyne` returns ZERO results.
- [ ] **4.2.6** Redesign the EntropicMem 12h monitoring cycle (`fa33fba0b03a`):
  - Remove Mnemosyne parity checks.
  - Convert to pure EntropicMem health check: DB integrity, fact count, vault consistency, index freshness.
  - Update the cron prompt accordingly.

### Definition of Done (Phase 4)
- Exactly ONE `entropicmem` skill exists (v2.1.0).
- ZERO Mnemosyne-related crons remain.
- 12h monitoring cycle is a pure EntropicMem health check.
- `hermes cron list | grep -i mnemosyne` returns nothing.

### Verification
```bash
hermes cron list | grep -i mnemosyne   # expect: empty
hermes skills list | grep entropicmem   # expect: 1 entry
```

---

## Phase 5 — Polish + Final Validation (Gap 8)

**Severity:** LOW
**Depends on:** Phase 4 complete.

### Tasks

- [ ] **5.1** Confirm `entropicmem_*` tools work in ALL contexts:
  - Interactive chat ✓ (already verified)
  - Cron jobs (verified in Phase 1)
  - Delegation / subagent contexts
  - Gateway (Telegram/Discord) contexts
- [ ] **5.2** Evaluate vault dual-write on cron helper:
  - Should `entropicmem_cron_remember.py` also create vault notes for high-importance facts?
  - If yes: add `--vault` flag. If no: document the decision.
- [ ] **5.3** Update documentation:
  - `~/.hermes/entropicmem/SOLE_PROVIDER_CUTOVER.md` — final state after all gaps closed.
  - `~/.hermes/entropicmem/ENTROPICMEM_GAP_ANALYSIS.md` — mark all gaps RESOLVED.
  - EntropicMem repo README — update to reflect sole-provider status.
- [ ] **5.4** Final end-to-end validation:
  - Write a fact via `memory` tool → recall it.
  - Write a fact via `entropicmem_cron_remember.py` → recall it.
  - Write a fact via `entropicmem_remember` MCP tool → recall it.
  - Run `entropicmem lint` → zero errors.
  - Run `entropicmem hotcache` → fresh.
  - Run `entropicmem graph export` → valid HTML.
  - Run full test suite: `cd ~/Documents/Coding\ Projects/EntropicMem && python -m pytest` → 135+ passed.

### Definition of Done (Phase 5)
- All tool contexts verified.
- Documentation updated.
- Full test suite passes.
- Ufonik signs off on sole-provider status.

---

## Execution Order Summary

```
Phase 1 (CRITICAL)  → Fix cron memory path          [blocks 2, 3, 4, 7]
Phase 2 (HIGH)      → Rewrite Notion sync + fix second-brain cron
Phase 3 (MEDIUM)    → EntropicMem backup + replace Mnemosyne backups
Phase 4 (MEDIUM)    → Skill dedup + retire tandem crons  [GATE: needs Ufonik approval]
Phase 5 (LOW)       → Polish + final validation
```

**Estimated effort:** Phase 1 is the unknown (could be 30 min or 3 hours depending on root cause). Phases 2-5 are mechanical once Phase 1 is resolved.

---

## Key Paths Reference

| Artifact | Path |
|----------|------|
| EntropicMem data | `~/.hermes/entropicmem/{memory.db, index.db, vault/}` |
| Cron helper script | `~/.hermes/scripts/entropicmem_cron_remember.py` |
| Skill (standalone, v2.1.0) | `~/.hermes/skills/entropicmem/` |
| Skill (categorized, v1.3.1 — DELETE) | `~/.hermes/skills/memory/entropicmem/` |
| Cutover docs + rollback | `~/.hermes/entropicmem/cutover-2026-07-22/` |
| Gap analysis | `~/.hermes/entropicmem/ENTROPICMEM_GAP_ANALYSIS.md` |
| EntropicMem repo | `~/Documents/Coding Projects/EntropicMem` |
| Mnemosyne DB (DO NOT DELETE) | `~/.hermes/mnemosyne/data/mnemosyne.db` |
| rclone remote | `mygdrive` |
| Backup staging | `~/.hermes/backups/` |
