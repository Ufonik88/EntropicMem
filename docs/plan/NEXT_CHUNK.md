# EntropicMem: next steps (one chunk at a time)

**Updated:** 2026-09-29, Chunk 2 landed; Chunk 3 split and **3.1 is the next piece**. **Read first:** `docs/plan/REMAINING_PLAN.md` (its §3 rules apply to everything here), then `AGENTS.md` and `docs/V3_FOUNDATIONS.md`.

**Plan exactly one chunk.** When a chunk ends, replace this file with the plan for the next single chunk; never more than one ahead. Chunk 3.2 is deliberately *not* planned here: it gets one line in the out-of-scope list until 3.1 closes.

---

## Part A: Chunk 2 — `entropicmem worker run`. **DONE (2026-09-29)**

- `feat(em-209): add entropicmem worker run` plus the docs commits (`0cfac9d`, `dca80f4`, `ad5f0e5`, `8fca999`);
- CI green on the exact SHA, `identity-guard` included; fast-forwarded into `main`; the branch deleted (local and remote);
- 1467 passed, 2 skipped, 4 xfailed on the merged tree (the 1462 baseline plus the 5 new CLI tests); `ruff check .` clean under the CI pin `ruff==0.16.2`;
- reviewed independently before merge: both safety guards mutation-checked, and each goes red when the guard it protects is broken;
- the EM-209 wording deviations are recorded in `docs/V3_FOUNDATIONS.md` → "Recorded deviations from the plan";
- the release follow-ups this file used to hold (Part A of the previous version) are all done, as plan §4 records.

**Also landed the same day (no-bump hygiene batch, `main` `8202081af`):** the CI action majors (`actions/checkout@v7`, `actions/setup-python@v7`), `perf-smoke` diagnostics (p50/p95/max, budget unchanged at 20 ms), the v3 concurrency AC test's empty-sample fix, the `ARCHITECTURE.md` v3 storage-core section, and two new guards (`tests/test_docs_links.py`, `tests/test_cli_reference_drift.py`). Then a docs pass (`1a4e57235`) added plan §11, the cold-start page. The commits are in plan §2 and §5.

**EntropicMem is at rest.** Feature work stays stopped until the owner starts Chunk 3.1.

---

## Part B: Chunk 3.1 — `snapshot()` covering both databases. **NEXT PIECE, NOT STARTED**

**Topic:** the first half of the EM-210 plan gaps: the snapshot layout.

**Why this chunk, and why it is split.** EM-210 shipped `BackupManager.create(reason) -> BackupInfo` over `memory.db` only, with flat files beside a JSON manifest. Plan §5's card asks for `snapshot(reason) -> Path` covering `index.db` too, written into `backups/<ts>-<reason>/`. That is a data-model change inside a 507-line module with 20 existing tests, so it is the whole of this chunk. The other EM-210 gap, the once-per-hour-per-reason throttle, is **Chunk 3.2** and is not planned here (the one-chunk-ahead rule above). Nothing here touches a schema, a migration, or the provider's live path.

**Size:** 90 to 120 minutes of active work, one session. The cost is the model change, not the index file: `_inspect()` already probes any database shape (integrity check, `user_version`, every non-FTS table counted, the audit chain only where `prev_hash` exists), so `index.db` needs no second inspection path. That was the main "could balloon" risk and it is not real.

**Budget:** one session, at most 2 commits (the card, then the end-of-chunk doc update). Stop at any stop condition in plan §3.1.

**Owner:** Hermes or Claude Code implements. The other reviews before merge (the owner relays the report).

