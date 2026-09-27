# EntropicMem: remaining plan (from the 2.8.1 safe point)

**Status date:** 2026-09-27. **Owner:** the owner (GitHub `Ufonik88`). **Builders:** Hermes (implements and merges), Claude Code (reviews, fixes, plans).
**Replaces:** the "remaining work" parts of the v3 master plan and every earlier hand-off. It does not replace the master plan's card text (see §1).

---

## 0. The change of plan, in one paragraph

The full v3 programme (sprints S1–S9) is too big to finish in one push. So EntropicMem stops at a **safe point**: **2.8.1**, a version people can install from the Hermes Marketplace and use safely. There is **no feature work** after that point.

Development continues later in **small, safe chunks**, one chunk per session, only when time and budget allow. Nobody plans or starts "the rest" in one go again. Every chunk must leave `main` releasable, and must leave the Marketplace entry untouched unless the chunk is a release.

---

## 1. Sources of truth, and a gap you must close

| Source | What it holds | Where |
|---|---|---|
| Code on `main` | the facts | `github.com/Ufonik88/EntropicMem` |
| **v3 master plan** | the intent: card text, acceptance criteria (AC), §-numbered specs (§3.x schema and API, §5 cards, §6.3 eval gates, §6.4 perf budgets) | **Hermes's machine only** (not in the repo) |
| `AGENTS.md`, `docs/V3_FOUNDATIONS.md` | the rules, invariants and recipes | the repo |
| This file and `docs/plan/NEXT_CHUNK.md` | what is left, and what is next | the repo (`docs/plan/`) and the owner's and Hermes's memory |

If the plan and the code disagree, the code is the fact and the plan is the intent. Record the difference; don't paper over it.

**The gap.** Claude Code has never been able to read the master plan. §6 of this file was reconstructed from every card reference in the repo, in CI and in the project's history. The card *numbers*, sprint *themes* and critical path are reliable. Most card *titles and AC* after S2 are not recorded anywhere except the plan. **`NEXT_CHUNK.md` task H3** makes Hermes paste each remaining card's plan text, verbatim, into §6 of the committed copy of this file. Until that is done, treat any card below that says "(plan text needed)" as a placeholder.

---

## 2. Where things stand (verified 2026-09-27)

### Repository `Ufonik88/EntropicMem` (public)
| Ref | SHA | Meaning |
|---|---|---|
| `main` | `93a7d81` or later (the commits that added `docs/plan/`) | 3.0 development line (`3.0.0.dev0`). All of S2 so far, the v3 foundations, the catalog-review fixes, the perf-smoke fix, EM-212, the 2.8.1 notes and these plans. Locally: 1461 passed, 3 skipped (2 with the private list), 3 xfailed. |
| branch `release/2.8.x` | `7e02412` | **2.8.1**: `v2.8.0` plus the safety fixes (see §4). Locally: 955 passed, 3 skipped (2 with the private list), 4 xfailed. CI on `7e02412`: the run passes, 10/11 jobs green, and `windows-import` is allowed to fail on 2.8.x (as on 2.8.0). The tag `v2.8.1` is still to be created (§4). |
| tag `v2.8.0` | tag `09a5459` → commit `060063d` | The release the Marketplace serves until the 2.8.1 re-pin merges. |
| leftover branches | `claude/eloquent-fermi-9e73i3` (= `7e02412`), `fix/perf-smoke-probes` (= `177f7f2`), `claude/chunk-1-s2-closeout` (on `main`) | Both are merged or duplicated. Hermes deletes them (Claude Code's session may not delete refs). |
| republish baseline | `35a02f4` | First commit of the cleaned public history. It must stay an ancestor of `main` forever. |

- **Dead SHAs** (never push them anywhere public): `e47e956`, `0e5e39c`, `93ef951`, `6b62a21`, `f15fe12`, `9a2c1df`, `437c89b`.
- **Private archive:** `Ufonik88/EntropicMem-archive`. It holds the old history with personal data. **Never make it public.**

### Marketplace (Hermes plugin catalog)
- NousResearch/hermes-agent#122476 is **merged** (`5b6033d`). The entry `entropicmem` 2.8.0 is pinned at `060063d`.
- Maintainer: Teknium. He re-read the plugin in full and amended the disclosure. His rule: **never rewrite history on a listed repo** (`AGENTS.md` rule 9).
- The fork branch `catalog/entropicmem-2.8.0` ends in Teknium's `cdfcd83` on top of our `01d30a9`. **Never push that branch again.** Any future catalog PR starts from a fresh branch off upstream.

### Hermes host (the owner's machine)
- **Live install:** `~/.hermes/entropicmem-live-2.8.0` at `e47e956`. Its plugin files are identical to `060063d`. The graph server runs on 8075/8076.
- **Crons:**
  - the old-clone cleanup script, due 2 Oct. It must use `git merge-base --is-ancestor 35a02f4… origin/main`. Hermes reported this "done" twice but has never shown the line, so `NEXT_CHUNK.md` task H4 verifies it.
  - the catalog-check cron. It stalled the box once when it built a second `HERMES_HOME` (4 GiB swap exhausted), so run it only when the box is idle.
- The denylist lives at `~/.config/entropicmem/privacy-digests.txt` (mode 600) and in the CI secret `ENTROPICMEM_PRIVACY_DIGESTS`.

---

## 3. How work is done from now on (applies to every chunk)

### 3.1 Chunk rules
1. **One chunk per session.** A chunk is at most about 5 commits, touches one area, and has a written scope *before* coding starts (in `docs/plan/NEXT_CHUNK.md`).
2. **A chunk must be safe to stop after.** `main` stays green and releasable, and nothing half-wired reaches the provider's live code path.
3. **Stop conditions.** Stop and report, instead of expanding scope, if:
   - the card's plan AC turns out bigger than the chunk's written scope;
   - a gate can't go green honestly;
   - anything would touch the live store, the Marketplace entry, a tag or published history.
4. **At the end of every chunk:**
   - update §2 and §6 of this file in the repo;
   - write the next chunk's plan (`docs/plan/NEXT_CHUNK.md`), with **only one** chunk planned ahead;
   - add a vault note entry (see §3.4).
5. **No release without the owner.** Releases, tags and catalog PRs are the owner's calls (§3.3).

### 3.2 Non-negotiable constraints (collected from `AGENTS.md`, earlier hand-offs and the plan)

**Git and CI**
- Merge fast-forward only: `git merge --ff-only`. Never force-push. Agents never tag. Never use GitHub's web Merge button or web editor (they stamp the owner's account email).
- CI must be green on the **exact** SHA being merged: check `headSha`. `identity-guard` must be green after every push to `main`. If it's red, stop and tell the owner.
- Never rewrite published history. Never delete a branch or tag that a release or catalog pin points at. Fix forward.
- Never rename or remove a provider tool, and never change `provides_tools`/`provides_hooks`, outside a release that re-pins the catalog. They are the catalog's verification basis.

