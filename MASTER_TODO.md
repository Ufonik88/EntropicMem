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

**Last reconciled:** 2026-10-07, against branch `main` at `52ca33b` (Chunk 14's
merge commit), with **Chunk 15 merged on top of it — its code is `50601b3`**. CI is
verified on the exact commit with the check-runs API, not with `run list`, which can
hand back a stale run and look green.

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
worker, `entropicmem worker run`), `em.formation` (`EntityLinker`), `em.retrieval`
(EM-301's analyzer and stopwords, EM-302's candidate generators), and
`em.facade` (the provider-facing contract plus `V3Engine`) — with migrations
`0001`–`0004`.

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
| 10 | **CLI parity** on v3 — 10.0 guard → 10.1 reads → 10.2 maintenance → 10.3 refusals → 10.4 route | **Done, merged** (`250320a`). **EM-211's AC is met except for seven named refusals** |
| 11 | **S3 begins** — EM-302, candidate generators (the critical path) | **Done, merged** (`0066fb5` the scope helper, `33b2b31` the generators). `vector` is EM-303's |
| 12 | **EM-301, the `QueryAnalyzer`** | **Done, merged** (`85afea4`) |
| 13 | **§3.5's `visibility` half** — the write stamp and the read guard | **Done, merged** (`fd9e06f`); **owner-ratified**, internal only, no release |
| 14 | **EM-304 — fusion, rerank, explainability** | **Done, merged** (`14552be`) |
| 15 | **EM-305 — gate, supersession collapse, MMR** | **Done, merged** (`50601b3`) |

**EM-211's acceptance criterion is met for every command except seven, and S2's
exit criteria are close.** The provider (Chunk 9) and the CLI (Chunks 10.0–10.4)
both select their engine by the store's `user_version`, so either one runs on a v3
store. The AC's "CLI commands work unchanged" holds for every command **except**
the seven v2-only features 10.3 refuses by name (triples → S5, `embed --rebuild` →
S3/EM-303, `memory project` → S6, publish/pull → S5, `migrate` → v2-only, and the
two v2-only `recall` forms). That is a deliberate, itemised exception: a refusal
that names its card, not a silent wrong answer. **What remains is the cutover** —
the owner's deliberate act, now technically available.

### In flight

**Nothing.** Chunk 14 (EM-304, fusion) is merged to `main` at `52ca33b` — its code
is `14552be` — with CI verified on the exact commit before the merge and again on
`main` after it, both on the **first** run. The branch is deleted, the remote carries
`main` and `release/2.8.x` only, and the Marketplace entry is untouched (still 2.8.1
at `7e02412`) — a chunk leaves it alone unless the chunk *is* a release.

Thirteen consecutive merges have now gone green on the **first** CI run, all because
the suite was checked on Python 3.10 as well as 3.12 before pushing.

**A measurement trap worth knowing:** `ghx run list --branch main --limit 1` can
return a **stale** run — the one just pushed may not be listed yet, and the
newest-first ordering then hands back an older green run, which looks exactly like
success. Verify with the check-runs API on the commit instead
(`ghx api repos/Ufonik88/EntropicMem/commits/<sha>/check-runs`), reading `head_sha`,
which is the check the rule actually names. This bit once on 2026-10-07 and was
caught only because the reported SHA did not match the pushed one.

**Chunk 13's change is internal only** — ratified by the owner on 2026-10-07 as a
ruling on the behaviour change, and still in no release. It must not reach the
marketplace until the owner explicitly approves a release. See plan §9 item 3.

**The cutover stays held.** The owner revisits it after EM-305 and decides; the agent
brings the decision. Do not switch the live store.

### Where the master plan is

The v3 master plan (1,587 lines) is on the owner's machine at
`~/Documents/EntropicMem Dev docs/EntropicMem_v3_Master_Plan.md`, with a copy under
the Claude session that wrote it. It is **not** committed (it is the owner's
document), so cards after S2 have had to be fetched by hand — which is what
blocked this chunk until the file was found. EM-302's card and the §3.6 text it
points at are now **transcribed into plan §6.2**, so that gap is closed for this
card at least. Before starting a card whose text is not in §6.2, read the file; if
it is unreachable, stop and report rather than inventing fields (plan §6.2's size
guard).

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

