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

**Last reconciled:** 2026-10-06, against branch `em/em-211-facade-writes` at
`9661e6b` — the docs close-out for Chunk 6, whose code tip is `6bd4b47`. `main`
at that moment is `03772e3`. A later docs-only commit moving the tip without
changing code, tests or counts is expected; see plan §11.

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

### Released line — frozen

**`v2.8.1`**, tag at `7e02412` on the protected `release/2.8.x`. This is what the
Hermes plugin catalog pins (`entropicmem` 2.8.1) and what users install. It
contains **no v3 code and no new features**: it is 2.8.0 plus safety fixes. Its
one user-visible change is that semantic recall now needs
`embeddings_enabled: true`. Nothing on this line changes without the owner.

### Development line — `main`, `3.0.0.dev0`

**All of S2 (the v3 storage core, `em/`) is merged and unwired.** The provider
still constructs the v2 `MemoryEngine`; nothing in `em/` is on the provider's
live path. That is deliberate — the core landed first so the facade could be
proven against it.

What `em/` contains today: `em.clock` (freezable UTC, ULIDs), `em.store`
(`db`/portable locking, numbered migrations `0001`–`0003`, `MemoryStore`,
`episodes`, `entities`, `jobs`, `backup`, hash-chained `audit`), `em.jobs` (queue,
worker, `entropicmem worker run`), `em.formation` (`EntityLinker`), and
`em.facade` (the provider-facing contract plus `V3Engine`).

### EM-211, the legacy facade — half done, and unwired

The facade is the card that lets the provider run on v3 without being rewritten.
It is split into four chunks, and they are numbered globally so a chunk number
means one thing:

| Chunk | What | State |
|---|---|---|
| 4 | Facade **reads** over `em.store` | **Done** (`0349b7b4b`, 2026-10-03, merged) |
| 5 | Facade **writes** over `em.store` | **Done** (`36355f3`) — committed, **not merged** |
| 6 | Facade **mirror call** | **Done** (`6bd4b47`) — committed, **not merged** |
| 7 | Facade **`EntityLinker` job** | Next |

**EM-211's acceptance criterion is not met and S2's exit criteria still fail.**
The reason has been the same after every chunk so far: the facade is complete as
a *library* but nothing is wired into the provider, so "full legacy test suite
green on a v3 DB" cannot be claimed yet. Chunk 6 narrowed that gap — the provider
no longer reads a raw connection, so it now talks to the engine only through
methods both engines implement — but it still constructs `MemoryEngine`. Do not
read three landed chunks as the card being done.

### In flight

**Chunks 5 and 6, on the local branch `em/em-211-facade-writes`** — six commits,
all committed with a clean tree:

| Commit | What |
|---|---|
| `36355f3` | `feat(em-211)`: Chunk 5, the seven write stubs become real write paths |
| `d055b74` | `docs`: close out Chunk 5, scope Chunk 6 |
| `436d360` | `docs`: `MASTER_TODO.md` + the document-control rule and its guard |
| `81859d0` | `docs`: point the status page at its own merge state |
| `6bd4b47` | `feat(em-211)`: Chunk 6, `find_mirrored` on both engines |
| `9661e6b` | `docs`: close out Chunk 6, scope Chunk 7 |

**Pushed 2026-10-06.** The first CI run was **red**, and it was right to be:

| Leg | What failed | Why local green missed it |
|---|---|---|
| `test (3.10)` | 5 consolidate tests | The facade borrowed v2's timestamp parser; Python 3.10 rejects the `Z` suffix v3 writes. Local interpreter is 3.12. |
| `test (3.10–3.13)` | `tests/test_master_todo.py` | CI checked out shallow, so the guard could not resolve its recorded SHA. |

Both are fixed in the commit that follows, with regression tests and a CI
checkout fix. Every other job passed on the first run, including `windows-import`,
`identity-guard`, `evals-ci`, `bench` and `lint`. `origin/main` is still
`03772e3` until the fix is green.

---

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
- **EM-211 Chunks 4, 5 and 6**: the facade's read half, its write half, and the
  mirror call. `PROVIDER_ATTRIBUTES` is now empty, so the provider reaches the
  engine only through methods both engines implement.
- **EM-212 partially done**: `_backend` loads its own `vault.py` by path. The
  package move is still open.
- **Repo hygiene that keeps all of this honest:** privacy guard v2, commit
  identity guard, a docs-link guard, a CLI-reference drift guard, a perf smoke
  test that prints its full distribution, and a document-control guard that
  fails when this page and the plan disagree about the truth.
- **The document-control rule itself** is now written into `AGENTS.md` and
  enforced, so the next agent picks it up on any harness without being told.

---

## What is next

**Chunk 7 — the `EntityLinker` job.** The last piece of EM-211:

1. Run `EntityLinker` from a `link:<memory_id>:<version>` job, enqueued on write
   and handled by the worker — **never inside `MemoryStore.add`**, which would
   put entity work inside a write transaction (invariant 2).
2. Bring the §3.5 owner-only rule for sensitive rows with it. That needs the
   gateway identity, and it is the read-side scope gap that has been deferred
   since Chunk 4: `get_fact` and recall still read profile-wide.
3. Closing it means EM-211's four chunks are all done — but the card's AC still
   needs the **wiring** chunk, which switches the provider onto the facade. That
   is a separate decision and is not scheduled.

Then, in order:

- **EM-212's package move.** Split it first; it is multi-file. Pinned by a strict
  xfail that flips when it lands.
- **Wiring, and only then the v3 cutover.** Owner-gated, needs the owner present.
- **S3 (retrieval v3)**, on the critical path in plan §6.2:
  EM-302 → EM-304 → EM-305 → EM-403 → EM-503 → EM-901 → EM-904.

---

## Gates that must be green before anything reaches `main`

| Gate | Command | Budget |
|---|---|---|
| Tests | `python -m pytest -q` | **1626 passed / 3 skipped / 4 xfailed** |
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
- **Merging Chunks 5 and 6**, which needs green CI on `6bd4b47` — see below.

### Why Chunks 5 and 6 are not merged

Both are committed and every gate that can run locally is green, but
`AGENTS.md` rule 1 forbids merging without green CI **on the exact SHA being
merged**, and no CI has been run for either.

**GitHub access is available from this machine** (as of 2026-10-06): the git
credential helper holds a valid OAuth token for `Ufonik88` with `repo`,
`workflow`, `user:email` and `read:user` scopes, so `git push` works, and
`~/.local/bin/ghx` runs the GitHub CLI with that same token. The token is read
from the macOS keychain on each call and never written to disk — see the wrapper's
own comments before changing that. The `ENTROPICMEM_PRIVACY_DIGESTS` repository
secret exists (set 2026-09-26), so CI's privacy guard can run and is not expected
to trip on a missing list.

So the remaining step is mechanical: push `em/em-211-facade-writes`, wait for
green CI on the tip (`9661e6b` or later), then fast-forward `main` with
`git merge --ff-only` and delete the branch — **never** the GitHub web merge
button, which stamps the owner's email on the commit. Branch protection on `main`
already forbids force-pushes and deletion, which matches the rules.

Local green is still not CI green: `windows-import`, `plugin-validate`, `bench`
and `identity-guard` have never run for these commits, and the privacy guard has
never run against these file changes.

Then, and only then, correct the merge state in three places: the chunk table and
the In flight section **here**, the "In flight" row in
[plan §11](docs/plan/REMAINING_PLAN.md), and the Part A headings in
[NEXT_CHUNK.md](docs/plan/NEXT_CHUNK.md). Until that is done, "committed, not
merged" is the accurate description and the guard will keep enforcing it.

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
