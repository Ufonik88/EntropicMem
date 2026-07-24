# EntropicMem — Sole Provider Cutover Record

**Date:** 2026-07-23
**Status:** ACTIVE PROVIDER — EntropicMem is the memory provider, Mnemosyne data preserved pending 1-week stability gate

> ⚠️ **NOT YET SOLE PROVIDER** — Mnemosyne crons paused, data intact. Full sole-provider promotion requires P0 blockers resolved and 1-week stability gate passed.

## Configuration

```yaml
memory:
  provider: entropicmem
  memory_enabled: true
  user_profile_enabled: true
```

## What Changed

| Component | Before | Current (Transition) | Target (Post-Gate) |
|---|---|---|---|
|-----------|--------|-------|
| Memory provider | `mnemosyne` | `entropicmem` (active) | `entropicmem` (sole) |
| Cron memory writes | `mnemosyne_remember` tool | `entropicmem_cron_remember.py` script | `entropicmem_cron_remember.py` script |
| Notion sync | `notion_to_mnemosyne_cron.py` | `notion_entropicmem_sync.py` (paused) | `notion_entropicmem_sync.py` (active) |
| Second-brain capture | `mnemosyne_remember` in prompt | `entropicmem_cron_remember.py --json` | `entropicmem_cron_remember.py --json` |
| Backup target | Mnemosyne DB → GDrive | EntropicMem DB → GDrive | EntropicMem DB → GDrive |
| 12h monitoring | Mnemosyne parity checks | Pure EntropicMem health check | Pure EntropicMem health check |
| Skill (active) | `memory/entropicmem` (v1.3.1) | `entropicmem` (v2.1.0+) | `entropicmem` (v2.1.0+) |
| Mnemosyne crons | Active | **Paused (6 crons)** | **Deleted** |
| Mnemosyne data | Live | **Preserved (~90MB)** | **Archived (not deleted)** |

## Crons

| Cron | Status | Notes |
|------|--------|-------|
| `fa33fba0b03a` EntropicMem 12h Health Check | **scheduled** | Pure health check (integrity, facts, vault, index, FTS, backup) |
| `4ec76cbf8193` EntropicMem → Google Drive Backup | **scheduled** | Daily 02:00, no_agent |
| `dff8a6a72447` Notion Knowledge Sync | **paused** | Rewritten to EntropicMem; resume when ready |
| `9483533865f1` second-brain-capture-review | **scheduled** | Uses `entropicmem_cron_remember.py` |
| `bf428b0b2e05` EntropicMem Mnemosyne Sync | **paused** | Legacy — delete after 1-week stability gate |
| `bacf5cca7c61` Mnemosyne Autonomous Memory Manager | **paused** | Legacy — delete after 1-week stability gate |
| `11b5bbe1fc68` Mnemosyne → Google Drive Backup | **paused** | Replaced by EntropicMem backup |
| `f893e7549326` Mnemosyne → Notion Backup | **paused** | Retired |
| `7cbacc0d9038` Mnemosyne → Logseq Sync | **paused** | Retired |
| `b20d38ad8edb` Mnemosyne → Obsidian Sync | **paused** | Retired |

> **6 Mnemosyne crons remain paused (not deleted)** — awaiting 1-week stability gate before deletion per Phase 6 gate.

## Data Paths

| Artifact | Path |
|----------|------|
| EntropicMem memory DB | `~/.hermes/entropicmem/memory.db` |
| EntropicMem index DB | `~/.hermes/entropicmem/index.db` |
| EntropicMem vault | `~/.hermes/entropicmem/vault/` |
| Cron helper | `~/.hermes/scripts/entropicmem_cron_remember.py` |
| Notion ingester | `~/.hermes/scripts/notion_entropicmem_sync.py` |
| Health check | `~/.hermes/scripts/entropicmem_health_check.py` |
| Backup script | `~/.hermes/scripts/entropicmem_backup.sh` |
| Skill | `~/.hermes/skills/entropicmem/` (symlink to repo) |
| Plugin | `~/.hermes/plugins/entropicmem/` |
| Mnemosyne data (preserved) | `~/.hermes/mnemosyne/data/mnemosyne.db` |
| Rollback | `bash ~/.hermes/entropicmem/cutover-2026-07-22/rollback.sh` |

## Rollback

If EntropicMem fails catastrophically:

```bash
bash ~/.hermes/entropicmem/cutover-2026-07-22/rollback.sh
```

This restores `memory.provider: mnemosyne` and re-enables Mnemosyne crons.

**Rollback validation:** After rollback, verify:
- `hermes config get memory.provider` returns `mnemosyne`
- `hermes plugins list` shows `mnemosyne` enabled
- 6 paused Mnemosyne crons resume and run successfully

**Rollback is NOT yet fully idempotent** — see Phase 6.5 (idempotent rollback script).

## Vault Dual-Write Decision

**Decision: NO vault dual-write on cron helper.**

Rationale:
- `entropicmem_cron_remember.py` is for lightweight, atomic fact storage with verified recall
- Vault notes are for richer content (ingest, research, linked markdown)
- Adding vault writes would increase complexity, slow cron execution, and conflate two storage patterns
- Vault is already populated via `entropicmem remember` CLI and `entropicmem ingest`
- If vault writes are needed from cron, use `entropicmem remember` CLI directly (which writes to both)

## Deletion Gate


After 1+ week of stable operation:
- [ ] Delete 6 paused Mnemosyne/tandem crons
- [ ] Delete `~/.hermes/mnemosyne/` data (with final backup)
- [ ] Remove rollback script
- [ ] Update this document to mark cutover FINAL
