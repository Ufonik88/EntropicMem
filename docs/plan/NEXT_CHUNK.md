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

**EM-211 and EM-212 are both code-complete, and the provider half of EM-211 is wired.** What remains of EM-211 is the CLI (Chunk 10) and the cutover.

---

## Part B: Chunk 10 — CLI parity on v3. **THE ROUTE IS DECIDED; 10.1 is the next piece**

**Updated:** 2026-10-07, the route decided and its first step landed. **Read first:** `MASTER_TODO.md`, then `docs/plan/REMAINING_PLAN.md` §9, then `AGENTS.md`.

### The route, decided (keep it simple, keep it honest)

The gap is measured: the facade implements the provider's 13 calls; the CLI makes about 28 more. Three of those groups are different problems and get different answers.

| Group | Calls | Decision |
|---|---|---|
| **Reads / listing** | `list_facts`, `list_pending`, `list_episodes`, `get_versions`, `episode_stats`, `embedding_stats`, `list_audit`, `profile_id`, `recall` (alias) | **Port.** v3 has all of it; the work is translation and return shapes. |
| **Maintenance + mappable recall** | `promote_pending`, `discard_pending`, `reinforce`, `rebuild_fts`, `timeline`, `recall_episodes` | **Port.** `set_status`, `touch`, episode FTS. `rebuild_fts` may be a no-op on v3 (triggers maintain it) — decide and say so. |
| **v2-only subsystems** | `triple_*` (4), `rebuild_embeddings`, `publish`, `pull`, `backfill`, `project_to_vault`, `migrate`, `recall_related` | **REFUSE clearly on a v3 store**, naming the card that will bring it (triples → S5, embeddings → S3/EM-303, publish/pull/backfill → S5, project_vault → S6, graph recall → S6). Porting them needs v3 features that do not exist yet. |

**Why refuse rather than port the last group.** They are not translations; they are features the v3 store has not built. Porting them inside a "parity" chunk would silently become S3/S5/S6 work with no plan behind it. A clear refusal is honest, keeps the cutover predictable, and is a two-line change per command. **A silent wrong answer is not acceptable; a named absence is.**

**Why refusing also makes the cutover safe.** After 10.1 and 10.2 land, the CLI serves a v3 store for everything except the refused group. The cutover can then proceed knowing exactly what a user loses — and the 3.0 upgrade notes list it. Without the refusals, a user could run `entropicmem triples` against a v3 store and get a confusing failure instead of a named one.

### Sequencing and estimates

Effort is given in **sessions and commits**, not calendar dates — the pace depends on when the owner runs sessions, which no plan can know. One session is one chunk, per `AGENTS.md`.

| Step | What | Estimate |
|---|---|---|
| **10.0** | **DONE.** The CLI refuses a v3 store clearly instead of handing it to the v2 engine (this commit). Nothing silently misbehaves in the meantime. | done |
| **10.1** | Port the reads/listing group + `profile_id` + the `recall` alias. | **~7 methods, 5–7 commits, 1 session** |
| **10.2** | Port maintenance + `recall_episodes`; decide `rebuild_fts` (= no-op?) and `timeline`. | **~6 methods, 3–5 commits, 1 session** |
| **10.3** | Make the v2-only group **refuse clearly** on a v3 store, each naming its card. | **~9 commands, 2–3 commits, ≤ 1 session** |
| **10.4** | Route `_engine()` through `open_engine` and run the full CLI suite against a **v3** store. This is the exit: EM-211's AC ("CLI commands work unchanged") is met for everything not refused. | **1 commit** |

**Total to CLI parity: about 3 sessions, ~12 commits.** Then the cutover (owner-gated) becomes available, and S3/S5/S6 can fill in the refused group later.

### 10.1 in detail (the next piece)

- **In scope:** `list_facts`, `list_pending`, `list_episodes`, `get_versions`, `episode_stats`, `embedding_stats`, `list_audit`, `profile_id`, and `recall` as an alias of the existing `recall_with_relevance`. Implemented **on the facade** (`V3Engine`), tested at the facade level against a real v3 store, with the return shape each CLI command expects.
- **Out of scope:** everything in 10.2/10.3/10.4, and the cutover.
- **Test first:** each method against a v3 store; mutation-check the two that carry logic (the `list_*` filters and `get_versions`' ordering).
- **Size guard — stop and report if:** a "read" method needs the v3 retriever or the graph (S3/S6, not translation), the CLI's expected return type cannot be produced without changing the provider contract, or the slice needs more than about seven commits. Take 10.2 first instead of widening.

### 10.1.0 Pre-flight (read-only)
1. `main` must contain this route's first step (the CLI guard). `git merge-base --is-ancestor <10.0 sha> main` proves it.
2. **Baseline:** `pytest -q` gives **1692 passed, 3 skipped, 3 xfailed** on **both Python 3.10 and 3.12**.
3. **Re-measure from the code.** For each command in the slice, read what it does with the engine's return value (the CLI has its own expectations the facade must meet); check `tests/test_cli_hermes_home.py::test_the_cli_builds_engines_only_through_the_helper` (the drift guard), and `docs/CLI_REFERENCE.md` for the documented output.

### 10.1.1 The slice (test first)
- Test first: each method on a v3 store, asserting the shape the CLI needs.
- Mutation-check the filters and the ordering.
- **Docs:** CHANGELOG; `REMAINING_PLAN.md` §5/§6.1/§11; `docs/CLI_REFERENCE.md` only if a documented behaviour changes.

### 10.1.2 End of chunk
1. Push, green CI on the exact SHA, `git merge --ff-only`, delete the branch.
2. Update `MASTER_TODO.md` and `REMAINING_PLAN.md` §2/§5/§6.1/§9/§11.
3. **Replace this file's Part B with Chunk 10.2.** Do not plan further ahead.

### Explicitly out of scope
- The cutover; the v2-only group's port; releases, tags, the catalog; schema changes; S3 itself; the 14 remaining unprefixed modules; `~/.hermes/entropicmem*`.
