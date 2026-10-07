# EntropicMem — MASTER TODO

**The single canonical "where are we" document.** Every agent reads this before
and after any development task, on any harness. It is deliberately short and
fact-checked rather than complete: the detail lives in the two plan files it
points at.

| Source of truth | What it holds |
|---|---|
| **[docs/plan/REMAINING_PLAN.md](docs/plan/REMAINING_PLAN.md)** | Status (§2), the ledger of everything done (§5), every remaining card by sprint (§6), recorded deviations, budgets, and **§11 the cold-start page** |
| **[docs/plan/NEXT_CHUNK.md](docs/plan/NEXT_CHUNK.md)** | The **one** next chunk, in detail. Part A is what just landed; Part B is the next piece |
| **[AGENTS.md](AGENTS.md)** | The rules: never / always / autonomy, **and the document-control rule** |
| [docs/V3_FOUNDATIONS.md](docs/V3_FOUNDATIONS.md) | The `em/` v3 layers, the ten invariants, recipes, repo guards, and the facade's write rules |
| [CHANGELOG.md](CHANGELOG.md) | One line per card, under `[Unreleased]` |

**Last reconciled:** 2026-10-07, against branch `main` at `04bb88c`, with Chunk 10's
second and third slices on `em/em-211-cli-maintenance`. A later docs-only commit moving
the tip without changing code, tests or counts is expected; see plan §11.

---

## The document-control rule (read this before working)

1. **Before starting any work**, update this file and the planning docs so they
   describe the project's real current state — what is done, in detail, and what
   the next logical steps are.
2. **Do the development work.**
3. **Before finishing**, update this file and the planning docs again to describe
   what was completed and what comes next.

Never end a development session without step 3. A task whose code is committed
but whose documentation still describes the previous state is **not finished** —
it has left the next agent to guess. This is enforced by
`tests/test_master_todo.py`, which fails when this file is missing, unlinked,
or missing its required sections, and when its recorded SHA is not a real
ancestor of the branch.

---

## Where we are

### Released line — **done and frozen**

**`v2.8.1`**, tag at `7e02412` on the protected `release/2.8.x`. This is what the
Hermes plugin catalog pins (`entropicmem` 2.8.1) and what users install. It
contains **no v3 code and no new features**: it is 2.8.0 plus safety fixes. Its
one user-visible change is that semantic recall now needs
`embeddings_enabled: true`. Nothing on this line changes without the owner.

> **There is no 2.8.x work left to do.** 2.8.1 is implemented, tagged, published
> as the repo's Latest release (2026-09-27), catalog-pinned, and install-verified.
> Users can already update to it, and do. If a request says "finish the 2.8.1
> sprint", the target it names is already complete — check this section before
> building anything. The only things that would legitimately create *new* 2.8.x
> work are (a) a security or correctness bug specific to 2.8.x, or (b) a
> deliberate owner decision to cut a 2.8.2 patch; neither is open today.

### Development line — `main`, `3.0.0.dev0`

**This is where all development happens, and the two lines are not patchable into
each other.** `main`'s provider, CLI and engine now import the `em` package
(`from em import __version__`, `em.store.locking.FileLock`, `em.jobs.cli`), so
`main` is not a set of cherry-picks for `release/2.8.x` — it is a different
program with an extra dependency. `git rev-list --count origin/release/2.8.x..main`
is ~80 commits; the 12 in the other direction are 2.8.1's own cherry-picked
safety fixes, all already released.

**All of S2 (the v3 storage core, `em/`) is merged and unwired.** The provider
still constructs the v2 `MemoryEngine`; nothing in `em/` is on the provider's
live path. That is deliberate — the core landed first so the facade could be
proven against it.

