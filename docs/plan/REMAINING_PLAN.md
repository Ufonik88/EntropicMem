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
| `main` | `1b5c71ccf` or later | 3.0 development line (`3.0.0.dev0`). All of S2, the v3 foundations, the catalog-review fixes, the perf-smoke fix, EM-212 (first step), the 2.8.1 notes, the plans, the §5 card text pastes, Chunk 2 (`entropicmem worker run` plus the EM-209/EM-210 deviation record), the 2026-09-29 hygiene batch (CI action majors, perf-smoke diagnostics, the concurrency-test flake fix, the doc-link and CLI-reference guards), **Chunk 3.1** (`snapshot()` over `memory.db` + `index.db` in `backups/<reason>-<stamp>/`) and **Chunk 3.2** (the once-per-hour-per-reason snapshot throttle, `snapshot_if_due()`), **Chunk 4** (`em/facade/engine.py`, the facade's read half over `em.store`, `0349b7b4b`), the live-store deny-list fix (`03772e3c`) and a contributor's `tests/test_vault.py` path fix (`1b5c71ccf`). **Chunks 5 and 6 are committed but not merged** — see the In flight row in §11. |
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
| **Chunk 5** | The 7 stubs replaced with real write paths: `remember` (stamps `legacy_id = sha256(content)[:16]` — profile-wide only, since `legacy_id` is UNIQUE and content-derived; `MemoryStore.add` carries policy/PII/injection/dup/version/outbox/audit/embed), `forget` and `consolidate` as §3.4 status transitions with a throttled `snapshot_if_due` taken **outside** the write txn, `touch` resolving ids and returning the matched count, `extract_and_store` quarantining into `pending` then promoting over `pending -> active` (one versioned row, not v2's two), `prune_pending` over the same edge, `add_episode` stamping `episodes.legacy_id` and upserting a refired id. `WRITE_ENGINES` gains `v3-facade` and the `_remember` dispatch is deleted, so **6 write-path parity scenarios run against both engines; no assertion changed**. Recorded deviations: no fuzzy overwrite, `linked_fact_ids`/`domain`/`source` ignored on episodes (no column, no migration in this chunk), no deprecation warnings. 56 new tests + 6 parity params; 1604 passed / 3 skipped / 4 xfailed; 12 mutation checks | `36355f3` (**unmerged**) |
| **Chunk 6** | The mirror call: `find_mirrored(needle) -> Optional[str]` on **both** engines, so `_locate_mirror` stops running `SELECT id, content, tags FROM facts` against `engine.db` — the provider's last raw-connection read and the one thing a v3 facade could not serve. `PROVIDER_ATTRIBUTES` is now **empty**, `BEHAVIOURS["mirror-scan"]` moves from the last OPEN item to a cited behaviour with five parity scenarios, and `open_items` in the coverage test is an empty set. v2's version is the provider's scan moved behind a method; v3's adds the three filters v2 got for free — `status='active'` (a forgotten mirror must not be locatable), the §3.5 scope rule (invariant 5), and `mirrored` as a whole tag where the quoted JSON `LIKE` is only a pre-filter and the parsed **list** decides. The `make_id(previous_content)` fast path is unchanged. 15 new tests; 1624 passed / 3 skipped / 4 xfailed; nine mutation checks | `6bd4b47` (**unmerged**) |
| Document control | `MASTER_TODO.md` created at the repo root (the plan had pointed at one that existed only in a single agent's private memory); `AGENTS.md` gains "Document control — first and last" and always-rule 8; `tests/test_master_todo.py` enforces it — exists, carries its sections, is **linked** from `AGENTS.md` and the README, records a SHA that is a real ancestor, and cannot report a chunk `Done` while In flight says unmerged. 5 tests, six mutation checks | `436d360`, `81859d0` (**unmerged**) |
| Vault path fix (contributor) | `tests/test_vault.py` compares resolved paths instead of raw strings so the explicit-precedence check passes off Linux (macOS `/tmp` → `/private/tmp`); author email rewritten to the contributor's GitHub noreply on merge so no personal address entered published history | `1b5c71ccf` |

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
- **EM-212, first step:** `_backend` loads its own `vault.py` by path under a private module name (fixes another plugin's `vault` hijacking the path lookup); `test_f010` is now a real check and passes.

**Housekeeping (all done 2026-09-28):**
- master plan §5 text pasted into §6 (`25322dc7e`);
- leftover remote and local branches deleted;
- cleanup cron ancestor check verified.

**EM-212, rest of the card (open; plan §5 below asks for it):** move the engine modules under a package namespace so no unprefixed `vault`/`index`/`security`/`policy`/`embeddings`/`retrieval` module is registered in the host process, with a CLI shim. The strict xfail `test_em212_plan_ac_no_unprefixed_engine_modules_in_process` (`tests/test_backend_namespace.py`) pins the plan AC and flips when it lands. It is a larger, multi-file card: split it before starting.

**EM-211: legacy facade.** Implement `LegacyEngine` over `em.store` so the provider can run on v3 unchanged.
- Done when it is added to `ENGINES` in `tests/parity/test_engine_parity.py` and to `_implementations()` in `tests/unit/test_em_facade_contract.py`, and both pass **unchanged**.
- Known requirements:
  - `get_fact(StoredFact.make_id(content))` must resolve: store `sha256(content)[:16]` as `legacy_id` on `remember` — **done in Chunk 5**, and only for a profile-wide write, because `memories.legacy_id` is UNIQUE and content-derived;
  - replace the raw `engine.db` read in `_locate_mirror` with an engine method on **both** engines, then drop `db` from `PROVIDER_ATTRIBUTES` — **done in Chunk 6** (`find_mirrored`; `PROVIDER_ATTRIBUTES` is now empty);
  - run `EntityLinker` from a `link:<memory_id>:<version>` job, never inside `MemoryStore.add` — still open, Chunk 7;
  - the `§3.5` owner-only rule for sensitive rows needs the gateway identity and lands here.
- Too big for one chunk. Split it into facade reads, then writes, then mirror, then linker. **Reads: DONE (`0349b7b4b`, merged). Writes: DONE (`36355f3`) and mirror: DONE (`6bd4b47`) — both committed, neither merged.** Only the linker (Chunk 7) remains, and it carries the §3.5 owner-only rule with it. **The card's whole AC is still not met** — nothing is wired into the provider and S2's exit criteria still fail, exactly as the Chunk 4 review recorded.

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
- **EM-211 (foundation):** met as a foundation; the facade itself is three quarters done (above). **Chunk 4 (reads) landed 2026-10-03 at `0349b7b4b`** — see §5. **Chunks 5 (writes, `36355f3`) and 6 (mirror, `6bd4b47`) are committed but not merged.** **Chunk 7 (the linker) remains**, and the provider still runs v2.

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
  - **`perf-smoke` has flapped once on unchanged code:** 2026-09-27, warm p95 34.815 ms on a docs-only commit, with the next commit (no code change) passing. The dev-box reference for the same command is 6.175 ms p95 (p50 5.131, max 8.161, 20 probes): `env -u ENTROPICMEM_MEMORY_DB -u ENTROPICMEM_INDEX_DB -u ENTROPICMEM_VAULT_PATH PYTHONPATH=plugins/entropicmem/scripts python3 -m evals.perf --sizes 1000 --probes 20 --out-dir /tmp`. The job now prints p50/p95/max/samples, so a low p50 with a high max reads as one noisy sample and a p50 near the budget reads as a regression. A lone red `perf-smoke` is not a regression until it repeats on the same commit, and the budget stays at 20 ms (already 2× §6.4);
  - entity linking p95 of 2 ms per memory at 10k entities (measured 0.18 ms).
- **Evals:**
  - `evals-ci` compares only the §6.3 gated metrics against the `v2.8.0*` baselines;
  - the §6.3 thresholds were "gate from 2.8.0".
- **Concurrency (EM-202 AC):** 4 writers × 500 writes + 1 reader, zero errors, reader p95 under 50 ms.
- **Jobs (EM-209):** a 4-process exactly-once test.

## 9. Open decisions (owner)
1. **When to merge Chunks 5 and 6.** Both are committed on `em/em-211-facade-writes` with every locally-runnable gate green, but neither is pushed and no CI has run for either, so neither may be merged (`AGENTS.md` rule 1). `gh` is unauthenticated on the machine that built them. Merging is the first thing the next session with push access should do.
2. **When to start Chunk 7** (the `EntityLinker` job, which completes EM-211 and carries the §3.5 owner-only rule). Scoped in `NEXT_CHUNK.md` Part B, with a size guard that splits it if the scope rule turns out to need provider changes. Chunk 6 (the mirror call) and Chunk 5 (the writes) were both completed 2026-10-06; Chunk 4 (the reads) landed 2026-10-03 at `0349b7b4b` and passed em-qa review; Chunks 2, 3.1 and 3.2 landed 2026-09-29.
3. **Retention for snapshots: settled (decided by the implementing agent on 2026-09-29, at the owner's instruction to stop asking) — the current rule stays.** 7 routine + 5 safety, not EM-113's keep-10 + one per day for 7 days. Chunks 3.1 and 3.2 both kept it, §6.1 and the EM-210 row of `docs/V3_FOUNDATIONS.md` record it, and it is reopened only if a real backup-scarcity problem appears.

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
| **Last landed chunk** | **Chunk 4: EM-211's facade reads** (`0349b7b4b`), landed 2026-10-03 and approved by em-qa. **Chunks 5 and 6 are complete but unmerged** — see the In flight row; do not read them as landed. | Chunk 3.2 (`e058e93be`), 3.1 and 2 landed 2026-09-29. |
| **Same-day hygiene batch** | Five no-bump commits: the CI action majors, `perf-smoke` diagnostics, the concurrency-test flake fix, the `ARCHITECTURE.md` v3 section, and two new doc guards. |
| **Next piece of development** | **Chunk 7: the `EntityLinker` job** — enqueue `link:<memory_id>:<version>` on write, a handler registered in `em/jobs/cli.py`, never inside `MemoryStore.add` (invariant 2), and with it the §3.5 owner-only rule for sensitive rows. Scoped in `NEXT_CHUNK.md` Part B with a size guard that splits it into 7.1 (the job) and 7.2 (the scope rule) if the rule turns out to need provider changes. It completes EM-211's four chunks. |
| **In flight** | **Chunks 5 and 6, committed on the local branch `em/em-211-facade-writes` and NOT merged** — five commits: `36355f3` (Chunk 5, the write half), `d055b74` (its docs close-out), `436d360` and `81859d0` (`MASTER_TODO.md` and the document-control guard), `6bd4b47` (Chunk 6, `find_mirrored`). Every gate that can run locally is green — **1624 passed / 3 skipped / 4 xfailed**, `ruff==0.16.2` clean, eval gate with no gated metric regressed, `perf-smoke` warm p95 3.666 ms against the 20 ms budget, `tests/unit` green for `windows-import`. But the branch is unpushed and no CI has run for it, so `origin/main` is still `03772e3`, and four CI-only jobs (`windows-import`, `plugin-validate`, `bench`, `identity-guard`) plus the privacy guard are unverified here. Merging waits on green CI **on the exact SHA** (rule 1); `gh` is unauthenticated on the machine that built them, so that step needs a session with push access. The remote otherwise carries exactly `main` and `release/2.8.x`. |
| **Stage** | S2 remainder. EM-211 is **three quarters done** — its 4 sub-chunks are global Chunks 4–7: reads (4, merged), writes (5) and mirror (6) committed but unmerged, linker (7) remains. `PROVIDER_ATTRIBUTES` is empty, so the provider now reaches the engine only through methods both engines implement. Nothing is wired into the provider, so the card's whole AC and S2's exit criteria are still unmet. EM-212's package move is still open with its card blocked on a split. S3 (retrieval v3) starts only after both finish. |

### Verify before you touch anything

```bash
cd ~/Documents/Coding\ Projects/EntropicMem
git fetch --all --prune && git status -sb && git log --oneline -12
git ls-remote --heads origin        # expect exactly main + release/2.8.x

# The repo's own pre-flight. Expect 1624 passed, 3 skipped, 4 xfailed (about 1 minute on a warm box).
# 3 skips here because the private digest list is not configured on this machine; on the
# Hermes host it is, so the run there is 1624 passed, 2 skipped, 4 xfailed.
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

The suite total rises with every card: 1462 at Chunk 2's pre-flight, 1495 after the hygiene batch, 1509 after Chunk 3.1, 1519 after Chunk 3.2, 1542 after Chunk 4, 1604 after Chunk 5 (1542 + 56 new unit + 6 new parity params), 1609 once `tests/test_master_todo.py` added its 5 document-control tests, **1624 after Chunk 6** (+15: five `mirror-scan` parity scenarios × 2 engines, plus five v3 unit tests). Read the expected number from `NEXT_CHUNK.md`'s pre-flight (§7.0 for the current chunk), which is rewritten at the end of each chunk, and **stop and report on a mismatch** instead of assuming the older number is right.

The skipped count moved from 2 to 3 at Chunk 5. Nothing was skipped or xfailed to get there: the extra skip is `tests/evals/test_no_personal_data.py`, which skips when the private digest list is not configured on the machine running the suite (and *fails* when `ENTROPICMEM_REQUIRE_PRIVACY_DIGESTS=1` and the list is missing — which is how CI runs it). On the Hermes host the list exists, so the run there is 1624 passed / 2 skipped / 4 xfailed. Read the two numbers as a pair.

Documentation-only commits move the tip SHA without changing code, tests or counts. When they do, `§2` and this table keep the last **code** state, which is why both say "or later"; a later tip that only touched `docs/`, `README.md` or `CHANGELOG.md` is expected.

### What to do next, in order

1. **Merge Chunks 5 and 6.** They are committed on `em/em-211-facade-writes`, unpushed, with no CI run. Push, wait for green CI on the exact tip SHA, `git merge --ff-only`, delete the branch — then correct the merge state in `MASTER_TODO.md`, §11's In flight row, and `NEXT_CHUNK.md` Part A.
2. **Chunk 7, the next piece of development: the `EntityLinker` job.** Scope is in `NEXT_CHUNK.md` Part B. **Not started** — the owner picks the moment.
3. **EM-212's package move** can sit beside it. It is a larger, multi-file card: split it first.
4. **S3 (retrieval v3)** after the S2 remainder, on the critical path in §6.2: EM-302 → EM-304 → EM-305 → EM-403 → EM-503 → EM-901 → EM-904.

The EM-210 gaps are both closed: Chunk 3.1 built the snapshot, Chunk 3.2 the throttle, and Chunk 5 made the facade's destructive paths use the throttle.

### Frozen until the owner says otherwise

- Releases, tags and catalog PRs (§3.3). The catalog pins `7e02412`; only a release moves it.
- The tool rename (`entropicmem_patch_core` → `entropicmem_patch_core_memory`), which ships only with a release that re-pins the catalog (rule 10).
- The v3 cutover: `ENTROPICMEM_ALLOW_LIVE_MIGRATION=1` against the live store, with the owner present.
- S3 and later, until the S4 decision gate in §6.6 says continue.
- `auto_extract_enabled`'s default, and the `provides_tools` / `provides_hooks` lists.

### If a gate goes red, do not widen it

Two flakes are already on record, and both were fixed at the test or CI layer, never by moving a threshold:

- `perf-smoke` flapped once at 34.815 ms p95 on a docs-only commit (§8 has the numbers, the budget is unchanged at 20 ms, and the job now prints p50/p95/max).
- The v3 concurrency AC test could compute its p95 from an empty sample list when the writers outran the reader's spawn. The reader now floors at 20 samples.

The pattern that confirms a flake: `gh run rerun <id> --failed` on the **same** SHA. A rerun that goes green on an unchanged commit is the evidence. Never loosen a budget, skip a test or mark a job non-blocking to clear a red gate.
