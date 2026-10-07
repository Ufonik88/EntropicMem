# EntropicMem v3: storage foundations

This is the map of the v3 storage core (`plugins/entropicmem/scripts/em/`) as of Sprint 2. It covers what each layer is for, the rules that keep it safe, and step-by-step recipes for adding to it. Read it before building on `em/`. The master plan says what to build; this file says how the existing pieces must be used.

If this file and the code disagree, the code is the fact. Fix whichever is wrong, and say which in the PR.

## Layers

```
Hermes provider (plugins/entropicmem/__init__.py)   <- unchanged in S2; talks to one engine API
        |
        v
em.facade  (EM-211)       contract.py: the exact API + behaviours the provider relies on
        |                 engine.py: V3Engine, the whole LegacyEngine API over em.store
        |                 select.py: which engine a store needs, by user_version
        |                   (the PROVIDER and the CLI both select it — Chunks 9, 10.
        |                    A chunk leaves it alone unless it is a release; the
        |                    cutover is the owner's act.)
        v
em.formation              entity_linker.py (EM-208): turns memories into graph links
em.retrieval (S3)        query.py: AnalyzedQuery (EM-301 fills in the analyzer)
                          temporal.py: TimeRange (EM-310 fills in the parser)
                          candidates.py: EM-302's generators (bm25, entity,
                          episodic, recent, pinned), Candidate, RetrievalContext,
                          and scope_sql (the §3.5 rule as SQL, cross-checked
                          against _in_scope over a row matrix). vector is EM-303's.
em.jobs   (EM-209)        worker.py: claims jobs, runs handlers OUTSIDE transactions
                          cli.py: `entropicmem worker run`, the cron entry point (refuses a live path)
        |
        v
em.store                  the storage core; every module takes a connection the caller owns
  db.py        EM-202     open_db(), write_txn(), Store (per-thread readers, one writer)
  locking.py   EM-202     portable FileLock (fcntl / msvcrt)
  migrations/  EM-203/4   numbered, checksummed, backed-up, contiguous; 0003 = audit triggers
  memories.py  EM-205     MemoryStore: add/update/supersede/set_status/get/list/touch/purge
  audit.py     EM-206     hash-chained audit_log: append() inside the caller's txn, verify()
  episodes.py  EM-207     episodes + content-addressed transcript chunks
  entities.py  EM-208     entities, aliases, relations, two-sighting promotion
  jobs.py      EM-209     JobQueue: durable queue over the jobs table
  backup.py    EM-210     BackupManager: verified snapshots of memory + index, rotation, guarded restore
em.clock                  the only source of time and ids (freezable in tests)
```

`em.*` is standard-library only. It never imports the Hermes host or the provider, and never reads `HERMES_HOME`; paths are passed in.

## The invariants

Breaking any of these is a bug even if every test passes. Each one names what enforces it today.

