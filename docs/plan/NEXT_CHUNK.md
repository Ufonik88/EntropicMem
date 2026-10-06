# EntropicMem: next steps (one chunk at a time)

**Updated:** 2026-10-06, Chunk 7.1 merged to `main` at `64a2685`; **Chunk 7.2 is the next piece**. **Read first:** `MASTER_TODO.md`, then `docs/plan/REMAINING_PLAN.md` (its §3 rules apply to everything here), then `AGENTS.md` and `docs/V3_FOUNDATIONS.md`.

**Plan exactly one chunk.** When a chunk ends, replace this file with the plan for the next single chunk; never more than one ahead.

---

## Part A: what has landed


### Chunk 5 — EM-211's facade writes. **DONE, MERGED (2026-10-06, `36355f3`, in `e25db32`)**

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
- **Merged** to `main` at `e25db32` after green CI on that exact SHA; branch deleted. The first CI run had been red on two real defects — a Python-3.10-only `Z`-timestamp parse failure and the doc guard failing under a shallow checkout — both fixed in the same merge. 1626 passed on both 3.10 and 3.12.

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

### Chunk 6 — EM-211's mirror call. **DONE, MERGED (2026-10-06, `6bd4b47`, in `e25db32`)**

- `feat(em-211): find_mirrored on both engines; the provider stops reading engine.db (Chunk 6)`: `_locate_mirror` ran `SELECT id, content, tags FROM facts` against `engine.db` — the provider's last raw-connection read, and the one thing a v3 facade could not serve. Both engines now answer `find_mirrored(needle) -> Optional[str]`, the provider calls that, and **`PROVIDER_ATTRIBUTES` is empty**.
- `BEHAVIOURS["mirror-scan"]` moves from the last OPEN item to a cited behaviour with five parity scenarios, and `open_items` in `test_every_behaviour_is_covered` is now an empty set — the exit signal the plan named.
- v2's implementation is the scan that was in the provider, moved behind a method. v3's adds the three filters v2 got for free: `status='active'` (a forgotten mirror must not be locatable, or a replace resurrects it), the §3.5 scope rule (invariant 5), and `mirrored` as a whole tag — where the quoted JSON `LIKE` is only a pre-filter and the **parsed list** decides, and the parse must insist on a list because the JSON scalar `"mirrored"` would pass both.
- The `make_id(previous_content)` fast path is unchanged; only the substring fallback moved. The facade is still **not wired into the provider**.
- 15 new tests (5 parity scenarios × 2 engines, 5 v3 unit). Nine mutation checks, each red for the right reason with the tree restored byte-identical.
- **One escaped mutation was worth keeping.** Dropping v3's whole-tag check stayed green, because the quoted pre-filter already excludes `mirrored-archive` — so the parity test was passing for a reason other than the code it claimed to cover. The layer the pre-filter cannot reach (an unparsable or scalar `tags` value) is now pinned separately in `tests/unit/test_em_facade_engine.py`, and that mutation is caught.
- Gates: **1624 passed / 3 skipped / 4 xfailed**, `ruff==0.16.2` clean, eval gate vs `v2.8.0-ci.json` with no gated metric regressed, `perf-smoke` warm p95 3.666 ms against the unchanged 20 ms budget, `tests/unit` green standalone for `windows-import`.
- **Merged** to `main` at `e25db32`, together with Chunk 5. Every job was green on the exact SHA, `windows-import` and `plugin-validate` included.

### Chunk 7.1 — the entity-link job. **DONE, MERGED (2026-10-06, `96c4ccb`, in `64a2685`)**

- `feat(em-211): entity linking runs as a job`: `EntityLinker` and `EntityStore.link` already existed (EM-208), but nothing called them on v3 — no write queued a link job and no worker registered a handler, so a v3 memory was never bound to an entity. `MemoryStore` now enqueues `link:<memory_id>:<version>` beside the `embed` enqueue, and `make_link_handler` runs outside any write transaction (invariant 2).
- Idempotent across a retry, because delivery is at-least-once: `EntityStore.link` upserts and a phrase's sighting counter counts distinct memories. Asserted by re-running the same job.
- Dead-letters a payload with no `memory_id` and a memory that no longer exists; a memory that is merely not live (pending/archived/forgotten) is **done**, not failed, because deletion is a status change. The row's own scope is used.
- Promotion (`pending -> active`) and a content `update` both queue a link job, matching the embed enqueue deliberately.
- **Known limitation, asserted:** the two-sighting rule is EM-208's, so promotion links whichever memory's job trips the counter and does not retro-link the earlier one. Backfilling is S5's `reconcile`.
- 17 new tests; 1643 passed / 3 skipped / 4 xfailed on Python 3.10 **and** 3.12; seven mutation checks. One existing test updated rather than weakened: it counted all jobs and now counts per type.
- **Merged** to `main` at `64a2685`; green on the exact SHA, first CI run, `identity-guard` included.

**EM-210 is fully closed. EM-211 is nearly done: reads, writes, the mirror call and the link job are in; only the §3.5 owner-only read rule (7.2) remains.**

---

## Part B: Chunk 7.2 — the §3.5 owner-only rule for sensitive reads. **NEXT PIECE, NOT STARTED**

**Topic:** the last piece of EM-211, and the read-side scope gap deferred since Chunk 4.

**Why this chunk.** The facade's reads are profile-wide today. `get_fact` calls `MemoryStore.get(id)` with **no scope at all**, and `recall_with_relevance` / `_like_fallback` build raw SQL with no scope or sensitivity clause. So in a profile that has a gateway user, any user of that profile can read a `sensitive` or `secret` memory. Chunk 5 fixed the **write** side (scope is set correctly on every row); this is the read side.

**What already exists (measured from the code, so the chunk is not re-derived).**

