# EntropicMem: next steps (one chunk at a time)

**Updated:** 2026-10-07, Chunk 8 merged to `main` at `c922970`; **Chunk 9 (the wiring by `user_version`) is the next piece**. **Read first:** `MASTER_TODO.md`, then `docs/plan/REMAINING_PLAN.md` (its §3 rules apply to everything here), then `AGENTS.md` and `docs/V3_FOUNDATIONS.md`.

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

### Chunk 7.2 — the §3.5 owner-only rule for sensitive reads. **DONE, MERGED (2026-10-07, `563afe5`, in `783aae9`)**

- `feat(em-211): sensitive memories are owner-only on read`: the facade's reads were profile-wide, so in a profile with a gateway user any user could read a `sensitive`/`secret` memory. The rule now lives in `_in_scope` — the one function invariant 5 names — and all four facade read paths route through it: `get_fact` passes `scope`, FTS recall and the literal-LIKE fallback filter through `_in_scope`, and `find_mirrored` does too.
- **The decision:** `Scope.is_owner` defaults to **False** (fail-closed), and a profile-wide caller (`user == ""`) is the owner context. Only a scoped caller can leak, so the default makes it assert ownership; a wiring mistake then hides the owner's own sensitive rows (visible) rather than showing them to a guest (silent). This mirrors the provider's `_is_guest()`. `V3Engine` takes `is_owner` as a constructor argument, never an environment read.
- 26 new tests: a 15-case truth table, the fail-closed default, the four read paths, and a migrated `secret` row (which the write policy refuses to create). 1669 passed / 3 skipped / 4 xfailed on Python 3.10 and 3.12. Six mutation checks. No existing test needed changing.
- **Known gap recorded, not fixed:** `MemoryStore.list` keeps profile+user only, so the facade's `prune_pending`/`consolidate` are not tier-filtered. They are the owner's operations and the facade is unwired.
- **Merged** to `main` at `783aae9`; green on the exact SHA, first CI run, `identity-guard` included.

### Chunk 8 — EM-212's package move. **DONE, MERGED (2026-10-07, `025f012`, in `c922970`)**

- `fix(em-212): the engine's shared-name modules live under a package`: `vault`, `index`, `security`, `policy`, `embeddings` and `retrieval` moved under `scripts/em_internal/`, so the import system registers `em_internal.*` and never the bare names. The strict xfail **flipped to a passing test**.
- The move is what the card's AC names — six modules, and the six `hermes plugins validate` warned about. `_backend._own_module` (the path-loading shim) is deleted in favour of a qualified import, because a qualified name cannot collide.
- **Three silent coverage losses were repaired**, each of which the move would have hidden: `test_f005`'s non-recursive glob stopped seeing the moved modules; `test_plugin_imports`'s module list stopped checking them for the 2026-08-14 bug class; and the packaging guard only required `em.*`, so `em_internal` could have shipped missing from the wheel. All three now cover the package, and each was mutation-checked.
- 52 files touched (6 renames). 1671 passed / 3 skipped / 3 xfailed on Python 3.10 and 3.12; the xfail count dropping 4→3 **is** the flip. Provider, CLI and `graph_server` all still import.
- **The other 14 modules keep unprefixed names, deliberately** — the AC names only the six. Moving them is a follow-up, not a silent omission.
- **The AC's second half is confirmed by CI.** `hermes plugins validate` runs as the `plugin-validate` job and passed: `✓ loadable`, `✓ built-in tool collisions — no collisions`, `✓ security scan — safe`, no module-shadow warning, and only the known `provides_*` warnings.
- **Merged** to `main` at `c922970`; green on the exact SHA, first CI run, `identity-guard` and `plugin-validate` included.

**EM-211 and EM-212 are both code-complete.** EM-211 is unwired (its AC needs the provider on the facade) and EM-212's six named modules are namespaced (its AC also wants `hermes plugins validate`, unrun here).

---

## Part B: Chunk 9 — the wiring, engine selection by `user_version`. **NEXT PIECE, NOT STARTED**

**Topic.** The provider still constructs v2's `MemoryEngine`. EM-211's four sub-chunks are code-complete, so the facade can serve every call the provider makes — but nothing selects it. This chunk puts the selection in: **the v2 engine for a v2 store, the facade for a v3 one**, keyed on `PRAGMA user_version`.

**Why that shape, and not a swap.** `V3Engine.__init__` calls `migrate(conn)`. A wired provider pointed at an existing v2 store would therefore migrate it in place — that *is* the v3 cutover, which the rules reserve for the owner with the owner present. Selecting by store version means the wiring lands and is fully testable **without opening anyone's store for a migration**, and the cutover stays a separate, deliberate act. This is the approach the owner settled on 2026-10-07.

**What already exists (measured from the code).**

