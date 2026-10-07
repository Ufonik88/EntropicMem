# EntropicMem: next steps (one chunk at a time)

**Updated:** 2026-10-07, Chunk 9 merged to `main` at `0200424`; **Chunk 10 (CLI parity) is the next piece**. **Read first:** `MASTER_TODO.md`, then `docs/plan/REMAINING_PLAN.md` (its §3 rules apply to everything here), then `AGENTS.md` and `docs/V3_FOUNDATIONS.md`.

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

### Chunk 9 — the provider selects its engine by `user_version`. **DONE, MERGED (2026-10-07, `b615bcf`, in `0200424`)**

- `feat(em-211): the provider selects its engine by the store's schema`: a v2 store gets `MemoryEngine`, a v3 store the facade. All **nine** `MemoryEngine(` sites in the provider route through one `_open_engine()`, with a drift guard against a tenth.
- **Selection happens before any engine is constructed**, from a read-only peek, because `V3Engine.__init__` calls `migrate()` — so opening a v2 store cannot cut it over. The selector refuses a store newer than this build and a versioned store with no `memories` table.
- The gateway identity is threaded into the facade (`is_owner = not _is_guest()`), the half of the §3.5 rule Chunk 7.2 left for here. An empty `owner_user_ids` means nobody is a guest, so a default install stays the owner.
- **The CLI was deliberately left alone.** It calls ~28 methods the facade lacks, so it keeps `MemoryEngine`. That is the next chunk, and the cutover waits on it.
- Deviation: `pii_locales` has no facade equivalent (routed to v2 only).
- 16 new tests; 1687 passed / 3 skipped / 3 xfailed on Python 3.10 and 3.12; seven mutation checks, the key one being that **opening a v2 store leaves it byte-for-byte unmigrated**.
- **Merged** to `main` at `0200424`; green on the exact SHA, first CI run, `identity-guard` and `plugin-validate` included.

### Chunk 10.1 — the facade's CLI read/listing calls. **DONE, MERGED (2026-10-07, `f439e55`, in `b807e4c`)**

- The first slice of the route: eight methods (`list_facts`, `list_pending`, `list_audit`, `get_versions`, `episode_stats`, `embedding_stats`, `list_episodes`, `recall`), each returning **the shape its CLI command prints**. Nothing calls them yet — the CLI still refuses v3 (10.0) and is routed in 10.4.
- **Two refusals by name**, not silent partials: `list_episodes(domain=...)` (v3 episodes carry `kind`) and `recall(scope='shared'|'all')` (shared store is S5).
- `get_versions` normalises two v3-vs-v2 differences — the creation-row duplicate and the order — **both verified against v2 by probe**, not assumed.
- **Plan correction:** `profile_id()` was dropped from the slice; its only CLI caller is `cmd_migrate --status`, which is in the refuse group.
- 15 new tests; 1707 passed / 3 skipped / 3 xfailed on Python 3.10 and 3.12; nine mutation checks, all caught.
- **Merged** to `main` at `b807e4c`; green on the exact SHA, first CI run.

### Chunk 10.2 — the facade's CLI maintenance calls. **DONE, MERGED (2026-10-07, `cc19337`, in `f36c5e6`)**

- Six state-changing calls: `promote_pending`, `discard_pending`, `reinforce`, `rebuild_fts`, `timeline`, `recall_episodes`. Tests assert the **transition**, not the return value.
- **v3's model shows in promotion:** v2 re-`remember`ed the quarantine row into a new durable fact and produced a new id; on v3 the pending row **is** the memory, so promotion is a `pending -> active` edge and the id is unchanged. Recorded deviation: no `source="promoted"` re-stamp and no `"promoted"` tag (the store does not allow editing `source`).
- **`rebuild_fts` is a report, not a repair** — v3's FTS is trigger-maintained, so there is nothing to fix. It keeps v2's keys and touches nothing.
- `recall_episodes` windows in the facade (not via `search_episodes`, which filters a different column), through a shared `_episode_to_v2` mapper so the two episode reads cannot drift.
- 15 new tests.

