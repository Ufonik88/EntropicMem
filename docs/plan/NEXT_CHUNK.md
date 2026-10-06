# EntropicMem: next steps (one chunk at a time)

**Updated:** 2026-10-06, Chunks 5 and 6 merged to `main` at `e25db32`; **Chunk 7 is the next piece**. **Read first:** `MASTER_TODO.md`, then `docs/plan/REMAINING_PLAN.md` (its §3 rules apply to everything here), then `AGENTS.md` and `docs/V3_FOUNDATIONS.md`.

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

**The EM-210 gaps are both closed. EM-211 is three quarters done (reads, writes, mirror).** Feature work stays stopped until the owner starts Chunk 7.

---

## Part B: Chunk 7 — the `EntityLinker` job. **NEXT PIECE, NOT STARTED**

**Topic:** the last quarter of EM-211 — entity linking off the write path, and with it the §3.5 owner-only rule.

**Why this chunk.** Chunks 4–6 made the facade complete enough to serve every call the provider makes, and `PROVIDER_ATTRIBUTES` is now empty. What the facade still does not do is the work v2 did inline: binding a memory to entities. On v3 that must be a job, because entity work inside `MemoryStore.add` would be slow work inside a write transaction (invariant 2). This chunk is also where the read-side scope gap that has been deferred since Chunk 4 finally gets closed, because the linker is the first thing that needs to know whose row it is looking at.

**What already exists (measured from the code, so the chunk is not re-derived).**

| Piece | Where | State |
|---|---|---|
| `EntityLinker(conn, scope).link(memory) -> list[str]` | `em/formation/entity_linker.py` | **Exists**, 57 lines, a thin wrapper over `EntityStore.link` |
| `EntityStore.link(memory_id, content, *, scope)` | `em/store/entities.py` | Exists; two-sighting promotion, aliases, relations |
| `EntityStore.forget_sightings(memory_id, *, profile)` | same | Exists, and `MemoryStore.purge` already calls it — invariant 6 is satisfied |
| `link:<memory_id>:<version>` enqueued on write | `em/store/memories.py` | **Missing.** `_add_as_live` enqueues only `embed:<id>:<version>` |
| A registered `link` handler | `em/jobs/cli.py` | **Missing.** Only `backup` is registered (`registry.register("backup", …)`) |
| §3.5 owner-only read for sensitive rows | `em/store/memories.py` `_in_scope` | **Missing by design** — its own docstring says the rule "lands with the facade (EM-211), which knows the gateway identity" |

`Scope` already carries `is_owner: bool = True` and an `author` field, so the identity the owner-only rule needs is on the type; nothing has to be invented.

**In scope for Chunk 7.**
- Enqueue `link:<memory_id>:<version>` from the write path, next to the existing `embed` enqueue, and never run the linker inside the transaction.
- A `make_link_handler(...)` following the recipe in `docs/V3_FOUNDATIONS.md` ("Add a job type"): idempotent because delivery is at-least-once, its own short transactions via `ctx.store.transaction()`, `PermanentJobError` for a memory that no longer exists, content kept out of exception messages.
- Register it in `em/jobs/cli.py` beside `backup`, so `entropicmem worker run` picks it up. Note the CLI's documented-command count is pinned by `tests/test_cli_reference_drift.py` — only add a documented command if one is genuinely new.
- The §3.5 owner-only rule for sensitive rows: a `sensitive`/`secret` memory is readable only by its owner, with `_in_scope` as the single place that decides, plus a truth-table unit test (invariant 5 says every read is scoped).
- Apply that rule to the facade's reads, which currently read profile-wide: `get_fact`, `recall_with_relevance`, `_like_fallback` and `find_mirrored`.

**Size guard — split if this grows.** The link job is small and mechanical (the linker already exists; the work is enqueue + handler + registration). The owner-only rule is the risk: it touches every read path, needs a gateway identity threaded from the provider into `Scope`, and a wrong answer there is a privacy leak rather than a bug. **If the chunk starts to need provider changes to supply that identity, stop and split:** land 7.1 as the link job alone, and plan 7.2 as the scope rule. The plan's own §3.1 stop condition applies — a card AC bigger than the chunk's written scope means stop and report, not expand.