| Piece | Where | State |
|---|---|---|
| `MemoryEngine(` construction sites | `plugins/entropicmem/__init__.py`, `scripts/entropicmem.py` | **11 sites**, and two factories already funnel most of them |
| Provider factory | `EntropicMemMemoryProvider._memory_engine()` (`__init__.py:1568`) | Exists — the seam |
| CLI factory | `_engine(db)` (`entropicmem.py:419`) | Exists — the seam. `tests/test_...` asserts no bare `MemoryEngine(...)` in the CLI |
| `PRAGMA user_version` | `em/store/migrations/__init__.py` | Read at `:327`; `migrate()` refuses a store newer than this build |
| Facade | `em/facade/engine.py` `V3Engine` | Code-complete; takes `profile_id`, `scope_user`, `scope_chat`, `is_owner` |
| Provider contract | `em/facade/contract.py` | `PROVIDER_CALLS` derived from the provider source; `PROVIDER_ATTRIBUTES` empty |

**In scope.**
- **Engine selection, in the two factories only.** Read `PRAGMA user_version` **read-only** and choose: a store at the v2 baseline (or with no `em` tables at all) → `MemoryEngine`; a v3 store → `V3Engine`. A store that is neither → refuse loudly, the way `entropicmem worker run` already refuses a non-v3 database.
- **Pass the gateway identity into the facade** — `scope_user = self._gateway_user_id`, `is_owner = not self._is_guest()` (the same computation `_is_guest()` already makes, so the default config with an empty `owner_user_ids` stays the owner context and nobody becomes a guest). This is the half of the §3.5 rule that Chunk 7.2 deliberately left for here.
- A test that a **v2 store is not migrated** by the wired path, and a test that a v3 store selects the facade. Those two are the whole point of the chunk.
- A test that `user_version` is read without opening the database read-write.

**Out of scope — and this is the boundary that matters.**
- **The v3 cutover.** No migration of any real store, no `ENTROPICMEM_ALLOW_LIVE_MIGRATION=1`, no switch-over. The wiring makes the cutover *possible*, not *done*.
- Releases, tags, the catalog, the tool rename.
- Any schema change or new migration; `0001`–`0003` stay untouched.
- Moving the other 14 modules under a package (EM-212's deliberate remainder).
- S3 and later.

**Size guard — stop and report if any of these appears.** Moving `_locate_mirror`/recall call sites themselves (they should not need to change: they go through the factory); a provider behaviour change other than engine selection; any code path that migrates on selection; or the contract test demanding a `PROVIDER_CALLS` change beyond what the selection needs. If the facade turns out to be missing something the provider calls, **stop** — that is a Chunk 10, not a quiet widening of this one.

### 9.0 Pre-flight (read-only)
1. `main` must be at `c922970` or later: Chunks 5–7.2 and 8 are all merged there, with green CI on each exact SHA. `git merge-base --is-ancestor c922970 main` proves it.
2. **Baseline:** `pytest -q` gives **1671 passed, 3 skipped, 3 xfailed** on **both Python 3.10 and 3.12**. Run 3.10 as well as your default interpreter.
3. **Re-measure from the code.** Read `_memory_engine()` and `_engine()`, every `MemoryEngine(` site, `is_guest`/`_gateway_user_id`, `V3Engine.__init__`, and how `entropicmem worker run` refuses a non-v3 store (`em/jobs/cli.py` — copy that shape for the "neither v2 nor v3" case).

### 9.0a Document control (do this before and after the chunk)
Per `AGENTS.md`: reconcile `MASTER_TODO.md`, `REMAINING_PLAN.md` and this file **before** starting and **again before finishing**. Merge state counts as truth — committed is not merged. `tests/test_master_todo.py` enforces it.

### 9.1 The selection (one commit, test first)
- Test first: a v2 fixture DB selects `MemoryEngine` **and is byte-for-byte unmigrated afterwards** (compare `user_version` before and after, and that no `em` tables appeared); a v3 store selects `V3Engine`; a store that is neither is refused; the identity passed to the facade matches `not _is_guest()`.
- Mutation-check: make selection always choose the facade and confirm the "v2 store untouched" test goes red; drop the identity plumbing and confirm a guest can read the owner's sensitive row through the wired path.
- **Docs:** CHANGELOG (**Changed** — the provider can now run on either engine); the EM-211 rows in `REMAINING_PLAN.md` §5, §6.1 and §11; `docs/V3_FOUNDATIONS.md`'s layer map.

### 9.2 End of chunk
1. Push, green CI on the exact SHA, `git merge --ff-only`, delete the branch.
2. Update `MASTER_TODO.md` and `REMAINING_PLAN.md` §2/§5/§6.1/§9/§11.
3. **Replace this file's Part B with the next piece** — with the wiring landed, the candidates are the **v3 cutover** (owner-scheduled, now unblocked) and **S3 (retrieval v3)**. Say which and why; do not plan both.
4. Report to the owner in plain language.

### Explicitly out of scope for Chunk 9
- The cutover, releases, tags, the catalog, the tool rename.
- Any schema change or migration.
- The 14 remaining unprefixed modules.
- S3 and later, and anything touching `~/.hermes/entropicmem*`.