**The only route to a new user-facing update is the 3.0 release (EM-904)**, and
it cannot happen until the v3 core is wired in and the live store is migrated.
That work is listed under [What is next](#what-is-next); the cutover itself is
owner-gated.

What `em/` contains today: `em.clock` (freezable UTC, ULIDs), `em.store`
(`db`/portable locking, numbered migrations `0001`–`0003`, `MemoryStore`,
`episodes`, `entities`, `jobs`, `backup`, hash-chained `audit`), `em.jobs` (queue,
worker, `entropicmem worker run`), `em.formation` (`EntityLinker`), and
`em.facade` (the provider-facing contract plus `V3Engine`).

### Hermes Marketplace — the catalog entry

The plugin is listed in the Hermes catalog as `plugin-catalog/entropicmem.yaml`
in `NousResearch/hermes-agent`. **The pin is the release:** the entry names an
exact 40-hex commit, and that commit is what every install clones.

**Verified live 2026-10-07:** `entropicmem` version **2.8.1**, pinned at
`7e02412366408234629e759a575edc31eb138721` (= the `v2.8.1` tag commit on
`release/2.8.x`), subdir `plugins/entropicmem`, capabilities matching
`plugin.yaml` exactly (7 tools, 5 hooks). `main` is **not** what users install.

**Releases and re-pins are owner-gated end to end**, and a chunk of work leaves
the entry untouched unless that chunk *is* a release. The full procedure — tag
ordering, catalog PR mechanics, fresh-`HERMES_HOME` install verification, and the
pitfalls that have already cost time — is in
[docs/MARKETPLACE.md](docs/MARKETPLACE.md). Read it before doing anything that
touches the entry, a tag, or `release/2.8.x`.

### Chunks — the global ledger

Chunk numbers are global, so a number means one thing across the whole project.
EM-211 (the legacy facade) is chunks 4–7.2 plus the wiring; EM-212 is chunk 8.

| Chunk | What | State |
|---|---|---|
| 4 | Facade **reads** over `em.store` | **Done** (`0349b7b4b`, 2026-10-03, merged) |
| 5 | Facade **writes** over `em.store` | **Done, merged** (`36355f3`, in `e25db32`) |
| 6 | Facade **mirror call** | **Done, merged** (`6bd4b47`, in `e25db32`) |
| 7.1 | The **entity-link job** (`link:<memory_id>:<version>`) | **Done, merged** (`96c4ccb`) |
| 7.2 | The **§3.5 owner-only rule** for sensitive reads | **Done, merged** (`563afe5`) |
| 8 | EM-212's **package move** | **Done, merged** (`025f012`, in `c922970`) |
| 9 | The **provider** selects its engine by `user_version` | **Done, merged** (`b615bcf`) |
| 10 | **CLI parity** on v3 — split 10.0 guard → 10.1 reads → 10.2 maintenance → 10.3 refusals → 10.4 route | 10.0–10.1 **merged**; 10.2–10.3 **done** (`cc19337`, not merged); 10.4 next. The cutover waits on 10.4 |

**EM-211's acceptance criterion is still not met, and S2's exit criteria still
fail — but for the first time the reason is narrow and named.** Chunk 9 wired the
**provider** onto the facade, so an agent now runs on whichever engine the store
needs. What remains is (a) **the CLI**, which calls ~28 methods the facade does not
implement and therefore still runs on `MemoryEngine`, and (b) **the cutover**, which
is the owner's deliberate act. The card's AC says "CLI commands work unchanged" on a
v3 DB, so Chunk 10 is what closes it — and the cutover cannot happen before Chunk 10,
because after a cutover the CLI would read a v3 store with a v2 engine.

### In flight

**Chunk 10's second and third slices (10.2, the maintenance calls, and 10.3, the
refusals)** — `cc19337`, on the local branch `em/em-211-cli-maintenance`. **Not pushed, not
merged, no CI run yet.** `origin/main` is `04bb88c`. Locally green on both Python
3.10 and 3.12 — **1734 passed / 3 skipped / 3 xfailed**, `ruff==0.16.2` clean,
eval gate with no gated metric regressed, `perf-smoke` warm p95 4.421 ms against
the 20 ms budget, `tests/unit` green standalone. Push, green CI on the exact SHA,
`git merge --ff-only`.

## What is done

Only the parts a later reader needs to know. The full ledger with commit SHAs is
[plan §5](docs/plan/REMAINING_PLAN.md).

- **2.8.1 reached and is catalog-pinned** (2026-09-28). Safe point.
- **S2, the v3 storage core**, merged to `main`: migrations, `MemoryStore`,
  episodes and content-addressed transcript chunks, entities with a two-sighting
  linker, the durable job queue and its `entropicmem worker run` CLI, the
  verified `BackupManager`, and the hash-chained audit log.
- **EM-210 closed in two chunks:** `snapshot()` covers both databases, and
  `snapshot_if_due()` throttles destructive callers to one snapshot per reason
  per hour. Retention settled at 7 routine + 5 safety.
- **EM-211 Chunks 4, 5, 6, 7.1 and 7.2 — the facade is now code-complete**: its
  read half, its write half, the mirror call, the entity-link job, and the §3.5
  owner-only rule for sensitive reads. `PROVIDER_ATTRIBUTES` is empty, entity
  linking runs off the write path as `link:<memory_id>:<version>`, and a
  `sensitive`/`secret` row is readable only by its owner.
