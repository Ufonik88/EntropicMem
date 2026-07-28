# Spike: Runtime DB Encryption (SQLCipher)

**Status:** Design only (Phase 2) — not implemented in 2.1.6  
**Date:** 2026-07-28

## Problem

Offline Fernet whole-file encrypt (`security.py`) is incompatible with always-on Hermes:
the DB must be plaintext while the agent runs. Disk theft / backup leakage remain risks
mitigated today by FS modes + encrypted backup archives.

## Options

| Approach | Pros | Cons |
|----------|------|------|
| **SQLCipher** | Transparent page encryption, mature | Native dep, key management, WAL complexity |
| **App-level field AES-GCM** | Stdlib+cryptography, selective fields | Breaks FTS on ciphertext; need blind index |
| **dm-crypt/fscrypt volume** | OS-level, zero app change | Host/ops dependent |

## Recommended path (future)

1. Keep encrypted **backups** as primary control (done in 2.1.6).
2. Optional SQLCipher build extra `entropicmem[sqlcipher]` when:
   - fact count > 5k **or** multi-user host
   - key unlocked once per session via VaultKnox / keyring into env `ENTROPICMEM_DB_KEY`
3. Migration: export capsule → import into SQLCipher DB; dual-run integrity check.
4. FTS remains inside encrypted pages (SQLCipher advantage over field encryption).

## Non-goals now

- Do not enable offline full-tree encrypt on the live Hermes path.
- Do not store passphrase beside DB without OS keyring.

## Exit criteria for implementation PR

- [ ] Open/close with key; wrong key fails closed
- [ ] WAL + concurrent Hermes sessions
- [ ] Backup/restore of encrypted DB
- [ ] Perf: prefetch p95 ≤ +15% vs plaintext baseline
