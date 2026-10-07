# EntropicMem: remaining plan (from the 2.8.1 safe point)

**Status date:** 2026-10-06. **Where we are: `MASTER_TODO.md` first (the short canonical page), then §11 (cold start), §2 (state), §5 (the ledger).** **Owner:** the owner (GitHub `Ufonik88`). **Builders:** Hermes (implements and merges), Claude Code (reviews, fixes, plans).
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

## 2. Where things stand (verified 2026-10-06, after Chunks 5 and 6)

### Repository `Ufonik88/EntropicMem` (public)
| Ref | SHA | Meaning |
|---|---|---|
| `main` | `1b5c71ccf` or later | 3.0 development line (`3.0.0.dev0`). All of S2, the v3 foundations, the catalog-review fixes, the perf-smoke fix, EM-212 (first step), the 2.8.1 notes, the plans, the §5 card text pastes, Chunk 2 (`entropicmem worker run` plus the EM-209/EM-210 deviation record), the 2026-09-29 hygiene batch (CI action majors, perf-smoke diagnostics, the concurrency-test flake fix, the doc-link and CLI-reference guards), **Chunk 3.1** (`snapshot()` over `memory.db` + `index.db` in `backups/<reason>-<stamp>/`) and **Chunk 3.2** (the once-per-hour-per-reason snapshot throttle, `snapshot_if_due()`), **Chunk 4** (`em/facade/engine.py`, the facade's read half over `em.store`, `0349b7b4b`), the live-store deny-list fix (`03772e3c`), a contributor's `tests/test_vault.py` path fix (`1b5c71ccf`), **Chunks 5, 6 and the document-control rule**, merged 2026-10-06 at `e25db32` after green CI on that exact SHA, and the 2.8.x-status clarification (`f2deea0`). **Chunk 7.1 (the entity-link job)**, merged at `64a2685` after green CI on that exact SHA, the 2.8.x-status clarification (`6f9a3cf`), the 2.8.x-status clarification (`ed03ad8`), and **Chunk 7.2 (the owner-only read rule)**, merged at `783aae9` after green CI on that exact SHA. **Chunk 8 (EM-212's package move)**, merged at `c922970`, and the 2.8.x marketplace guideline (`ed03ad8`). **Chunk 9 (the provider's engine selection)**, merged at `0200424` after green CI on that exact SHA. |
| branch `release/2.8.x` | `7e02412` | **2.8.1**: `v2.8.0` plus the safety fixes (see §4). Protected (no force-push, no deletion). Tag `v2.8.1` exists. |
| tag `v2.8.0` | tag `09a5459` → commit `060063d` | The previous release. |
| tag `v2.8.1` | `7e02412` | **Current release.** Safety patch on 2.8.0. GitHub Release published. |
| leftover branches | None | All merged or duplicated branches deleted. Only `main` + `release/2.8.x` remain on remote. |
| republish baseline | `35a02f4` | First commit of the cleaned public history. It must stay an ancestor of `main` forever. |

- **Dead SHAs** (never push them anywhere public): `e47e956`, `0e5e39c`, `93ef951`, `6b62a21`, `f15fe12`, `9a2c1df`, `437c89b`.
- **Private archive:** `Ufonik88/EntropicMem-archive`. It holds the old history with personal data. **Never make it public.**

### Marketplace (Hermes plugin catalog)
- **2.8.1 is live.** PR #124936 landed on `NousResearch/hermes-agent` main (Teknium closed our #124837 and landed it himself). The catalog entry `entropicmem` is version `2.8.1`, pinned at `7e02412`.
- Fresh install verified on Mac (2026-09-28): sha `7e02412`, 7 tools, 5 hooks, remember/recall round-trip passed.
- Maintainer: Teknium. His rule: **never rewrite history on a listed repo** (`AGENTS.md` rule 9).
- The fork branch `catalog/entropicmem-2.8.0` ends in Teknium's `cdfcd83`. **Never push that branch again.** Any future catalog PR starts from a fresh branch off upstream.

### Hermes host (the owner's machine)
- **Live install:** `~/.hermes/entropicmem-live-2.8.1` at `7e024123`, the pinned read-only clone (no remote). The default profile's `~/.hermes/plugins/entropicmem` stays a real directory and is version 2.8.1; the other nine profiles symlink to the pinned clone. The graph server runs on 8075/8076.
- **Crons:**
  - the old-clone cleanup script, due 2 Oct. Ancestor check verified: `git merge-base --is-ancestor 35a02f4… origin/main` (line 58).
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
   - update `MASTER_TODO.md`, and §2 and §6 of this file in the repo;
   - write the next chunk's plan (`docs/plan/NEXT_CHUNK.md`), with **only one** chunk planned ahead;
   - add a vault note entry (see §3.4).

   Document control is **first and last**, not a closing formality: reconcile
   the docs *before* starting a task as well as after, so the next agent never
   begins from a stale description. The rule is written out in full in
   `AGENTS.md` ("Document control — first and last") and enforced by
   `tests/test_master_todo.py`.
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

### 3.3 Autonomy, and the calls the owner keeps

The agent decides and acts on its own judgment for everything not listed
below, then reports what it did: card assessment and rewrites, plan edits,
dispatch, code review, CI triage, docs and bug fixes. Waiting on the owner
when the evidence in front of the agent settles the question costs a round
trip and buys nothing.

The owner is asked only when the action is irreversible or public:

- Anything touching real data or the live store, including the v3 cutover.
- Releases, tags and the Hermes catalog entry (including public replies on the catalog PR).

A test that cannot pass without weakening it is a hard stop for the agent:
report the gate, do not weaken the test and do not ask permission to.

Whether to continue past the decision gate after S4 (§6.6) is the agent's
call, taken with a written recommendation the owner can veto at any time.

### 3.4 Memory and logging
- **The canonical short status page is `MASTER_TODO.md` at the repo root**, written 2026-10-06. It and this file and `NEXT_CHUNK.md` are the three documents an agent needs; `MASTER_TODO.md` is the one to open first. `tests/test_master_todo.py` enforces that it exists, stays linked, keeps its sections, and that its recorded SHA is a real ancestor of the branch.
- These files live in the repo (this file and `NEXT_CHUNK.md`, `NEXT_CHUNK.md` task H3), and the owner links them from the Claude vault (`projects/entropicmem.md`).
- **Claude Code cloud sessions can't reach the vault.** They produce a `/save` file; the owner files it from Claude on his Mac.

---

## 4. Step 0: reach the safe point (2.8.1). **DONE (2026-09-28).**

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

**Steps (all done):**
1. Branch `release/2.8.x` created at `7e02412` (Claude Code).
2. Tag `v2.8.1` and GitHub Release published. `release/2.8.x` protected.
3. Catalog re-pin PR opened (#124837), then landed by Teknium via PR #124936. Catalog: version `2.8.1`, sha `7e02412`.
4. Fresh catalog install verified on Mac (2026-09-28): sha `7e02412`, 7 tools, 5 hooks, remember/recall round-trip passed.

**Public reply on #122476:** skipped (owner did not say "post it").

**Safe point reached. Feature development stops until the owner schedules Chunk 2.**

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
| EM-212 (first step) | `_backend` loads its own `vault.py` by path; `test_f010` made real. The plan's full EM-212 (package move) is still open | `4ae5b11` |
| docs | 2.8.1 notes forward-ported; `docs/plan/` added | `cdff579` and later |
| **2.8.1** | safety patch branch `release/2.8.x` | `7e02412` (tagged, released, catalog-pinned, install-tested) |
| Chunk 2 | `entropicmem worker run` (v3-only; refuses a live path and a non-v3 store; one JSON line; a `dead` job exits 1) and the recorded EM-209/EM-210 deviations | `0cfac9d`, `dca80f4`, `ad5f0e5`, `8fca999` |
| Chunk 2 close-out (docs) | §2, §5, §6.1, §9 and §10 refreshed; Chunk 3 planned in `NEXT_CHUNK.md` | 2026-09-29 |
| Hygiene batch (no-bump) | `actions/checkout@v7` + `actions/setup-python@v7`; `perf-smoke` prints p50/p95/max; the concurrency AC test can no longer measure an empty sample list; `ARCHITECTURE.md` gains the v3 core; new `tests/test_docs_links.py` and `tests/test_cli_reference_drift.py` | `e6e8fdb`, `3d70496`, `74ce059`, `453b4ad`, `fa623e8`, `a6fc6f7`, `a38a47f` |
| Chunk 3 split (docs) | the EM-210 gaps split into **3.1** (`snapshot()` covering `index.db`, `backups/<ts>-<reason>/`) and **3.2** (the throttle) | 2026-09-29 |
| **Chunk 3.1** | `snapshot(reason) -> Path`: a snapshot is a directory holding `memory.db`, `index.db` (when it exists) and `manifest.json` with a per-file sha256/size/counts/user_version; `create()` kept as an alias; `verify()` re-hashes every file; restore stages every file and swaps only when all verify; rotation counts both layouts; pre-3.1 flat backups stay readable; a snapshot that cannot copy a database fails whole and leaves nothing behind | `2d60cccfb` |
| **Chunk 3.2** | `snapshot_if_due(reason, *, window=3600)`: at most one snapshot per reason per hour for destructive callers ("100 `forget` → ≤ 1 snapshot/hour"), with the window derived from the `created_at` every manifest already carries so there is no schema and no migration; safety reasons (`pre-migrate*`, `pre-restore*`) and a zero window exempt; `snapshot()`/`create()` still unthrottled. Retention recorded as settled at 7 routine + 5 safety | `e058e93be` |
| **Chunk 4** | `V3Engine` read half of `LegacyEngine` over `em.store`: `get_fact` (v3 id, unique id prefix, and `legacy_id`, so `get_fact(StoredFact.make_id(content))` resolves), `stats`, `recall_with_relevance`, `recall_hybrid`, `next_episode_wave`, with recall reached through a lazy `memory_engine` import to avoid the 3.0 cycle. Registered in `ENGINES` and `_implementations()`. The 7 write methods stay `NotImplementedError` stubs. Parity seed fixture split per plan §4.0.3 (`_remember` dispatch falling back to `MemoryStore.add`; `WRITE_ENGINES` v2-only); **no assertion changed**. 17 new tests; 1542 passed / 2 skipped / 4 xfailed; em-qa APPROVED | `0349b7b4b` |
| **Chunk 5** | The 7 stubs replaced with real write paths: `remember` (stamps `legacy_id = sha256(content)[:16]` — profile-wide only, since `legacy_id` is UNIQUE and content-derived; `MemoryStore.add` carries policy/PII/injection/dup/version/outbox/audit/embed), `forget` and `consolidate` as §3.4 status transitions with a throttled `snapshot_if_due` taken **outside** the write txn, `touch` resolving ids and returning the matched count, `extract_and_store` quarantining into `pending` then promoting over `pending -> active` (one versioned row, not v2's two), `prune_pending` over the same edge, `add_episode` stamping `episodes.legacy_id` and upserting a refired id. `WRITE_ENGINES` gains `v3-facade` and the `_remember` dispatch is deleted, so **6 write-path parity scenarios run against both engines; no assertion changed**. Recorded deviations: no fuzzy overwrite, `linked_fact_ids`/`domain`/`source` ignored on episodes (no column, no migration in this chunk), no deprecation warnings. 56 new tests + 6 parity params; 1604 passed / 3 skipped / 4 xfailed; 12 mutation checks | `36355f3` (merged in `e25db32`) |
| **Chunk 6** | The mirror call: `find_mirrored(needle) -> Optional[str]` on **both** engines, so `_locate_mirror` stops running `SELECT id, content, tags FROM facts` against `engine.db` — the provider's last raw-connection read and the one thing a v3 facade could not serve. `PROVIDER_ATTRIBUTES` is now **empty**, `BEHAVIOURS["mirror-scan"]` moves from the last OPEN item to a cited behaviour with five parity scenarios, and `open_items` in the coverage test is an empty set. v2's version is the provider's scan moved behind a method; v3's adds the three filters v2 got for free — `status='active'` (a forgotten mirror must not be locatable), the §3.5 scope rule (invariant 5), and `mirrored` as a whole tag where the quoted JSON `LIKE` is only a pre-filter and the parsed **list** decides. The `make_id(previous_content)` fast path is unchanged. 15 new tests; 1624 passed / 3 skipped / 4 xfailed; nine mutation checks | `6bd4b47` (merged in `e25db32`) |
| Document control | `MASTER_TODO.md` created at the repo root (the plan had pointed at one that existed only in a single agent's private memory); `AGENTS.md` gains "Document control — first and last" and always-rule 8; `tests/test_master_todo.py` enforces it — exists, carries its sections, is **linked** from `AGENTS.md` and the README, records a SHA that is a real ancestor, and cannot report a chunk `Done` while In flight says unmerged. 5 tests, six mutation checks | `436d360`, `81859d0` (merged in `e25db32`) |
| **Chunk 7.1** | The entity-link job. `MemoryStore` enqueues `link:<memory_id>:<version>` from the write path, beside the existing `embed` enqueue, and the linker never runs inline (invariant 2). `make_link_handler` opens its own transaction and is idempotent across a retry (`EntityStore.link` upserts; the sighting counter counts distinct memories). A payload with no `memory_id`, or a memory that no longer exists, dead-letters; a memory that is merely not live is done, not failed. The row's own scope is used. Promotion (`pending -> active`) and a content `update` both queue a link job, matching the embed enqueue. `entropicmem worker run` registers the handler and knows `--types link`. Known limitation, asserted: promotion links whichever memory's job trips the sighting counter and does not retro-link the earlier one (backfill is S5's `reconcile`). 17 new tests; 1643 passed / 3 skipped / 4 xfailed on 3.10 and 3.12; seven mutation checks | `96c4ccb` (merged in `64a2685`) |
| **Chunk 7.2** | The §3.5 owner-only rule for reads. `_in_scope` (the one function invariant 5 names) now hides a `sensitive`/`secret` row from anyone but its owner, and the facade's four read paths route through it: `get_fact` passes `scope`, FTS recall and the literal-LIKE fallback filter through `_in_scope`, and `find_mirrored` does too. `Scope.is_owner` defaults to **False** (fail-closed) with a profile-wide caller treated as the owner context, so a wiring mistake hides the owner's own sensitive rows rather than showing them to a guest. `V3Engine` takes `is_owner` as a constructor argument. Known gap recorded: `MemoryStore.list` keeps profile+user only, so `prune_pending`/`consolidate` are not tier-filtered. 26 new tests; 1669 passed / 3 skipped / 4 xfailed on 3.10 and 3.12; six mutation checks | `563afe5` (merged in `783aae9`) |
| **Chunk 8** | EM-212's package move. The six shared-name engine modules (`vault`, `index`, `security`, `policy`, `embeddings`, `retrieval`) moved under `scripts/em_internal/`, so the import system registers `em_internal.*` and never the bare names; every importer updated (provider, CLI, `graph_server`, `em/`'s two lazy `policy` imports, tests), and `_backend._own_module` deleted in favour of a qualified import. The strict xfail **flipped to a passing test**. Three silent coverage losses repaired: `test_f005`'s non-recursive glob, `test_plugin_imports`'s module list, and the packaging guard (now derived from every package under `scripts/`, so `em_internal` cannot ship missing). The other 14 modules keep unprefixed names deliberately — the AC names only the six. 52 files touched; 1671 passed / 3 skipped / 3 xfailed on 3.10 and 3.12; two mutation checks. `hermes plugins validate` runs in CI and passed: no module-shadow warning, only the expected `provides_*` pair | `025f012` (merged in `c922970`) |
| **Chunk 9** | The provider selects its engine by the store's `user_version`: v2 stores get `MemoryEngine`, v3 stores get the facade. Read **read-only before any engine is constructed**, because `V3Engine.__init__` calls `migrate()` — so opening a v2 store cannot cut it over. All **nine** `MemoryEngine(` sites in the provider route through one `_open_engine()`, with a drift guard. The selector (`em/facade/select.py`) refuses a store newer than this build and a versioned store with no `memories` table. The gateway identity is threaded into the facade (`is_owner = not _is_guest()`). **The CLI is deliberately not wired** — it calls ~28 methods the facade lacks — so it stays on `MemoryEngine`; CLI parity is Chunk 10 and the cutover waits on it. Deviation: `pii_locales` has no facade equivalent. 16 new tests; 1687 passed / 3 skipped / 3 xfailed on 3.10 and 3.12; seven mutation checks. | `b615bcf` (merged in `0200424`) |
| **Chunk 10.0** | The CLI's `_engine()` now refuses a **v3 store clearly** instead of handing it to the v2 engine, which would fail confusingly part-way through a command. It still opens v2 and not-yet-existing stores exactly as before. This is the first step of the CLI-parity route and it means nothing silently misbehaves while the rest of the gap is filled. 3 new tests | `a518f3f` (merged in `87243f8`) |
| **Chunk 10.1** | The facade's eight CLI read/listing calls (`list_facts`, `list_pending`, `list_audit`, `get_versions`, `episode_stats`, `embedding_stats`, `list_episodes`, `recall`), each returning the shape the CLI prints. Two refusals by name: `list_episodes(domain=...)` and `recall(scope='shared'|'all')`. `get_versions` collapses v3's creation-row duplicate and reverses the order, both verified against v2 (probe: create A, update B, update C → `['B','A']` on both). `profile_id` was dropped from the slice after measuring — its only caller is `cmd_migrate --status`, which is in the refuse group. Known papercut recorded for 10.4: `remember` returns the v3 id while reads present the legacy id. 15 new tests; 1707 passed / 3 skipped / 3 xfailed on 3.10 and 3.12; nine mutation checks | `f439e55` (merged in `b807e4c`) |
| **Chunk 10.2** | The facade's six CLI maintenance calls (`promote_pending`, `discard_pending`, `reinforce`, `rebuild_fts`, `timeline`, `recall_episodes`). `promote_pending`/`discard_pending` are §3.4 transitions, so a promoted row keeps its id — v2 re-`remember`ed and produced a new one. Recorded deviation: v3 does not re-stamp `source="promoted"` or add the tag. `rebuild_fts` is a report-only no-op (v3's FTS is trigger-maintained). 15 new tests | `cc19337` (merged in `f36c5e6`) |
| **Chunk 10.3** | The CLI's **v2-only features now refuse by name** on a v3 store, before `_engine()` is reached: triples (S5), `embed --rebuild` (S3/EM-303), `memory project` (S6), publish/pull (S5), `migrate` (v2-only), `recall --related` (S6) and `recall --scope shared\|all` (S5). These are what stops an `AttributeError` once 10.4 routes. 12 new tests, one asserting every refusal names a trigger | `cc19337` (merged in `f36c5e6`) |
| **Chunk 10.4** | The CLI selects its engine by `user_version` through the same `open_engine` the provider uses, so its ported commands run against a v3 store and the v2-only ones still refuse by name (their guards run before `_engine()`). **EM-211's AC is met except for seven named refusals.** The chunk's point is the **v2 regression pass**: routing changed engine construction for every store, and a subprocess suite proves a v2 store still works and is **not migrated**. Fixed alongside: Chunk 9 passed `profile_id=self._profile_id or "default"`, making the profile *explicit* and overriding the `hermes_home`-derived slug a v2 store has always carried — `open_engine` now takes `profile_id=None` meaning "the engine decides". 18 new tests + 2 regression tests; 1751 passed / 3 skipped / 3 xfailed; six mutation checks | `250320a` (merged in `c50d7b6`) |
| **EM-302 (first piece)** | `em.retrieval` created, with **`scope_sql`** — the §3.5 rule as SQL, the helper every generator filters through. `may_read_owner_only(scope)` moved into `em/store/types.py` so `_in_scope` (the predicate) and `scope_sql` (the SQL) share one definition of the owner context and cannot drift; the tier names come from `OWNER_ONLY_TIERS` on both sides. Tests cross-check the two forms over a real row matrix instead of restating the rule, plus a guard that the matrix discriminates. 6 new tests; 1757 passed / 3 skipped / 3 xfailed; six mutation checks | `0066fb5` (merged in `50c5310`) |
| **Chunk 13 (visibility)** | §3.5's other half, both sides. **Write:** `MemoryDraft.visibility`'s default becomes `''` = *derive from the scope* (`'profile'` profile-wide, `'user'` otherwise, explicit preserved) — the old `'user'` default stamped every profile-wide write with the value §3.5 reserves for user-scoped rows, which is the exact shape §3.5 makes owner-only. **Read:** `em.store.types.row_is_owner_only` owns both owner-only conditions (the tier, and a profile-wide row stamped `'user'`), called by `_in_scope` and `scope_sql`. **The direction was the point:** the read clause alone would have hidden every profile-wide memory from non-owners. **Also fixed:** `_outbox` never checked sensitivity, which the old default hid by accident — v2 published every non-sensitive fact, and this restores that. **No migration, reversible.** 30 new tests; 1862 / 3 / 3; 13 mutation checks. Agent-proposed, owner-authorised, **internal only** | `fd9e06f` (merged to `main`) |
| **EM-301 (analyzer)** | `em/retrieval/query.py` gained `analyze()`: `<memory-context>` stripped, `\w+` tokens, 180-word stopword list (the same set v2 uses), IDF term selection capped at 12, intent via a 42-query labelled table (39/42 = 92.9%, three declared misses), entity aliases resolved in one profile-scoped `IN` probe, and the common temporal shapes. **Migration `0004`** adds `memories_vocab`. **Two findings kept:** the `fts5vocab` view holds porter *stems*, so a raw-token IDF lookup would silently collapse into length ordering — bridged with an FTS5 `MATCH` count for the tokens the view lacks; and an all-stopword query ("who am I") keeps its own tokens, which §3.6 does not cover. `write_generation` and `query_rewrite` recorded as gaps. 37 new tests; 1832 / 3 / 3 on 3.10 and 3.12; 19 mutation checks | `85afea4` (merged to `main`) |
| **EM-302 (generators)** | The card text was **found** (master plan on the owner's machine) and is transcribed into §6.2. Five generators — `bm25` (§3.6's column weights), `entity` (＋1 hop at ×0.5), `episodic` (`owner_type='episode'`, time window), `recent` (48 h, intent-gated), `pinned` — plus `Candidate` = ranked `(owner_type, owner_id, raw_score)`, `RetrievalContext`, and `match_expression`. Deadline discipline is structural: checked before any SQL and between pages. **`scope_sql` gained §3.5's chat half**, retiring a drift where `MemoryStore.list` filtered `scope_chat` and `_in_scope` did not. `vector` is EM-303's. 38 new tests; 1795 / 3 / 3 on 3.10 and 3.12; 15 mutation checks | `33b2b31` (merged at `33b2b31`) |
| **PII locale fix** | `pii_locales` (EM-115 packs) now reaches redaction on **both** engines: `MemoryDraft` carries them to `MemoryStore._redact`, which passes them to `redact_pii`, and `V3Engine` takes and forwards them. v2 took the packs on the engine; v3 had silently dropped them, so a store configured for the `za` pack lost that detection. The tier gate (redact only `sensitive`/`secret`) is deliberate and tested, and stays. 3 new tests | `a518f3f` (merged in `87243f8`) |
| Vault path fix (contributor) | `tests/test_vault.py` compares resolved paths instead of raw strings so the explicit-precedence check passes off Linux (macOS `/tmp` → `/private/tmp`); author email rewritten to the contributor's GitHub noreply on merge so no personal address entered published history | `1b5c71ccf` |

---

## 6. What is left: the full remaining plan

Cards are grouped by the master plan's sprints. **"(plan text needed)"** marks cards whose title and AC must be pasted from master plan §5 (`NEXT_CHUNK.md` task H3). Everything stated about a card here is known from code or earlier decisions and must be kept when the plan text is added.

**Known gaps (2026-10-07), carried from `MASTER_TODO.md`:** §3.5's `visibility='user'` owner-only clause for profile-wide rows is not implemented (privacy; own card); `vector` is EM-303's; `recent`'s session half needs a session id; EM-211's seven refusals each name the card that lifts them. **The master plan is at `~/Documents/EntropicMem Dev docs/EntropicMem_v3_Master_Plan.md`; EM-302's card and §3.6 are transcribed in §6.2.**

**The critical path, as recorded in the plan:**
- EM-201 → EM-203 → EM-204 → EM-205 (done);
- then S3: EM-302 → EM-304 → EM-305 → EM-403 → EM-503 → EM-901 → EM-904.

### 6.1 S2 remainder: finish the storage core (small cards, good first chunks)

**Done on 2026-09-27 by Claude Code:**
- `fix/perf-smoke-probes` merged into `main`;
- the 2.8.1 notes and the README semantic-recall line forward-ported;
- this plan committed to `docs/plan/`;
- **EM-212, first step:** `_backend` loads its own `vault.py` by path under a private module name (fixes another plugin's `vault` hijacking the path lookup); `test_f010` is now a real check and passes.

**Housekeeping (all done 2026-09-28):**
- master plan §5 text pasted into §6 (`25322dc7e`);
- leftover remote and local branches deleted;
- cleanup cron ancestor check verified.

**EM-212, rest of the card — DONE (Chunk 8).** The six named modules moved under `scripts/em_internal/`, so no unprefixed `vault`/`index`/`security`/`policy`/`embeddings`/`retrieval` module is registered in the host process. The strict xfail `test_em212_plan_ac_no_unprefixed_engine_modules_in_process` (`tests/test_backend_namespace.py`) **flipped to a passing test**. `_backend`'s path-loading shim is gone, because a qualified import cannot collide. The remaining 14 modules keep unprefixed names: the AC names only the six, and moving the rest is a deliberate follow-up rather than part of this card.

**EM-211: legacy facade.** Implement `LegacyEngine` over `em.store` so the provider can run on v3 unchanged.
- Done when it is added to `ENGINES` in `tests/parity/test_engine_parity.py` and to `_implementations()` in `tests/unit/test_em_facade_contract.py`, and both pass **unchanged**.
- Known requirements:
  - `get_fact(StoredFact.make_id(content))` must resolve: store `sha256(content)[:16]` as `legacy_id` on `remember` — **done in Chunk 5**, and only for a profile-wide write, because `memories.legacy_id` is UNIQUE and content-derived;
  - replace the raw `engine.db` read in `_locate_mirror` with an engine method on **both** engines, then drop `db` from `PROVIDER_ATTRIBUTES` — **done in Chunk 6** (`find_mirrored`; `PROVIDER_ATTRIBUTES` is now empty);
  - run `EntityLinker` from a `link:<memory_id>:<version>` job, never inside `MemoryStore.add` — **done in Chunk 7.1** (`96c4ccb`, merged in `64a2685`): the store enqueues, the handler runs outside the transaction, and the worker registers the type;
  - the `§3.5` owner-only rule for sensitive rows needs the gateway identity and lands here.
- **All four sub-chunks are now code-complete**: reads (`0349b7b4b`, merged), writes (`36355f3`) and mirror (`6bd4b47`) merged in `e25db32`, the link job (`96c4ccb`) merged in `64a2685`, and the §3.5 owner-only read rule (`563afe5`) committed. **The provider and the CLI both select their engine now (Chunks 9 and 10), so the card's AC is met for every command except seven named refusals.** The exception is the seven v2-only features 10.3 refuses by name (triples → S5, `embed --rebuild` → S3/EM-303, `memory project` → S6, publish/pull → S5, `migrate` → v2-only, and the two v2-only `recall` forms) — a deliberate, itemised exception, each naming the card that lifts it. **The only thing left is the cutover**, which is the owner's act and is now technically available.

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
- **EM-209: closed in Chunk 2 (2026-09-29).** `entropicmem worker run` exists, and the remaining wording differences (`em/jobs/worker.py` vs `em/worker.py`, keyword-only `claim`, the capped and jittered backoff, no per-job `time_budget`) are recorded as deviations in `docs/V3_FOUNDATIONS.md` → "Recorded deviations from the plan". Priority semantics match the plan (lower number runs first, default 5).
- **EM-210: split into two chunks, both done (2026-09-29).** The gaps were independent, so they travelled separately:
  - **Chunk 3.1: the snapshot layout.** `snapshot(reason) -> Path` covers `index.db` and writes `backups/<reason>-<stamp>/`; today's flat files stay readable, verifiable and restorable. Detail in `docs/V3_FOUNDATIONS.md` and `docs/BACKUP_RESTORE.md`.
  - **Chunk 3.2: the once-per-hour-per-reason throttle.** `snapshot_if_due(reason, *, window=3600)` returns `None` while a snapshot for that reason is younger than the window, which is the plan's "100 `forget` → ≤ 1 snapshot/hour" AC. The window comes from the `created_at` already in every manifest, so no schema and no migration. Safety reasons (`pre-migrate*`, `pre-restore*`) are deliberately exempt, and `snapshot()`/`create()` stay unthrottled for the migration hook, the daily job and the tests.
  - **Retention: settled, the current rule stays.** 7 routine + 5 safety, not EM-113's keep-10 + one per day for 7 days. Recorded in §9 and in the EM-210 row of the deviation table.
- **EM-211 (foundation):** met as a foundation; the facade itself is nearly done (above). **Chunk 4 (reads) landed 2026-10-03 at `0349b7b4b`** — see §5. **Chunks 5 (writes, `36355f3`) and 6 (mirror, `6bd4b47`) are merged in `e25db32`.** **Chunk 7.1 (the link job, `96c4ccb`) is merged in `64a2685`; 7.2 (the §3.5 owner-only rule) is next.** The provider still runs v2.

**Tool rename (3.0 only):** `entropicmem_patch_core` → `entropicmem_patch_core_memory` (catalog maintainer's ask). Update the provider, `plugin.yaml`, `SKILL.md`, docs and tests together. It ships only with a release that re-pins the catalog (rule 10).

**Stays true:** `SKILL.md` keeps describing the installed version until EM-806/EM-904 bump it.

### 6.2 S3: retrieval v3 (critical path starts here)
- **EM-301 — QueryAnalyzer · M. — DONE (Chunk 12, `85afea4`).** Card text from master plan §5.
  - **Files:** `em/retrieval/query.py`, `em/retrieval/stopwords.py`, `em/retrieval/temporal.py` (EM-310).
  - **Spec (verbatim):** "as §3.6. `memories_vocab` = `CREATE VIRTUAL TABLE memories_vocab USING fts5vocab(memories_fts, 'row')` (migration 0003). IDF = `log((N - df + 0.5)/(df + 0.5) + 1)` with `N` = active memory count (cached per `write_generation`). Defensively strip `<memory-context>…</memory-context>` (the host already strips skill scaffolding — markers in `agent/skill_commands.py` — before calling the provider)."
  - **AC (verbatim):** "unit tests for term selection, intent detection table (≥ 30 labelled queries, ≥ 90% accuracy), entity detection."
  - **Note:** migration `0003` is already taken by `0003_audit_append_only`, so the vocabulary table becomes **migration `0004`**.
  - **§3.6 term rules (verbatim):** "`\w+` tokens, casefold, drop stopwords (built-in English list ~180 words + config `extra_stopwords`), drop tokens `len < 2`. Prefix match (`"tok"*`) only for `len ≥ 4`; otherwise exact. Max 12 terms, selected by **IDF** from `memories_fts` vocab (`fts5vocab` table `memories_vocab` 'row' type) then length as tiebreak." Intent: "`profile` (who am I / my preferences), `temporal` (when / last time), `procedural` (how do I / steps), `lookup` (default). Intent adjusts generator weights."
- **EM-302 — Candidate generators · M. — DONE (Chunk 11, `33b2b31`).** Card text transcribed here from master plan §5 so it never has to be fetched again.
  - **Files:** `em/retrieval/candidates.py`, plus `em/retrieval/query.py` (`AnalyzedQuery`) and `em/retrieval/temporal.py` (`TimeRange`), both types-only until EM-301/EM-310 fill them.
  - **Card text (verbatim):** "each generator is a function `(ctx: RetrievalContext) -> list[Candidate]` where `RetrievalContext` has `aq`, `scope`, `now`, `limits`, `deadline`. All SQL filters by scope via a single helper `scope_sql(scope) -> (clause, params)` implementing §3.5 (unit-tested truth table). BM25 query uses per-column weights. Episodic generator returns `owner_type='episode'`."
  - **AC (verbatim):** "each generator has tests incl. scope isolation (user A never sees user B's rows); deadline respected (generator returns partial within 5 ms of deadline)."
  - **The generator set is defined by §3.6, not by the card** — "candidate generators (parallel-safe, each ≤ N) … each returns ranked `(owner_type, owner_id, raw_score)` restricted by `ScopeContext` and `status='active'`":
    | Generator | Source | Default k | Notes |
    |---|---|---|---|
    | `bm25` | `memories_fts MATCH` | 40 | `bm25(memories_fts, 1.0, 0.5, 0.3, 0.1)` column weights |
    | `vector` | embeddings (memory) | 40 | cosine; only if backend available and coverage ≥ 50% — **EM-303, not in EM-302** |
    | `entity` | `memory_entities` for detected entities (+1 hop relations) | 30 | |
    | `episodic` | `episodes_fts` + time window | 10 | owner_type `episode` |
    | `recent` | memories `ORDER BY updated_at DESC` in current session / last 48 h | 10 | only when intent ∈ {temporal, lookup} |
    | `pinned` | `pinned=1` or kind `constraint` for scope | 10 | bypasses gate (still budgeted) |
  - **Landed:** the five non-`vector` generators; `Candidate` (exactly the three fields); `RetrievalContext` (plus `conn`, which the stated signature requires — a generator's job is SQL and the card's field list gives it nowhere to get a connection); `match_expression` (EM-301 picks terms, this renders them); `scope_sql` extended with §3.5's chat dimension and its `owner_only=False` form for `episodes` (no `sensitivity` column).
  - **Deadline (AC):** structural, not timing-dependent — `RetrievalContext.out_of_time()` is consulted *before* any SQL and between result pages, so an expired generator issues no query at all (proved with a recording connection) and one that expires mid-scan returns a partial list (proved by driving `candidates._monotonic`).
  - **Recorded gaps** (V3_FOUNDATIONS.md): `vector` → EM-303; §3.5's `visibility='user'` owner-only clause for profile-wide rows → its own card (privacy); `recent`'s "current session" half needs a session id the context does not carry; `raw_score` is made higher-is-better (SQLite's `bm25()` negated) although §3.6's fusion is rank-based.
  - **Evidence:** 38 new tests; 1795 passed / 3 skipped / 3 xfailed on Python 3.10 and 3.12; 15 mutation checks.
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
After S4 the agent decides whether S5–S9 are worth continuing, and records a
written recommendation (scope, cost, what is still missing) before starting
them. The owner can veto at any time; the agent does not block waiting for
approval. The plan does not have to be finished for EntropicMem to be useful.

---

## 7. Known limitations (true at 2.8.1 unless noted)
- **Recall is lexical** (FTS5) unless embeddings are installed *and* enabled. The hard-suite ageing recall@5 is 0.733 (S3).
- Episodes are stored, not recalled (S3).
- Per-user isolation is interim (S4).
- Prefetch is synchronous (S4).
- `hermes plugins validate` prints two "declared but not registered" warnings. They're kept on purpose (the catalog verifies against those lists).
- Native Windows is unsupported on 2.8.x (fixed on the 3.0 line).
- Audit-chain limitation: deleting a middle row *and* re-chaining the tail is undetectable without an anchor outside the database (documented and deliberately not built).
- **Strict xfails that remain:** F-009 episodes, per-user isolation, async prefetch, and the EM-212 plan AC (package namespace). F-010 (`_backend` bare import) is fixed on `main`.

## 8. Budgets and gates that stay in force
- **Performance:**
  - prefetch warm p95 of 10 ms (§6.4); CI allows 20 ms, with 20 probes;
  - **`perf-smoke` has flapped twice on unchanged code.** 2026-09-27: warm p95 34.815 ms on a docs-only commit, with the next commit (no code change) passing. 2026-10-07 at `f36c5e6` (the Chunks 10.2/10.3 merge): the branch run and the local run were ~4–5 ms p95, `main` came back **p95 69.392 / p50 4.544 / max 109.506**, and a rerun of the same SHA gave **p95 5.388 / p50 3.437 / max 8.142**. The chunk's code is not on that path at all — `evals/perf.py` builds `MemoryEngine` directly, never through `_open_engine`. The dev-box reference for the same command is 6.175 ms p95 (p50 5.131, max 8.161, 20 probes): `env -u ENTROPICMEM_MEMORY_DB -u ENTROPICMEM_INDEX_DB -u ENTROPICMEM_VAULT_PATH PYTHONPATH=plugins/entropicmem/scripts python3 -m evals.perf --sizes 1000 --probes 20 --out-dir /tmp`. The job now prints p50/p95/max/samples, so a low p50 with a high max reads as one noisy sample and a p50 near the budget reads as a regression. A lone red `perf-smoke` is not a regression until it repeats on the same commit, and the budget stays at 20 ms (already 2× §6.4);
  - entity linking p95 of 2 ms per memory at 10k entities (measured 0.18 ms).
- **Evals:**
  - `evals-ci` compares only the §6.3 gated metrics against the `v2.8.0*` baselines;
  - the §6.3 thresholds were "gate from 2.8.0".
- **Concurrency (EM-202 AC):** 4 writers × 500 writes + 1 reader, zero errors, reader p95 under 50 ms.
- **Jobs (EM-209):** a 4-process exactly-once test.

## 9. Open decisions (owner)
1. **Merge Chunks 5 and 6: DONE (2026-10-06).** Merged to `main` at `e25db32` (`git merge --ff-only`) after green CI on that exact `headSha`; branch deleted. The first CI run was red on two real problems — a Python-3.10-only timestamp bug in the facade and a shallow-checkout failure in the new doc guard — and both fixes rode in the same merge. See `CHANGELOG.md` under Fixed.
2. **The cutover is now available; the call is recorded in item 5.** Both the provider (Chunk 9) and the CLI (Chunk 10) select their engine by `user_version`, so migrating the live store is the last step before 3.0 for real — migrate a copy, verify against the parity suite, then swap, with the owner present. **The CLI-parity route is finished:** the reads (10.1), the maintenance calls (10.2) and the by-name refusals (10.3) landed, and 10.4 routes the CLI. EM-211's AC is met except for **seven named refusals**, each naming the card that lifts it (triples and publish/pull → S5, `embed --rebuild` → S3/EM-303, vault projection and graph recall → S6, `migrate` → v2-only). **The PII trade-off is resolved:** the locale packs reach v3 redaction, and the tier gate is deliberate and tested.
3. **§3.5's `visibility` half — PROPOSED by the implementing agent and IMPLEMENTED (Chunk 13, `fd9e06f`); the owner authorised the *implementation*, not the behaviour change.** It is recorded as a proposal awaiting the owner's sign-off on the change itself, and it stays **internal — in no release, and not to reach the marketplace without the owner's explicit approval of a release.** The finding, measured rather than inferred: `MemoryDraft.visibility` defaults to `'user'` and **no call site anywhere sets it**, so every row written by `MemoryStore.add` — the facade's `remember` included — carries `visibility='user'`, profile-wide or not. §3.5 pairs `visibility='user'` with a *user-scoped* write (`scope_user=<user>`) and profile-wide with `visibility='profile'`; the v2→v3 migration also stamps `'profile'` for migrated facts. So a profile-wide row carrying `'user'` is self-contradictory, and §3.5's owner rule makes exactly that combination owner-only. **Which way to fix it matters:** implementing the read clause alone would silently hide *every* profile-wide memory from non-owners, the opposite of §3.5's intent that profile-wide `public`/`internal` rows are shared knowledge — so the write path is the real fix and the read clause is the defensive half. The chunk therefore does both: `MemoryDraft.visibility` gains a "derive from scope" default (profile-wide → `'profile'`, user-scoped → `'user'`, explicit values preserved) **and** `_in_scope`/`scope_sql` implement the `visibility='user'` owner-only clause, with `MemoryStore.list` either treated the same way or given a recorded reason not to. **Why after EM-301 rather than first:** v3 stores are unreleased, the provider and CLI only serve v3 for a store that is already v3, and the live store is v2 with zero facts — so no user-reachable data is affected and nothing is exposed while it waits. The finding and this reasoning are in `docs/V3_FOUNDATIONS.md`.
4. **The v3 cutover — DEFERRED, and the owner has since confirmed the deferral and set the rule for revisiting it: `REVISIT ONLY AFTER EM-305`, and the owner decides — the agent brings the decision, it does not make it.** Four reasons, in order of weight. (a) **The live store holds zero facts**, so there is nothing to cut over yet and nothing to gain. (b) On v3 the CLI still refuses seven commands (Chunk 10.3), so the owner's daily driver would be degraded on exactly the store they use. (c) **S3 is mid-flight:** cutting over now would put the owner on a v3 store *without* the retrieval that justifies v3, and the parity suite does not yet cover the v3 read path end to end. (d) It is irreversible and owner-present, so it should be done once, deliberately, when the v3 read path is complete. **Revisit after EM-305**, when the gate in §6.6 can be answered with data.
5. **Retention for snapshots: settled (decided by the implementing agent on 2026-09-29, at the owner's instruction to stop asking) — the current rule stays.** 7 routine + 5 safety, not EM-113's keep-10 + one per day for 7 days. Chunks 3.1 and 3.2 both kept it, §6.1 and the EM-210 row of `docs/V3_FOUNDATIONS.md` record it, and it is reopened only if a real backup-scarcity problem appears.

## 10. Operations checklist (Hermes host)
- **Before 2 Oct:** dry-run the cleanup script (`--dry-run`). Ancestor check already verified.
- **Gateway heartbeat:** the cron scheduler once reported "no gateway or no fresh profile heartbeat". Confirm the gateway is up before crons fire.
- **Catalog-check cron:** idle box only. It must never push the old fork branch.
- **Stale local branches:** none as of 2026-09-29. The 2026-09-28 list (`fix/em-211-facade`, `fix/plan-gaps`, `em/em-205…208*`) was already gone; `docs/plan-s5-text` (merged into `main` long before) and the merged `em/em-209-worker-cli` were deleted on 2026-09-29. Re-check with `git branch --merged main` and `git ls-remote --heads origin`.
---

## 11. Picking this up (cold start)

**Read this section first, then §2 (state) and §5 (the ledger of everything done).** It is refreshed at the end of every chunk.

### State as of 2026-10-06

| What | Where |
|---|---|
| **Released version** | `v2.8.1`, tag at `7e02412` on the protected `release/2.8.x`. This is what the Hermes catalog pins and what users install. |
| **Development line** | `main` at `e058e93be` or later, version `3.0.0.dev0`. All of S2 (the `em/` storage core) is merged; none of it is wired into the provider yet. `main` must stay green and releasable. |
| **Last landed chunk** | **Chunk 13 — the §3.5 `visibility` fix** (`fd9e06f`). (Chunk 12, EM-301, was `85afea4`; Chunk 11, EM-302, `33b2b31`; Chunk 10.4 `250320a`.) |
| **Same-day hygiene batch** | Five no-bump commits: the CI action majors, `perf-smoke` diagnostics, the concurrency-test flake fix, the `ARCHITECTURE.md` v3 section, and two new doc guards. |
| **Next piece of development** | **Chunk 7: the `EntityLinker` job** — enqueue `link:<memory_id>:<version>` on write, a handler registered in `em/jobs/cli.py`, never inside `MemoryStore.add` (invariant 2), and with it the §3.5 owner-only rule for sensitive rows. Scoped in `NEXT_CHUNK.md` Part B with a size guard that splits it into 7.1 (the job) and 7.2 (the scope rule) if the rule turns out to need provider changes. It completes EM-211's four chunks. |
| **In flight** | **Nothing.** Chunk 13 is merged with green CI on the exact SHA; the feature branch is deleted; the remote carries `main` and `release/2.8.x` only, and the Marketplace entry is untouched (2.8.1 at `7e02412`). **The next step is Chunk 14 (EM-304).** Chunk 13's change is **internal only** — it must not reach the marketplace until the owner approves a release. |
| **Stage** | **S2 remainder done; S3's retrieval base is in place.** The provider and the CLI both serve a v3 store; EM-301's analyzer and EM-302's generators are merged; **EM-304 (fusion) is unblocked.** One privacy gap is recorded and approved for its own chunk (see §9 items 3–4). |

### Verify before you touch anything

```bash
cd ~/Documents/Coding\ Projects/EntropicMem
git fetch --all --prune && git status -sb && git log --oneline -12
git ls-remote --heads origin        # expect exactly main + release/2.8.x

# The repo's own pre-flight. Expect 1757 passed, 3 skipped, 3 xfailed (about 1 minute on a warm box).
# 3 skips here because the private digest list is not configured on this machine; on the
# Hermes host it is, so the run there is 1757 passed, 2 skipped, 3 xfailed.
env -u ENTROPICMEM_MEMORY_DB -u ENTROPICMEM_INDEX_DB -u ENTROPICMEM_VAULT_PATH \
  ENTROPICMEM_REQUIRE_PRIVACY_DIGESTS=1 python3 -m pytest -q

# CI pins ruff==0.16.2. A newer local ruff disagrees in both directions, so use the pin.
uv venv --seed /tmp/ruff-parity
uv pip install --python /tmp/ruff-parity/bin/python "ruff==0.16.2"
/tmp/ruff-parity/bin/ruff check skills/ plugins/ scripts/ tests/ benchmarks/ evals/
```

Prove you did not touch the live store (the fact count and the newest `created_at` must not move):

```bash
sqlite3 "file:$HOME/.hermes/entropicmem/memory.db?mode=ro&immutable=1" \
  "select count(*), max(created_at) from facts;"
```

On 2026-09-29, after Chunk 3.1 merged, that read 1627 rows with newest
`2026-09-29T08:59:01Z`; after Chunk 3.2 it read **1628 rows** with newest
`2026-09-29T09:45:11Z`, and it read the same 1628/`09:45:11` immediately after
that chunk's full 4m45s suite run, which is the isolation proof. The count only
grows while the agent works (memory writes are not test activity), so read it as
a pair: record it before a test run and compare it afterwards. What must hold is
that it does **not** move across a test run. The same reading was 1617 earlier
that day, before that day's own memory writes.

### The expected counts drift, on purpose

The suite total rises with every card: 1462 at Chunk 2's pre-flight, 1495 after the hygiene batch, 1509 after Chunk 3.1, 1519 after Chunk 3.2, 1542 after Chunk 4, 1604 after Chunk 5 (1542 + 56 new unit + 6 new parity params), 1609 once `tests/test_master_todo.py` added its 5 document-control tests, 1624 after Chunk 6 (+15: five `mirror-scan` parity scenarios × 2 engines, plus five v3 unit tests), 1626 once the two Python-3.10 timestamp-parser regression tests landed, 1643 after Chunk 7.1 (+17), 1669 after Chunk 7.2 (+26), 1671 after Chunk 8 (whose xfail flip moved the xfail count 4 to 3), 1687 after Chunk 9 (+16), 1692 after the CLI guard and the PII locale fix (+5), 1707 after 10.1 (+15), 1734 after 10.2 + 10.3 (+27), 1751 after 10.4 (+17 net; the 10.0 refusal test became a routing test), 1757 after EM-302's `scope_sql` (+6), 1795 after EM-302's generators (+38), 1832 after EM-301 (+37), **1862 after the visibility fix** (+30). **Run the suite on 3.10 as well as the default interpreter: the `Z`-suffix bug below was invisible to 3.12 and only the 3.10 CI leg caught it.** Read the expected number from `NEXT_CHUNK.md`'s pre-flight (§7.0 for the current chunk), which is rewritten at the end of each chunk, and **stop and report on a mismatch** instead of assuming the older number is right.

The skipped count moved from 2 to 3 at Chunk 5. Nothing was skipped or xfailed to get there: the extra skip is `tests/evals/test_no_personal_data.py`, which skips when the private digest list is not configured on the machine running the suite (and *fails* when `ENTROPICMEM_REQUIRE_PRIVACY_DIGESTS=1` and the list is missing — which is how CI runs it). On the Hermes host the list exists, so the run there is 1757 passed / 2 skipped / 3 xfailed. Read the two numbers as a pair.

Documentation-only commits move the tip SHA without changing code, tests or counts. When they do, `§2` and this table keep the last **code** state, which is why both say "or later"; a later tip that only touched `docs/`, `README.md` or `CHANGELOG.md` is expected.

### What to do next, in order

1. **Chunk 14 — EM-304 (fusion, rerank, explainability).** Unblocked: EM-302's generators and EM-301's analyzer are both merged. "Exactly §3.6 formulas", unit-tested against hand-computed scores, deterministic tie-break.
2. **EM-305 (gate, supersession collapse, MMR)** next — and **the cutover decision comes to the owner after EM-305**, not before.
3. **EM-303 (embedding backends + the `vector` generator)** can interleave; independent of both.
4. **EM-310 (temporal parsing v2)** carries the rest of the grammar EM-301 deliberately left out.
5. **The owner's sign-off on Chunk 13's behaviour change** is still open; it is internal until then.

### Frozen until the owner says otherwise

- Releases, tags and catalog PRs (§3.3). The catalog pins `7e02412`; only a release moves it.
- The tool rename (`entropicmem_patch_core` → `entropicmem_patch_core_memory`), which ships only with a release that re-pins the catalog (rule 10).
- The v3 cutover: `ENTROPICMEM_ALLOW_LIVE_MIGRATION=1` against the live store, with the owner present.
- S3 and later, until the S4 decision gate in §6.6 says continue.
- `auto_extract_enabled`'s default, and the `provides_tools` / `provides_hooks` lists.

### If a gate goes red, do not widen it

Two flakes are already on record, and both were fixed at the test or CI layer, never by moving a threshold:

- `perf-smoke` has flapped twice — 34.815 ms p95 on a docs-only commit (2026-09-27) and 69.392 ms p95 on the Chunks 10.2/10.3 merge (2026-10-07, rerun 5.388 ms on the same SHA). §8 has the numbers; the budget is unchanged at 20 ms and the job prints p50/p95/max so a low p50 with a high max reads as noise.
- The v3 concurrency AC test could compute its p95 from an empty sample list when the writers outran the reader's spawn. The reader now floors at 20 samples.

The pattern that confirms a flake: `gh run rerun <id> --failed` on the **same** SHA. A rerun that goes green on an unchanged commit is the evidence. Never loosen a budget, skip a test or mark a job non-blocking to clear a red gate.
