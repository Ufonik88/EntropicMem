# EntropicMem: next steps (one chunk at a time)

**Updated:** 2026-09-29, Chunk 3.2 landed; **Chunk 4 is the next piece**. **Read first:** `docs/plan/REMAINING_PLAN.md` (its §3 rules apply to everything here), then `AGENTS.md` and `docs/V3_FOUNDATIONS.md`.

**Plan exactly one chunk.** When a chunk ends, replace this file with the plan for the next single chunk; never more than one ahead.

---

## Part A: what has landed

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

**The EM-210 gaps are both closed.** EntropicMem is at rest: feature work stays stopped until the owner starts Chunk 4.

---

## Part B: Chunk 4 — EM-211's facade reads. **NEXT PIECE, NOT STARTED**

**Topic:** the first quarter of EM-211, the legacy facade on v3.

**Why this chunk.** EM-211 is the last card before the provider can run on v3, and the plan says outright that it is too big for one chunk: *"Too big for one chunk. Split it into facade reads, then writes, then mirror, then linker."* The read half is what the provider needs first, and it can be verified without touching a write path, so it goes first.

**What the card requires (plan §6, EM-211).** `memory_engine.MemoryEngine` keeps its public method names and signatures, implemented over `MemoryStore`/`EpisodeStore`/`EntityStore`, and returns `StoredFact` built from `Memory` (id = `legacy_id` if present, else a new id). The card is done only when the engine is added to `ENGINES` in `tests/parity/test_engine_parity.py` **and** to `_implementations()` in `tests/unit/test_em_facade_contract.py`, with both passing **unchanged**.

**In scope for Chunk 4 (reads only).**
- The read half of `LegacyEngine` (`em/facade/contract.py`) over `em.store`: `get_fact`, `stats`, `recall_with_relevance`, `recall_hybrid`, `next_episode_wave`, and whatever the two parity harnesses need in order to construct the engine.
- `get_fact(StoredFact.make_id(content))` must resolve. That is the `legacy_id` requirement: `remember` stores `sha256(content)[:16]` as `legacy_id`. The write half of that pairing belongs to the writes chunk; Chunk 4 needs the read half plus the fixture that proves it.
- Register the engine in both parity lists and get the read-path assertions green.

**Out of scope, in the order they land later:** the writes (`remember`, `forget`, `touch`, `extract_and_store`, `prune_pending`, `add_episode`, `consolidate`), then the mirror call (replace the raw `engine.db` read in `_locate_mirror` with an engine method on both engines, then drop `db` from `PROVIDER_ATTRIBUTES`), then `EntityLinker` from a `link:<memory_id>:<version>` job, and with it the §3.5 owner-only rule for sensitive rows and the gateway identity that needs.

**Size:** not yet measured. Chunk 4's first act is the read-only recon in 4.0.3, which produces the number before any code is written. The split basis: the read methods are `em.store` lookups with no transaction-scope risk, while the write half carries the `legacy_id` write, the supersede semantics and the deprecation warnings. If the read parity assertions turn out to need a write path (a fixture that must `remember` before it can read), say so in the recon and split that fixture out rather than pulling the writes chunk forward.

### 4.0 Pre-flight (read-only)
1. `main` must contain `e058e93be` (Chunk 3.2), and `35a02f4` must be an ancestor of `main`.
2. **Baseline:** `env -u ENTROPICMEM_MEMORY_DB -u ENTROPICMEM_VAULT_PATH -u ENTROPICMEM_INDEX_DB ENTROPICMEM_REQUIRE_PRIVACY_DIGESTS=1 python -m pytest -q` gives **1519 passed, 2 skipped, 4 xfailed**. `ruff check .` is clean under the CI pin `ruff==0.16.2`. If the numbers differ, read `REMAINING_PLAN.md` §11 before stopping: the total is expected to rise with every card.
3. **Measure the chunk from the code** and write the number into this file before writing a test: `em/facade/contract.py`, the v2 `memory_engine` it mirrors, `tests/unit/test_em_facade_contract.py`, `tests/parity/test_engine_parity.py`, and the callers of the read methods inside the provider.

### 4.1 The facade reads (one commit, test first)
- Test first: the read methods, the `legacy_id` lookup, and the engine registered in both parity lists.
- Mutation-check the `legacy_id` lookup and every guard the parity tests pin.
- **Docs:** CHANGELOG; the EM-211 rows in `REMAINING_PLAN.md` §6.1 and `docs/V3_FOUNDATIONS.md` say the reads are done and the rest is split.

### 4.2 End of chunk
1. Push a branch. Wait for green CI on the exact SHA (`windows-import` included), then fast-forward `main` and delete the branch.
2. **Update `docs/plan/REMAINING_PLAN.md`:** §2 (SHA, counts), §5 (ledger), §6.1, §9, §11 (state table, next piece, counts).
3. **Replace this file's Part B with Chunk 5: EM-211's facade writes.**
4. Report to the owner in plain language, and update MASTER_TODO.

### Explicitly out of scope for Chunk 4
- **Any provider wiring, or a provider behaviour change of any kind.** The facade is added and tested, not switched on.
- The rest of EM-211 (writes, mirror, linker) and the §3.5 owner-only rule for sensitive rows.
- Any schema change or new migration; `0001`–`0003` stay untouched.
- Retention (settled at 7 routine + 5 safety), the EM-212 package move, S3 and later, the v3 cutover, releases, tags and the catalog, and the tool rename.
- Anything touching `~/.hermes/entropicmem*`.