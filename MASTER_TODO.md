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

**Last reconciled:** 2026-10-10, against branch `main` at `b8e170a` — the fast-forward
merge of Chunk 31 (EM-401 slice 2: the provider moves into `em/provider/provider.py`
and the plugin package becomes a host shell), named deliberately instead of the tip. **All check-runs were green on that exact SHA, `identity-guard`
included** (11 on the branch push, 22 across both events on the `main` push). The
branch is deleted; the remote carries `main` and `release/2.8.x` only.

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

**All of S2 (the v3 storage core, `em/`) is merged, and S3's retrieval is now
wired.** On a v2 store the provider still constructs the v2 `MemoryEngine` and
nothing changes. On a v3 store the facade serves the read half — and with
`ENTROPICMEM_V3_RETRIEVAL=1` (P0b, default off) prefetch is served by
`em.retrieval` in ranking and gate terms, rather than by the v2 scoring the
facade otherwise borrows. That flag is what completes the cutover re-decision
condition (a). The live store remains v2 and untouched.

> **Live retrieval is lexical. Semantic retrieval is not shipped.** The EM-303
> stack (backends, jobs, cache, cosine gate, MMR) is merged and measured, but
> the provider does not produce a query embedding yet: that wiring is
> **EM-401–403**, and until it lands a live turn is served by lexical,
> entity and episodic scoring only. Do not describe semantic retrieval as
> shipped, and do not quote vector eval numbers without their
> `retrieval_mode` label (vector runs are comparable only to vector
> baselines; the frozen suites' baselines are lexical).
>
> **Vector-mode results exist as context only (2026-10-09).** With fastembed
> (`BAAI/bge-small-en-v1.5`) and the explicit `--embeddings` override, the hard
> suite reads **recall@5 0.988** (lexical 0.933), **ageing 1.000** (lexical
> 0.733), paraphrase 1.000, noise 0.172 unchanged, parsed as
> `v3-hard-vector.json` / `v3-ci-vector.json`; both comparisons printed
> cross-mode and never gated. **The recommended live-promotion gate (owner
> confirms): coverage ≥ 95% with zero stale exclusions on the sample, hard
> recall@5 ≥ 0.95, ageing ≥ 0.85, abstain ≥ 0.95, noise ≤ 0.172, must_not = 1,
> turn-path p95 ≤ 150 ms, and the shadow's `v3_only == 0` still holding.**
> Nothing about the live store moves without that and the owner's go.

**The only route to a new user-facing update is the 3.0 release (EM-904)**, and
it cannot happen until the v3 core is wired in and the live store is migrated.
That work is listed under [What is next](#what-is-next); the cutover itself is
owner-gated.

What `em/` contains today: `em.clock` (freezable UTC, ULIDs), `em.store`
(`db`/portable locking, numbered migrations `0001`–`0004`, `MemoryStore`,
`episodes`, `entities`, `jobs`, `backup`, hash-chained `audit`), `em.jobs` (queue,
worker, `entropicmem worker run`), `em.formation` (`EntityLinker`), `em.retrieval`
(the full §3.6 pipeline: EM-301's analyzer, EM-302's generators, EM-304's fusion,
EM-305's gate/collapse/MMR, and `pipeline.retrieve` — the one shared sequence),
and `em.facade` (the provider-facing contract plus `V3Engine`) — with migrations
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
| 15 | **EM-305 — gate, supersession collapse, MMR** | **Done, merged** (`50601b3`); two review-driven pins added at `9f4b39b` |
| 16 | **The v3 eval adapter** (P1) — the first end-to-end v3 number | **Done, merged** (`ff0d3c3`) |
| 17 | **P0a — the v3 shadow read** | **Done, merged** (`f0a7c70`, id-space fix `636a685`, test fix `d1060c1`) |
| 18 | **P0b — a v3 store serves prefetch *from* S3**, behind `ENTROPICMEM_V3_RETRIEVAL` | **Done** (code `be6352e`; two commits, merged `--ff-only` after green check-runs on the branch tip). Includes the gate's `kind='constraint'` bypass fix found by its end-to-end run |
| 19 | **P0c's readout — score a shadow log against the frozen observable, and collect one honestly** | **Done, merged** (`94dd3c7` + docs `2b1e49b`; count-guard deferral `b213dc0`). **The data itself is still not collected** — see the environment finding below |
| 20 | **The ceiling split — the owner's ruling of 2026-10-08** | **Done** (code `3c8b301`; two commits, merged `--ff-only` after green check-runs on the tip). Fabrication stays hard (`max_v3_only = 0`); the miss side is its own ceiling, **pre-registered and un-armed**, and an un-armed ceiling blocks `met` rather than passing silently |
| 21 | **EM-306 — the calibration harness; it arms the miss ceiling** | **Done** (code `4a2b25e`; code + docs commits, merged `--ff-only` after green check-runs on the tip). `evals tune` splits by id hash, searches a pre-declared grid, commits `em/config.py`; the same holdout armed `max_v2_miss_rate` at `0.107143` |
| 22 | **EM-307 — packer, renderer, and retrieval wiring** | **Done, merged** (`7d6a22e`, ff from `a674383`; library `6cd0943`). A gated retrieval renders. **The eval adapter and the provider still do not call it** — deliberately, and pinned |
| 23 | **EM-303, first slice — search stored embeddings** | **Done, merged** (`7d6a22e`, ff from `9d5a72b`). Cosine + the `vector` generator behind `retrieve()`'s query-vector seam and the 50% coverage gate. **No embedder, no numpy cache; the default call is unchanged** |
| 24 | **EM-303 — MMR's embedding path** | **Done, merged** (`000a268`, ff from `156370e`). `diversity.mmr` takes an optional pairwise similarity; the pipeline supplies cosine when a query vector and model were given (clamped at 0), Jaccard otherwise. **Default path unchanged** |
| 25 | **EM-303 closed — backends, `embed`/`embed_backfill`, model identity, vector cache** | **Done, merged** (`3439b77`, ff from `e8997d8`). Four backends + auto/none selection; jobs with a write-time version recheck and `meta.embedding_model`; a numpy/pure-Python snapshot cache behind migration 0005 (50k p95 **3.86 ms**) |
| 26 | **The EM-303 follow-ups: episode embeddings, query embeddings in evals, numpy in CI** | **Done, merged** (`42e16c7`, ff from `51cdcb3`). `EpisodeStore` enqueues `embed` jobs; the backfill and handler cover episodes; the v3 eval adapter embeds documents and the query when `disable_embeddings=False`; CI installs numpy so the cache tests and the 50k AC run there. **The capture-on-idle/compaction feature is planned as EM-411** (plan §6.3) |
| 27 | **EM-303 precision — version-checked vector reads, episode read path, retrieval-mode labels** | **Done, merged** (`6d9bf3b`). Memory `content_hash` and episode `updated_at` are verified on every read; reads filter to the query width; `candidates.episodic` reads episode vectors into EM-307's renderer; backfill idempotence/resume is pinned; every eval report labels lexical vs vector, cross-mode compare is context only, baselines labelled |
| 28 | **EM-303 observability, promotion evidence, model-switch hygiene** | **Done, merged** (`60f0d67`, ff from `514a6a5`). Per-query coverage/stale logging + stale→re-embed round trips; the CI numpy guard; explicit `--embeddings` and committed **vector-mode baselines** (hard 0.988, ageing 1.000 vs lexical 0.933/0.733) with the recommended promotion gate; old-model storage measured (21 MB/10k/set) and prune policy decided; checksum replay oracle; EM-411 test-first briefs |
| 29 | **EM-401 slice 1 — the §4.1 hook skeleton and the pinned host contract** | **Done, merged** (`f8af1a9` as `db7c24f`, ff). `fail_soft` wraps every hook (timed, counted, over-budget at WARNING, exceptions swallowed with the type only) and is **fail-closed** on `on_pre_compress`/`initialize`/`save_config`/`backup_paths`; `ProviderState` holds the session-scoped fields; `em/provider/provider.py` is the §4.1 surface table with `on_delegation`→EM-405 and `identity_signature`→EM-402 deferred by name; the contract test enumerates `MemoryProvider` from the pinned hermes-agent (`tests/harness/pinned_memory_provider.json`, re-derived against the real host when reachable); the harness drives every §4.1 hook and proves from the metrics that each ran and none failed. The class itself stays in `plugins/entropicmem/__init__.py` — the move is the next slice |

| 30 | **`save_config` blank-home fix + the two hygiene corrections the EM-401 run surfaced** | **Done, merged** (`6646351`). `save_config(values, "")` resolved `Path("")` to `Path(".")` and merged `plugins.entropicmem` into the CWD's `config.yaml`, rewriting that file; it now refuses a blank home and raises (the fail-closed shape §4.1 asks for; the host always passes `str(get_hermes_home())`, so this is defence in depth). `.gitignore` covers `uv*.lock` so `git add -A` cannot sweep a stray lock file in again. `AGENTS.md`'s mutation rule records that a mutation must be restored from a **copy**, never `git checkout -- <file>`. 2 new tests; **2223 / 5 / 3** bare and **2225 / 3 / 3** with numpy on 3.10 and 3.12; ruff clean; 3 mutation checks red |
| 31 | **EM-401 slice 2 — the provider moves into `em/provider/provider.py`** | **Done, merged** (`b8e170a`). `plugins/entropicmem/__init__.py` is a **145-line** host shell: `register` + a `MemoryProvider` subclass over `_HermesHost`, which injects the path/config resolvers, the P0a shadow read, the context-propagating thread factory, the host's bounded tool-error formatter and `RecallStatus`. `em/provider/provider.py` holds `EntropicMemProvider` (the whole provider; EM-404 later splits `tools.py`) plus the `ProviderHost` ABC. `em` imports no host and no plugin package — an AST guard pins that, another pins the 150-line shell. Six source-scanning guards now read the implementation. 3 new tests; **2226 / 5 / 3** bare and **2228 / 3 / 3** with numpy on 3.10 and 3.12; ruff clean; 8 mutation checks red |
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

**Nothing.** Chunk 31 (EM-401 slice 2, the provider move) is merged (`b8e170a`) with all checks green on that exact SHA. The branch is deleted; the remote carries `main` and `release/2.8.x` only. The Marketplace entry is untouched (2.8.1 at `7e02412`). EM-411 remains planned and unbuilt; the promotion gate is recommended, awaiting the owner's confirmation. **EM-401's remaining slices:** the provider class moves into `em/provider/provider.py`, then EM-402 (ScopeContext) and EM-403 (PrefetchService) — and only then does a query embedding reach the live path.

**P0's code is complete: P0a (the shadow read) and P0b (a v3 store serving prefetch
from S3 behind `ENTROPICMEM_V3_RETRIEVAL`) are both merged, P0c's **readout** landed
(`94dd3c7`), the **ceiling split the owner ruled on 2026-10-08 landed
(`3c8b301`)**, and **EM-306 (`4a2b25e`) armed the miss side from its holdout** —
fabrication stays a hard ceiling (`max_v3_only = 0`), and the miss ceiling is now
`0.107143`, so a clean sample can conclude. The divergence-definition question that
readout raised is therefore **settled, not open**. **What remains of P0 is the data itself**, and it is blocked on the environment
rather than on a decision: this box does not run the plugin at all (no `memory.provider`
key, `plugins.enabled` lists only `homeassistant`, no `~/.hermes/plugins/entropicmem`),
so no turn reaches a write path and the live store stays empty. Real turns need a host
where the plugin is installed and enabled — the owner's act.

**A measurement trap worth knowing:** `ghx run list --branch main --limit 1` can
return a **stale** run — the one just pushed may not be listed yet, and the
newest-first ordering then hands back an older green run, which looks exactly like
success. Verify with the check-runs API on the commit instead
(`ghx api repos/Ufonik88/EntropicMem/commits/<sha>/check-runs`), reading `head_sha`,
which is the check the rule actually names. This bit once on 2026-10-07 and was
caught only because the reported SHA did not match the pushed one.

**The visibility change is internal only** — ratified by the owner on 2026-10-07 as a
ruling on the behaviour change, and still in no release. It must not reach the
marketplace until the owner explicitly approves a release. See plan §9 item 3.

**The cutover re-decision point is now met in full:** (a) the provider reads
through S3 — P0b, in code and measured, behind a flag that defaults off — and (b) the
v3 adapter produced its first end-to-end number. **The decision goes back to the
owner; the agent does not switch the live store without an explicit go.**

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
- **EM-306 landed (2026-10-08) and armed the miss ceiling:** `python -m evals tune`
  calibrates the hard suite on a dev/holdout split by id hash and commits its choice as
  `em/config.py` scalars (unwired until EM-401–403); the same holdout executed the
  pre-registered arming rule, so `_shadow`'s promotion observable is fully armed and
  **P0's code is complete**.
- **EM-307 landed (2026-10-09, `7d6a22e`): the token packer and §3.6 renderer, and a
  gated retrieval can be rendered.** `render_retrieval` produces the sectioned block
  (superseded notes, episodes, follow-ups) under a 450-token budget. The eval adapter
  and the provider deliberately still emit full-id bullets; switching them is a
  separate, measured change.
- **EM-303's first slice landed (2026-10-09, `7d6a22e`): stored embeddings can be
  searched.** A stdlib cosine ranker over one joined query, the 50%-coverage gate, and
  the gate's cosine condition behind `retrieve(query_vector=, embedding_model=)`. The
  default path, the adapter and the provider pass no query vector, so scores today are
  unchanged. Backends, `embed` job, numpy cache and MMR's cosine path remain.
- **EM-303's MMR embedding path landed (2026-10-09, `000a268`, merged):**
  `diversity.mmr` accepts a pairwise similarity; the pipeline supplies cosine when a
  vector and a model were given, clamped at 0, with a per-pair Jaccard fallback.
  `similarities=None` is exactly the old behaviour.
- **EM-303 closed (2026-10-09, `3439b77`, merged):** the four backends with `auto`
  selection and a silent `none` fallback;
  the `embed`/`embed_backfill` handlers (write-time version recheck; model identity
  in `meta.embedding_model`, written only when the backfill completes); the
  snapshot vector cache (numpy matrix or pure Python; fingerprint = count + max
  rowid + write generation) behind migration 0005's index. **50k × 128 warm search
  p95 3.86 ms** against the 25 ms AC.
- **EM-303's follow-ups (2026-10-09, `42e16c7`, merged):** episodes
  are now first-class embedding owners (`add_episode`/`upsert_episode` enqueue;
  the handler and backfill cover them, with the `updated_at` stamp as the stale
  guard); the v3 eval adapter embeds scenario documents at load and the query in
  `_run` when a suite allows embeddings, so vector quality is measurable with
  `evals run --adapter v3` on a box with a backend; CI installs numpy, so the
  cache tests and the 50k AC run there rather than skipping.
- **Repo hygiene that keeps all of this honest:** privacy guard v2, commit
  identity guard, a docs-link guard, a CLI-reference drift guard, a perf smoke
  test that prints its full distribution, a document-control guard that
  fails when this page and the plan disagree about the truth, a pre-flight
  **count** guard that fails when the three pages stating the expected suite
  size disagree with each other, and a **cited-SHA guard** that fails when a
  tracked doc or a landing commit cites a SHA that does not resolve (closed,
  reasoned allowlist for the dead and upstream tokens).
- **The document-control rule itself** is now written into `AGENTS.md` and
  enforced, so the next agent picks it up on any harness without being told.

---

## What is next

### The v3 cutover — **deferred 2026-10-07; both re-decision conditions are now met**

The owner ruled: **defer the cutover; wire S3's read path into the provider first.**
The reasoning recorded at the time: the retrieval layer was complete but *unwired*, so a
cutover would land the owner on a v3 store whose new capability nothing called. The owner
also rejected "defer indefinitely" and set the condition explicitly:

> **Reconsidered when (a) the provider reads through S3, and (b) the v3 adapter has
> produced one end-to-end eval number. Not before.**

**(b) is now met.** The evidence from the v3 adapter, against v2 on the same runs:

| suite | v3 | v2 |
|---|---|---|
| **ci** overall | recall@5 1.000 · abstain 1.000 · noise 0.143 · must_not_ok 1.000 | identical |
| **hard** overall | **recall@5 0.933** · abstain 1.000 · **noise 0.172** · must_not_ok 1.000 | 0.939 · 1.000 · 0.219 · 1.000 |
| hard/ageing | **0.733** | **0.733** |

Parity on recall with **lower noise** — the gate working — and `ageing` at 0.733 for
both, which is §6.2's predicted lexical-only figure because the four paraphrase misses
share no words with the stored fact and vectors are EM-303's.

**(a) is now met in code.** **P0a — the shadow read — is merged** (`f0a7c70`): served
by v2 as today, S3 post-turn over a v3 copy, divergence logged with the copy's age and
the caveat. **P0b is merged too** (`be6352e`): on a v3 store, `ENTROPICMEM_V3_RETRIEVAL=1`
serves prefetch from `em.retrieval` — ranking and gate — while the off path stays
byte-identical to v2's scoring, pinned by a golden. So the provider both *reads* through
S3 (off the turn path, on a copy) and can *serve* from it (on a v3 store, behind the
flag), which is what condition (a) means. What remains is **P0c**: reading the shadow
data against the observable fixed in advance.

**Both conditions are met, so the cutover decision is back with the owner.** The
evidence, all recorded above: (b) the adapter's numbers, and (a) P0b's measured turn-path
cost. Nothing about the live store has moved.

**The shadow's own honesty, so its numbers cannot be over-read:** the copy lags, so
divergence is a **lower bound**; v3 has no cosine condition until EM-303, so it is not
an apples-to-apples quality comparison; and the promotion observable was fixed in
advance — **≥ 200 turns, copy within 900 s, `v3_only` never once non-zero (hard),
the miss rate against its pre-registered ceiling (armed at `0.107143` from EM-306's
holdout), off-turn p95 ≤ 150 ms.** The observable was amended once, by owner ruling on
2026-10-08 and *before any real turn was read*: the old symmetric `divergence ≤ 10%`
counted a miss like a fabrication, and the measured sample was 150 misses with 0
additions. One thing the first real run settled: ids are compared through
**`COALESCE(legacy_id, id)`**, because v2's content id and v3's `mem_…` ULID name the
same row — without that mapping every line reads as a divergence. The first real run
also showed v3 injecting exactly what v2 injected, divergence empty.

**Owner questions, answered from the code:**

* **Chunk 13 is forward-only, and no data needs repairing.** Confirmed rather than
  assumed: the v2→v3 migration stamps **`visibility='profile'`** for every migrated fact
  (so migrated rows are profile-readable, *not* the owner-only shape), and the only
  producer of the owner-only shape was `MemoryStore.add`'s old default — which no
  released store ever ran, because the live store is `user_version=0` with v2 tables
  only. **So there is no repair path, no backfill, and nothing hidden from a non-owner
  today**; an explicit CHANGELOG line says so rather than leaving silence to be read as
  "history is clean".
* **Chunk 13's release vehicle.** `release/2.8.x` carries **no `em/` directory at all**
  (verified with `git ls-tree`), so the visibility fix *cannot* be a 2.8.x patch — its
  only vehicle is the release that ships `em/` (3.0). It does **not** need to land
  before the cutover: the code is already on `main`, the fix adds no migration, and
  shipping code is an independent act from migrating the live store. Recorded in
  plan §9 item 3.
* **Provider wiring behind a flag?** Both forms landed, and they answer different
  questions. `ENTROPICMEM_V3_RETRIEVAL` (P0b) switches the ranking *on a v3 store*;
  it can only matter once the store **is** v3, because engine selection is by
  `PRAGMA user_version`. The **shadow** (P0a) is the form that exercises v3 on real
  turns *without* committing the store, at the cost of a lagging copy.

### START HERE TOMORROW

**EM-401 is complete in code: slice 1 (the §4.1 hook skeleton, `db7c24f`) and
slice 2 (the provider move, `b8e170a`) are merged, with the `save_config` fix
(`6646351`) between them.** Local suite **2226/5/3** bare and **2228/3/3** with
numpy on Python 3.10 and 3.12, `ruff==0.16.2` clean, CI green on every merge SHA.
`plugins/entropicmem/__init__.py` is now a 145-line host shell and
`em/provider/provider.py` holds the provider — so **EM-402 (ScopeContext) and
EM-403 (PrefetchService) build on the moved class**, and only then does a query
embedding reach the live path. `on_delegation` (EM-405) and `identity_signature`
(EM-402) remain explicitly deferred in the §4.1 surface table. Live retrieval is
still lexical. EM-411 stays test-first, unbuilt, default off. The cutover stays
with the owner. P0's observable stays armed at `0.107143`.

**P0c's data is blocked on the environment, and the reason is now measured rather than
assumed.** This box is not running EntropicMem at all: `~/.hermes/config.yaml` has **no
`memory.provider` key** (so the host uses its built-in memory), `plugins.enabled` lists
only `homeassistant`, there is **no `~/.hermes/plugins/entropicmem`** and no
`entropicmem-live-2.8.1` clone, no vault, and `index.db` holds 0 notes. Every table in
`~/.hermes/entropicmem/memory.db` is empty — `facts`, `pending_facts`, `episodes`,
`audit_log`, `triples`, `sync_outbox` — at `user_version=0`. **So the zero-fact state is
expected: no write path is being exercised, because no turn ever reaches the plugin.** It
is not a broken write path, and it will not fix itself by accumulating. Real turns need a
host running the **dev-line** plugin — the released 2.8.1 carries no shadow code
(verified with `git ls-tree origin/release/2.8.x`), so the owner's active 2.8.1
deployment cannot collect as-is — with `ENTROPICMEM_SHADOW_V3` set. **Owner-reported
2026-10-08: the owner's machine (§2) is an active deployment whose live store holds
real data, so the host exists; the owner-facing step is enabling the shadow-capable
line there.**

1. **Read:** this file, then `docs/plan/NEXT_CHUNK.md` **Part B**, then
   `REMAINING_PLAN.md` §9 (items 6 and 7 are the owner's rulings) for what is in force.
2. **P0c, the data.** Needs (a) a host with the **dev-line (shadow-capable) plugin** enabled — the
   released 2.8.1 has no shadow, and the owner's active machine (§2) is the candidate —
   (b) `ENTROPICMEM_SHADOW_V3` set there, (c) ≥ 200 real turns, then `python <plugin>/_shadow.py report`. The
   observable is fully armed now, so a clean sample can conclude; until (a) exists, the
   only honest sample is a synthetic one — and a synthetic sample is evidence about the
   *metric*, never about turns, so it must not be used to re-arm a ceiling.
3. **EM-303 is closed and merged** (backends, jobs, model identity, cache).
   Nothing embeds on the query path yet by design; the provider cards wire
   `ensure_embedding_model` and a query embedding. Do not point the eval adapter
   at short citations and do not wire `em/config.py` as a drive-by. Measure before
   any adapter switch: the 450-token budget can drop an id the current bullet
   emits.
4. **Pre-flight:** `python -m pytest -q` gives **2226 passed / 5 skipped / 3 xfailed**
   on **both Python 3.10 and 3.12** (CI's extra set: fastapi, httpx, cryptography, pyyaml).
   `git merge-base --is-ancestor 4eb8097 HEAD` proves the base. A fresh venv without
   those extras skips and fails tests that are green in CI — that is the environment,
   not the tree.
5. **Two commits** (code, then docs), then **check-runs on the exact SHA** — not
   `run list`, which can hand back a stale green.
6. **The cutover decision is (a)+(b) complete and back with the owner.** Bring the
   evidence and the recommendation; do not switch the live store.

### What is next — the owner's priority order

The owner set the order explicitly; do not reorder it without asking.

| # | Work | Why now | State |
|:--|:--|:--|:--|
| **1** | **P0c — collect the shadow data and read it against the frozen observable** | It is the gating empirical step for the cutover; the readout landed in `94dd3c7`, the **data has not** | **Readout DONE, observable fully armed, data outstanding** — needs ≥200 real turns on a host running the **dev-line shadow** (the owner's active machine is the candidate) |
| **2** | **P2 / EM-306 — calibration harness** (`evals tune`, `em/config.py`, and the armed miss ceiling) | It was the next buildable chunk and it unblocks P0c's reading | **DONE (`4a2b25e`)** — holdout reported, defaults committed, ceiling armed at `0.107143` |
| **3** | **EM-307 — packer and renderer** | §3.6's block, fed by a real retrieval | **DONE, merged (`7d6a22e`).** A gated retrieval renders. The adapter and the provider do not call it. Next build is EM-303's remainder |
| **4** | **EM-303 — vectors: the gate's cosine condition, MMR's embedding path** | The remaining quality lever behind the gate, and the only thing that moves `hard/ageing` off 0.733 | **DONE, merged (`3439b77`):** backends, jobs, model identity, cache (50k p95 3.86 ms). Next chunk is a choice — S3's remaining cards, the adapter switch, or EM-401 |
| **5** | **Next chunk — EM-401–403 (live embedding wiring)**, then EM-411 | Closes the largest user-visible gap: today live retrieval is lexical, and the provider cards are where `ensure_embedding_model`, a query embedding and the capture hooks are wired | **Chosen (owner's recommendation, agreed):** EM-401 first; **EM-411 after EM-406**, spec ready below |
| **—** | **P3 — the cutover** | Both re-decision conditions are met in code | **Held: the owner decides; the agent brings it** |

**The owner's order was re-set on 2026-10-08** (this table): P0c first as the gating
empirical step — now blocked only on a host, with the observable armed — then EM-306
(**done**), then EM-307 (**done, merged**), then EM-303 (**closed and merged
`3439b77`**: search, MMR, backends, jobs and the cache). **The next chunk's order
is the owner's to set**; the candidates are listed in the table. P1 is done and P3
stays with the owner. Do not reorder without asking.

**P0b's shape, as landed — serve prefetch from S3 on a v3 store:**

* `ENTROPICMEM_V3_RETRIEVAL=1` (strictly `"1"`, default off, read per call so a store
  is comparable both ways without a redeploy) switches `V3Engine.recall_with_relevance`
  from v2's borrowed scoring to `em.retrieval.pipeline.retrieve` — the shared pipeline
  the eval adapter and the shadow call — **with** the gate.
* The pipeline's memory rankings map back to v2 `StoredFact`s (`legacy_id` as the id),
  so the provider's renderer, config and dedup are untouched and no renderer was added.
* The **off** path is byte-identical to pre-P0b, pinned by a golden captured before the
  flag existed and re-checked against a detached worktree of the base commit.
* Two recorded differences: **episodes are skipped** from the served list (no v2 fact
  shape; §3.6's render is EM-307's), and v2's `min_relevance`/decay knobs are not
  applied over S3's gate. Measured on the turn path at 1000 memories: prefetch p95
  **4.18 ms → 9.32 ms**, against the pre-declared 150 ms ceiling.
* P0a's half is unchanged: `ENTROPICMEM_SHADOW_V3=<path>` serves v2 and logs S3's
  divergence over a lagging v3 copy, off the turn path.

**EM-306's detail is in `docs/plan/NEXT_CHUNK.md` Part B** — including its two
prerequisites, one of which (the v3 adapter) P1 has now cleared, and the owner's
standing constraint that **the gate must not depend on the 92.9%-on-42 intent table**.

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
* **`vector` is complete (EM-303, merged `3439b77`; follow-ups merged `42e16c7`).**
  Search, MMR, backends, jobs, model identity and the cache
  are merged. The follow-ups: `EpisodeStore` enqueues `embed` jobs and the jobs
  and backfill cover episodes; the v3 eval adapter embeds documents and the query
  when `disable_embeddings=False` (the frozen suites stay lexical); CI installs
  numpy so the cache tests and the 50k AC run there. **What is still deliberately
  absent:** the **provider** does not embed a query yet — the provider cards
  (EM-401–403) call `ensure_embedding_model` at initialize and embed the query.
  The cache's one recorded caveat: a raw-SQL same-length rewrite is not re-read
  until reset (all `put_embedding` writes are seen).
* **§3.6's IDF cache and `query_rewrite` have no source (EM-301)** — nothing defines
  the `write_generation` counter the cache would key on, so the vocabulary is read
  per call, and there is no config module to enable `query_rewrite` or a hook to
  call. Both are recorded in V3_FOUNDATIONS; they belong to EM-403/EM-407.
* **The full temporal grammar is EM-310's** — EM-301 handles an ISO date, "since",
  "before", "between" and "last N days/weeks/months/years"; month names,
  weekdays, "earlier this week" and the `timezone` config are EM-310's.
* **`ranking.*` is still the spec defaults at the call site (EM-304 / EM-306).**
  `fusion.RankWeights` carries §3.6's numbers. EM-306's tuned scalars are in
  `em/config.py` and nothing in retrieval reads them. `superseded_note` is emitted
  by EM-305; `render_retrieval` prints it when the pipeline kept a predecessor.
  The provider's served block still does not.
* **`recent`'s "current session" half** — §3.6 reads "in current session / last
  48 h"; the 48 h window is implemented and the session half needs a session id
  `RetrievalContext` does not carry.
* **`EM-211`'s seven CLI refusals** — each names the card that lifts it. Closing
  them is S3/S5/S6 work, not a bug.
* **P0b's served path is memories-only, and the flag defaults off.** The pipeline also
  ranks episodes; they are skipped from the served prefetch because a v2 `StoredFact`
  has no episode shape. `render_retrieval` can print an episode; the served path
  does not call it. On that path v2's
  `min_relevance`/decay/evergreen parameters are not applied — the gate's support test
  and `min_score` are S3's filter — so the provider's `min_relevance_score` config
  governs the off path only until EM-306 owns the scalars. Flipping the flag's default
  (or plumbing it to config) is the remaining owner-facing step, not an agent's.
* **The gate's `kind='constraint'` bypass was missing and is fixed (Chunk 18).** The
  pinned generator surfaces `pinned=1` **or** `kind='constraint'`; `gate.load_rows`
  read only the column, so a constraint with no lexical overlap was filtered instead
  of bypassing. Found by P0b's end-to-end run; pinned at the loader and at
  `apply_gate`, mutation-checked both ways, no scored dataset affected.
* **P0c has a readout and no data — and the blocker is now measured, not assumed.**
  `_shadow.py report` scores a log against the observable; `scripts/shadow_collect.py`
  produces a sample from real engines over a read-only copy. What is missing is **200+
  real turns**, and this box cannot produce them: `~/.hermes/config.yaml` has **no
  `memory.provider` key** (the host uses its built-in memory), `plugins.enabled` lists
  only `homeassistant`, there is **no `~/.hermes/plugins/entropicmem`** and no live
  clone, and every table in the live store is empty at `user_version=0`. So the
  zero-fact state is **expected** — no turn reaches the plugin, so no write path runs.
  It is not a broken write path and it will not fix itself by accumulating; installing
  and enabling the plugin on a host is the owner's act.
* **The promotion ceiling is split (owner ruling, 2026-10-08) and the miss side is
  armed (EM-306, `4a2b25e`).** `max_v3_only = 0` stays hard: a fabricated hit is a
  correctness failure. `max_v2_miss_rate` (ids v3 dropped / ids v2 injected) is
  `0.107143`, from the pre-registered holdout reference; the un-armed shape is still
  supported and tested (it reports the rate, gates nothing, and blocks `met`). The arming rule is pre-registered in code (`_shadow.MISS_CEILING_RULE`):
  v2's own miss rate against a held-out reference, `1 − recall@5` of the v2 adapter on
  **EM-306's holdout split** — so EM-306 is what arms it, and a synthetic sample must
  never be used. The rule's wording was corrected before any real turn (`de495f2`): the
  rate is **v3-vs-v2**, the bound is **v2-vs-truth** applied to it — a **policy choice,
  not an identity**. **EM-306 executed it (`4a2b25e`): armed at `0.107143`**
  (`evals/results/tune-hard-4eb8097.json`), with a test pinning the chain; the un-armed
  shape still exists and is tested. The retired symmetric rate is still
  reported as context, which is why
  the earlier 37.5% finding (150 misses, 0 additions) stays comparable: the same sample
  reads 38.46% id-level.
* **The privacy digest list is not at the default path on the dev box, but it is on this
  machine** — `~/Documents/EntropicMem Dev docs/privacy-digests.txt` (10 × 64-hex digests;
  format-checked only). Since 2026-10-08 the collision check has been run **in place** by
  pointing `ENTROPICMEM_PRIVACY_DIGESTS_FILE` at it: **7 passed** in
  `tests/evals/test_no_personal_data.py`, and the full suite then reads **2091/2/3**.
  Nothing is copied into the repo. With no list configured,
  `ENTROPICMEM_REQUIRE_PRIVACY_DIGESTS=1` **fails closed** (verified) — and the default run
  skips instead (the third skip in 2090/3/3).
* **Flipping P0b's flag default is one line, deliberately not flipped here.**
  `em/facade/engine.py`'s `v3_retrieval_enabled()` is the only reader in product code;
  the flip is `== "1"` → `!= "0"`, plus the tests and docs that pin default-off (the
  strictness test is meant to go red so the flip is a conscious act). Wiring the flag to
  a config key instead of an env var is EM-306/EM-407 work.
* **`gate.*`/`ranking.*` tuned defaults now exist in `em/config.py` (EM-306)** —
  committed but **unwired**: they reach call sites via the provider cards
  (EM-401–403), and the typed loader/schema is EM-407's. `extra_stopwords` remains
  EM-301's parameter.

### The v3 cutover — **both conditions met; the owner decides**

The owner deferred on 2026-10-07 with an explicit re-decision point: **reconsider when
(a) the provider reads through S3 and (b) the v3 adapter has produced one end-to-end
number — not before.** **(b)** was met by `ff0d3c3`; **(a)** is now met in code: P0a
(`f0a7c70`) reads S3 off the turn path over a copy, and P0b (`be6352e`) serves prefetch
from S3 on a v3 store behind `ENTROPICMEM_V3_RETRIEVAL`, measured at p95 9.32 ms
against the pre-declared 150 ms. **So the decision goes back to the owner, with P0c's
collected data as the evidence once it exists.** The objections still in force and to
be weighed: the CLI still refuses seven commands on v3, and the act is irreversible and
owner-present. **(The first objection as recorded — the live store holds zero facts, so
there is nothing to cut over — was corrected 2026-10-08: that measurement was the dev
box's store; the owner's live store on the Hermes host holds real data (≈1,700 facts,
owner-reported), so there is something to cut over.)** **The owner decides; the agent does
not.**

## Gates that must be green before anything reaches `main`

| Gate | Command | Budget |
|---|---|---|
| Tests | `python -m pytest -q` | **2226 passed / 5 skipped / 3 xfailed** |
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
**four times** — on 2026-10-07 at `f36c5e6` (Chunks 10.2/10.3), at `a70028a` (Chunk 11),
and at `d1060c1` (session close), each time on a **tests-only or docs-only** change. At `f36c5e6` the branch and local runs were both ~4–5 ms
p95, the `main` run came back **p95 69.392 ms with p50 4.544 and max 109.506**, and a
rerun of the *same SHA* returned **p95 5.388 ms (p50 3.437)**. At `a70028a` the failed
run was **p95 51.752 ms with p50 4.769 and max 96.29**; at `d1060c1` it was **p95
47.011 ms with p50 4.628 and max 81.13**, on a change that touches no production code.
The rerun of the *same SHA* was green every time, and the check-runs API is what
confirms it. The tell each time is the p50: a low p50 with a huge max is one noisy
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