| Piece | Where | State |
|---|---|---|
| `_in_scope(row, scope)` | `em/store/memories.py` | Exists. Same profile **and** (same user **or** `scope_user == ''`). Its docstring says the owner-only rule "lands with the facade (EM-211), which knows the gateway identity" |
| `MemoryStore.get(id, *, scope=None)` | same | Already accepts a scope and calls `_in_scope` — `get_fact` just passes nothing |
| `MemoryStore.list(*, scope, ...)` | same | Requires a scope, filters profile+user only |
| `Scope.is_owner`, `Scope.author` | `em/store/types.py` | Exist on the type; nothing sets them from a gateway today |
| Facade reads | `em/facade/engine.py` | `get_fact` unscoped; `recall_with_relevance`, `_like_fallback`, `find_mirrored` hand-written SQL with no sensitivity clause |

**The rule to implement.** A memory whose `sensitivity` is `sensitive` or `secret` is readable only when the caller **is the owner** of that scope. Everything else keeps the current rule. `_in_scope` is the single place it belongs (invariant 5), so every read that already goes through it inherits the rule and there is one function to test.

**In scope.**
- The rule in `_in_scope`, with a truth-table test: owner/guest × `sensitive`/`secret`/`internal`/`public` × profile-wide/user-scoped.
- Apply it on every facade read: `get_fact` passes `self.scope`; `recall_with_relevance` and `_like_fallback` gain the scope and sensitivity clauses; `find_mirrored` gains the sensitivity clause (it already filters scope).
- `V3Engine` accepts the caller's identity (`is_owner`, and the gateway user it already takes as `scope_user`) and threads it into `self.scope`. Constructor argument, never an environment read — the same rule the existing `scope_user` follows.
- A test that a guest **cannot** read another user's sensitive row through each of the four read paths, and that an owner **can**. The leak test is the point: if the rule is deleted, it must fail loudly.
- Mutation-check: drop the sensitivity branch and confirm the guest-read test goes red; drop the scope clause from `recall` and confirm the cross-user test goes red.

**The decision this chunk must surface, not bury.** What happens when the facade is constructed without a known identity? Two options, and they are not equivalent:

- **fail-closed** (`is_owner=False` by default): a misconfigured facade hides sensitive rows even from the owner. Safe against a leak, but a silent data-visibility bug.
- **fail-open** (`is_owner=True` by default): the owner always sees their own data, but forgetting to pass the identity leaks sensitive rows to guests.

`Scope.is_owner` currently defaults to `True`, which is the fail-open choice. **Do not silently inherit that default.** Decide deliberately, write the reason down, and test whichever is chosen. This is the one genuinely owner-facing judgement in the chunk.

**Size guard — this chunk may split further.** The rule, the facade reads and the tests are self-contained. Threading the identity from the provider is **not**: the provider still constructs the v2 `MemoryEngine`, so there is nothing to pass the gateway user *to* until the wiring chunk. If the work starts needing provider changes, stop and land the rule + facade half alone, then plan the wiring. `V3Engine` taking an `is_owner` argument satisfies this chunk; the provider supplying it is the wiring chunk's job.

### 7.2.0 Pre-flight (read-only)
1. `main` must be at `64a2685` or later: Chunks 5, 6 and 7.1 are all merged there, with green CI on each exact SHA. `git merge-base --is-ancestor 64a2685 main` proves it.
2. **Baseline:** `pytest -q` gives **1643 passed, 3 skipped, 4 xfailed** on **both Python 3.10 and 3.12** (2 skipped on a machine that has the private digest list). Run 3.10 as well as your default interpreter — the last two chunks each shipped a bug only the 3.10 leg could see.
3. **Re-measure from the code.** Read `_in_scope`, `MemoryStore.get` / `list`, every read in `em/facade/engine.py`, `Scope.is_owner`, and how the provider tracks the gateway user (`_gateway_user_id`, `_is_guest`) — that is where the identity will come from when the provider is wired.

### 7.2.0a Document control (do this before and after the chunk)
Per `AGENTS.md`: reconcile `MASTER_TODO.md`, `REMAINING_PLAN.md` and this file
**before** starting and **again before finishing**. Merge state counts as truth —
a chunk committed without CI merged is "committed, not merged", never "landed".
`tests/test_master_todo.py` fails the suite if this page and the plan disagree
about it, and it now understands decimal chunk ids (7.1, 7.2) because sub-chunks
are real.

### 7.2.1 The rule (one commit, test first)

- Test first: the `_in_scope` truth table, then the four facade read paths.
- Mutation-check as above.
- **Docs:** CHANGELOG (**Security** section — this is a privacy rule); the EM-211 rows in `REMAINING_PLAN.md` §5, §6.1 and §11; the EM-211 entry and the `_in_scope` deferral note in `docs/V3_FOUNDATIONS.md`.

### 7.2.2 End of chunk
1. Push, green CI on the exact SHA, `git merge --ff-only`, delete the branch.
2. Update `MASTER_TODO.md` and `REMAINING_PLAN.md` §2/§5/§6.1/§9/§11.
3. **Replace this file's Part B with the next piece.** EM-211's four sub-chunks are then all done; the candidates are the **wiring** chunk (switch the provider onto the facade — a separate, owner-aware decision) and **EM-212's package move**. Say which and why; do not plan both.
4. Report to the owner in plain language.

### Explicitly out of scope for Chunk 7.2
- **Switching the provider onto the facade.** The facade is completed and tested, not switched on.
- Releases, tags, the catalog, the tool rename, the v3 cutover.
- Any schema change or new migration; `0001`–`0003` stay untouched.
- S3 and later, EM-212's package move, retention (settled at 7 routine + 5 safety).
- Anything touching `~/.hermes/entropicmem*`.
