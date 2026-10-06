# EntropicMem: next steps (one chunk at a time)

**Updated:** 2026-10-06, Chunk 5 committed (not yet merged); **Chunk 6 is the next piece**. **Read first:** `MASTER_TODO.md`, then `docs/plan/REMAINING_PLAN.md` (its §3 rules apply to everything here), then `AGENTS.md` and `docs/V3_FOUNDATIONS.md`.

**Plan exactly one chunk.** When a chunk ends, replace this file with the plan for the next single chunk; never more than one ahead.

---

## Part A: what has landed


### Chunk 5 — EM-211's facade writes. **DONE, COMMITTED, NOT MERGED (2026-10-06, `36355f3`)**

- `feat(em-211): the legacy facade's write half over the v3 store (Chunk 5)`: the 7 `NotImplementedError` stubs in `em/facade/engine.py` are real write paths, so `V3Engine` now implements the whole provider-facing `LegacyEngine` contract.
- **`remember` is the load-bearing one, as the plan said.** It stamps `legacy_id = sha256(content)[:16]`, which is what makes the read half's `get_fact(StoredFact.make_id(content))` resolve — the pair that proves the chunk. **One rule the plan did not anticipate:** `memories.legacy_id` is `UNIQUE` and content-derived, and v3 scopes every row to a user where v2 had one owner per database. So the stamp applies to a **profile-wide write only**; a user-scoped write leaves it empty, which is what stops two users storing the same sentence from colliding on one hash. Tested in both directions, including that two users *can* store the same sentence.
- The plan's size guard held: **283 lines of facade write code against v2's 546.** `MemoryStore.add` already carried policy, PII redaction, injection screening, exact-duplicate collapse, the version row, the sync outbox, the audit row and the queued embed job, so `remember` is translation rather than reimplementation. The one store change needed was `legacy_id` on `MemoryDraft` and in `_insert` (the migration already stamps that column; nothing in the store could *write* it through the draft).
- **`forget` and `consolidate` are §3.4 status transitions**, not deletes and not a side `facts_archive` copy. `get_fact` reads a terminal row as absent and `stats` leaves it out of the live count, so callers see v2's behaviour while the row and its versions stay for the audit trail. `forget(id, confirm=True)` returns `False` the second time, as v2's DELETE reported.
- **EM-210's acceptance criterion is now met through the facade too.** Both destructive paths call `snapshot_if_due(reason="pre-forget"/"pre-consolidate")`, *outside* the write transaction per §3.3. A test writes 5 memories, forgets all 5 and asserts the backup directory holds exactly one snapshot.
- `extract_and_store` quarantines each candidate into `pending` (the write policy routes an `auto_extracted` source there) and promotes over the `pending -> active` edge when asked — one versioned row instead of v2's two, and the extraction record is the same row. No LLM call added or changed.
- `add_episode` stamps `episodes.legacy_id`, which is what `next_episode_wave` reads, so the cadence numbering survives the cutover. A refired `episode_id` upserts in place (the provider derives it from the session id and refires it); with no session key the episode is `manual`.
- **The parity harness is single-path now:** `v3-facade` joined `WRITE_ENGINES`, the `_remember` dispatch and its `NotImplementedError` fallback are **deleted**, and **6 write-path scenarios run against both engines on their full API. No assertion changed.**
- 56 new tests (`tests/unit/test_em_facade_engine.py`'s stub test was rewritten as a shape test, since the stubs are gone) + 6 new parity params. Twelve mutation checks, each red for the right reason with the tree restored byte-identical.
- Gates: **1604 passed / 3 skipped / 4 xfailed** at the code commit (1542 + 56 + 6), `ruff==0.16.2` clean, eval gate vs `v2.8.0-ci.json` with no gated metric regressed, `perf-smoke` warm p95 3.693 ms against the unchanged 20 ms budget, `tests/unit` green standalone for the `windows-import` job. **1609** after the document-control guard added its 5 tests.
- **Document control ran under the new rule:** `MASTER_TODO.md` was created (the plan had been pointing at one that lived only in a single agent's private memory, unreadable by the next), `AGENTS.md` gained the "Document control — first and last" section, and `tests/test_master_todo.py` enforces it — 6 mutation checks, each red for the right reason.
- **The card's whole AC is still NOT met and S2's exit criteria still fail**, for the same reason as after Chunk 4: the facade is complete but unwired, and the provider still runs v2.
- **Not merged.** `em/em-211-facade-writes` is unpushed and no CI has run for it, so `origin/main` is still `03772e3`. To finish: push, wait for green CI on `d055b74`, `git merge --ff-only`, delete the branch, then correct the "DONE" markers here and in `MASTER_TODO.md`.

### Chunk 4 — EM-211's facade reads. **DONE (2026-10-03, `0349b7b4b`)**

- `feat(em-211): the facade's read half over the v3 store (Chunk 4)`: `V3Engine` in `em/facade/engine.py` implements the read half of the provider-facing `LegacyEngine` contract over `em.store` — `get_fact` (resolving the v3 id, a unique id prefix, and the load-bearing `legacy_id`, so `get_fact(StoredFact.make_id(content))` finds what the migration and the future `remember` stamp), `stats`, `recall_with_relevance`, `recall_hybrid`, `next_episode_wave`. Recall reuses v2's scoring helpers through a **lazy** `memory_engine` import, because at 3.0 that module becomes a shim over this facade and a top-level import would be a cycle.
- The plan §4.0.3 recon was right: the parity fixtures did need a write path, so the **seed fixture was split** rather than pulling the writes chunk forward. That split is now closed (Chunk 5).
- Registered in both harnesses: `ENGINES["v3-facade"]` and `_implementations()`.
- 17 new tests (`tests/unit/test_em_facade_engine.py`), mutation-checked in both directions on the `legacy_id` rule, the deleted-row hide, the recall status filter, the `stats` active-only count, the tags JSON parse and the wave `+1`.
- Gates: **1542 passed / 2 skipped / 4 xfailed**, `ruff==0.16.2` clean, eval gate clean. CI green on the exact SHA including `identity-guard`.
- Landed by fast-forward as PR #6; branch deleted; remote back to `main` + `release/2.8.x`.
- **em-qa review: APPROVED** with recorded caveats (see plan §5): the card's whole AC is *not* met by Chunk 4 — the facade is unwired and the writes are stubs — and Chunk 4 alone does not satisfy the S2 exit criteria.

### Chunk 3.2 — the once-per-hour-per-reason throttle. **DONE (2026-09-29, `e058e93be`)**

- `feat(em-210): throttle routine snapshots to one per reason per hour`: `BackupManager.snapshot_if_due(reason, *, window=3600.0, conn=None)` writes a snapshot only when that reason has had none inside the window. Two exemptions, decided and tested: safety reasons (`pre-migrate*`, `pre-restore*`) are never throttled, and a `window` of zero or less never throttles.
- 10 new tests (47 in `tests/unit/test_em_backup.py`); three guards mutation-checked in both directions.
- **Retention is settled:** 7 routine + 5 safety stays, decided 2026-09-29 at the owner's instruction to stop asking.

### Chunk 3.1 — `snapshot()` covering both databases. **DONE (2026-09-29, `2d60cccfb`)**

- `feat(em-210): snapshot directories covering both databases`: `snapshot(reason) -> Path` writes `backups/<reason>-<stamp>/` holding `memory.db`, `index.db` when it exists, and a `manifest.json`. Restore stages every file and swaps only when all of them verify.
- 14 new tests; layout-contract updates in five existing tests plus two migration tests. One **vacuous** test was fixed on the way.

### Chunk 2 — `entropicmem worker run`. **DONE (2026-09-29, `8fca999de`)**

- `entropicmem worker run` (EM-209's missing CLI), plus the EM-209/EM-210 deviation record; 1467 passed / 2 skipped / 4 xfailed at the time.

**The EM-210 gaps are both closed. EM-211 is half done (reads and writes).** Feature work stays stopped until the owner starts Chunk 6.

---

## Part B: Chunk 6 — EM-211's mirror call. **NEXT PIECE, NOT STARTED**

**Topic:** the third quarter of EM-211: the one raw database access the provider still makes.

**Why this chunk.** `_locate_mirror` in `plugins/entropicmem/__init__.py` runs a literal `SELECT id, content, tags FROM facts` against `engine.db`, the v2 engine's raw `sqlite3.Connection`. A v3 facade cannot offer a `facts` table, so this is the **last thing in the provider that a v3 engine cannot serve**. It is also recorded as an open behaviour:

> `BEHAVIOURS["mirror-scan"]`: OPEN (EM-211): `_locate_mirror`'s fallback reads `engine.db` directly. Add an engine method, `find_mirrored(needle) -> Optional[str]`, to BOTH engines, switch the provider to it, and drop `'db'` from `PROVIDER_ATTRIBUTES`.

**In scope for Chunk 6.**
- Add `find_mirrored(needle) -> Optional[str]` to **both** `memory_engine.MemoryEngine` (v2) and `em.facade.engine.V3Engine`, with matching semantics. The parity suite is the arbiter.
- Switch `_locate_mirror` to call it. The `StoredFact.make_id(previous_content)` fast path already goes through `get_fact` and is **unchanged** — only the substring fallback moves.
- Record `find_mirrored` in `PROVIDER_CALLS` and drop `db` from `PROVIDER_ATTRIBUTES`. **Both** halves matter: the contract test re-derives `PROVIDER_CALLS` from the provider's source by AST scan, so it will fail until the method is listed, and it separately asserts every registered engine accepts every recorded call.
- Move `BEHAVIOURS["mirror-scan"]` from an open item to a cited behaviour with a parity test, and remove `mirror-scan` from `open_items` in `test_every_behaviour_is_covered`. **That last one is the chunk's exit signal: no open items left.**
- v3 semantics to decide and record: the fallback matches `old_text` as a substring against mirrored rows. On v3 that means `content LIKE '%needle%'` over `memories` **scoped** (invariant 5) and filtered to `status='active'`, with the `mirrored` tag as v2 requires. A deleted row must not match — the provider's replace/remove path would otherwise locate a forgotten mirror.

**Out of scope.**
- **Any provider wiring beyond this one call.** The facade stays unwired; the provider still constructs `MemoryEngine`.
- The `EntityLinker` job and the §3.5 owner-only rule — that is Chunk 7.
- EM-212's package move, S3 and later, the v3 cutover, releases, tags, the catalog, the tool rename.
- Any schema change or new migration; `0001`–`0003` stay untouched.
- Anything touching `~/.hermes/entropicmem*`.

**Known gaps to carry in.**
- `get_fact`/recall read with no scope filter (profile-wide). The §3.5 owner-only rule for sensitive rows is deferred to the linker chunk and documented in `docs/V3_FOUNDATIONS.md`. Chunk 5 set `owner` correctly on write, so scope is now handled on the write side; the read side still waits on the gateway identity.
- The `engine.db` attribute stays in `PROVIDER_ATTRIBUTES` until *both* engines serve the method. Removing it early breaks the contract test in a way that looks like a facade bug.

### 6.0 Pre-flight (read-only)
1. `main` must contain `1b5c71ccf`, `35a02f4` must be an ancestor of `main`, and `34 9b7b4` (Chunk 4) plus the Chunk 5 commit must be present.
2. **Baseline:** `env -u ENTROPICMEM_MEMORY_DB -u ENTROPICMEM_VAULT_PATH -u ENTROPICMEM_INDEX_DB python3 -m pytest -q` gives **1609 passed, 3 skipped, 4 xfailed** (2 skipped instead of 3 on a machine that has the private digest list — read the two counts as a pair, see plan §11). `ruff check .` is clean under the CI pin `ruff==0.16.2`. If the numbers differ, read `REMAINING_PLAN.md` §11 before stopping: the total is expected to rise with every card.
3. **Re-measure from the code before writing a test.** Read `_locate_mirror` in `plugins/entropicmem/__init__.py` (it has moved at least once), the `PROVIDER_ATTRIBUTES` assertion in `tests/unit/test_em_facade_contract.py`, and the `mirror-scan` entry in `em/facade/contract.py`.

### 6.0a Document control (do this before and after the chunk)
Per `AGENTS.md`: reconcile `MASTER_TODO.md`, `REMAINING_PLAN.md` and this file
**before** starting and **again before finishing**. The file to update at the
end is whichever of the three your chunk changed the truth of — and the merge
state counts as truth, so a chunk that commits without CI merged is recorded as
"committed, not merged", never as "landed". `tests/test_master_todo.py` fails
the suite if the status page and the plan disagree about that.

### 6.1 The mirror call (one commit, test first)
- Test first: `find_mirrored` on both engines (found / not found / empty needle / a deleted row must not match / a non-mirrored row must not match), then the parity scenario for `mirror-scan`, then the contract-test change.
- Mutation-check: the `status='active'` filter, the scope filter, the `mirrored` tag filter, and the `db`-attribute removal (the contract test must go red if `db` is still listed or still read).
- **Docs:** CHANGELOG; the EM-211 rows in `REMAINING_PLAN.md` §5, §6.1 and §11; the EM-211 entry in `docs/V3_FOUNDATIONS.md`.

### 6.2 End of chunk
1. Push a branch. Wait for green CI on the exact SHA (`windows-import` included), then fast-forward `main` and delete the branch.
2. **Update `docs/plan/REMAINING_PLAN.md`:** §2 (SHA, counts), §5 (ledger), §6.1, §9, §11 (state table, next piece, counts).
3. **Replace this file's Part B with Chunk 7: the `EntityLinker` job** (which completes EM-211 and carries the §3.5 owner-only rule).
4. Report to the owner in plain language.

### Explicitly out of scope for Chunk 6
- **Switching the provider onto the facade.** The facade is completed and tested, not switched on.
- The linker, and the §3.5 owner-only rule for sensitive rows.
- Any schema change or new migration; `0001`–`0003` stay untouched.
- Retention (settled at 7 routine + 5 safety), the EM-212 package move, S3 and later, the v3 cutover, releases, tags and the catalog, and the tool rename.
- Anything touching `~/.hermes/entropicmem*`.