**Known gaps to carry in.**
- `get_fact`/recall read with no scope filter (profile-wide). Chunk 5 set scope correctly on **write**; this chunk is the read side. Until it lands, the deferral stays documented in `docs/V3_FOUNDATIONS.md`.
- Promotion of a `pending` memory to `active` does not currently enqueue an embed job (only `_add_as_live` does). If the link job is enqueued on write, decide deliberately whether promotion enqueues too, and say so — do not let the two paths differ by accident.
- `find_mirrored` already filters by scope; extending the owner-only rule must not make a profile-wide mirror invisible to the owner's own replace/remove path.

### 7.0 Pre-flight (read-only)
1. `main` must be at `e25db32` or later: Chunks 5 and 6 are merged there, with green CI on the exact SHA. `git merge-base --is-ancestor e25db32 main` proves it.
2. **Baseline:** `env -u ENTROPICMEM_MEMORY_DB -u ENTROPICMEM_VAULT_PATH -u ENTROPICMEM_INDEX_DB python3 -m pytest -q` gives **1626 passed, 3 skipped, 4 xfailed** on both Python 3.10 and 3.12 (2 skipped instead of 3 where the private digest list exists — read the pair, see plan §11). `ruff check .` clean under the CI pin `ruff==0.16.2`.
3. **Re-measure from the code before writing a test.** Read `em/formation/entity_linker.py`, `EntityStore.link`, the `embed` enqueue in `em/store/memories.py` (the pattern to copy), `em/jobs/cli.py`'s registration, the job-type recipe in `docs/V3_FOUNDATIONS.md`, and `_in_scope`.

### 7.0a Document control (do this before and after the chunk)
Per `AGENTS.md`: reconcile `MASTER_TODO.md`, `REMAINING_PLAN.md` and this file **before** starting and **again before finishing**. Merge state counts as truth — a chunk committed without CI merged is "committed, not merged", never "landed". `tests/test_master_todo.py` fails the suite if this page and the plan disagree about it.

### 7.1 The link job (one commit, test first)
- Test first: the handler through `JobWorker(...).run_until_idle()`; a re-run of the same job (idempotency); the permanent-failure path for a missing memory; and that `add` enqueues exactly one `link:<id>:<version>` with the dedupe key that identifies the work.
- Assert the handler runs **outside** any write transaction — `test_handler_runs_outside_any_write_transaction` is the existing pattern for that.
- Mutation-check: the enqueue, the dedupe key, the idempotency, and the missing-memory path.

### 7.2 The owner-only rule (separate commit, or its own chunk if 7.1 grew)
- Test first: a `_in_scope` truth table (owner/guest × sensitive/internal × profile-wide/user-scoped), then the four facade read paths against it.
- Mutation-check: drop the sensitivity branch and confirm a guest reads an owner's sensitive row — that is the leak the rule exists to prevent, so the test must fail loudly.
- **Docs:** CHANGELOG (Security section, since this is a privacy rule); the EM-211 rows in `REMAINING_PLAN.md` §5, §6.1 and §11; the EM-211 entry and the `_in_scope` deferral note in `docs/V3_FOUNDATIONS.md`.

### 7.3 End of chunk
1. Push a branch. Wait for green CI on the exact SHA (`windows-import` included), then fast-forward `main` and delete the branch.
2. **Update `docs/plan/REMAINING_PLAN.md`:** §2 (SHA, counts), §5 (ledger), §6.1, §9, §11 (state table, next piece, counts).
3. **Replace this file's Part B with the next piece.** With EM-211's four chunks done, that is either the **wiring** chunk (switch the provider onto the facade — a separate decision, not yet scheduled) or **EM-212's package move**. Say which and why; do not plan both.
4. Update `MASTER_TODO.md`, and report to the owner in plain language.

### Explicitly out of scope for Chunk 7
- **Switching the provider onto the facade.** The facade is completed and tested, not switched on.
- Releases, tags, the catalog, the tool rename, the v3 cutover.
- Any schema change or new migration; `0001`–`0003` stay untouched. If the owner-only rule turns out to need a column, that is a new migration and a stop-and-report.
- S3 and later, EM-212's package move, retention (settled at 7 routine + 5 safety).
- Anything touching `~/.hermes/entropicmem*`.
