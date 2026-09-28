# EntropicMem: next steps (one chunk at a time)

**Updated:** 2026-09-28, safe point closed out. **Read first:** `docs/plan/REMAINING_PLAN.md` (its §3 rules apply to everything here), then `AGENTS.md` and `docs/V3_FOUNDATIONS.md`.

**Plan exactly one chunk.** When a chunk ends, replace this file with the plan for the next single chunk; never more than one ahead.

---

## Part A: release follow-ups — **ALL DONE (2026-09-28)**

- `v2.8.1` tagged at `7e02412`, Release page published;
- `release/2.8.x` protected;
- leftover branches cleaned up;
- plan §5 text pasted;
- cleanup cron verified (ancestor check against `35a02f4`);
- catalog re-pin landed via PR #124936 (Teknium closed #124837, landed it himself);
- fresh install verified on Mac: sha `7e02412`, 7 tools, 5 hooks, remember/recall passed;
- reply to Teknium skipped (owner did not say "post it").

**EntropicMem is at rest.** Feature work stays stopped until the owner schedules Chunk 2.

---

## Part B: Chunk 2, the next development chunk (only when the owner schedules it)

**Topic:** EM-209's missing CLI, `entropicmem worker run`, plus recording the remaining EM-209 and EM-210 plan deviations.

**Why this chunk:** it is the one piece of EM-209's plan text (now in `REMAINING_PLAN.md` §6.1) that the code doesn't have yet. It's small, self-contained, touches no schema or migration, and never touches the provider's live path. The rest of EM-209's AC is already met and tested:
- two worker processes never run the same job (the 4-process exactly-once test);
- a crash mid-job leads to lease expiry and a retry;
- `dedupe_key` prevents duplicates.

**Budget:** one session, at most 3 commits. Stop at any stop condition in plan §3.1.

**Owner:** Hermes or Claude Code implements. The other reviews before merge (the owner relays the report).

### 2.0 Pre-flight (read-only)
1. `main` must contain `25322dc`, and `35a02f4` must be an ancestor of `main`.
2. **Baseline:** `env -u ENTROPICMEM_MEMORY_DB -u ENTROPICMEM_VAULT_PATH -u ENTROPICMEM_INDEX_DB ENTROPICMEM_REQUIRE_PRIVACY_DIGESTS=1 python -m pytest -q` gives 1462 passed, 2 skipped, 4 xfailed. `ruff check .` is clean. If different, stop and report.

### 2.1 `entropicmem worker run` (one commit, test first)
The plan's spec, verbatim: `entropicmem worker run [--once] [--types ...] [--max-seconds N]` (for Hermes cron: document a cron entry that runs it hourly).
- Build it on the existing `em.jobs.JobWorker` and `HandlerRegistry`:
  - `--once` runs `run_once()`;
  - otherwise it runs `run_until_idle()`, stopping early after `--max-seconds`;
  - `--types` limits the registry to those types.
- **Registered handlers today:** `backup` (from `em.store.backup.make_backup_handler`). Unknown `--types` values are an error, not a silent no-op.
- **Refuses a live path** unless `ENTROPICMEM_ALLOW_LIVE_MIGRATION=1`, using the same `assert_safe_db_path` guard as migrations. The v3 store is not live yet, and this must not create or change one.
- **Refuses a non-v3 database** (no `jobs` table with the v3 shape) with a clear message and exit code 1. It never migrates.
- **Output:** one JSON line, `{"done": n, "failed": n, "dead": n, "lost": n}`. Exit code 1 if any job is `dead`.
- **Tests:**
  - on a temp v3 database with one queued `backup` job, the job runs, a verified backup exists, and the output reads `done: 1`;
  - `--once` runs exactly one job when two are queued;
  - an unknown `--types` value fails;
  - a v2 database is refused and left byte-identical;
  - a non-test path is refused. Use a unique, non-existent directory under the home directory; **never** `~/.hermes`.

  Mutation-check the live-path guard and the v2 refusal.
- **Docs:** `docs/CLI_REFERENCE.md` gains the command, plus the hourly cron line the plan asks for, marked "only after the v3 cutover". `CHANGELOG` gets an `### Added` entry.

### 2.2 Record the remaining deviations (docs only, one commit)
In `docs/V3_FOUNDATIONS.md`, add a section **"Recorded deviations from the plan"**. Give each line the plan's words, what the code does, and why.

| Card | Plan says | Code does | Decision |
|---|---|---|---|
| EM-209 | files `em/store/jobs.py`, `em/worker.py` | `em/store/jobs.py`, `em/jobs/worker.py` | keep (package holds registry + context) |
| EM-209 | `claim(worker_id, types, lease_s=60)` | `claim(worker_id, *, types, lease_seconds=60)` | keep (keyword-only is safer) |
| EM-209 | backoff `2^attempts * 30s` | `30·2^(attempts-1)`, cap 3600 s, ±10 % jitter | keep (same curve one step earlier, capped, jittered; tested) |
| EM-209 | `Worker(handlers, stop_event, budget_s)`, per-job `time_budget`, cooperative cancellation | `JobWorker(store, registry)`, `run(stop)`, leases + `ctx.heartbeat()` | keep; a per-job time budget is a later card if a real job needs it |
| EM-210 | `snapshot(reason) -> Path`, memory.db **+ index.db**, `backups/<ts>-<reason>/` dirs, EM-113 retention, once per hour per reason, AC: 100 `forget` → ≤ 1 snapshot/hour | `create(reason) -> BackupInfo`, memory.db only, flat files + manifest, 7 routine + 5 safety | **open: this is Chunk 3** (the throttle AC and index.db are real gaps) |

### 2.3 End of chunk
1. Push a branch. Wait for green CI on the exact SHA (`windows-import` included). The other agent reviews, then fast-forward `main` and delete the branch.
2. **Update `docs/plan/REMAINING_PLAN.md`:** §2 (SHA, counts), §5 (ledger) and §6.1 (remove the EM-209 CLI item).
3. **Replace this file's Part B with Chunk 3:** the EM-210 plan gaps.
   - A `snapshot()` name, covering `index.db` too, in `backups/<ts>-<reason>/`;
   - the once-per-hour-per-reason throttle, with the plan's AC test "100 `forget` → ≤ 1 snapshot/hour";
   - no provider behaviour change until the facade exists.
4. Report to the owner in plain language. Hermes updates MASTER_TODO. Claude Code produces a `/save` file.

### Explicitly out of scope for Chunk 2
- EM-210 changes (that is Chunk 3).
- The EM-211 facade, and any provider wiring to v3.
- The rest of EM-212 (the package move: a larger card, split before starting).
- The v3 cutover, or anything touching `~/.hermes/entropicmem*`.
- Releases, tags, catalog PRs and public comments.
- The tool rename.
- Changes to `provides_*`, or to migrations `0001`–`0003`.
- New dependencies.
- S3 and later.