**Data safety**
- Never write to the live store (`~/.hermes/entropicmem*`). Measure on copies. Run tests with `ENTROPICMEM_MEMORY_DB`, `ENTROPICMEM_VAULT_PATH` and `ENTROPICMEM_INDEX_DB` unset.
- A test that exercises a safety guard must never target the real path.
- The v3 cutover (a live migration, `ENTROPICMEM_ALLOW_LIVE_MIGRATION=1`) needs the owner's explicit confirmation.

**Privacy**
- No real person, employer, family or bank names anywhere, test data included. Use Acme / Globex / Initech, Alice / Bob Example, example.com; phone digits only from the allowlist `0000`, `1234`, `9876`, `5432`.
- Never commit an identifier list, hashed or not.
- Before every push, hash the words in changed files against the private list. Report only file, line and column.

**Tests**
- Test first, see it fail for the right reason, then mutation-check it.
- Never weaken, skip, delete or xfail a test to get green.
- Strict xfails are acceptance criteria: they flip to passing, never get deleted.

**Migrations**
- Never edit an applied migration; add a new one.
- Numbering is contiguous. Each migration is self-contained (no imports except `em.clock`). Every migration runs after a verified backup.

**Commits**
- One card per commit, each with a CHANGELOG line under `[Unreleased]` in the right section (Added / Fixed / Security / Changed).
- Never delete CHANGELOG history; a moved entry must arrive intact (check line by line).
- Only noreply identities: `Ufonik88@users.noreply.github.com`, `noreply@anthropic.com`, `noreply@github.com`.

**Compatibility**
- Product code must run on Python 3.10–3.13 (CI matrix). Hermes runs 3.11 (supports >=3.11,<3.14). 3.14 is untested.
- `em.*` is standard-library only, never imports the Hermes host or the provider, and never reads `HERMES_HOME`.
- Windows: `tests/unit` runs on windows-latest (main line). Don't assert POSIX mode bits there; use `Path.as_uri()`; close every connection.

**The ten v3 invariants** (`docs/V3_FOUNDATIONS.md`)
1. Transactions belong to the caller.
2. No slow work inside a write transaction.
3. Every change writes an audit row in the same transaction.
4. Time and ids come from `em.clock`.
5. Every read is scoped.
6. `purge` forgets everything derived from a memory.
7. Applied migrations are immutable.
8. Development never touches the live store.
9. Every `em` subpackage is listed in `pyproject`.
10. Code is portable.