### Chunk 10.3 — the CLI's by-name refusals. **DONE, MERGED (2026-10-07, `cc19337`, in `f36c5e6`)**

- Seven v2-only features now exit up front, before `_engine()`, naming the card that lifts them: `triple` (S5), `embed --rebuild` (S3/EM-303), `memory project` (S6), `publish`/`pull` (S5), `migrate` (v2-only), `recall --related` (S6), `recall --scope shared|all` (S5).
- **The tests monkeypatch `_engine` to raise**, so a passing test proves the refusal fired first. That is what makes them meaningful *now*, while 10.0's coarser refusal is still in force — after 10.4 these guards are the only thing between a v3 store and an `AttributeError`.
- `memory project`'s guard sits before path resolution, so a refusing command does not create vault/index directories.
- 12 new tests, including one asserting every refusal names a trigger.

### Chunk 10.4 — the CLI routes. **DONE, MERGED (2026-10-07, `250320a`, in `c50d7b6`)**

- `_engine()` selects through the same `open_engine` the provider uses, so the CLI's ported commands run against a **v3** store and the v2-only ones still refuse by name (their guards run before `_engine()`). **EM-211's AC is met except for seven named refusals.**
- **The chunk's point is the v2 regression pass:** routing changed engine construction for *every* store. A subprocess suite runs the real CLI against a v3 store (remember → list → recall, history, audit, pending, episode stats, timeline) and against a v2 store, including that a v2 store is **not migrated**.
- **Fixed alongside: a latent v2 regression Chunk 9 introduced.** `MemoryEngine.profile_id()` resolves `explicit > hermes_home basename > 'default'`, and Chunk 9 passed `profile_id=self._profile_id or "default"` — making it explicit and overriding the home-derived slug a v2 store has always carried. `open_engine` now takes `profile_id=None` meaning **"the engine decides"**. Two regression tests pin it; reverting the fix reddens exactly the one on the provider path, which is where the bug lived and where nothing else looked.
- 18 new tests + 2 regression tests; 1751 passed / 3 skipped / 3 xfailed on Python 3.10 and 3.12; six mutation checks, all caught.
- **Merged** to `main` at `c50d7b6`; green on the exact SHA, first CI run, all 11 jobs.

### EM-302's first piece — `scope_sql`. **DONE, MERGED (2026-10-07, `0066fb5`, in `50c5310`)**

- `em.retrieval` created, with **`scope_sql(scope) -> (clause, params)`**: the §3.5 rule as SQL, the helper every generator filters through, unit-tested. The **generators are deliberately not written** — see Part B.
- **`may_read_owner_only(scope)` moved into `em/store/types.py`**, next to `Scope` and `OWNER_ONLY_TIERS`. `_in_scope` uses it as a predicate and `scope_sql` uses it to decide the SQL exclusion, so the plan's "if the two ever disagree, `_in_scope` wins" is true by construction rather than by test. The tier names come from the same tuple on both sides.
- The tests **cross-check the two forms over a real row matrix** instead of restating the rule, with a guard that the matrix discriminates so the check cannot pass vacuously.
- 6 new tests; 1757 passed / 3 skipped / 3 xfailed on Python 3.10 and 3.12; six mutation checks. The `is_owner` mutant reddens four tests across two suites — the shared predicate working.
- `em.retrieval` added to `pyproject` (invariant 9), verified by the packaging guard.
- **Merged** to `main` at `50c5310`; green on the exact SHA, first CI run.

**EM-211 and EM-212 are code-complete, both engines serve a v3 store, and S3 has begun.** EM-211's AC is met except for the seven refusals; the cutover is the owner's call; **EM-302 is blocked on card text that is not in the repo.**

---

## Part B: Chunk 11 continued — EM-302, **BLOCKED ON CARD TEXT**. The unblocked alternative is EM-303.

**Updated:** 2026-10-07, EM-302's `scope_sql` landed; **the generators are blocked, and EM-303 is the next unblocked piece**. **Read first:** `MASTER_TODO.md` (§ "Waiting on the owner"), then this file's Part B, then `AGENTS.md`.

