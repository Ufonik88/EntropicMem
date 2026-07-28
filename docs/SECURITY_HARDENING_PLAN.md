# EntropicMem × Hermes — Security & Robustness Hardening Plan

**Created:** 2026-07-28  
**Completed:** 2026-07-28  
**Status:** Phases 1–3 complete in v2.1.6  
**Branch/release:** `security/phase1-hardening` → tag `v2.1.6`

See `CHANGELOG.md` and `MASTER_TODO.md` for execution log.

## Delivered

### Phase 1
- Graph server localhost + token; no default full_body; FS 700/600
- Encrypted backups; auto_extract off; patch_core gated; prefetch denylist
- remember sanitization; LIKE domain fix

### Phase 2
- Sensitivity tiers + write policy (`policy.py`) — secret blocked, auto quarantine
- `audit_log` + `pending_facts` tables; CLI `audit` / `pending`
- forget/consolidate require confirm; consolidate dry-run default
- Path pin (no Obsidian fallback in plugin); merge-safe save_config
- SSRF DNS resolve + private IP recheck
- reinforce_on_recall default false
- Backup restore docs; SQLCipher spike doc

### Phase 3
- Extended pytest security pack
- Health checks: security_posture + audit_log
- Backup restore game-day doc
