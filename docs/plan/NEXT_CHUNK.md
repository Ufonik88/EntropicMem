# EntropicMem: next steps (one chunk at a time)

**Updated:** 2026-09-29, Chunk 2 landed. **Read first:** `docs/plan/REMAINING_PLAN.md` (its §3 rules apply to everything here), then `AGENTS.md` and `docs/V3_FOUNDATIONS.md`.

**Plan exactly one chunk.** When a chunk ends, replace this file with the plan for the next single chunk; never more than one ahead.

---

## Part A: Chunk 2 — `entropicmem worker run`. **DONE (2026-09-29)**

- `feat(em-209): add entropicmem worker run` plus the docs commits (`0cfac9d`, `dca80f4`, `ad5f0e5`, `8fca999`);
- CI green on the exact SHA, `identity-guard` included; fast-forwarded into `main`; the branch deleted (local and remote);
- 1467 passed, 2 skipped, 4 xfailed on the merged tree (the 1462 baseline plus the 5 new CLI tests); `ruff check .` clean under the CI pin `ruff==0.16.2`;
- reviewed independently before merge: both safety guards mutation-checked, and each goes red when the guard it protects is broken;
- the EM-209 wording deviations are recorded in `docs/V3_FOUNDATIONS.md` → "Recorded deviations from the plan";
- the release follow-ups this file used to hold (Part A of the previous version) are all done, as plan §4 records.

**EntropicMem is at rest again.** Feature work stays stopped until the owner schedules Chunk 3.

---

## Part B: Chunk 3, the next development chunk (only when the owner schedules it)

**Topic:** the EM-210 plan gaps — the backup manager is smaller than its card.

**Why this chunk:** EM-210 shipped as `BackupManager.create(reason) -> BackupInfo` over `memory.db` only, with flat files and a 7-routine + 5-safety retention. The plan asks for `snapshot(reason) -> Path` covering `index.db` too, in `backups/<ts>-<reason>/`, and for a destructive operation to snapshot **at most once per hour per reason**. The difference is recorded in `docs/V3_FOUNDATIONS.md`; this chunk closes it. It adds no schema and no migration, and it does not touch the provider's live path.

**Budget:** one session, at most 3 commits. Stop at any stop condition in plan §3.1.

**Owner:** Hermes or Claude Code implements. The other reviews before merge (the owner relays the report).

### 3.0 Pre-flight (read-only)
1. `main` must contain `8fca999de` (Chunk 2), and `35a02f4` must be an ancestor of `main`.
2. **Baseline:** `env -u ENTROPICMEM_MEMORY_DB -u ENTROPICMEM_VAULT_PATH -u ENTROPICMEM_INDEX_DB ENTROPICMEM_REQUIRE_PRIVACY_DIGESTS=1 python -m pytest -q` gives **1467 passed, 2 skipped, 4 xfailed**. `ruff check .` is clean (CI pins `ruff==0.16.2`). If different, stop and report.

### 3.1 `snapshot()` covering both databases (one commit, test first)
- Add the plan's name, `snapshot(reason) -> Path`. Grep the callers first (`create()` is used by the CLI, the daily job and the tests) and keep `create()` as a thin alias rather than breaking them in the same commit.
- Cover `memory.db` **and** `index.db` whenever the index exists.
- Write into `backups/<ts>-<reason>/`, with the manifest inside that directory.
- Existing flat backups stay exactly where they are: never move or delete one. Document that both layouts are readable and that restore accepts either.
- **Tests:** a snapshot holds both files; the directory is named `<ts>-<reason>/`; a store with no index still snapshots; the manifest lists every file with its hash and `verify()` passes per file; a corrupted or missing file makes `verify()` fail.
- Mutation-check the per-file hash check and the index-inclusion branch.
- **Docs:** the backup section of `docs/V3_FOUNDATIONS.md` and `docs/BACKUP_RESTORE.md` (both layouts); CHANGELOG under `### Added` / `### Changed`.

### 3.2 The once-per-hour-per-reason throttle (one commit, test first)
- The plan's AC, verbatim: **100 `forget` calls → ≤ 1 snapshot/hour.** A destructive operation calls `snapshot` at most once per hour *per reason*, not once per call.
- Implement it store-side with an injectable clock (`em.clock`) so a test can move time, and persist the last-snapshot time per reason. It must survive a restart, so a process-local variable is not enough.
- **Tests:** 100 forgets inside one hour produce exactly 1 snapshot; the next hour allows another; two different reasons each get their own allowance; a non-destructive caller is unaffected.
- Mutation-check the throttle.
- **Docs:** CHANGELOG; the EM-210 row of the deviation table flips to "closed (Chunk 3)".
- Retention stays as it is (7 routine + 5 safety) unless the owner asks for EM-113's exact rule. If it does not change, say that in the deviation table instead of leaving the difference implied.

### 3.3 End of chunk
1. Push a branch. Wait for green CI on the exact SHA (`windows-import` included). The other agent reviews, then fast-forward `main` and delete the branch.
2. **Update `docs/plan/REMAINING_PLAN.md`:** §2 (SHA, counts), §5 (ledger), §6.1 (drop the EM-210 deviation bullets), §9.
3. **Replace this file's Part B with Chunk 4.** The four no-bump candidates scouted on 2026-09-29 all landed on `main` the same day (see plan §2 and §5), so nothing is waiting there. The next real card is EM-211's facade reads, which needs splitting first.
4. Report to the owner in plain language. Hermes updates MASTER_TODO. Claude Code produces a `/save` file.

### Explicitly out of scope for Chunk 3
- Any schema change or new migration; `0001`–`0003` stay untouched.
- The EM-211 facade, and any provider wiring to v3. The throttle must not change provider behaviour before the facade exists.
- The EM-212 package move (a larger card: split before starting).
- The v3 cutover, or anything touching `~/.hermes/entropicmem*`.
- Releases, tags, catalog PRs and public comments.
- The tool rename (`entropicmem_patch_core` → `entropicmem_patch_core_memory`) — 3.0 only, with the release that re-pins the catalog.
- New dependencies; S3 and later.