### 3.3 What only the owner decides
- Anything touching real data or the live store, including the v3 cutover.
- Releases, tags and the Hermes catalog entry (including public replies on the catalog PR).
- A test that cannot pass without weakening it.
- Whether to continue past the decision gate after S4 (§6.6).

### 3.4 Memory and logging
- **This file and the next-chunk file** live in the repo (`NEXT_CHUNK.md` task H3), in the owner's Claude vault (`projects/entropicmem.md` links to them), and in Hermes's memory (MASTER_TODO).
- **Claude Code cloud sessions can't reach the vault.** They produce a `/save` file; the owner files it from Claude on his Mac.

---

## 4. Step 0: reach the safe point (2.8.1). Mostly owner clicks, about 30 minutes.

2.8.1 is built and CI-verified on `release/2.8.x` (`7e02412`). It contains **no v3 (`em/`) code and no new features**; every change was cherry-picked from `main` with `-x`:

| In 2.8.1 | From `main` |
|---|---|
| `ingest` re-validates every redirect hop (SSRF via redirect) | `49feb3f` |
| Vector embeddings opt-in: no silent Hugging Face download; encoding runs outside the write lock | `76478b2` |
| The CLI honours `HERMES_HOME` for the shared publish store | `835b49b` |
| Duplicate `hooks:` list removed (EM-213 re-scoped) | `becf2d7` |
| README "Network Access" table; graph-export docstrings corrected | `08af922` |
| Privacy guard v2 and CI identity guard | `198c30c`, `35a02f4` |
| S1 follow-ups: graph server returns 400 on a malformed Host, lifespan hooks, CI 3.13, tar filter | `30bac13`, `43f24e7` |
| `perf-smoke` 20 probes | `177f7f2` |
| 2.8.1 version bump and CHANGELOG, a README note that native Windows is unsupported on 2.8.x | new on the branch |

**The only user-visible behaviour change:** semantic recall now needs `embeddings_enabled: true`.

**Known and accepted on 2.8.x:** native Windows doesn't load (the engine imports `fcntl`). CI's `windows-import` job is allowed to fail on this line, as on 2.8.0. It is fixed on the 3.0 line (EM-202).