### OWNER DECISION NOW DUE: the v3 cutover

**EM-305 was the milestone the owner set: "revisit only after EM-305, and bring me
the decision rather than making it."** It is reached. The decision is the owner's;
nothing below is done without it.

What an informed decision needs, all of it measured rather than asserted:

* **The retrieval layer is now end to end** — analyzer (EM-301), generators
  (EM-302), fusion and rerank (EM-304), gate, collapse and MMR (EM-305). The v3
  store has the machinery that justifies it.
* **What v3 still cannot do on the live path:** the provider and the CLI serve a
  v3 store, but S3's read path is not wired into the provider's prefetch, and the
  CLI still refuses seven v2-only commands by name (Chunk 10.3). `publish`/`pull`
  (S5) refuse, and nothing drains the sync outbox on v3.
* **The live store holds zero facts** (`~/.hermes/entropicmem/memory.db`, v2
  schema) and did not move across any run this session.
* **`embed`/`vector` do not exist yet** (EM-303), so on v3 the vector generator,
  the gate's cosine condition and MMR's embedding path are all inert — retrieval
  is lexical plus entities plus episodes.
* **EM-306 (calibration) has not run**, so §3.6's thresholds are the plan's
  numbers rather than tuned ones.
* **Chunk 13's `visibility` change is ratified but unreleased**, and it changes
  what a non-owner may read; the cutover would be the first time it matters to a
  real store.

**The agent's recommendation, for the owner to accept or refuse:** defer the cutover
to after EM-306, and prefer to wire S3's read path into the provider first — the
cutover is irreversible and owner-present, and doing it while the retrieval layer
is complete but *unwired* lands the owner on a v3 store whose new capability
nothing calls yet.

**If the owner says go, the procedure is in plan §6.3:** verified backup, migrate a
**copy**, verify against the parity suite, then swap — with
`ENTROPICMEM_ALLOW_LIVE_MIGRATION=1` set only for that act.

### Chunk 16 — EM-306, the calibration harness (§3.6). **Next.**

Owner's instruction: "treat as the fix for the thin intent margin, not a
nice-to-have. Its AC is exactly this tuning; widen the weight table there."

- **Spec (§3.6):** split scenarios into `dev` (70%) / `holdout` (30%) by id hash;
  `python -m evals tune --params gate.min_score,gate.min_coverage,ranking.w_*
  --grid …` optimising `0.4*recall@5 + 0.3*mrr + 0.3*abstain_correct −
  0.2*noise_rate`; write the chosen defaults into `em/config.py` with a comment
  linking the result file; calibrate `gate.min_cosine` per embedding model.
- **AC:** holdout metrics reported in PR; defaults committed; §6.3 gates updated.
- **It is also where the thin margin gets fixed:** EM-301's intent table is
  **92.9% on 42 samples**, and the owner's standing constraint is that **the gate
  must not depend on it** — if tuning shows the gate keyed on intent, widen the
  table first.

### Known gaps, recorded so they are not lost

* **§3.5's `visibility` half — FIXED in Chunk 13 (`fd9e06f`) and RATIFIED by the
  owner on 2026-10-07 as a ruling** on the behaviour change: `row_is_owner_only()` as
  the single owner-only predicate, the restored `_outbox` sensitivity gate, and
  `_resolved_visibility()` stamped at insert. *Provenance:* the implementing agent
  proposed it and implemented it under the owner's authorisation. It is **internal
  only** — in no release, and not to reach the marketplace until the owner explicitly
  approves a release. Measured, not inferred: the `MemoryDraft.visibility` default was
  `'user'` and **nothing anywhere set it**, so every profile-wide write carried the
  value §3.5 reserves for user-scoped rows — the exact shape §3.5 makes owner-only.
  **The direction was the point:** the read clause alone would have hidden every
  profile-wide memory from non-owners, so the write stamp was the real fix and the read
  guard is the defence. **Contract:** derive-on-write-only — historical rows keep their
  stamp and a pre-existing profile-wide `'user'` row is owner-only (fails closed);
  re-deriving them would be a bulk change to who may read what, so it is a one-off
  owner-approved migration if ever wanted, never a silent rewrite. Reversible: no
  migration, no rewrite of existing rows. Full reasoning, including the outbox
  consumer analysis, in [V3_FOUNDATIONS.md](docs/V3_FOUNDATIONS.md).