### 3.1.0 Pre-flight (read-only)
1. `main` must contain `1a4e57235` (Chunk 2, the hygiene batch and the doc pass), and `35a02f4` must be an ancestor of `main`.
2. **Baseline:** `env -u ENTROPICMEM_MEMORY_DB -u ENTROPICMEM_VAULT_PATH -u ENTROPICMEM_INDEX_DB ENTROPICMEM_REQUIRE_PRIVACY_DIGESTS=1 python -m pytest -q` gives **1495 passed, 2 skipped, 4 xfailed**. `ruff check .` is clean under the CI pin `ruff==0.16.2`. If the numbers differ, read `REMAINING_PLAN.md` §11 before stopping: the total is expected to rise with every card (1462 at Chunk 2's pre-flight, 1495 after the batch).

### 3.1.1 `snapshot()` and the directory layout (one commit, test first)
- Add the plan's name: `snapshot(reason) -> Path`. **Keep `create()` as a thin alias**, because three callers exist and none should change behaviour in this commit: the migration hook in `em/store/migrations/__init__.py`, the daily job through `make_backup_handler`, and the tests.
- Cover `memory.db` **and** `index.db` whenever the index exists. The store never resolves `index.db` today, so add an `index_path` parameter that defaults to the sibling `index.db` in the database's own directory. Do **not** read `HERMES_HOME` (invariant: `em.*` never does).
- Write into `backups/<ts>-<reason>/`, with the directory named the way today's flat files are named (`<reason>-<stamp>`, collision-suffixed), and the manifest **inside** that directory.
- `BackupInfo` goes from one file to a list of files with a hash and size each. `verify()` re-hashes all of them. `restore()`, `rotate()`, `list()`, `latest()` and the pre-restore safety copy must all work on the new layout **and** keep working on today's flat backups: never move or delete a legacy backup, and keep both layouts readable.
- **Tests:** a snapshot holds both databases; the directory is named `<ts>-<reason>/`; a store with no `index.db` still snapshots; the manifest lists every file with its hash; `verify()` fails on a missing file, a truncated file, and a manifest that lies; a legacy flat backup is still listed, verified and restorable; `rotate()` applies one policy across both layouts; restore round-trips both files.
- Mutation-check the per-file hash check and the index-inclusion branch.
- **Docs:** the backup section of `docs/V3_FOUNDATIONS.md` and `docs/BACKUP_RESTORE.md` (both layouts, each with its restore drill), CHANGELOG under `### Added` / `### Changed`.

### 3.1.2 Size guard
If restore's dual-layout handling needs substantially more than the tests listed above, **stop and report** rather than expanding the chunk: the repair is a smaller follow-up, and 3.2 is still waiting.

### 3.1.3 End of chunk
1. Push a branch. Wait for green CI on the exact SHA (`windows-import` included). The other agent reviews, then fast-forward `main` and delete the branch.
2. **Update `docs/plan/REMAINING_PLAN.md`:** §2 (SHA, counts), §5 (ledger), §6.1 (the EM-210 line now says the snapshot half is done), §9, §11 (state table, next chunk, counts).
3. **Replace this file's Part B with Chunk 3.2:** the once-per-hour-per-reason throttle, behind the plan's "100 `forget` → ≤ 1 snapshot/hour" acceptance criterion. Derive it from existing snapshot timestamps, so no schema and no migration, with `em.clock.freeze` for the time-travelling test.
4. Report to the owner in plain language. Hermes updates MASTER_TODO. Claude Code produces a `/save` file.

### Explicitly out of scope for Chunk 3.1
- **Chunk 3.2: the once-per-hour-per-reason throttle.** Named here, planned when 3.1 closes.
- **Retention.** 7 routine + 5 safety stays as the recorded deviation unless the owner asks for the plan's EM-113 rule (keep 10, plus one per day for 7 days). That decision is open in plan §9.
- Any schema change or new migration; `0001`–`0003` stay untouched.
- The EM-211 facade, and any provider wiring to v3. The snapshot must not change provider behaviour.
- The EM-212 package move (a larger card: split before starting).
- The v3 cutover, or anything touching `~/.hermes/entropicmem*`.
- Releases, tags, catalog PRs and public comments.
- The tool rename (`entropicmem_patch_core` → `entropicmem_patch_core_memory`) — 3.0 only, with the release that re-pins the catalog.
- New dependencies; S3 and later.