1. **Transactions belong to the caller.** Store modules run SQL on the connection they're given and never commit. Group work with `Store.transaction()` (which is `write_txn`, `BEGIN IMMEDIATE`). Never nest transactions. *Enforced by: convention, and reviewers.*
2. **No slow work inside a write transaction.** Embeddings, LLM calls, network, anything that can hang: enqueue a job instead. `MemoryStore.add` queues `embed:<id>:<version>` and returns. The worker runs handlers with no transaction open. *Enforced by: `test_handler_runs_outside_any_write_transaction`.*
3. **Every change writes an audit row in the same transaction.** Call `audit.append(conn, action, actor, target_id, detail)` before the transaction ends. `detail` values are capped at 128 characters, so content never enters the log. The log is append-only (triggers from `0002`/`0003`) and hash-chained (`audit.verify`). *Enforced by: the audit tests and `test_em_migration_0003.py`.*
4. **Time and ids come from `em.clock`.** Use `utc_now()`, `to_iso()` and `new_id(prefix)`. Timestamps are fixed-width UTC strings, so SQL string comparison is time comparison. Never call `datetime.now()` in `em/`. *Enforced by: convention.*
5. **Scope on every read.** Memories are per profile and user (`Scope`). A read that ignores scope leaks one profile into another. *Enforced by: `MemoryStore._in_scope` and its tests.*
6. **Forgetting means forgetting.** `purge` removes the row and everything derived from it: versions, relations, entity links, outbox rows, entity sightings, and (EM-705) embeddings and vault projections. Anything new that stores text derived from a memory must be added to `purge`, with a test that the text is gone from `iterdump()`. *Enforced by: the EM-208 follow-up purge tests.*
7. **Applied migrations never change.** They are checksummed. To fix one, add a new migration (see `0003`). Numbering is contiguous, and every migration runs after a verified backup. Development code refuses live paths (`assert_safe_db_path`); the real cutover opts in with `ENTROPICMEM_ALLOW_LIVE_MIGRATION=1`, and only with the owner's explicit go-ahead. *Enforced by: `test_em_migrations.py`.*
8. **Nothing in development touches the live store.** That means `~/.hermes/entropicmem*`. Run tests with `ENTROPICMEM_MEMORY_DB`, `ENTROPICMEM_VAULT_PATH` and `ENTROPICMEM_INDEX_DB` unset. Measure on *copies*. A test that exercises a safety guard must never point at the real path: if the guard regresses, the test would do the damage itself (see `test_restore_refuses_a_non_test_path_and_touches_nothing`).
9. **Every `em` subpackage is listed in `pyproject.toml`.** *Enforced by: `test_pyproject_lists_every_em_subpackage`.*
10. **Portable.** Windows runs `tests/unit` in CI. Don't assert POSIX mode bits on Windows, build `file:` URIs with `Path.as_uri()`, and close every connection explicitly (`contextlib.closing`), because an open handle locks the file on Windows.

## Repo guards that are not invariants

These run inside the ordinary gate, or as their own CI job, and they are easy to trip without knowing they exist.

| Guard | What it refuses |
|---|---|
| `scripts/check_commit_identity.sh` (CI job `identity-guard`) | Any commit whose author or committer is not a noreply address (`*@users.noreply.github.com`, `noreply@github.com`, `noreply@anthropic.com`). On a push it checks the whole history reachable from the pushed commit. |
| `tests/test_privacy_guard.py` | Any identifier from the private digest list, in any file including fixture databases. The list itself lives outside the repo: `~/.config/entropicmem/privacy-digests.txt`, or the CI secret. |
| `tests/test_docs_links.py` | A relative link in `docs/`, `skills/` or the four root Markdown files whose target is missing, **or** exists only on your disk (CI checks out tracked files, so a local-only target is broken there). |
| `tests/test_cli_reference_drift.py` | A top-level CLI command whose count in `docs/CLI_REFERENCE.md` or `README.md` no longer matches argparse, or that has no reference entry. |
| `tests/test_master_todo.py` | The document-control rule (`AGENTS.md`): `MASTER_TODO.md` must exist, carry its sections, be linked from `AGENTS.md` and the README, record a SHA that is a real ancestor of the branch, and not claim a chunk is merged while its In flight section says it is not. |
| `tests/test_plugin_imports.py` | A deferred `from X import Y` in the provider that does not resolve against the real modules (AST scan). |
| `tests/test_backend_namespace.py` | A bare `import vault`-style engine import returning to `_backend.py`, plus EM-212's package-namespace acceptance criterion — a real (no longer xfail) test since Chunk 8. |
| `tests/unit/test_em_store_concurrency.py`, the `perf-smoke` job | The EM-202 concurrency budget and the §6.4 prefetch budget. Both have flapped once already. `REMAINING_PLAN.md` §8 and §11 record how to tell a flake from a regression, and neither budget may be widened to clear a red gate. |

## Recipes

### Add a job type