* **`vector` (EM-303)** — §3.6's sixth generator, deferred to the card that builds
  the embedding backend and its numpy cache, which its spec requires.
* **§3.6's IDF cache and `query_rewrite` have no source (EM-301)** — nothing defines
  the `write_generation` counter the cache would key on, so the vocabulary is read
  per call, and there is no config module to enable `query_rewrite` or a hook to
  call. Both are recorded in V3_FOUNDATIONS; they belong to EM-403/EM-407.
* **The full temporal grammar is EM-310's** — EM-301 handles an ISO date, "since",
  "before", "between" and "last N days/weeks/months/years"; month names,
  weekdays, "earlier this week" and the `timezone` config are EM-310's.
* **`ranking.*` config does not exist (EM-304)** — `fusion.RankWeights` carries
  §3.6's numbers as defaults, and `superseded_note` (the third `why_retrieved`
  flag) waits on EM-305's collapse. Both recorded in V3_FOUNDATIONS.
* **`recent`'s "current session" half** — §3.6 reads "in current session / last
  48 h"; the 48 h window is implemented and the session half needs a session id
  `RetrievalContext` does not carry.
* **`EM-211`'s seven CLI refusals** — each names the card that lifts it. Closing
  them is S3/S5/S6 work, not a bug.
* **S3's read path is not wired into the provider.** The retrieval layer is complete
  and unwired, exactly as the facade was before Chunk 9. Prefetch still uses v2's
  scoring on a v2 store; on a v3 store the facade's read half serves it.
* **`gate.*` config (EM-305)** joins `ranking.*` and `extra_stopwords` as
  parameters with the spec's defaults, all waiting on `em/config.py` (EM-407).

### The v3 cutover — **the decision is due now; see above**

Previously deferred (2026-10-07) on four grounds, three of which still hold: the live
store holds zero facts, the CLI still refuses seven commands on v3, and the act is
irreversible and owner-present. The fourth — "S3 is mid-flight" — has changed: S3's
retrieval is complete. **The owner decides; the agent does not.**

## Gates that must be green before anything reaches `main`

| Gate | Command | Budget |
|---|---|---|
| Tests | `python -m pytest -q` | **1966 passed / 3 skipped / 3 xfailed** |
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

Two gates have flapped on unchanged code before, and `perf-smoke` has now done it
**three times** — on 2026-10-07 at `f36c5e6` (Chunks 10.2/10.3), and again the same
day at `a70028a` (Chunk 11). At `f36c5e6` the branch and local runs were both ~4–5 ms
p95, the `main` run came back **p95 69.392 ms with p50 4.544 and max 109.506**, and a
rerun of the *same SHA* returned **p95 5.388 ms (p50 3.437)**. At `a70028a` the failed
run was **p95 51.752 ms with p50 4.769 and max 96.29**, and the rerun of the *same
SHA* was green. The tell each time is the p50: a low p50 with a huge max is one noisy
shared runner, not a regression. (Chunk 11's code is not even on the perf path —
`evals/perf.py` builds `MemoryEngine` directly, not through `_open_engine`, and
`em/store`'s scope helpers are not imported by it.) The way to tell a flake from a
regression is a rerun of the **same** SHA. Never widen a budget, skip a test or mark
a job non-blocking to clear red.

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
- **Sensitive rows are owner-only on read; profile-wide rows are not — yet.** The
  rule restricts *tiers* (`sensitive`/`secret`), not profile-wide rows as such — those
  stay shared knowledge for the profile. Do not "simplify" one into the other. Note
  §3.5's second owner-only condition (`visibility='user'`, on a profile-wide row) is
  **not implemented** — see "Known gaps"; it is a leak to fix, not a settled rule.
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
