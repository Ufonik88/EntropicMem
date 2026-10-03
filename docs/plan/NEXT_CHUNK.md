# EntropicMem: next steps (one chunk at a time)

**Updated:** 2026-10-03, Chunk 4 landed; **Chunk 5 is the next piece**. **Read first:** `docs/plan/REMAINING_PLAN.md` (its §3 rules apply to everything here), then `AGENTS.md` and `docs/V3_FOUNDATIONS.md`.

**Plan exactly one chunk.** When a chunk ends, replace this file with the plan for the next single chunk; never more than one ahead.

---

## Part A: what has landed


### Chunk 4 — EM-211's facade reads. **DONE (2026-10-03, `0349b7b4b`)**

- `feat(em-211): the facade's read half over the v3 store (Chunk 4)`: `V3Engine` in `em/facade/engine.py` implements the read half of the provider-facing `LegacyEngine` contract over `em.store` — `get_fact` (resolving the v3 id, a unique id prefix, and the load-bearing `legacy_id`, so `get_fact(StoredFact.make_id(content))` finds what the migration and the future `remember` stamp), `stats`, `recall_with_relevance`, `recall_hybrid`, `next_episode_wave`. Recall reuses v2's scoring helpers through a **lazy** `memory_engine` import, because at 3.0 that module becomes a shim over this facade and a top-level import would be a cycle.
- The plan §4.0.3 recon was right: the parity fixtures did need a write path, so the **seed fixture was split** rather than pulling the writes chunk forward. Read-path scenarios now run on both engines via a `_remember` dispatch that falls back to `MemoryStore.add` (legacy-stamped); `WRITE_ENGINES` keeps write scenarios v2-only. **No assertion changed.**
- Registered in both harnesses: `ENGINES["v3-facade"]` and `_implementations()`. The 7 write methods are correctly-shaped `NotImplementedError` stubs, so the contract binds and the facade is testable while still unwired.
- 17 new tests (`tests/unit/test_em_facade_engine.py`), mutation-checked in both directions on the `legacy_id` rule, the deleted-row hide, the recall status filter, the `stats` active-only count, the tags JSON parse and the wave `+1`.
- Gates: **1542 passed / 2 skipped / 4 xfailed** (1519 baseline + 17 unit + 5 parity params + 1 contract param), `ruff==0.16.2` clean, eval gate vs `v2.8.0-ci.json` with no gated metric regressed. CI green on the exact SHA including `identity-guard`.
- Landed by fast-forward as PR #6; branch deleted; remote back to `main` + `release/2.8.x`.
- **em-qa review: APPROVED** with recorded caveats (see plan §5): the card's whole AC is *not* met by Chunk 4 — the facade is unwired and the writes are stubs — and Chunk 4 alone does not satisfy the S2 exit criteria.

### Chunk 3.2 — the once-per-hour-per-reason throttle. **DONE (2026-09-29, `e058e93be`)**

- `feat(em-210): throttle routine snapshots to one per reason per hour`: `BackupManager.snapshot_if_due(reason, *, window=3600.0, conn=None)` writes a snapshot only when that reason has had none inside the window, and returns `None` while the newest one is still young. That is EM-210's acceptance criterion: 100 `forget` calls inside one hour write exactly one snapshot.
- The window is derived from the `created_at` every manifest already carries (both layouts, a legacy flat backup included), so there is **no new table, no bookkeeping file and no migration**. Reasons are independent: a `forget` snapshot never suppresses a `prune` one.
- `snapshot()` and `create()` stay unthrottled on purpose: the migration hook, the daily job through `make_backup_handler` and the tests keep taking a snapshot every time they ask for one. The throttled entry point is the new call.
- Two exemptions, decided here and written down: **safety reasons** (`SAFETY_PREFIXES`: `pre-migrate*`, `pre-restore*`) are never throttled, because a stale copy before a migration or a restore is a data risk rather than noise, and **a `window` of zero or less** never throttles. A clock moved backwards leaves the age negative, which still counts as inside the window, and an unreadable `created_at` does not block a real backup.
- 10 new tests (47 in `tests/unit/test_em_backup.py`). Three guards mutation-checked in both directions, each red for the right reason with the tree restored byte-identical: the window comparison, the zero/negative-window exemption, and the safety-reason exemption.
- Gates: **1519 passed / 2 skipped / 4 xfailed** (1509 baseline + the 10 new), `ruff check .` clean under the CI pin `ruff==0.16.2`. The live store did not move across the run: 1628 facts with newest `2026-09-29T09:45:11Z`, before and after.
- **Retention is settled:** 7 routine + 5 safety stays, decided 2026-09-29 at the owner's instruction to stop asking, recorded in plan §9 and in the EM-210 row of the deviation table.