### Why this is blocked, precisely

The size guard for this chunk says: *"stop and report if the `RetrievalContext`/`Candidate` shapes turn out to need §3.x text that is not in the repo (the master plan lives on the owner's machine — record the gap rather than inventing fields)."* That is what happened. §6.2's card summary fixes the shapes' **names**, not their fields:

| Missing | Consequence of guessing |
|---|---|
| **`Candidate`'s fields** | The summary says generators return `list[Candidate]` and names exactly one field (`owner_type='episode'`). Everything else a candidate carries is unrecorded. |
| **`RetrievalContext`'s field types** | `aq`, `scope`, `now`, `limits`, `deadline` are named but untyped: is `aq` a term list, a raw string, a weighted struct? Is `deadline` wall-clock or monotonic? What is in `limits`? |
| **The generator set** | The card says "candidate generators" (plural); the summary names BM25 and an episodic one. The full list is not recorded. |
| **BM25's per-column weights** | "per-column weights" is stated; the columns and the weights are not. |
| **The §3.6 formulas** | Needed by EM-304 ("exactly §3.6 formulas", deterministic `score desc, updated_at desc, id asc` tie-break). Not needed to *write* EM-302, but they are written against `Candidate`, which is why guessing its shape puts EM-304 on sand. |

**The ask, whenever it suits:** paste the **EM-302 card text from master plan §5** (and the §3.6 extract if handy) into this file or into §6.2. That is the §1 gap the plan already records for most cards after S2, now with a concrete consumer. Nothing else is needed.

### What already landed, and why it is safe to have landed it

`scope_sql` is fully specified in the repo — the signature is in §6.2 and the rule it implements is §3.5, whose authoritative form is `MemoryStore._in_scope`. It does not depend on `Candidate`. It is also the piece worth getting right first, since it is the one place the retrieval layer could leak an owner-only row to a guest. See Part A.

### The unblocked alternative: Chunk 11′ — EM-303, embeddings

If the card text is not to hand, **EM-303 is the next development piece and does not need it.** Records from §6.2:

* an **`embed` job handler** — `MemoryStore.add` already enqueues `embed:<id>:<version>`, and nothing consumes it yet;
* upsert into `embeddings` on **`(owner_type, owner_id, model)`**, so re-runs are harmless;
* **must respect the 2.8.1 opt-in** (`embeddings_enabled` / `ENTROPICMEM_EMBEDDINGS`): no model download without it;
* target: the hard-suite ageing **recall@5 from 0.733 to 0.90**. The four misses share no words with the stored fact — **do not build a synonym table and do not edit the fixture**;
* it is also what lifts the CLI's `embed --rebuild` refusal (Chunk 10.3).

The same size guard applies: stop if the `embeddings` table's shape or the model-loading contract needs something not in the repo — record the gap rather than invent it.

### Pre-flight (either path)
1. `main` must be at `50c5310` or later: EM-302's `scope_sql` is merged there. `git merge-base --is-ancestor 50c5310 main` proves it.
2. **Baseline:** `pytest -q` gives **1757 passed, 3 skipped, 3 xfailed** on **both Python 3.10 and 3.12**.
3. **Re-measure from the code.** For EM-303: `MemoryStore._enqueue_embed`, the `embeddings` table in `0002_v3_core`, `em/store/jobs.py`'s registry, `embeddings.py`'s opt-in gate, and `evals/`'s hard-suite fixture. For EM-302 once unblocked: whatever the pasted card text says.

### Document control (before and after)
Per `AGENTS.md`: reconcile `MASTER_TODO.md`, `REMAINING_PLAN.md` and this file **before** starting and **again before finishing**. Merge state counts as truth.

### End of chunk
1. Push, green CI on the exact SHA, `git merge --ff-only`, delete the branch.
2. Update `MASTER_TODO.md` and `REMAINING_PLAN.md` §2/§5/§6.2/§9/§11.
3. **Replace this file's Part B with the next piece** — EM-302's generators once the card text lands, else the next S3 card (EM-304 after EM-303, say which and why).