1. Pick a type name and a dedupe key that identifies the *work*, not the attempt, for example `embed:<memory_id>:<version>` or `backup:<YYYY-MM-DD>`. Work that recurs puts its period in the key.
2. Enqueue inside the transaction that creates the need: `JobQueue(conn).enqueue(type, payload, dedupe_key=...)`. The payload holds ids, never content.
3. Write the handler as `def handler(job, ctx) -> None`:
   - **It must be idempotent,** because delivery is at-least-once. Upsert results, and check whether the work is already done.
   - Open your own short transactions with `ctx.store.transaction()`.
   - Raise `PermanentJobError` for input that can never succeed (a missing memory, a bad payload).
   - Call `ctx.heartbeat()` in long loops, and stop if it returns False.
   - Keep content out of exception messages.
4. Register it: `registry.register(type, handler, lease_seconds=...)`. The lease must exceed the handler's worst normal runtime.
5. Test it:
   - the handler through `JobWorker(...).run_until_idle()`;
   - a re-run of the same job (idempotency);
   - the permanent-failure path.

   `make_backup_handler` in `em/store/backup.py` is a complete worked example.

### Add a migration

1. Create `em/store/migrations/NNNN_<slug>.py` with `VERSION`, `NAME` and `up(conn)`. The next number is `LATEST + 1`.
2. It must be self-contained: copy constants in, don't import helpers that could change under the checksum. `em.clock` is the one allowed import.
3. Never commit inside `up()`, and never use `executescript` (it commits implicitly).
4. Test it:
   - a fresh install;
   - a store already at `NNNN-1`;
   - a migrated v2 fixture (`tests/fixtures/db/v2_*.db`);
   - idempotency.
5. Update any test that pinned the previous `LATEST` so it says what it means ("reaches LATEST"), not a bumped number.

### Add a store module

1. `class XStore: def __init__(self, conn)`. Plain SQL on the caller's connection, no commits.
2. Every write goes in the same transaction as its `audit.append`.
3. Anything derived from memory text joins `purge` (invariant 6).
4. List any new subpackage in `pyproject.toml`; the test will tell you if you forget.

### Back up and restore

```python
from em.store.backup import BackupManager

mgr = BackupManager(db_path)              # backups live in <db dir>/backups
path = mgr.snapshot(reason="manual")      # writes a directory, returns it (0700)
info = mgr.create(reason="manual")        # the pre-3.1 name: same snapshot, returns the details
mgr.verify(info).ok                       # re-hash every file + integrity + audit chain
mgr.rotate(keep=7, keep_safety=5)
mgr.restore(info)                         # refuses live paths, a running provider, bad backups
mgr.restore(info, allow_live=True)        # real restore; stop the provider first
```

A snapshot is a directory (Chunk 3.1): `backups/<reason>-<stamp>/` holds
`memory.db`, `index.db` when the index exists, and `manifest.json`, which lists
every file with its role, source name, sha256, size, row counts and
`user_version`. `index_path` defaults to the `index.db` beside the memory
database; pass it explicitly for another layout. A snapshot fails **whole** if
any of its databases cannot be copied, and the partial directory is removed:
a backup that silently omitted the index would be worse than none.

Snapshots written before 3.1 (`<reason>-<stamp>.db` beside
`<reason>-<stamp>.json`, manifest `format: 1`) stay listed, verified and
restorable. Rotation counts both layouts under one policy, and nothing rewrites
or deletes a legacy file.

Restore stages every file of the snapshot first and swaps only when all of them
verify, so a half-restored store cannot happen. A snapshot without an index
never touches the live one.

Scheduled backups: `enqueue_daily_backup(JobQueue(conn))`, handled by `make_backup_handler(mgr)`.

## What's next, and what each card builds on