- **EM-212 done (Chunk 8)**: the six shared-name engine modules (`vault`, `index`,
  `security`, `policy`, `embeddings`, `retrieval`) live under `scripts/em_internal/`,
  so the import system registers `em_internal.*` and never the bare names, and the
  strict xfail flipped to a passing test. The other 14 modules still carry
  unprefixed names — the AC names only the six.
- **Repo hygiene that keeps all of this honest:** privacy guard v2, commit
  identity guard, a docs-link guard, a CLI-reference drift guard, a perf smoke
  test that prints its full distribution, and a document-control guard that
  fails when this page and the plan disagree about the truth.
- **The document-control rule itself** is now written into `AGENTS.md` and
  enforced, so the next agent picks it up on any harness without being told.

---

## What is next

**The CLI-parity route is decided, and its first step has landed.** Effort below is
in sessions and commits, not dates — the pace depends on when the owner runs
sessions, which no plan can know. One chunk per session.

| Step | What | Estimate |
|---|---|---|
| **10.0** | The CLI **refuses a v3 store clearly** instead of handing it to the v2 engine | **done** |
| **10.1** | Port the CLI's read/listing calls to the facade (`list_facts`, `list_pending`, `list_episodes`, `get_versions`, `episode_stats`, `embedding_stats`, `list_audit`, `recall`; `profile_id` dropped — its only caller is in the refuse group) | **done** |
| **10.2** | Port maintenance (`promote_pending`, `discard_pending`, `reinforce`, `rebuild_fts`, `timeline`, `recall_episodes`) | **done** |
| **10.3** | Make the **v2-only group refuse clearly** on v3, each naming its card (triples → S5, embeddings → S3, publish/pull/backfill → S5, vault projection → S6, graph recall → S6) | **done** |
| **10.4** | Route `_engine()` through `open_engine` and run the CLI suite against a **v3** store — this meets EM-211's AC for everything not refused | 1 commit |

