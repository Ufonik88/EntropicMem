# EntropicMem: next steps (one chunk at a time)

**Updated:** 2026-09-29, Chunk 3.1 landed; **Chunk 3.2 is the next piece**. **Read first:** `docs/plan/REMAINING_PLAN.md` (its §3 rules apply to everything here), then `AGENTS.md` and `docs/V3_FOUNDATIONS.md`.

**Plan exactly one chunk.** When a chunk ends, replace this file with the plan for the next single chunk; never more than one ahead.

---

## Part A: what has landed

### Chunk 3.1 — `snapshot()` covering both databases. **DONE (2026-09-29, `2d60cccfb`)**

- `feat(em-210): snapshot directories covering both databases`: `snapshot(reason) -> Path` writes `backups/<reason>-<stamp>/` holding `memory.db`, `index.db` when it exists, and a `manifest.json` that lists every file with its role, source name, sha256, size, row counts and `user_version`; `create()` stays as an alias for its three callers. Restore stages every file and swaps only when all of them verify; a snapshot without an index never touches the live one; rotation counts both layouts; pre-3.1 flat backups stay readable, verifiable and restorable.
- 14 new tests. The per-file hash check and the index-inclusion branch were mutation-checked (each went red for the right reason, file restored byte-identical).
- Gates: 1509 passed / 2 skipped / 4 xfailed (1495 + the 14 new), `ruff check .` clean under the CI pin `ruff==0.16.2`.
- Layout-contract updates were required in five existing tests (snapshot name, `is_dir()`, per-file manifest reads, rotation count, tamper target) plus the two migration tests that globbed for `pre-migrate-*.db`. One **vacuous** test was fixed on the way: `test_noop_migrate_writes_no_backup` globbed `*.db`, which after this change matched nothing and would have passed no matter what.
- Budget: landed inside its written scope; the size guard was not needed (restore's dual-layout handling fitted in the listed tests).

### Chunk 2 — `entropicmem worker run`. **DONE (2026-09-29, `8fca999de`)**

- `entropicmem worker run` (EM-209's missing CLI), plus the EM-209/EM-210 deviation record; both safety guards mutation-checked by the reviewer; CI green on the exact SHA; 1467 passed / 2 skipped / 4 xfailed at the time.
- Same day, a no-bump hygiene batch (`8202081af`) and a docs pass that added plan §11 (`1a4e57235`). Details in plan §2 and §5.

**EntropicMem is at rest.** Feature work stays stopped until the owner starts Chunk 3.2.

---

## Part B: Chunk 3.2 — the once-per-hour-per-reason throttle. **NEXT PIECE, NOT STARTED**

**Topic:** the second half of the EM-210 plan gaps.

**Why this chunk.** The plan's EM-210 text asks that a destructive operation call `snapshot` at most once per hour per reason, not once per call, with the acceptance criterion **"100 `forget` calls → ≤ 1 snapshot/hour"**. Today every call writes a snapshot. Chunk 3.1 built what this throttles; nothing here changes what a snapshot contains.

**Size:** 45 to 60 minutes of active work, one session.

**Design note (keep it schema-free).** The last-snapshot time per reason is already recorded: every manifest in both layouts carries `created_at`, and `list()` parses them. Derive the window from that, so there is no new table, no bookkeeping file and no migration. `created_at` comes from `em.clock`, and `em.clock.freeze` already exists, so a time-travelling test needs nothing else.

**Budget:** one session, at most 2 commits (the card, then the end-of-chunk doc update). Stop at any stop condition in plan §3.1.

**Owner:** Hermes or Claude Code implements. The other reviews before merge (the owner relays the report).

### 3.2.0 Pre-flight (read-only)
1. `main` must contain `2d60cccfb` (Chunk 3.1), and `35a02f4` must be an ancestor of `main`.
2. **Baseline:** `env -u ENTROPICMEM_MEMORY_DB -u ENTROPICMEM_VAULT_PATH -u ENTROPICMEM_INDEX_DB ENTROPICMEM_REQUIRE_PRIVACY_DIGESTS=1 python -m pytest -q` gives **1509 passed, 2 skipped, 4 xfailed**. `ruff check .` is clean under the CI pin `ruff==0.16.2`. If the numbers differ, read `REMAINING_PLAN.md` §11 before stopping: the total is expected to rise with every card.

### 3.2.1 The throttle (one commit, test first)
- Add one entry point to `BackupManager` for destructive callers, e.g. `snapshot_if_due(reason, *, window=...)` returning `None` when a snapshot with the same reason is younger than the window. The exact name and signature are the implementer's call; the plan fixes the behaviour and the AC, not the spelling.
- **Do not throttle `snapshot()` or `create()`.** The migration hook, the daily job and the tests must keep taking a snapshot every time they ask for one. The throttled caller is the new entry point.
- Reasons are independent: a `pre-migrate-*` snapshot must not suppress a `pre-restore` one, or the reverse. Decide explicitly whether safety reasons are subject to the window at all, and write the decision down.
- A legacy flat snapshot counts toward the window: it carries a `created_at` and a reason like any other.
- **Tests:** 100 calls inside one frozen hour write exactly one snapshot; the next hour writes one more; two different reasons each get their own window; a reason whose newest snapshot is older than the window is allowed again; the clock can be moved back and forth without a second snapshot appearing; nothing about job or provider behaviour changes.
- Mutation-check the window comparison in both directions (a zero window must never throttle; a window longer than the test's span must write exactly one).
- **Docs:** CHANGELOG; the EM-210 row of the deviation table says the throttle is done; the `REMAINING_PLAN.md` §6.1 bullet loses its throttle line.

### 3.2.2 End of chunk
1. Push a branch. Wait for green CI on the exact SHA (`windows-import` included). The other agent reviews, then fast-forward `main` and delete the branch.
2. **Update `docs/plan/REMAINING_PLAN.md`:** §2 (SHA, counts), §5 (ledger), §6.1, §9, §11 (state table, next piece, counts).
3. **Replace this file's Part B with Chunk 4: EM-211's facade reads.** Split that card before starting it: reads, then writes, then the mirror call, then the linker. Retention stays the recorded deviation unless the owner asks for EM-113's rule.
4. Report to the owner in plain language. Hermes updates MASTER_TODO. Claude Code produces a `/save` file.

### Explicitly out of scope for Chunk 3.2
- Any schema change or new migration; `0001`–`0003` stay untouched.
- Changing what a snapshot contains, or either layout (Chunk 3.1's ground).
- **Retention.** 7 routine + 5 safety stays the recorded deviation unless the owner asks for the plan's EM-113 rule (keep 10, plus one per day for 7 days). Open in plan §9.
- Wiring the throttle into the provider or into the v2 CLI's `forget`: no provider behaviour change before EM-211's facade exists.
- The EM-211 facade, and any provider wiring to v3.
- The EM-212 package move (a larger card: split before starting).
- The v3 cutover, or anything touching `~/.hermes/entropicmem*`.
- Releases, tags, catalog PRs and public comments.
- The tool rename (`entropicmem_patch_core` → `entropicmem_patch_core_memory`) — 3.0 only, with the release that re-pins the catalog.
- New dependencies; S3 and later.