# EntropicMem v3: storage foundations

This is the map of the v3 storage core (`plugins/entropicmem/scripts/em/`) as of Sprint 2. It covers what each layer is for, the rules that keep it safe, and step-by-step recipes for adding to it. Read it before building on `em/`. The master plan says what to build; this file says how the existing pieces must be used.

If this file and the code disagree, the code is the fact. Fix whichever is wrong, and say which in the PR.

## Layers

```
Hermes provider (plugins/entropicmem/__init__.py)   <- unchanged in S2; talks to one engine API
        |
        v
em.facade  (EM-211)       contract.py: the exact API + behaviours the provider relies on
        |                 (facade implementation: EM-211, proven by tests/parity/)
        v
em.formation              entity_linker.py (EM-208): turns memories into graph links
em.jobs   (EM-209)        worker.py: claims jobs, runs handlers OUTSIDE transactions
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
  backup.py    EM-210     BackupManager: verified snapshots, rotation, guarded restore
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
mgr = BackupManager(db_path)              # backups in <db dir>/backups
info = mgr.create(reason="manual")        # verified, manifested, 0600
mgr.verify(info).ok                       # re-hash + integrity + audit chain
mgr.rotate(keep=7, keep_safety=5)
mgr.restore(info)                         # refuses live paths, a running provider, bad backups
mgr.restore(info, allow_live=True)        # real restore; stop the provider first
```

Scheduled backups: `enqueue_daily_backup(JobQueue(conn))`, handled by `make_backup_handler(mgr)`.

## What's next, and what each card builds on

- **EM-211 (legacy facade).** Implement `LegacyEngine` over `em.store`, add it to `ENGINES` in `tests/parity/test_engine_parity.py` and to `_implementations()` in `tests/unit/test_em_facade_contract.py`, and pass both unchanged. The two known hard parts:
  - `id-from-content`: the provider finds mirrors by `sha256(content)[:16]`, so store that as `legacy_id` on `remember`.
  - The open `mirror-scan` item: replace `engine.db` in `_locate_mirror` with a method on both engines.
- **EM-212 / EM-213.** The acceptance criteria are the strict xfails at `tests/regressions/test_findings_v27.py:670` and `:693`. They must flip to passing, not be deleted. Re-implement from the plan; the closed pre-2.8.0 attempt is not a source.
- **EM-303 (embeddings, S3).** An `embed` job handler. Jobs are already queued by `MemoryStore.add`. Upsert into `embeddings` on `(owner_type, owner_id, model)` so re-runs are harmless.
- **Wiring `EntityLinker`.** Run it from a job (`link:<memory_id>:<version>`), not inside `MemoryStore.add`, to keep entity work out of the write transaction.