**10.1–10.3 have landed**, each in one session as estimated (10.1 with 8 methods rather than 9 — `profile_id` was dropped after measuring; 10.2 and 10.3 were done together on the owner's instruction). **Only 10.4 remains** — one commit that routes `_engine()` and runs the CLI suite against a v3 store. Then **the v3 cutover**
(owner-gated) becomes available, and S3/S5/S6 can fill in the refused group later.

**The shape of the answer, in one line:** port what maps, refuse what does not, and
name the card that will bring each refusal — a named absence is honest, a silent
wrong answer is not.

## Gates that must be green before anything reaches `main`

| Gate | Command | Budget |
|---|---|---|
| Tests | `python -m pytest -q` | **1734 passed / 3 skipped / 3 xfailed** |
| Lint | `ruff check .` under the CI pin `ruff==0.16.2` | clean |
| Evals | `evals run --suite ci --compare evals/baselines/v2.8.0-ci.json` | no gated metric regressed |
| Performance | `evals.perf --sizes 1000 --probes 20` | prefetch warm p95 ≤ 20 ms |
| Identity | CI `identity-guard` | every commit a noreply address |

Run the suite with `ENTROPICMEM_MEMORY_DB`, `ENTROPICMEM_VAULT_PATH` and
`ENTROPICMEM_INDEX_DB` unset. **The skip count is 3 on a machine without the
private digest list and 2 with it** — read the pair, not either number alone.
The total rises with every card; the expected figure is in
[NEXT_CHUNK.md](docs/plan/NEXT_CHUNK.md)'s pre-flight, and a mismatch means stop
and report, not "assume the older number is right".

**Run the suite on Python 3.10 as well as your default interpreter**, at least
when you touch `em/`. CI's floor is 3.10 and the two are not interchangeable:
a 3.12-only local run passed while `em/facade/engine.py` could not parse its own
`Z`-suffixed timestamps on 3.10, which silently disabled `consolidate` and decay.
`uv python install 3.10` and a second venv is enough to catch that class. A bug
that only shows on the CI floor is exactly the kind local green cannot rule out.

Two gates have flapped on unchanged code before (`perf-smoke` once, the v3
concurrency AC test once). The way to tell a flake from a regression is a rerun
of the **same** SHA. Never widen a budget, skip a test or mark a job
non-blocking to clear red.

---

## Open blockers (owner-only)

Nothing below may be done by an agent without the owner's explicit go-ahead,
because it is irreversible or public:

- **Releases, tags, and the Hermes catalog entry.** The catalog pins an exact
  commit SHA; only a release moves it.
- **The v3 cutover** — `ENTROPICMEM_ALLOW_LIVE_MIGRATION=1` against the live
  store, with the owner present.
- **The tool rename** `entropicmem_patch_core` →
  `entropicmem_patch_core_memory`, which ships only with a release that re-pins
  the catalog.
- **Nothing else at the moment.** The merge blocker that used to sit here is
  cleared: Chunks 5 and 6 are on `main` at `e25db32` with green CI on that exact
  SHA (verified via the check-run `headSha`, not assumed).

### How GitHub access works from this machine

The git credential helper holds a valid OAuth token for `Ufonik88` with `repo`,
`workflow`, `user:email` and `read:user` scopes, so `git push` works, and
`~/.local/bin/ghx` runs the GitHub CLI with that same token. The token is read
from the macOS keychain on each call and never written to disk, logged, or
printed — read the wrapper's own comments before changing that. The
`ENTROPICMEM_PRIVACY_DIGESTS` repository secret exists, so CI's privacy guard
runs for real. Branch protection on `main` forbids force-pushes and deletion,
which matches the rules.

Merge with `git merge --ff-only` from the CLI after checking green CI on the
exact `headSha` — **never** the GitHub web merge button, which stamps the owner's
email on the commit.

---

## Deviations a reader must not "fix"

Each is a deliberate, recorded decision. The full table with reasons is in
[plan §6.1](docs/plan/REMAINING_PLAN.md) and
[V3_FOUNDATIONS.md](docs/V3_FOUNDATIONS.md).

- **`legacy_id` is stamped on profile-wide writes only.** It is `UNIQUE` and
  content-derived, and v3 scopes rows per user where v2 had one owner per
  database. This is what keeps the provider's mirror lookup working.
- **Deleting is a status change**, not a `DELETE`. Callers see v2's behaviour;
  the row stays for audit.
- **No fuzzy overwrite.** v2 could rewrite a stored fact in place; v3 collapses
  only exact duplicates.
- **Retention stays 7 routine + 5 safety**, not EM-113's rule. Settled by the
  owner's instruction to stop asking.
- **`add_episode` ignores `linked_fact_ids`, `domain` and `source`.** v3's
  `episodes` table has no column for them and adding one means a migration.
- **`Scope.is_owner` defaults to `False` — fail-closed, on purpose.** Flipping it
  to `True` silently reopens the guest-reads-sensitive leak that Chunk 7.2 closed.
  A profile-wide caller (`user == ""`) is the owner context regardless, which is
  why the default facade and the CLI do not need to assert anything.
- **v3 redacts PII only for `sensitive`/`secret` rows, not on every write.** v2's
  write-time pass destroyed only `api_key`/`password` on every write; v3 redacts
  every detected type but only where the row is sensitive. That is deliberate and
  pinned by `test_public_content_is_not_redacted`. What *was* an accident — the
  locale packs being dropped — was fixed: `pii_locales` now reaches redaction on
  both engines, so a store configured for the `za` pack keeps that detection.
- **Sensitive rows are owner-only on read; profile-wide rows are not.** The rule
  restricts *tiers* (`sensitive`/`secret`), not profile-wide rows as such — those
  stay shared knowledge for the profile. Do not "simplify" one into the other.
- **Entity linking is two-sighting, so promotion links only the memory that trips
  the counter.** The earlier memory that also mentioned the phrase is not
  retro-linked, and its link job has already run, so it stays unlinked until its
  content changes. This is EM-208's semantics and Chunk 7.1 asserted it rather
  than changed it. Two ways to close the hole, both deliberate and neither done:
  link the whole sighting list at promotion (prevents *new* holes, a small change
  to `EntityStore.link`), and the plan's `reconcile` job (S5) repairs *existing*
  ones. See [plan §6.1](docs/plan/REMAINING_PLAN.md).

---

## Things that will waste your time if you don't know them

- **GitHub access is configured from this machine.** `~/.local/bin/ghx` wraps the
  CLI with a keychain-held token; `git push` uses the same keychain credential.
  See the access note under [Open blockers](#open-blockers) for what it can and
  cannot do.
- **The v2 engine is still the live path.** Editing `em/` changes nothing a user
  sees until the wiring chunk.
- **`memory_engine.py` is the v2 reference, not a shim yet** (about 3,000 lines;
  don't trust a line number quoted anywhere). At
  3.0 it becomes a shim over the facade — which is why the facade imports v2's
  helpers *lazily*; a module-level import would be a cycle at that point.
- **There is no live store data to read on this machine.** `~/.hermes/entropicmem/memory.db`
  exists and holds a v2 schema with zero facts, and it did not move across a full
  suite run (the isolation proof is in plan §11).
- **No commit may carry a real email address.** Configure
  `Ufonik88@users.noreply.github.com` before committing, or `identity-guard`
  fails and a bad commit lands in published history.