- **EM-211 (legacy facade).** Split into four chunks: **reads → writes → mirror → linker** (plan §6.1, `docs/plan/REMAINING_PLAN.md`). **Reads landed 2026-10-02 (`0349b7b4b`); writes and the mirror call merged at `e25db32` (`36355f3`, `6bd4b47`); the link job (7.1) merged at `64a2685` (`96c4ccb`).** So `V3Engine` implements the whole provider-facing `LegacyEngine` contract over `em.store`, and `PROVIDER_ATTRIBUTES` is **empty** — the provider no longer reads a raw connection anywhere, which was the last thing only v2 could serve. It is registered in `_implementations()` in `tests/unit/test_em_facade_contract.py` and in both `ENGINES` and `WRITE_ENGINES` in `tests/parity/test_engine_parity.py`. **Nothing is wired into the provider yet**: the provider still constructs `MemoryEngine`, so the card's AC and S2's exit criteria are still unmet. What remains:
  - **Chunk 7.1 — the link job: DONE (`96c4ccb`, committed, not merged).** `MemoryStore` enqueues `link:<memory_id>:<version>` beside the `embed` enqueue; `make_link_handler` in `em/formation/entity_linker.py` runs the linker outside any write transaction (invariant 2) and is idempotent across a retry; `entropicmem worker run` registers the type.
  - **Chunk 7.2 — the §3.5 owner-only rule: DONE (`563afe5`, committed, not merged).** A `sensitive`/`secret` row is readable only by its owner, enforced in `_in_scope` and applied on all four facade read paths. `Scope.is_owner` defaults to **False** (fail-closed); a profile-wide caller (`user == ""`) is the owner context, so the default facade and the CLI are unaffected. `V3Engine` takes `is_owner` as a constructor argument.
  - **Chunk 9 — the provider's engine selection: DONE (`em/em-211-provider-wiring`, committed, not merged).** `em/facade/select.py` picks by `PRAGMA user_version`, read **read-only before any engine is constructed**, so opening a v2 store cannot migrate it; all nine `MemoryEngine(` sites in the provider route through one `_open_engine()`. The gateway identity is threaded in (`is_owner = not _is_guest()`).
  - **Chunk 10 — CLI parity: DONE (`em/em-211-cli-routing`, committed, not merged).** The reads (10.1), the maintenance calls (10.2) and the by-name refusals (10.3) landed; 10.4 routes `_engine()` through `select.py`, so the CLI serves either engine. **The AC is met except for seven v2-only features, each refused by name with the card that lifts it.**

### The facade's write rules worth knowing before you build on it

These are decisions the writes chunk made that are not obvious from the signatures:

