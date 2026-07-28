# EntropicMem × Hermes — Security & Robustness Hardening Plan

**Created:** 2026-07-28  
**Source:** Lead security audit of sole-provider integration  
**Status:** Phase 1 complete (pending PR merge)  
**Owner:** Entropy / Ufonik

---

## Context

EntropicMem v2.1.5 is the sole Hermes memory provider. Live store ~711 facts (Finance/tax content present). Encryption-at-rest unused. Graph server was bound `0.0.0.0:8075` without auth and HTML embeds full note bodies.

---

## Risk matrix (audit)

| ID | Finding | Severity |
|----|---------|----------|
| H1 | Graph server unauth on all interfaces; full bodies | High |
| H2 | Plaintext DB/vault/backups; weak file modes | High |
| H3 | Context poisoning via prefetch/Core Memory | High |
| H4 | `patch_core` without dual-control/audit | High |
| H5 | Auto-extract default-on writes unvetted text | High |
| M1 | Offline-only encryption unused in prod | Medium |
| M2 | PII incomplete for finance/tax | Medium |
| M3 | Agent `consolidate` destructive | Medium |
| M4 | CLI graph serve binds all interfaces | Medium |
| M5 | SSRF DNS rebinding gaps | Medium |
| M6 | Vault path can fall through to Obsidian | Medium |
| M7 | Dual-store SoT confusion | Medium |
| M8 | No write audit trail | Medium |
| M9 | `save_config` YAML clobber risk | Medium |
| M10 | LIKE domain filter operator precedence | Medium |
| M11 | Recall auto-reinforce write-on-read | Medium |
| M12 | GDrive backups unencrypted | Medium |
| L1–L6 | FTS hygiene, domain validation, test residue, XSS residual, id collision | Low |

---

## Phase 1 — Immediate / Critical

| # | Action | Status |
|---|--------|--------|
| 1.1 | Graph server bind `127.0.0.1`; token on `/refresh` | Done |
| 1.2 | Default HTML export without `full_body` (opt-in flag) | Done |
| 1.3 | `chmod 600/700` DBs/vault/backups; secure create modes | Done |
| 1.4 | Encrypt backup tarballs before rclone | Done |
| 1.5 | `auto_extract_enabled` default **false** | Done |
| 1.6 | Gate `patch_core` (`core_memory_writable` config) | Done |
| 1.7 | Prefetch source denylist + instruction-marker strip on remember | Done |
| 1.8 | Fix LIKE domain parentheses | Done |
| 1.9 | Verify no public listener; health checks | Done |

## Phase 2 — Architectural

- Sensitivity tiers; audit_log; privileged-tool policy
- Pending-facts for auto-extract; transactional dual-write
- Pin vault paths (no Obsidian fallback in plugin)
- SSRF DNS+IP recheck; reinforce decoupling
- Runtime encryption design (SQLCipher spike)
- Config save merge-safe

## Phase 3 — Testing & validation

- Security test pack (path, FTS, SSRF, fence, PII, consolidate)
- Adversarial poisoned-fact suite
- Backup restore game day
- Exposure scan in health check
- CI regression + benchmarks

---

## Verification (Phase 1 gates)

1. `ss` shows graph on `127.0.0.1` only  
2. Unauthenticated `/refresh` returns 401 without token  
3. Default `graph.html` has no `full_body` fields  
4. DBs/backups not world-readable  
5. Remote backup is `.enc` ciphertext  
6. No new `auto_extracted` facts unless explicitly enabled  
7. `patch_core` blocked when `core_memory_writable=false`  
8. Domain LIKE filter unit test passes  
9. Targeted pytest green  

---

## Non-goals (Phase 1)

- Enabling whole-DB offline encrypt on live Hermes path (would take memory offline)
- Deleting Mnemosyne / sole-provider promotion gate
- Full audit_log schema (Phase 2)