### Chunk 3.1 — `snapshot()` covering both databases. **DONE (2026-09-29, `2d60cccfb`)**

- `feat(em-210): snapshot directories covering both databases`: `snapshot(reason) -> Path` writes `backups/<reason>-<stamp>/` holding `memory.db`, `index.db` when it exists, and a `manifest.json` that lists every file with its role, source name, sha256, size, row counts and `user_version`; `create()` stays as an alias for its three callers. Restore stages every file and swaps only when all of them verify; a snapshot without an index never touches the live one; rotation counts both layouts; pre-3.1 flat backups stay readable, verifiable and restorable.
- 14 new tests. The per-file hash check and the index-inclusion branch were mutation-checked (each went red for the right reason, file restored byte-identical).
- Gates: 1509 passed / 2 skipped / 4 xfailed (1495 + the 14 new), `ruff check .` clean under the CI pin `ruff==0.16.2`.
- Layout-contract updates were required in five existing tests (snapshot name, `is_dir()`, per-file manifest reads, rotation count, tamper target) plus the two migration tests that globbed for `pre-migrate-*.db`. One **vacuous** test was fixed on the way: `test_noop_migrate_writes_no_backup` globbed `*.db`, which after this change matched nothing and would have passed no matter what.
- Budget: landed inside its written scope; the size guard was not needed (restore's dual-layout handling fitted in the listed tests).

### Chunk 2 — `entropicmem worker run`. **DONE (2026-09-29, `8fca999de`)**

- `entropicmem worker run` (EM-209's missing CLI), plus the EM-209/EM-210 deviation record; both safety guards mutation-checked by the reviewer; CI green on the exact SHA; 1467 passed / 2 skipped / 4 xfailed at the time.
- Same day, a no-bump hygiene batch (`8202081af`) and a docs pass that added plan §11 (`1a4e57235`). Details in plan §2 and §5.

**The EM-210 gaps are both closed, and Chunk 4 has landed.** Feature work stays stopped until the owner starts Chunk 5.

---

## Part B: Chunk 5 — EM-211's facade writes. **NEXT PIECE, NOT STARTED**

**Topic:** the second quarter of EM-211, the legacy facade on v3.

**Why this chunk.** Chunk 4 landed the read half and left 7 write methods as `NotImplementedError` stubs in `em/facade/engine.py`. The parity harness already carries `WRITE_ENGINES = {"v2": _v2}` with a comment saying Chunk 5 adds `"v3-facade"` to it and collapses the `_remember` dispatch — so the exit is pre-written into the harness. The write half is what makes the facade usable rather than merely inspectable, and it is the last code the provider needs before it can run on v3.

**What the card requires (plan §6, EM-211).** `memory_engine.MemoryEngine` keeps its public method names and signatures, implemented over `MemoryStore`/`EpisodeStore`/`EntityStore`, returning `StoredFact` built from `Memory` (id = `legacy_id` if present, else a new id).

**Measured from the code (this is the size guard).**

| Method | v2 body (`memory_engine.py`) | Backing store API (already exists) |
|---|---|---|
| `remember` | L921–1121, **201 lines** | `MemoryStore.add` / `_add_as_live` / `_add_as_pending` |
| `consolidate` | L1222–1360, **139 lines** | `MemoryStore.list` / `set_status` / `touch` |
| `extract_and_store` | L1811–1873, **63 lines** | `MemoryStore.add` + formation |
| `forget` | L1163–1221, **59 lines** | `MemoryStore.set_status` / `purge` |
| `add_episode` | L2313–2361, **49 lines** | `EpisodeStore.add_episode` / `upsert_episode` |
| `prune_pending` | L900–920, **21 lines** | `MemoryStore.list` + `set_status` |
| `touch` | L2002–2015, **14 lines** | `MemoryStore.touch` |
| **Total** | **546 lines** | |

546 lines of v2 write logic is the number to beat. Every backing call already exists, so the work is translation and semantics — not new store features. If the chunk starts growing toward that 546 rather than shrinking beneath it, the store is not carrying its share and the chunk must be split (remember alone, then the rest).

**In scope for Chunk 5 (writes only).**
- All 7 stubs: `remember`, `forget`, `touch`, `extract_and_store`, `prune_pending`, `add_episode`, `consolidate`.
- **`remember` is the load-bearing one.** It must write `legacy_id = sha256(content)[:16]` — the read half in Chunk 4 already resolves it, and `get_fact(StoredFact.make_id(content))` is the parity assertion that proves the pair. This is the whole reason the fixture was split in Chunk 4.
- Supersede semantics and the v2 deprecation warnings must match v2 behaviour; the parity suite is the arbiter.
- Add `"v3-facade"` to `WRITE_ENGINES` in `tests/parity/test_engine_parity.py` and collapse the `_remember` dispatch so seeding goes through the engine for both engines.
- `extract_and_store` may lean on formation, but no LLM call is added or changed.

**Out of scope, in the order they land later:** the mirror call (replace the raw `engine.db` read in `_locate_mirror` with an engine method on both engines, then drop `db` from `PROVIDER_ATTRIBUTES`), then `EntityLinker` from a `link:<memory_id>:<version>` job, and with it the §3.5 owner-only rule for sensitive rows and the gateway identity that needs.

**Known gaps to close in this chunk (from em-qa's Chunk 4 review):**
- `get_fact`/recall currently read with no scope filter (profile-wide). The §3.5 owner-only rule for sensitive rows is deferred and documented in `docs/V3_FOUNDATIONS.md`; the write half is where `owner` is actually set on write, so scope must be handled here rather than deferred twice.

### 5.0 Pre-flight (read-only)
1. `main` must contain `1b5c71ccf` (Chunk 4 + the contributor's vault fix), and `35a02f4` must be an ancestor of `main`.
2. **Baseline:** `env -u ENTROPICMEM_MEMORY_DB -u ENTROPICMEM_VAULT_PATH -u ENTROPICMEM_INDEX_DB ENTROPICMEM_REQUIRE_PRIVACY_DIGESTS=1 python -m pytest -q` gives **1542 passed, 2 skipped, 4 xfailed**. `ruff check .` is clean under the CI pin `ruff==0.16.2`. If the numbers differ, read `REMAINING_PLAN.md` §11 before stopping: the total is expected to rise with every card.
3. **Re-measure the write methods from the code before writing a test** — the table above is from `main` at `1b5c71ccf`; if `memory_engine.py` moved, recompute.

### 5.1 The facade writes (one commit, test first)
- Test first: `remember`'s `legacy_id` round-trip against `get_fact(StoredFact.make_id(content))`, the supersede semantics, the deprecation warnings, and every parity scenario flipping to run against `v3-facade`.
- Mutation-check the `legacy_id` write, the supersede path, and the forget/`set_status` mapping.
- **Docs:** CHANGELOG; the EM-211 rows in `REMAINING_PLAN.md` §6.1 and `docs/V3_FOUNDATIONS.md`.

### 5.2 End of chunk
1. Push a branch. Wait for green CI on the exact SHA (`windows-import` included), then fast-forward `main` and delete the branch.
2. **Update `docs/plan/REMAINING_PLAN.md`:** §2 (SHA, counts), §5 (ledger), §6.1, §9, §11 (state table, next piece, counts).
3. **Replace this file's Part B with Chunk 6: EM-211's mirror call** (then Chunk 7, the linker, completes EM-211).
4. Report to the owner in plain language, and update MASTER_TODO.

### Explicitly out of scope for Chunk 5
- **Any provider wiring, or a provider behaviour change of any kind.** The facade is completed and tested, not switched on.
- The mirror call, the linker, and the §3.5 owner-only rule beyond setting `owner` correctly on write.
- Any schema change or new migration; `0001`–`0003` stay untouched.
- Retention (settled at 7 routine + 5 safety), the EM-212 package move, S3 and later, the v3 cutover, releases, tags and the catalog, and the tool rename.
- Anything touching `~/.hermes/entropicmem*`.