- **`legacy_id` is stamped on profile-wide writes only.** `memories.legacy_id` is `UNIQUE` and content-derived. v2 used that id as the primary key with one owner per database; v3 scopes every row to a user, so two users storing the same sentence are two facts that would collide on one hash. `remember` therefore stamps `sha256(content)[:16]` when `scope.user == ""` and leaves it empty otherwise. That is what keeps `get_fact(StoredFact.make_id(content))` — the provider's mirror lookup — exactly as reliable as v2. An extracted candidate never stamps it at all: it is not a content-addressed mirror row.
- **Writes that destroy or archive take a throttled snapshot** via `BackupManager.snapshot_if_due(reason=...)`, *outside* the write transaction (§3.3). Reasons are `pre-forget` and `pre-consolidate`. This is what makes EM-210's "100 forget calls → at most 1 snapshot/hour" true through the facade, rather than v2's unthrottled per-call `_backup()`.
- **Deleting is a status change.** `forget` and `consolidate` move rows through the §3.4 machine (`deleted` / `archived`) rather than deleting or copying to a side table. `get_fact` reads a terminal row as absent and `stats` counts only `active`, so callers see v2's behaviour while the row and its version history remain for the audit trail. `forget(id, confirm=True)` returns `False` when there is nothing left to take, so forgetting twice is `False` the second time.
- **Extraction writes one row, not two.** An `auto_extracted` source is routed to `pending` by the shared write policy, and promotion is the `pending -> active` edge. v2 kept a `pending_facts` row *and* wrote a separate durable fact; here the quarantine record and the memory are the same versioned row.
- **`add_episode` stamps `episodes.legacy_id`,** which is what `next_episode_wave` reads, so the `{base}_wN` cadence numbering survives the cutover. A caller-supplied `episode_id` upserts in place, because the provider derives it from the session id and refires it. `linked_fact_ids`, `domain` and `source` are accepted and ignored: v3's `episodes` table has no column for them, and adding one would mean a migration.
- **`find_mirrored` is the one scoped read the facade has.** `_locate_mirror`'s substring fallback used to run against `engine.db`, so on v3 it filters `status='active'` (a forgotten mirror must not be locatable, or a replace resurrects it), applies the §3.5 scope rule (one user cannot locate another's mirror, while a profile-wide row stays visible), and matches `mirrored` as a whole tag. Because v3 stores tags as a JSON list, the quoted `LIKE '%"mirrored"%'` is only a cheap pre-filter — the parsed **list** decides, and the parse insists on a list, since the JSON scalar `"mirrored"` would otherwise pass both. The other reads (`get_fact`, recall) are still profile-wide; that gap closes with the linker chunk.
- **Sensitive reads are owner-only, and the rule lives in `_in_scope`.** A row whose tier is `sensitive`/`secret` is visible only to its owner; a profile-wide row is not restricted (that stays shared knowledge for the profile). "Owner" is a profile-wide caller (`user == ""`) or one that asserts `is_owner`. The facade routes all four read paths through the same `_in_scope`, rather than duplicating the rule in SQL where it could drift. `MemoryStore.list` is the exception: it keeps profile+user only, so `prune_pending`/`consolidate` are not tier-filtered — a recorded gap for the wiring chunk.
- **Recorded deviations from v2, each pinned by a test:** no fuzzy overwrite (v2's EM-109 near-duplicate rule could rewrite a stored fact in place; v3 collapses only *exact* duplicates), and no deprecation warnings (the card asks for once-per-process warnings on methods "suled for removal in 3.1", but v2 emits none, no list of which methods is recorded, and the provider calls all of them every session).
- **EM-212 — DONE (Chunk 8, 2026-10-07).** The six shared-name engine modules (`vault`, `index`, `security`, `policy`, `embeddings`, `retrieval`) now live under the `em_internal` package, so the import system registers `em_internal.*` and never the bare names; `_backend._own_module` (the 2026-09-27 first step) is gone in favour of a qualified import, because a qualified name cannot collide. The strict xfail `test_em212_plan_ac_no_unprefixed_engine_modules_in_process` **flipped to a passing test**. The other 14 modules keep unprefixed names deliberately — the AC names only the six. The packaging guard now derives every package under `scripts/` from disk, so a new one cannot ship missing from the wheel.
- **EM-213** is done, re-scoped on 2026-09-26: the Hermes catalog verifies the plugin against `provides_tools`/`provides_hooks`, so they stay and only the duplicate `hooks:` list went. `test_f011_plugin_manifest_declares_tools_and_hooks_once` pins it. Do not remove the provides lists.
- **EM-303 (embeddings, S3).** An `embed` job handler. Jobs are already queued by `MemoryStore.add`. Upsert into `embeddings` on `(owner_type, owner_id, model)` so re-runs are harmless.
- **Wiring `EntityLinker`.** Run it from a job (`link:<memory_id>:<version>`), not inside `MemoryStore.add`, to keep entity work out of the write transaction.
- **§3.5's `visibility` half is not implemented — a recorded privacy gap, not a settled one.** §3.5 makes a *profile-wide* row (`scope_user=''`) owner-only when `sensitivity IN ('sensitive','secret')` **or `visibility='user'`**. `_in_scope` implements the tier half only. It matters because `MemoryDraft.visibility` defaults to `'user'`, so a profile-wide write made with the default is, per the plan, owner-only — and today it is not. That is a leak in the tightening direction, so it needs fixing rather than only recording; it is left for its own card because implementing it reclassifies rows that already exist, and `MemoryStore.list` (`scope_user=?` exactly, no tier filter) would need the same treatment. On `MASTER_TODO.md` under gaps.
- **§3.5's chat half now lives in one place (Chunk 11, EM-302).** `scope_chat IN (<chat>, '')` was already emitted by `MemoryStore.list` but not by the row predicate `_in_scope`. `em.store.types.chat_in_scope` is now the single decision, called by `_in_scope` and rendered into SQL by `scope_sql`; a no-op while `scope.chat` is empty (every caller today). The scope cross-check matrix includes chat rows, so the two forms cannot drift again.
- **EM-302's `vector` generator is EM-303's, deliberately.** §3.6 gates it on an embedding backend ("only if backend available and coverage ≥ 50%") and forbids re-reading vector blobs per query, so it belongs with the backends and the numpy cache. `em/retrieval/__init__.py` records it.
- **EM-302's "current session" `recent` window is not wired.** §3.6 reads "in current session / last 48 h"; the 48 h window is implemented, and the session half needs a session id that the card's `RetrievalContext` (aq, scope, now, limits, deadline) does not carry. It also needed a read connection, so `RetrievalContext` carries `conn` as well — the one field added beyond the card's list, because the stated signature `(ctx) -> list[Candidate]` leaves a generator nowhere else to get one.

## Recorded deviations from the plan

The code is the fact. These lines are the plan's words, what the code does, and why the difference stays.

| Card | Plan says | Code does | Decision |
|---|---|---|---|
| EM-209 | files `em/store/jobs.py`, `em/worker.py` | `em/store/jobs.py`, `em/jobs/worker.py` | keep (package holds registry + context) |
| EM-209 | `claim(worker_id, types, lease_s=60)` | `claim(worker_id, *, types, lease_seconds=60)` | keep (keyword-only is safer) |
| EM-209 | backoff `2^attempts * 30s` | `30·2^(attempts-1)`, cap 3600 s, ±10 % jitter | keep (same curve one step earlier, capped, jittered; tested) |
| EM-209 | `Worker(handlers, stop_event, budget_s)`, per-job `time_budget`, cooperative cancellation | `JobWorker(store, registry)`, `run(stop)`, leases + `ctx.heartbeat()` | keep; a per-job time budget is a later card if a real job needs it |
| EM-210 | `snapshot(reason) -> Path`, memory.db **+ index.db**, `backups/<ts>-<reason>/` dirs, EM-113 retention, once per hour per reason, AC: 100 `forget` → ≤ 1 snapshot/hour | **done:** Chunk 3.1 the layout (`snapshot(reason) -> Path` over memory.db + index.db in `backups/<reason>-<stamp>/`, `create()` kept as an alias, pre-3.1 flat backups still read); Chunk 3.2 the throttle (`snapshot_if_due(reason, *, window=3600)` → `None` inside the window, safety reasons exempt, window from the manifests' `created_at`, no schema); Chunk 5 the facade's `forget` and `consolidate` call it with `pre-forget` / `pre-consolidate`, outside the write txn | **settled (2026-09-29):** retention stays 7 routine + 5 safety; the AC is met by the throttled entry point, not by `snapshot()` itself |
| EM-211 | `promote_pending` re-stamps `source="promoted"` and adds a `"promoted"` tag (v2 did, via a fresh `remember`) | v3 promotion is the `pending -> active` edge, so the row keeps its `auto_extracted` source and gains no tag — the store does not allow editing `source` | keep: one row with one history is the point of the v3 model; the consequence (a promoted row is consolidation-eligible like any other) is recorded in the CHANGELOG |
| EM-211 | `pii_locales` reaches the engine | routed to the v2 engine only: v3 redaction is `pii.redact_pii` with no locale packs, so a v3 store loses the locale-aware PII pass v2 had. Recorded in Chunk 9 |
| EM-211 | `remember` stores `make_id(content)` as `legacy_id` so the read half's lookup keeps working; deprecation warnings once per process for methods slated for removal in 3.1; fuzzy overwrite as in v2 | **`legacy_id` stamped on profile-wide writes only** (`memories.legacy_id` is UNIQUE and content-derived, and v3 scopes rows per user); **no deprecation warnings** (v2 emits none and no list of methods is recorded anywhere); **no fuzzy overwrite** (exact duplicates only) | keep all three: the stamp is narrower for a real uniqueness reason, and the other two would be behaviour changes the provider has never seen. Chunk 5; see "The facade's write rules" above |