**Steps** (all Hermes; the owner's only part is saying yes to the public reply, or not):
1. **Done by Claude Code:** branch `release/2.8.x` created at `7e02412`. The Claude Code session is not allowed to push tags.
2. **Hermes** creates the tag and the Release page in one command (details in `docs/plan/NEXT_CHUNK.md` Part A). The tag must exist before the catalog pin, so the pinned commit can never vanish (rule 9). Hermes also protects `release/2.8.x` (no force-push, no deletion).
3. **Hermes** opens the catalog re-pin PR from a *fresh* branch off upstream `hermes-agent`:
   - version `2.8.1`, sha = the tagged commit, and all pinned URLs moved to it;
   - run `scripts/validate_plugin_catalog.py`, check each URL anonymously, and run `hermes plugins validate --install-deps plugins/entropicmem` on a clean checkout (use the safe `HERMES_HOME` method, on an idle box);
   - the PR body lists the fixes above in plain words and states that no history was rewritten;
   - the disclosure changes since 2.8.0: embeddings are now opt-in (strictly less egress than disclosed).
4. **After it merges,** run a fresh catalog install:
   - sha correct, 7 tools and 5 hooks load, remember → recall works;
   - with `sentence-transformers` present but not enabled, **no** model download happens.

**Only when the owner says "post it":** the one-time reply on #122476 (draft in the previous hand-off).

When Step 0 is done, EntropicMem is at the safe point and feature development stops.

---

## 5. What is done (ledger, so nobody redoes it)

**S1: 2.8.0 hotfix sprint (EM-101…EM-118).** Released at `060063d`. It includes:
- EM-114 graph server hardening (Host allowlist, CSP, run token);
- EM-113 capsule export/import hardening, and backups before destructive operations;
- EM-117 release;
- eval gating on the §6.3 metrics only;
- 2.8.0 baselines.

S0 cards EM-001…EM-007 (fixtures, harness, xfail findings, perf smoke, Windows import smoke) came before S1.

**Public cutover and privacy repair (2026-09-26).** History scrubbed and republished at `35a02f4`, archive kept private, Marketplace re-pinned, branch protection and secret scanning on.

**S2: storage core v3.** On `main`, not wired into the provider (the provider still uses the v2 engine):

| Card | What | Commit(s) |
|---|---|---|
| EM-201 | `em/` package, `em.clock` (freezable UTC, ULIDs), single-source version | `691d9c2` |
| EM-202 | portable locking (`em.store.locking`), `open_db`/`write_txn`/`Store`; Windows CI blocking | `3b80825`, `de73723` |
| EM-203 | migration framework, `0001_baseline_v27`, live-DB refusal guard | `38a695b` |
| EM-204 | `0002_v3_core`: v3 schema plus a lossless v2 move with parity checks | `eadc5fc` |
| (guards) | privacy guard v2 (private denylist), identity guard | `198c30c`, `35a02f4` |
| EM-206 | hash-chained audit, `entropicmem audit verify` (read-only) | `0b2ca9c` |
| EM-205 | `MemoryStore` (add/update/supersede/set_status/get/list/history/touch/purge) | `4f3a0cd` |
| EM-207 | episodes and content-addressed transcript chunks | `00a3bcc` |
| EM-208 | entities, aliases, relations, two-sighting linker, and follow-up fixes | `d368d15`, `d5f014e`, `decbc27` |
| EM-209 | `JobQueue` and `JobWorker` (leased, atomic, dead-letter, handlers outside transactions) | `f94784b` |
| EM-210 | `BackupManager` (verified snapshots, rotation, guarded restore, daily job) | `b743a43` |
| EM-206 fix | `0003_audit_append_only` (fresh installs lacked the triggers) | `c14c19b` |
| EM-211 (foundation) | `em/facade/contract.py` (derived from the provider source by AST scan), `tests/parity/` | `a0252ac` |
| EM-213 | re-scoped and done: keep `provides_*`, drop the duplicate `hooks:` | `becf2d7` |
| docs | `AGENTS.md`, `docs/V3_FOUNDATIONS.md` | `5908277`, `147e00a` |
| catalog-review fixes | ingest redirects, embeddings opt-in, CLI `HERMES_HOME`, network docs | `49feb3f`, `76478b2`, `835b49b`, `08af922` |
| CI | `perf-smoke` 20 probes | `177f7f2` |
| EM-212 | `_backend` loads its own `vault.py` by path; `test_f010` made real | `4ae5b11` |
| docs | 2.8.1 notes forward-ported; `docs/plan/` added | `cdff579` and later |
| **2.8.1** | safety patch branch `release/2.8.x` | `7e02412` (tag pending, §4) |

---

## 6. What is left: the full remaining plan

Cards are grouped by the master plan's sprints. **"(plan text needed)"** marks cards whose title and AC must be pasted from master plan §5 (`NEXT_CHUNK.md` task H3). Everything stated about a card here is known from code or earlier decisions and must be kept when the plan text is added.

**The critical path, as recorded in the plan:**
- EM-201 → EM-203 → EM-204 → EM-205 (done);
- then S3: EM-302 → EM-304 → EM-305 → EM-403 → EM-503 → EM-901 → EM-904.

### 6.1 S2 remainder: finish the storage core (small cards, good first chunks)

**Done on 2026-09-27 by Claude Code:**
- `fix/perf-smoke-probes` merged into `main`;
- the 2.8.1 notes and the README semantic-recall line forward-ported;
- this plan committed to `docs/plan/`;
- **EM-212** done: `_backend` loads its own `vault.py` by path under a private module name; `test_f010` is now a real check and passes.

**Still open from housekeeping:**
- paste the master plan §5 text into §6 (Hermes; `NEXT_CHUNK.md` task H3);
- delete the leftover remote and local branches (Hermes).

**EM-212 follow-up (only if plan §5 asks for it):** move `scripts/` off `sys.path[0]` and replace the provider's own bare `from memory_engine import …` imports. That is a separate, larger card.

**EM-211: legacy facade.** Implement `LegacyEngine` over `em.store` so the provider can run on v3 unchanged.
- Done when it is added to `ENGINES` in `tests/parity/test_engine_parity.py` and to `_implementations()` in `tests/unit/test_em_facade_contract.py`, and both pass **unchanged**.
- Known requirements:
  - `get_fact(StoredFact.make_id(content))` must resolve: store `sha256(content)[:16]` as `legacy_id` on `remember`;
  - replace the raw `engine.db` read in `_locate_mirror` with an engine method on **both** engines, then drop `db` from `PROVIDER_ATTRIBUTES`;
  - run `EntityLinker` from a `link:<memory_id>:<version>` job, never inside `MemoryStore.add`;
  - the `§3.5` owner-only rule for sensitive rows needs the gateway identity and lands here.
- Too big for one chunk. Split it into facade reads, then writes, then mirror, then linker.

**Master plan §5 card text (verbatim, pasted 2026-09-27 per `NEXT_CHUNK.md` H3):**

#### EM-209 — Durable job queue & worker · M
- **Files:** `em/store/jobs.py`, `em/worker.py`.
- **Spec:** `enqueue(type, payload, *, dedupe_key=None, run_after=None, priority=5)`; `claim(worker_id, types, lease_s=60)` via `BEGIN IMMEDIATE; SELECT … LIMIT 1; UPDATE … SET status='running', locked_by, locked_until` (no RETURNING); `complete(id)`, `fail(id, err)` with exponential backoff `2^attempts * 30s`, `dead` after `max_attempts`. `Worker(handlers: dict[str, Callable], stop_event, budget_s)` loop with `time_budget` per job and cooperative cancellation. Job types registered in S3/S5: `embed`, `embed_backfill`, `extract_window`, `extract_session`, `summarize_window`, `summarize_session`, `reconcile`, `consolidate`, `reflect`, `synthesize_profile`, `project_vault`, `reindex_vault`, `retract_turns`, `prune`.
  CLI: `entropicmem worker run [--once] [--types ...] [--max-seconds N]` (for Hermes cron: document a cron entry that runs it hourly).
- **AC:** two worker processes never run the same job; crash mid-job → lease expiry → retried; dedupe_key prevents duplicates.

#### EM-210 — Backup manager · S ‖
- **Files:** `em/store/backup.py`. **Spec:** `snapshot(reason) -> Path` via `backup()` API for memory.db + index.db into `backups/<ts>-<reason>/`; retention policy (EM-113 rules); optional encryption hook (EM-704). Destructive ops call `snapshot` at most once per hour per reason (not per call).
- **AC:** 100 `forget` calls → ≤ 1 snapshot/hour.

#### EM-211 — Legacy facade on v3 · M
- **Depends on:** EM-204, EM-205.
- **Spec:** `memory_engine.MemoryEngine` keeps its public method names/signatures, implemented over `MemoryStore`/`EpisodeStore`/`EntityStore`; returns `StoredFact` built from `Memory` (id = legacy_id if present else new id). Deprecation warnings (once per process) for methods slated for removal in 3.1. All current tests either pass unchanged or are updated with a note explaining the v3 semantic change (e.g. no fuzzy overwrite).
- **AC:** full legacy test suite green on a v3 DB; CLI commands work unchanged.

#### EM-212 — Plugin namespace isolation · S ‖
- **Why:** Teknium review note (2026-09-24, §2.4 finding 10). `_backend.resolve_paths` inserts `scripts/` at `sys.path[0]` and bare-imports `vault`, `index`, `security`, `policy`, `embeddings`, `retrieval` — unprefixed module names that share the process-wide namespace with every other plugin and site-package.
- **Files:** `plugins/entropicmem/_backend.py`, `plugins/entropicmem/scripts/` → `plugins/entropicmem/scripts/em/` (package).
- **Spec:** Move engine modules under a package namespace (`em_vault`, `em_index`, etc.) or convert `scripts/` to a package with relative imports. The bare `from vault import …` / `from index import …` calls in `_backend.py` become `from entropicmem.scripts.em.vault import …` or `from em_internal import …`. No unprefixed module names in the process namespace. Update `__init__.py` registration to use the new import path. Keep CLI working as `python3 scripts/entropicmem.py` via a thin shim if needed.
- **AC:** `python -c "import sys; sys.path.insert(0, 'plugins/entropicmem/scripts'); import vault"` on a clean interpreter shows **no** `vault`/`index`/`security` module registered (only `em_vault` etc.); `hermes plugins validate` does not emit module-shadow warnings.

**Plan deviations found by Hermes's §5 comparison.** Resolve each by a small fix *or* a recorded deviation; don't rewrite working code to match wording.
- **EM-209:**
  - no `entropicmem worker run` CLI subcommand, and no cron doc;
  - no per-job `time_budget`;
  - backoff is `30·2^(attempts-1)` capped at 3600 s ±10 % jitter, versus the plan's `2^attempts·30s` (record as a deviation);
  - `claim(worker_id, *, types, lease_seconds)` versus the plan's `(worker_id, types, lease_s)` (naming; record).
  - Priority semantics match the plan (lower number runs first, default 5).
- **EM-210:**
  - `create()` versus the plan's `snapshot()`;
  - covers `memory.db` only, not `index.db`;
  - flat files versus `backups/<ts>-<reason>/` directories;
  - retention is 7 routine + 5 safety, versus EM-113's keep-10 + one per day for 7 days;
  - no once-per-hour throttle, and no "100 forgets" AC test.
- **EM-211 (foundation):** met as a foundation; the facade itself is still open (above).

**Tool rename (3.0 only):** `entropicmem_patch_core` → `entropicmem_patch_core_memory` (catalog maintainer's ask). Update the provider, `plugin.yaml`, `SKILL.md`, docs and tests together. It ships only with a release that re-pins the catalog (rule 10).

**Stays true:** `SKILL.md` keeps describing the installed version until EM-806/EM-904 bump it.

### 6.2 S3: retrieval v3 (critical path starts here)
- **EM-302 — Candidate generators · M.**
  - **Files:** `em/retrieval/candidates.py`.
  - **Spec:** each generator is a function `(ctx: RetrievalContext) -> list[Candidate]` where `RetrievalContext` has `aq`, `scope`, `now`, `limits`, `deadline`. All SQL filters by scope via a single helper `scope_sql(scope) -> (clause, params)` implementing §3.5 (unit-tested truth table). BM25 query uses per-column weights. Episodic generator returns `owner_type='episode'`.
  - **AC:** each generator has tests incl. scope isolation (user A never sees user B's rows); deadline respected (generator returns partial within 5 ms of deadline).
- **EM-303: embeddings.**
  - An `embed` job handler. Jobs are already queued by `MemoryStore.add` as `embed:<id>:<version>`.
  - Upsert into `embeddings` on `(owner_type, owner_id, model)` so re-runs are harmless.
  - **Must respect the 2.8.1 opt-in** (`embeddings_enabled`); no model download without it.
  - Target: hard-suite ageing recall@5 from 0.733 to the plan's 0.90. The four misses share no words with the stored fact; don't build a synonym table and don't edit the fixture.
- **EM-304 — Fusion, rerank, explainability · M.**
  - **Files:** `em/retrieval/fusion.py`. **Spec:** exactly §3.6 formulas; all weights in `ranking.*` config; `explain` structure; deterministic tie-break `(score desc, updated_at desc, id asc)`.
  - **AC:** unit tests with synthetic ranks reproduce hand-computed scores to 1e-9.
- **EM-305 — Gate, supersession collapse, MMR · M.**
  - **Files:** `em/retrieval/gate.py`, `em/retrieval/diversity.py`. **Spec:** §3.6. Collapse also groups `status=active` memories linked by `superseded_by` chains (safety) and exact-hash duplicates across scopes (prefer narrower scope).
  - **AC:** abstention scenarios ≥ 0.95 correct; `update` scenarios return only the latest version by default and both with `include_history=True`.
- **Episode recall (F-009, R8):** strict xfail `test_f009_episodes_reach_recall`. Episodes are stored but `recall()` never surfaces them.
- **EM-309: sync.** Sync `fact_id` references move from legacy ids to v3 ids. Until then `0002` keeps the sync tables and legacy ids untouched.

### 6.3 S4: isolation, prefetch and config (the "real milestone" for users)
- **Full per-user isolation:** strict xfail. Today `owner_user_ids` is only an interim owner/guest guard (EM-118).
- **Async prefetch:** strict xfail. Today `queue_prefetch` is a no-op and prefetch runs inline.
- **EM-403 — PrefetchService · L.**
  - **Depends on:** S3.
  - **Spec:** §4.2 exactly. Metrics: `prefetch.latency_ms`, `prefetch.cache_hit`, `prefetch.partial`, `prefetch.injected_count`, `prefetch.tokens`.
  - **AC:** harness: warm p95 ≤ 150 ms @ 50k, cache-hit path ≤ 10 ms; forced-slow generator → returns within 1.5 s with partial result; never exceeds 9,000 chars; cumulative replayed memory tokens over 50 turns ≤ 50 × budget × 0.6 (dedup working).
- **EM-407: typed config module.** It replaces today's parameters with config values, for example `entities.seed_builtin` (default false) and `privacy.transcript_retention_days` (default 30). It should also carry `embeddings_enabled`.
- **EM-410: JobWorker cron and scheduling.** Scheduled jobs must be deterministic. It pairs with the EM-209 gap (`worker run` CLI).
- **v3 cutover** (owner-gated): migrate the live store with `ENTROPICMEM_ALLOW_LIVE_MIGRATION=1` after a verified backup, with the owner present. It needs EM-211 finished and the parity suite green.

### 6.4 S5
- **EM-503 — Reconciliation & commit policy · L.**
  - **Depends on:** EM-502, EM-205, S3.
  - **Files:** `em/formation/reconcile.py`.
  - **Spec:** §3.7 steps 2–4; LLM prompt Appendix C.2. Deterministic "attribute" detector: `(entity|user) (is|are|was|uses|prefers|lives in|works (at|for)|moved to|switched to|runs on|costs|=) X` → key `(entity_id, attribute)`; same key + different value → SUPERSEDE. CONFLICT decisions (LLM says contradictory but unsure) → new memory `pending` + `trust_flags=["conflict:<id>"]`, surfaced by `review`.
  - **AC:** `update` and `contradiction` eval categories ≥ 0.9 with rule path; audit contains decision records; no memory is ever overwritten without a version row.

### 6.5 S6–S9 (only if the gate in §6.6 says continue)

**S6: vault and graph upgrades.** Goal: the vault becomes a clean, human-first projection of memory (not a note-per-fact dump), robust to hand edits; the graph shows entities and time. A parked idea: opening the memory graph from a phone or another computer. Drop it unless someone asks.

- **EM-601 — Vault projection v3 · L.**
  - **Files:** `em/vault/projection.py`.
  - **Spec:** config `vault.projection: none|entities|entities+journal|legacy` (default `entities+journal`; `legacy` = v2 note-per-fact for users who want it).
    - `Entities/<Entity Name>.md`: frontmatter (`entropic_entity: ent_…`, aliases, kind), human region, and an auto-section `<!-- entropicmem:auto:begin id=facts -->` listing active memories linked to the entity (`- <content> ^m-<short>` block refs so Obsidian can link to lines), a "History" auto-section of superseded facts (last 10), and relations as wikilinks.
    - `Journal/YYYY-MM-DD.md`: episodes of that day (title, summary, decisions, open loops) in an auto-section.
    - `Memories/Unfiled.md`: active memories with no entity (paged by month if > 200).
    - Projection runs as `project_vault` job (debounced 60 s after writes); only auto-sections are rewritten; files written atomically; a file whose auto-section markers were deleted by the user is left untouched and reported by `lint`.
  - **AC:** idempotent (second run = zero writes); a hand edit outside markers survives 10 projection runs; `forget` removes the line from the entity page within one job cycle.
- **EM-602 — Frontmatter & wikilink robustness · M ‖.**
  - **Files:** `em/vault/frontmatter.py`, `vault.py` shim.
  - **Spec:** YAML subset writer with proper quoting/escaping (strings with `:`, `"`, `#`, leading `-`, newlines → block scalars), lists in flow or block style; reader uses PyYAML when available else the subset parser (round-trip tested against PyYAML output). Frontmatter delimiter detection only at file start and on its own line (a `---` in the body no longer truncates). Wikilinks parse `[[Target]]`, `[[Target|Alias]]`, `[[Target#Heading]]`, `[[Target^block]]`, `![[embed]]`. `note_id` = vault-relative path without `.md` (full path, POSIX separators) — migration of `index.db` note ids + graph edges (index.db `user_version` 2).
  - **AC:** property test: random titles/tags round-trip; notes in nested folders get unique ids.
- **EM-603 — Incremental index by mtime + chunk embeddings · M.**
  - **Spec:** `notes_meta` gains `mtime_ns`, `size`; diff by `(mtime_ns,size)` first, hash only when changed; index refresh scheduled as `reindex_vault` job after projection and on `entropicmem index refresh`; chunk embeddings enqueued (EM-308).
  - **AC:** 5k-note vault refresh with 1 change < 300 ms.
- **EM-604 — Vault → memory ingestion of human edits (opt-in) · M.**
  - **Spec:** `vault.ingest_human_edits: false` (default). When on, new bullet lines added by the user **inside** an entity page's human region that match `- <statement>` are proposed as `pending` memories (`source=vault_edit`) linked to that entity; deletions of auto-section lines are ignored (projection re-adds) but logged as a hint in `review` ("user removed line for m·… — forget?").
  - **AC:** end-to-end test with a simulated edit.
- **EM-605 — Graph export v3 · L ‖.**
  - **Spec:** split `graph_export.py` into `em/graph/model.py` (build nodes/edges from notes + entities + relations), `em/graph/export.py` (json/dot/canvas/html), `em/graph/assets/{graph.html,graph.js,graph.css}` (packaged via `importlib.resources`, inlined at export for a single self-contained HTML). New: entity nodes & relation edges (typed colours), time slider on `valid_from/valid_to`, scope filter (owner only by default), superseded edges dashed. Keep community detection, search, path tracing, orphan highlight.
  - **AC:** existing graph UX tests ported; template integrity test kept; export of 5k nodes < 3 s.
- **EM-606 — Graph server hardening (round 2) · S ‖.**
  - **Spec:** open DBs read-only (`mode=ro` URI); rate-limit `/api/search` (token bucket 10 rps); response bodies redacted per sensitivity (sensitive → summary only) and scope (owner scope only unless `--scope all`); per-run token from EM-114 rotates on restart.
  - **AC:** tests for ro connection (write attempt fails), rate limit, redaction.
- **EM-607 — Ingest v2 · M ‖.**
  - **Spec:** HTML → text via `html.parser` (drop script/style/nav/footer; keep headings/lists); size cap; chunked literature note under `Sources/`; entity mentions linked via EntityLinker (no more "every capitalised phrase becomes a note"); optional LLM "key points" (Appendix C.6) when an LLM backend is available; extracted claims become `pending` memories with `source=ingest` and the source URL as evidence.
  - **AC:** ingesting a 50 KB article creates 1 source note, ≤ 10 pending memories, 0 junk entity notes.
- **S6 exit criteria:** vault is readable and stable under hand edits; graph shows entities, relations and time.

**S7: security, privacy & governance.**
- **EM-703 — Write-path injection screening & trust policy · M.**
  - **Spec:** run `injection_screen.screen_text` in `MemoryStore.add` and in formation on candidates; flagged → `trust_flags += ["injection:<shape>"]`; policy `trust.injection_policy: flag|quarantine|drop` (default `quarantine` for extracted/ingested sources, `flag` for `user_stated`/`agent_tool`). Screen long content in 20k-char windows with 500-char overlap (fix truncation gap). Prefetch never injects `quarantine`d content; flagged content keeps the v2.7 warning marker.
  - **AC:** injection fixtures (from `tests/test_injection_screen.py`) written via extraction never reach prefetch.
- **EM-705:** `purge` also removes embeddings and vault projections, with the `iterdump()` proof per invariant 6.

**S8: EM-806 packaging** (entry points, extras layout, the `SKILL.md` bump).

**S9.**
- **EM-901 — Upgrade drills · M.**
  - **Spec:** scripted drills: v2.3 / v2.5 / v2.7 / 2.8 fixture DBs + vaults → 3.0; verify doctor clean, eval parity, legacy ids resolvable, sync still works between a 2.8 and a 3.0 profile (publish/pull compatibility) or documented as requiring both upgraded.
  - **AC:** drill report in `docs/UPGRADING.md`.
- **EM-904:** the 3.0 release (with the `SKILL.md` bump, the tool rename, and a catalog re-pin via a new PR).

### 6.6 Decision gate after S4
After S4, the owner decides whether S5–S9 are worth continuing. The plan does not have to be finished for EntropicMem to be useful.

---

## 7. Known limitations (true at 2.8.1 unless noted)
- **Recall is lexical** (FTS5) unless embeddings are installed *and* enabled. The hard-suite ageing recall@5 is 0.733 (S3).
- Episodes are stored, not recalled (S3).
- Per-user isolation is interim (S4).
- Prefetch is synchronous (S4).
- `hermes plugins validate` prints two "declared but not registered" warnings. They're kept on purpose (the catalog verifies against those lists).
- Native Windows is unsupported on 2.8.x (fixed on the 3.0 line).
- Audit-chain limitation: deleting a middle row *and* re-chaining the tail is undetectable without an anchor outside the database (documented and deliberately not built).
- **Strict xfails that remain:** F-009 episodes, per-user isolation, async prefetch. (F-010 / EM-212 is fixed on `main`.)

## 8. Budgets and gates that stay in force
- **Performance:**
  - prefetch warm p95 of 10 ms (§6.4); CI allows 20 ms, with 20 probes;
  - entity linking p95 of 2 ms per memory at 10k entities (measured 0.18 ms).
- **Evals:**
  - `evals-ci` compares only the §6.3 gated metrics against the `v2.8.0*` baselines;
  - the §6.3 thresholds were "gate from 2.8.0".
- **Concurrency (EM-202 AC):** 4 writers × 500 writes + 1 reader, zero errors, reader p95 under 50 ms.
- **Jobs (EM-209):** a 4-process exactly-once test.

## 9. Open decisions (owner)
1. Post the reply to Teknium on #122476, or not (draft exists).
2. After the safe point, when to schedule Chunk 2 (`NEXT_CHUNK.md`).

## 10. Operations checklist (Hermes host)
- **Before 2 Oct:** show the cleanup script's ancestor-check line and dry-run it.
- **Gateway heartbeat:** the cron scheduler once reported "no gateway or no fresh profile heartbeat". Confirm the gateway is up before crons fire.
- **Catalog-check cron:** idle box only. It must never push the old fork branch.
- **Stale local branches** (`fix/em-211-facade`, `fix/plan-gaps`, `em/em-205…208*`): their contents are in `main`; delete them.
