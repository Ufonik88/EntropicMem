# EntropicMem v3: storage foundations

This is the map of the v3 storage core (`plugins/entropicmem/scripts/em/`) as of Sprint 2. It covers what each layer is for, the rules that keep it safe, and step-by-step recipes for adding to it. Read it before building on `em/`. The master plan says what to build; this file says how the existing pieces must be used.

If this file and the code disagree, the code is the fact. Fix whichever is wrong, and say which in the PR.

## Layers

```
Hermes provider (plugins/entropicmem/__init__.py)   <- unchanged in S2; talks to one engine API
        |
        v
em.facade  (EM-211)       contract.py: the exact API + behaviours the provider relies on
        |                 engine.py: V3Engine, the whole LegacyEngine API over em.store.
        |                   Its read half has a second, flag-gated mode (P0b): with
        |                   ENTROPICMEM_V3_RETRIEVAL=1 it serves em.retrieval's pipeline
        |                   instead of the v2 scoring it otherwise borrows; unset is
        |                   byte-identical to pre-P0b (golden-pinned).
        |                 select.py: which engine a store needs, by user_version
        |                   (the PROVIDER and the CLI both select it — Chunks 9, 10.
        |                    A chunk leaves it alone unless it is a release; the
        |                    cutover is the owner's act.)
        v
em.formation              entity_linker.py (EM-208): turns memories into graph links
em.retrieval (S3)        query.py: AnalyzedQuery + analyze() — EM-301's text
                          normalisation, IDF term selection, intent, entity
                          detection and the common temporal shapes; stopwords.py:
                          the 180-word list (the same set v2 uses); temporal.py:
                          TimeRange. candidates.py: EM-302's generators (bm25,
                          entity, episodic, recent, pinned), Candidate,
                          RetrievalContext, and scope_sql (the §3.5 rule as SQL,
                          cross-checked against _in_scope over a row matrix).
                          fusion.py: EM-304's weighted RRF, feature rerank,
                          deterministic tie-break and explanation, with the
                          feature loader; gate.py and diversity.py: EM-305's
                          abstention gate, the collapse and MMR; pipeline.py:
                          retrieve() — the one shared sequence, called by the v3
                          eval adapter, the shadow read (P0a) and the facade's
                          flag-gated read half (P0b); EM-303 is closed:
                          candidates.vector searches stored vectors, MMR uses
                          them when present, em.embeddings holds the backends,
                          embed jobs and the snapshot cache; the
                          full temporal grammar is EM-310's.
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
em.config                 EM-306's calibrated scalars (committed; not yet read by call sites)
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
| `tests/test_cited_shas.py` | A SHA-like token (7–40 hex chars) in tracked markdown, or in the message of a commit not yet on the base branch, that does not resolve to a commit — unless it is in the file's closed, reasoned allowlist (the seven dead SHAs, the upstream fork commit, the tag-name date; an entry must stay cited and unresolvable). Published history is deliberately out of scope: it is never rewritten and legitimately cites dead and upstream SHAs. |
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

- **EM-211 (legacy facade).** Split into four chunks: **reads → writes → mirror → linker** (plan §6.1, `docs/plan/REMAINING_PLAN.md`). **Reads landed 2026-10-02 (`0349b7b4b`); writes and the mirror call merged at `e25db32` (`36355f3`, `6bd4b47`); the link job (7.1) merged at `64a2685` (`96c4ccb`).** So `V3Engine` implements the whole provider-facing `LegacyEngine` contract over `em.store`, and `PROVIDER_ATTRIBUTES` is **empty** — the provider no longer reads a raw connection anywhere, which was the last thing only v2 could serve. It is registered in `_implementations()` in `tests/unit/test_em_facade_contract.py` and in both `ENGINES` and `WRITE_ENGINES` in `tests/parity/test_engine_parity.py`. **The provider and the CLI both select their engine by `user_version` (Chunks 9–10), and P0b (Chunk 18) makes a v3 store serve its read half from `em.retrieval` behind `ENTROPICMEM_V3_RETRIEVAL`** — so the card's AC is met except for the seven v2-only refusals, and what remains is the cutover (the owner's act). **Chunks 7.1–10, all merged:**
  - **Chunk 7.1 — the link job: DONE, MERGED (`96c4ccb` in `64a2685`).** `MemoryStore` enqueues `link:<memory_id>:<version>` beside the `embed` enqueue; `make_link_handler` in `em/formation/entity_linker.py` runs the linker outside any write transaction (invariant 2) and is idempotent across a retry; `entropicmem worker run` registers the type.
  - **Chunk 7.2 — the §3.5 owner-only rule: DONE, MERGED (`563afe5` in `783aae9`).** A `sensitive`/`secret` row is readable only by its owner, enforced in `_in_scope` and applied on all four facade read paths. `Scope.is_owner` defaults to **False** (fail-closed); a profile-wide caller (`user == ""`) is the owner context, so the default facade and the CLI are unaffected. `V3Engine` takes `is_owner` as a constructor argument.
  - **Chunk 9 — the provider's engine selection: DONE, MERGED (`b615bcf` in `0200424`).** `em/facade/select.py` picks by `PRAGMA user_version`, read **read-only before any engine is constructed**, so opening a v2 store cannot migrate it; all nine `MemoryEngine(` sites in the provider route through one `_open_engine()`. The gateway identity is threaded in (`is_owner = not _is_guest()`).
  - **Chunk 10 — CLI parity: DONE, MERGED (`250320a` in `c50d7b6`).** The reads (10.1), the maintenance calls (10.2) and the by-name refusals (10.3) landed; 10.4 routes `_engine()` through `select.py`, so the CLI serves either engine. **The AC is met except for seven v2-only features, each refused by name with the card that lifts it.**

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
- **EM-303 (embeddings, S3) — CLOSED and merged (`e8997d8` as `3439b77`);
  search and MMR were merged earlier.**
  `em/store/embeddings.py` decodes the native float32 blobs v2 already writes and
  a stdlib cosine; `candidates.vector` searches active, in-scope memories only
  when `retrieve` was given a query vector and a model **and** ≥ 50% of active
  memories in scope carry a vector for that model; `diversity.mmr` takes a
  pairwise `similarities` callable and the pipeline supplies cosine (clamped at
  0) with a per-pair Jaccard fallback. The closing slice adds: the four backends
  (`fastembed` default, `sentence_transformers`, `openai_compat`, `none`) with
  `auto` selection and a silent `none` fallback, all optional imports lazy; the
  `embed`/`embed_backfill` handlers (`embed` re-checks the row version **inside
  the write transaction**; `embed_backfill` pages 64 and records
  `meta.embedding_model` only on completion; `ensure_embedding_model` dedupes;
  a backend-less box no-ops); and the snapshot cache (`em/embeddings/cache.py`)
  keyed by `(db, model, scope, mode)`, fingerprint `(count, max rowid, write
  generation)`, numpy or pure Python, behind migration 0005's index.
  **No embedding call ever runs on the agent/prefetch thread**, and a query with
  no caller-supplied vector does no vector work at all. **The follow-up slice
  (on `em/em-303-gaps`, not merged)** makes `EpisodeStore` an embedding producer
  (`add_episode`/`upsert_episode` enqueue; the handler and backfill cover
  episodes with `updated_at` as the stale guard) and has the v3 eval adapter
  embed documents and the query when a suite allows embeddings. **What is still
  absent by design:** the **provider** does not embed a query yet — EM-401–403
  call `ensure_embedding_model` at initialize and embed the query; and capture
  on idle/compaction is **planned as EM-411** (plan §6.3) — there is **no host
  idle hook** in the pinned contract, so idle is defined behaviourally.
  **Recorded deviation:** the cache keys by scope and loads through
  `scope_sql` instead of the card's "pre-computed id→scope arrays (mask)" —
  a numpy copy of the §3.5 owner rule is a second definition of a privacy
  rule, and the two would drift. **Recorded caveat:** a raw-SQL rewrite of a
  vector that leaves count, max rowid and the generation unchanged is not
  re-read until the cache resets; every `put_embedding` write is seen.
- **Wiring `EntityLinker`.** Run it from a job (`link:<memory_id>:<version>`), not inside `MemoryStore.add`, to keep entity work out of the write transaction.
- **Session capture: what exists and what EM-411 adds.** The v2 provider already
  captures on `on_session_end` (`session_end_capture`) and on a turn cadence
  (`turn_cadence_flush_turns`/`turn_cadence_min_interval_sec`); `on_pre_compress`
  checkpoints standing constraints only. There is **no host `idle` event** — the
  hook contract has `on_turn_start`, `on_session_end` and `on_pre_compress`.
  EM-411 makes compaction capture real (enqueue `extract_window` over EM-406's
  persisted precompress chunks, dedupe per session+window) and defines idle
  behaviourally (a turn gap ≥ `formation.idle_after_sec` seals the window).
  Do not invent an idle event; if a future host adds one, wire it to the same
  enqueue.
- **§3.5's `visibility` half is implemented (Chunk 13) — write stamp *and* read guard, agent-proposed and internal only.** Two row conditions, one definition: `em.store.types.row_is_owner_only` returns True for a `sensitive`/`secret` tier **or** for a *profile-wide* row (`scope_user=''`) stamped `visibility='user'`; `_in_scope` and `candidates.scope_sql` both call it, and the chat dimension goes through `chat_in_scope` the same way. The write side derives `MemoryDraft.visibility` from the scope (`'profile'` profile-wide, `'user'` otherwise, explicit preserved) — **and the direction matters**: the read clause alone would have hidden every profile-wide memory from non-owners. **Reversible: no migration, no rewrite of existing rows**, so a code revert is the whole story; rows written while it is live keep their stamp, which is why a revert restores future behaviour rather than history. It is in no release and needs the owner's explicit approval before one. **`MemoryStore.list` deliberately keeps `scope_user=?` exact** — a scoped caller can only receive rows already scoped to them, so the profile-wide rules govern rows it cannot return; that is why the Chunk 7.2 note is not a leak. See the `## Recorded deviations` note on publication below.
- **§3.5's chat half now lives in one place (Chunk 11, EM-302).** `scope_chat IN (<chat>, '')` was already emitted by `MemoryStore.list` but not by the row predicate `_in_scope`. `em.store.types.chat_in_scope` is now the single decision, called by `_in_scope` and rendered into SQL by `scope_sql`; a no-op while `scope.chat` is empty (every caller today). The scope cross-check matrix includes chat rows, so the two forms cannot drift again.
- **EM-302's `vector` generator landed, in full (EM-303).** `candidates.vector`
  searches embeddings already stored; it does not embed, and it is inert unless
  the caller supplies a query vector and a model (`retrieve(query_vector=,
  embedding_model=)`). MMR uses a cosine-then-Jaccard pairwise similarity in the
  same mode. The backends, the `embed` jobs and the numpy cache are merged;
  the query embedding is the provider cards' (EM-401–403) and the eval
  adapter's (when a suite allows it). `em/retrieval/__init__.py` records it.
- **§3.6's IDF cache has no key, and its cache key is the reason (EM-301).** §3.6
  says the IDF table is "cached per `write_generation`". **Nothing in the store
  defines or maintains a `write_generation`** — there is no counter and no `meta`
  key for it — so `em.retrieval.query.vocabulary` reads the view on each call. The
  view is a cheap indexed read and this is correct today; the cache wants the
  counter, which is a store change and not the analyzer's. Recorded so the next
  reader does not think the cache exists.
- **Coverage is measured with the tokenizer itself (EM-305).** §3.6 defines
  coverage "post-stem" and the gate is a **hard filter**, so a Python-only
  comparison under-counts on every stem the surface form hides and silently
  abstains on answers the generators had found. `gate.coverage` puts the candidate
  texts into a transient in-memory FTS5 declared with the *same* tokenizer as
  `memories_fts` and matches each query term once. Do not "simplify" it into a
  substring or token-set test.
- **`gate.*` config does not exist either (EM-305).** Same gap as `ranking.*`:
  `gate.GateConfig` carries §3.6's numbers as overridable defaults, and EM-407 owns
  the config module. The gate's cosine condition can now be switched on
  (EM-303 first slice): `retrieve` does it for the call, **only when it was given
  both a query vector and a model and no explicit `gate_config`**; an explicit
  config always wins. MMR's embedding path is the same seam (EM-303, merged):
  when a query vector and a model were given,
  `mmr` gets a cosine-then-Jaccard pairwise similarity (negative cosine clamped
  to 0); without them it is the token-Jaccard fallback as before.
- **P0b: the facade's read half has a flag-gated S3 mode (Chunk 18).**
  `V3Engine.recall_with_relevance` serves v2's borrowed scoring with
  `ENTROPICMEM_V3_RETRIEVAL` unset (**the default**; byte-identical to pre-P0b,
  golden-pinned) and `em.retrieval.pipeline.retrieve` — **with the gate** — when it
  is strictly `"1"`. The mapping back to v2 `StoredFact`s is deliberately narrow:
  **memories only** (an episode ranking has no v2 fact shape, and §3.6's render is
  EM-307's; episodes are a recorded omission from served prefetch), `legacy_id` as
  the id so dedup/`touch` keep resolving, `fusion.legacy_tokens` as the flat
  `why_retrieved`, and v2's `min_relevance`/decay/evergreen knobs are **not**
  applied over the gate's support test/`min_score` (`domain` is a post-filter). No
  renderer is added: the provider's `_format_block` prints the mapped facts
  unchanged. On a v2 store the flag cannot exist — selection is by `user_version`.
  The flag's default (or a config key) is a later, owner-facing decision.
- **P0b found and fixed the gate's `kind='constraint'` bypass (Chunk 18).** The
  pinned generator surfaces `pinned=1` **or** `kind='constraint'` rows, and §3.6's
  generator table says its hits bypass the gate; `gate.load_rows` read only the
  column, so a constraint with no lexical overlap was filtered. `RowInfo.pinned`
  is now the §3.6 input (column or kind), pinned at the loader and at
  `apply_gate`.
- **§3.6's "exact-hash duplicates across scopes" groups on text, not on the hash
  (EM-305).** `MemoryStore._content_hash` mixes the scope into the digest, so the
  hash cannot see the pair. The collapse groups on the loaded text, which is what
  the hash was derived from.
- **`ranking.*` call sites still use the spec defaults (EM-304 / EM-306).** §3.6
  says the rerank weights live in `ranking.*`. EM-306 committed tuned scalars in
  `em/config.py` and nothing in retrieval reads them — EM-401–403 wire them, and
  EM-407 owns the loader. `fusion.RankWeights` still carries the spec's numbers
  as the default a caller may override. Do not invent a second config system.
- **`superseded_note` renders from a gated retrieval, not from served prefetch
  (EM-304 → EM-305 → EM-307).** The collapse still emits the flag.
  `pipeline.retrieve(..., with_gate=True)` returns the predecessors MMR kept,
  and `render_retrieval` prints `(kind · updated <date>; was: <old>)`. The
  provider's `_format_block` does not call it, and the eval adapter still emits
  full-id bullets. **Merged to `main` (`7d6a22e`)**; switching either caller is a
  separate, measured change.
- **`why_retrieved_tokens` reaches a read path only in P0b's on mode (EM-304).**
  §3.6 keeps the legacy flat token list for one minor version.
  `fusion.legacy_tokens()` converts a `Ranking`, and the facade's flag-gated path
  uses it; giving the v2 scoring path the same flat form is the provider's card.
- **§3.6's `query_rewrite` hook is not wired (EM-301).** §3.6 makes it optional and
  background-only ("never blocking `prefetch`"). There is no config module to
  enable it and no `plugins.memory.query_rewrite` to call, so nothing does. It
  belongs with EM-403 (the prefetch service) and EM-407 (config).
- **`memories_vocab` holds porter *stems*, not words.** `memories_fts` is
  `tokenize='porter unicode61'`, so the `fts5vocab` view §3.6 names carries
  `stage`, not `staging`. A raw-token IDF lookup would miss for every word whose
  stem differs and would silently collapse IDF into length ordering. The view is
  still the base map; `vocabulary` counts each missing term with an FTS5 `MATCH`
  against `memories_fts`, which uses the same tokenizer and so cannot disagree with
  the query the generators run. Do not "simplify" that away.
- **The vocabulary migration is `0004`, not the plan's `0003`.** `0003` is
  `0003_audit_append_only`, and a migration's version is its filename. Its `NAME`
  is a space-free slug because the fresh-subprocess migration test reads the
  applied list from stdout and splits on whitespace.
- **EM-302's "current session" `recent` window is not wired.** §3.6 reads "in current session / last 48 h"; the 48 h window is implemented, and the session half needs a session id that the card's `RetrievalContext` (aq, scope, now, limits, deadline) does not carry. It also needed a read connection, so `RetrievalContext` carries `conn` as well — the one field added beyond the card's list, because the stated signature `(ctx) -> list[Candidate]` leaves a generator nowhere else to get one.

## Recorded deviations from the plan

**One behaviour change this line carries, stated plainly:** `MemoryStore._outbox`
publishes a row when it is not an owner-only tier **and** its visibility is
`'profile'`/`'shared'`. Before Chunk 13 the first half was satisfied by accident —
every profile-wide write was stamped `'user'` by the old default, so nothing
profile-wide was ever queued at all. v2's gate was `_publish_allowed(sensitivity)`,
so v2 published every non-sensitive fact, and Chunk 13 restores that with the tier
check explicit.

**Who consumes the outbox, and what happens to what is already in it** (checked, not
assumed): the only reader is v2's `MemoryEngine.publish()`, draining `emitted=0` into
the shared `sync_events` log. On a v3 store that path is **unreachable** —
`entropicmem publish`/`pull` are refused by name until S5 — and **no `em/` code reads
the outbox at all**; the store writes to it and `forget` deletes from it. **Nothing had
been queued by the old path either:** v2's `_publish_allowed` refuses
`secret`/`sensitive` outright, and v3's old default stamped `'user'`, so `_outbox`
returned early, and no call site ever paired an explicit `'profile'` with a sensitive
tier. So there is **nothing to replay, drop or backfill** — already-queued rows are all
non-sensitive, stay queued, and the v2→v3 migration leaves the table untouched (legacy
`fact_id`s preserved until EM-309).

**The visibility contract is derive-on-write-only, deliberately.** Only new writes
derive a stamp; historical rows are never rewritten, and the read guard changes only
what a non-owner sees. An existing profile-wide row carrying the old `'user'` default is
**owner-only** — §3.5's literal rule, failing closed. Re-deriving those rows is a bulk
change to who may read what, so it would be a one-off owner-approved migration rather
than a silent rewrite; in practice there are none, because v3 was never released and the
live store is v2 (zero facts on the dev box's copy; the owner's holds real data).


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

