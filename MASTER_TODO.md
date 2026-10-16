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

**Last reconciled:** 2026-10-16, against branch `main` at `ae525b6` — the §11 drift-guard follow-up atop the caveat-audit follow-up on the
**branch-first landing of EM-412's query-embedding wiring** (`em-412-query-embedding`:
the query embedding is wired into the v3 read paths behind `embeddings.enabled` —
one fail-soft **`QueryEmbedder`** seam (`em/embeddings/query.py`) built lazily by
the provider only when the flag is on and the store is v3, wired at the tool search
path, `PrefetchService`'s async precompute half and the facade's flag-on
`recall_with_relevance` via `open_engine`; a raise, timeout or unavailable service
returns no vector — nothing propagates — and the caller serves the lexical result;
per-session counts with one summary line at `shutdown`; `initialize` queues the
model-switch `embed_backfill`; the vector readers count and debug-log rows skipped
for another model, `Retrieval.diagnostics` carries them, and the search payload adds
`diagnostics` only when non-empty; cosine stays off; flag-off and v2 paths
byte-identical; 15 new tests; **7 mutation checks all red**). The tree
was verified on this box (**bare
2629 / 16 / 3**; with the digest list **2630 / 15 / 3**; CI-equivalent 3.12
**2707 / 2 / 3**; `ruff==0.16.2` clean) and `main` fast-forwarded to that exact
SHA after **all 11 CI jobs were green on it**; the current tree's CI 3.12 count
is **2705 / 4 / 3** (read at `ae525b6`). Before it: **the branch-first landing of EM-410's cron & worker** (`em-410-cron-worker`:
`initialize` starts the background **`JobWorker`** on v3 stores — primary
sessions when `jobs.run_in_primary` (default true), cron when `jobs.run_in_cron`
(default true), bounded there by a `jobs.cron_budget_s` (default 120) timer
firing the worker's stop event, and none in subagent/flush — with the handler
set from the new shared builder **`em/jobs/registry.py`** (`KNOWN_JOB_TYPES` =
backup/link/embed/embed_backfill/retract_turns; the `worker run` CLI now
delegates to it, so the two workers cannot drift; the formation types stay
absent for EM-502), and **`JobWorker.run(…, gate=)`** holds off claiming while
the provider's shared `_prefetch_in_flight` event is raised — the whole
`prefetch()` call, cleared in a `finally` so a raising service clears it too,
re-checked every 50 ms; concurrency is 1 by construction (one daemon thread,
one job per claim — the card's `jobs.max_concurrent=1`); a missing store file
starts nothing and leaves the `_v3_store()` probe cache unpinned (the EM-405
probe hazard); `shutdown` stops the worker before any store it holds closes;
and cron's card promises are pinned: tool writes answer `writes_disabled` and
prefetch still serves; 17 new tests; **13 mutation checks all red**). Before it: **the
branch-first landing of EM-409's system prompt** (`em-409-system-prompt`: the
block now renders **Appendix D's policy text** word for word, with the
tool-name bullets conditional on the tools the provider actually registers —
the search-the-past bullet names whichever of `entropicmem_search` /
`entropicmem_timeline` is present and drops when neither is — and the owed
alias rewrite is done: `entropicmem_recall` / `entropicmem_query` are gone
from the prompt; the Core Memory pair now renders **within
`core.token_budget`** (§4.3, default 800 — the cap lives in
`_core_memory_block()`, so the system prompt, the legacy full-block prefetch
mode, the changed-core delta and its baseline hash all share it, and the
hardcoded `[:2800]` slice is gone); 8 new tests; **8 mutation checks all
red**). Before that: **the
branch-first landing of EM-408's `hermes entropicmem …` mount** (`em-408-cli`:
the shared argparse tree in `em/cli/parser.py`, the host mount in
`plugins/entropicmem/cli.py` parsing into `entropicmem_command` so the host's
`args.command` survives, and the top-level `stats` shortcut — documented count
35→36; 7 new tests; **7 mutation checks all red**). Before that: **the
branch-first landing of EM-411's window capture on idle, cadence and
compaction** (`em-411-capture`, then the same-day floor correction
`em-411-floor-correction`: a per-session window ledger persisted to the v3
`meta` on `window:<sid>`, and one `extract_window` job per sealed range under
the shared key `extract:window:{sid}:{start}-{end}` — the cadence flush, an
idle gap and the post-commit compaction seal all share it, so a recomputed
range or a retried compression collapses onto one queued row; the idle floor
per the card's letter — **at least 2 turns or 200 characters**, under both
nothing and still sealed; gated off — `formation.mode` ships `off` and
`em.jobs.BUILT_FORMATION_HANDLERS` is empty until EM-502 registers the
handler; 15 new tests; **13 mutation checks all red**). The branches are
deleted, and the remote
carries `main` and `release/2.8.x`. Before it: **the branch-first landing of the
EM-407 hardening pull: the owner's verification queue in four landed items**
(`em-407-hardening`: the 50k numpy AC guard now
reads the **best of five** 20-probe windows — the 2026-10-15 3.13-leg flap
(single-window p95 31.61 ms from one stalled window) is fixed by statistic, not
filed as a flake, and a real regression still fails every window; **`save_config`
validates every key before anything touches disk** — unknown keys refused, legacy
spellings folded as the loader folds them — writes through a per-call `mkstemp`
temp, keeps the destination's mode, cleans up on failure, and documents the
Windows locked-destination contract; **the spec/calibration default split is
pinned as deliberate** — the eval adapter's `None` default is the pipeline's spec
defaults, the provider ships EM-306's calibration (`w_rrf` 0.60→0.50,
`w_importance` 0.15→0.25; gate values identical) — the 77-test count gap is
per-module named, and the query-embedding card was approved the same day as
`EM-412`; 8 new tests), verified on this box at that SHA (bare
**2549 / 16 / 3**; digest list **2550 / 15 / 3**; CI's 3.12 count there
**2626 / 3 / 3**). Named deliberately instead of the docs tip
that follows it. Before it: **EM-407's typed config** (`2b21ad1`, the
branch-first landing that completed the card — Appendix A's typed model in
`em/config.py`, §3.8's loader, the typed schema/save pair, and EM-306's
calibrated scalars reaching the search tool, the `PrefetchService` and the v3
facade), the **EM-405 lifecycle slice** (`e483d43`, which completes that card),
the **EM-404 validation slice** (`5000942`, which completes that card), the
**slice-2 landing** (`e5e54ef`) and the **owner-chosen landing of slice 1**
(`381197f`, `3dcb35f` + `84a555f`; the records are in §5).

**Follow-up landing, 2026-10-16 (`56dc588`, branch-first, 11/11 check-runs green
on the exact SHA, on top of the docs record `a74707a`): the guard's drift
telemetry, the `EM-412` approval, and two watch items.** The 50k numpy guard now
emits **every window's p95** as a warning on every run — green included — so
drift that stays under the assertion is visible over time, and the **3.13 leg's
pass rate watched for 20 runs and closed green (20/20: `dc3c77a`,
`a74707a`, `56dc588`, `6e86c98`, `5cfe82a`, `f7950d3` ×2, `fe5e53b` ×2,
`59bde57`, `def39cc` ×2, `e89471b`, `a472748` ×2, `98a9f87`,
`874b3d4` ×2, `3fe3148` and `637a269` — every push since the watch began, branch and main runs alike; the
report was delivered 2026-10-16, and the landing's main run extends the standing
record)**. The query-embedding card, **approved as `EM-412`** the same day
in this tracker and **landed 2026-10-16 (`637a269`)**, carried the four owner edits: a per-call timeout with hard fail-soft to
lexical and a per-session embed-count log for the optional, possibly-paid
`openai_compat` backend; stale-model skips logged at debug and surfaced in the
search diagnostics; a fifth mutation (a raising embedder still returns the
lexical result; the exception never reaches the caller); and the EM id assigned
here. **Counts quoted in docs are read from the CI-equivalent 3.12 venv with
CI's extras and the digest list installed — not the bare box venv.**

**A second reconciliation pass on 2026-10-15 (docs only, no product change) re-read
all pages against the tree and corrected five stale classes:** the EM-404 slice-1
row (**its CHANGELOG line landed as `84a555f`**; the ff-only aborted because `main`
moved — the landing choice stays the owner's), the priority rows for EM-307 /
EM-303 / EM-401–403, the superseded-note gap (**the wired path does render it** —
the service feeds `retrieval.predecessors` into `load_pack_items`), the
`gate.*`/`ranking.*` expectation (**EM-401–403 landed without wiring them; EM-407
was the named owner — resolved 2026-10-15: EM-407 landed (`2b21ad1`), the
provider passes the typed `GateConfig`/`RankWeights` at every call site, and the
eval adapter's own defaults remain the spec — a split pinned as deliberate on
2026-10-16, `dc3c77a`**), and the finding this pass records
loudest: **the query
embedding is not wired — `ensure_embedding_model` has no caller outside
`em/embeddings/jobs.py`, the service is built with no `embed_query`, and the
served path passes no `query_vector`, so even the wired v3+flag path scores
lexical/entity/episodic; no remaining card owns it and it needs one.** Also
recorded: `_shadow.py`'s printed caveat still says "until EM-303" while the real
reason for its no-vectors line is the unwired embedding — a one-string follow-up,
recorded rather than fixed (docs-only pass). **Suite re-verified on this box:**
`ruff==0.16.2` clean; bare **2288 / 16 / 3**; with the digest list in place
**2289 / 15 / 3**; CI's own count at `a5b613a` re-read from the job log:
**2365 / 3 / 3**.

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

**EM-403's first two slices are merged, and the card's provider half is now
complete.** On a v3 store the provider builds the `PrefetchService` lazily (`None` on
v2), routes the **synchronous** fact block through `PrefetchService.prefetch()`, routes
`queue_prefetch` into its `precompute`, and surfaces the five `prefetch.*` metrics
through `metrics()` — both routed paths gated on `ENTROPICMEM_V3_RETRIEVAL=1` as well
as the v3 store, so the wiring stays dormant at the flag's default-off (the gate
decision and its reasons are recorded on `_prefetch_service_for_turn` and in
`NEXT_CHUNK.md` Part A). v2 stores are byte-identical by construction. The card's AC
is green **through the wired provider**: warm p95 40.58 ms @ 50k, cache-hit 0.09 ms,
forced-slow 1.261 s partial, 7,648 chars, 50-turn replay 5,504 ≤ 13,500 tokens.

**EM-407 landed (2026-10-15, `2b21ad1`) and seated the typed config under the
provider.** Appendix A's model and §3.8's loader are `em/config.py`'s; the typed
`get_config_schema()` and the `memory.entropicmem`-nesting `save_config` are
live; and **EM-306's calibrated `gate.*`/`ranking.*` scalars reach the call
sites** — the search tool, the `PrefetchService` and the v3 facade all pass
`retrieve(gate_config=, rank_weights=)`. The eval adapter's defaults remain the
spec (the CI eval gate stays v2 by EM-306's call) — a split pinned as deliberate
by the hardening pull.

**The EM-407 hardening pull landed (2026-10-16, `dc3c77a`).** The 50k numpy AC
guard now reads the **best of five** 20-probe windows (the 2026-10-15 3.13-leg
flap fixed by statistic; a real regression still fails every window);
`save_config` validates every input against the typed rules **before anything
touches disk** — unknown keys refused, legacy spellings folded as the loader
folds them — writes through a per-call `mkstemp` temp, preserves the
destination's mode, and cleans up on failure; and the spec/calibration split is
pinned by
`test_the_default_adapter_keeps_the_spec_and_the_runtime_ships_the_calibration`.
The counts reconcile per module (67 fastapi + 7 cryptography + 2 numpy + 1
privacy = the 77-passed gap; the commands sit in the pre-flight). The
query-embedding card **landed as `EM-412`** (`637a269`, 2026-10-16 — the note
below; the four owner edits rode it); **EM-410 has landed**
(`874b3d4` — the note below; EM-409, EM-408, EM-411 and EM-406 preceded it),
and **no chunk is queued** — the next piece is the owner's call (the
recorded-owed candidates: the prune follow-up, `_shadow.py`'s one-liner, the
adapter/eval gate).

**EM-410 landed (2026-10-16, `874b3d4`), completing the cron & worker card.**
`initialize` now starts the background **`JobWorker`** on v3 stores — primary
sessions when `jobs.run_in_primary` (default true), cron when `jobs.run_in_cron`
(default true, bounded by a `jobs.cron_budget_s` (default 120) timer firing the
worker's stop event), none in subagent/flush — through the host's
`spawn_context_thread` (the provider's `_spawn`). The handler set comes from the
new shared builder **`em/jobs/registry.py`** (`KNOWN_JOB_TYPES` =
backup/link/embed/embed_backfill/retract_turns; `build_registry(db_path, *,
types=None)`), and `entropicmem worker run` now delegates to it, so the CLI
worker and the in-process worker cannot drift on the set; the formation types
stay absent while `BUILT_FORMATION_HANDLERS` ships empty for EM-502. **Low
priority, one at a time:** concurrency is 1 by construction — one daemon thread
per provider, one job per claim (the card's `jobs.max_concurrent=1`) — and
`JobWorker.run` gains a **gate**: while the provider's shared
`_prefetch_in_flight` `threading.Event` is raised, the worker holds off
claiming, so background work never competes with a live turn's retrieval. The
gate is raised for the whole `prefetch()` call and cleared in a `finally`, so a
raising service clears it too; the gated loop re-checks every 50 ms, and a job
already running is never interrupted. **First-run safety:** a missing store
file starts nothing *and* leaves the `_v3_store()` probe cache untouched —
probing a not-yet-created file would create it, read version 0 and pin the
whole session to the v2 path (the same reasoning as EM-405's
`_restore_turn_index`) — pinned both ways. `shutdown` stops the worker before
any store it holds closes (bounded 3 s wait), cancels the cron timer, and
closes the worker's own store; a worker that cannot start is a debug line,
never an `initialize` failure. Cron's other card promises were shipped
behaviour and are now pinned: tool writes answer `writes_disabled` with no row
written, and prefetch still serves. 17 new tests
(`tests/unit/test_em410_cron_worker.py` — 15 — plus the two gate-loop tests in
`test_em_jobs.py`); **13 mutation checks all red**; suite **2608 / 16 / 3**
bare, **2609 / 15 / 3** with the digest list, **2686 / 2 / 3** CI-equivalent
3.12; CI **2684 / 4 / 3**; `ruff==0.16.2` clean. **Recorded as still owed:**
the embedding-maintenance prune the EM-303 observability pass promised to
EM-410 ("the prune runs as a job under EM-410's maintenance pass":
non-current-model vector rows pruned after a completed backfill for the
current model plus a 7-day grace, then vacuum) — the master-plan card's
Spec/AC carry no prune, so it did not ride this landing — **drafted** as `docs/plan/PRUNE_CARD_DRAFT.md` for the owner's slotting decision (fold into the cutover or its own card). The record is in §5, START HERE and `NEXT_CHUNK.md` Part A.

**EM-409 landed (2026-10-16, `a472748`), completing the system-prompt card.**
`system_prompt_block()` no longer opens with the ad-hoc `# EntropicMem (active)`
base: it renders **Appendix D's policy text** (§4.5) word for word — the plan's
mid-sentence wraps as single-line bullets — and **the tool-name bullets are
conditional** (Appendix D's own note, the card's "phrase conditionally"): the
remember and update bullets follow their tools, and the search-the-past bullet
names whichever of `entropicmem_search` / `entropicmem_timeline` is present and
drops entirely when neither is, so the prompt can never advertise an absent
tool. The owed alias rewrite is done: the prompt names the new nine and no
longer mentions `entropicmem_recall` / `entropicmem_query` (the aliases
themselves still route for one minor version). The Core Memory pair (still
screened for injection first) is rendered **within `core.token_budget`** (§4.3,
default 800; `budget × 4` characters against §3.6's `ceil(len/4)` estimator),
and the cap lives in `_core_memory_block()` so every path that injects core —
the system prompt, the legacy full-block prefetch mode, the changed-core delta
and its baseline hash — is bounded by the one budget; the hardcoded `[:2800]`
character slice is gone. The skill-not-installed fallback and the
host-withholds-the-toolset behaviour are unchanged (the latter is host-side).
8 new tests (`tests/unit/test_em409_system_prompt.py`: the full-block snapshot,
policy alone with core off, the AC's token count — policy ≤ 350, core ≤
budget, total ≤ 350 + budget — a custom budget respected, the four conditional
cases, the legacy names gone); **8 mutation checks all red**; three deliberate
repoints, each the changed surface's own claim (`test_core_inject`'s cap test
now drives `core.token_budget`; the two byte-identity goldens repoint their
`system_prompt` field only). The record is in §5, START HERE and
`NEXT_CHUNK.md` Part A.

**EM-408 landed (2026-10-16, `def39cc`), completing the `hermes entropicmem …`
CLI card.** The argparse tree is one shared builder (`em/cli/parser.py`:
`add_commands(parser, *, dest="command")` + `build_parser()` — argparse-only, so
`--help` stays the stdlib-only contract) that the standalone
`scripts/entropicmem.py` and the new `plugins/entropicmem/cli.py` both mount —
the latter with the host's verified convention (`register_cli(subparser)` +
`entropicmem_command(args)`, discovered by `plugins.memory` only while
`memory.provider: entropicmem`). The mount parses into
`dest="entropicmem_command"` so the host's own `args.command` survives (read
after parsing by `set_process_surface` and the startup gates); the standalone
CLI keeps `command`. The shared tree gains the **top-level `stats`** shortcut
(the `memory stats` handler) — the card AC's `hermes entropicmem stats` — and
the documented command count moves 35→36 (README + CLI reference, both
guard-checked). 7 new tests; **7 mutation checks all red** (register_cli
renamed; the mount dest clobbered; the stats parser dropped; its default
dropped; `add_commands` ignoring its dest; the unknown-command rc zeroed; the
stats route dropped); two repoints recorded (the recall-parser scan reads the
new file; `pyproject.toml` gains `em.cli`). The record is in §5, START HERE and
`NEXT_CHUNK.md` Part A.

**EM-411 landed (2026-10-16, `fe5e53b`), completing the capture card.**
The provider keeps a per-session window ledger (v3 `meta`, `window:<sid>`) and
enqueues one `extract_window` job per sealed transcript range under the shared
dedupe key `extract:window:{sid}:{start}-{end}` — the cadence flush, an idle
gap (`formation.idle_after_sec`, 900 s) and the post-commit compaction seal in
`on_pre_compress` all share it, so a recomputed range or a retried compression
collapses onto one queued row. The idle floor reads the card's letter: a window
enqueues when it holds **at least 2 turns or 200 characters**; under both it
enqueues nothing and is still sealed; a turn is one `sync_turn` with content.
**Gated off**: `formation.mode` ships `off` and
`em.jobs.BUILT_FORMATION_HANDLERS` is empty — the enqueues are inert until
EM-502 registers the handler and its caps decide the flip. 15 new tests;
**13 mutation checks all red**; one same-day correction (the floor's first cut
was inverted; `fe5e53b`) and one flap (the Windows rewind-budget 0.250 s;
rerun green) recorded. The record is in §5, START HERE and `NEXT_CHUNK.md`
Part A.

**EM-406 landed (2026-10-16, `6e86c98`), completing the checkpoint-v2 card.**
`on_pre_compress` on a v3 store archives the evidence and returns the handoff in
one transaction: every user/assistant message into content-addressed
`transcript_chunks` (`source='precompress'`), plus one fingerprint-keyed
`precompress` episode carrying the deterministic handoff
(`session_digest.build_handoff`: constraints / decisions / open loops /
in-scope pins, ≤ 1,500 chars, no LLM) — a retried compression converges onto its
window, an empty handoff still persists the evidence, and a failure raises under
`require_checkpoint=True` and otherwise logs + returns `""`. The facade's new
`archive_pre_compress` and `pinned_constraints` (the §3.5-scoped pin read) are
bindable on both engines and **raise on v2**; v2 stores stay byte-for-byte
unchanged. 12 new tests; **10 mutation checks all red**; the record is in §5,
START HERE and `NEXT_CHUNK.md` Part A.

> **Live retrieval is lexical. Semantic retrieval is not shipped.** The EM-303
> stack (backends, jobs, cache, cosine gate, MMR) is merged and measured, but
> the provider does not produce a query embedding yet. **EM-401–403 are all
> complete and none of them wired it** (`ensure_embedding_model` has no caller
> outside `em/embeddings/jobs.py`; `_ensure_prefetch_service` builds the
> service with no `embed_query`; `prefetch`/`queue_prefetch` pass no query
> vector), so **even the wired v3+flag path scored lexical, entity and
> episodic only — until EM-412 wired all three (`637a269`, 2026-10-16)**, behind
> `embeddings.enabled` and hard fail-soft (a box with no backend still serves
> lexical). Do not describe
> semantic retrieval as shipped, and do not quote vector eval numbers without
> their `retrieval_mode` label (vector runs are comparable only to vector
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

What `em/` contains today: `em.clock` (freezable UTC, ULIDs), `em.config`
(EM-306's calibrated scalars inside EM-407's typed model, the `RULES` table and
§3.8's `load_config`), `em.store`
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
| 22 | **EM-307 — packer, renderer, and retrieval wiring** | **Done, merged** (`7d6a22e`, ff from `a674383`; library `6cd0943`). A gated retrieval renders. **The eval adapter and the provider still do not call it** — deliberately, and pinned *(true at this chunk; chunk 35 later routed the provider's served block through the service's `pack_chosen`/`render` — the eval adapter still does not, 2026-10-15)* |
| 23 | **EM-303, first slice — search stored embeddings** | **Done, merged** (`7d6a22e`, ff from `9d5a72b`). Cosine + the `vector` generator behind `retrieve()`'s query-vector seam and the 50% coverage gate. **No embedder, no numpy cache; the default call is unchanged** |
| 24 | **EM-303 — MMR's embedding path** | **Done, merged** (`000a268`, ff from `156370e`). `diversity.mmr` takes an optional pairwise similarity; the pipeline supplies cosine when a query vector and model were given (clamped at 0), Jaccard otherwise. **Default path unchanged** |
| 25 | **EM-303 closed — backends, `embed`/`embed_backfill`, model identity, vector cache** | **Done, merged** (`3439b77`, ff from `e8997d8`). Four backends + auto/none selection; jobs with a write-time version recheck and `meta.embedding_model`; a numpy/pure-Python snapshot cache behind migration 0005 (50k p95 **3.86 ms**) |
| 26 | **The EM-303 follow-ups: episode embeddings, query embeddings in evals, numpy in CI** | **Done, merged** (`42e16c7`, ff from `51cdcb3`). `EpisodeStore` enqueues `embed` jobs; the backfill and handler cover episodes; the v3 eval adapter embeds documents and the query when `disable_embeddings=False`; CI installs numpy so the cache tests and the 50k AC run there. **The capture-on-idle/compaction feature is planned as EM-411** (plan §6.3) |
| 27 | **EM-303 precision — version-checked vector reads, episode read path, retrieval-mode labels** | **Done, merged** (`6d9bf3b`). Memory `content_hash` and episode `updated_at` are verified on every read; reads filter to the query width; `candidates.episodic` reads episode vectors into EM-307's renderer; backfill idempotence/resume is pinned; every eval report labels lexical vs vector, cross-mode compare is context only, baselines labelled |
| 28 | **EM-303 observability, promotion evidence, model-switch hygiene** | **Done, merged** (`60f0d67`, ff from `514a6a5`). Per-query coverage/stale logging + stale→re-embed round trips; the CI numpy guard; explicit `--embeddings` and committed **vector-mode baselines** (hard 0.988, ageing 1.000 vs lexical 0.933/0.733) with the recommended promotion gate; old-model storage measured (21 MB/10k/set) and prune policy decided; checksum replay oracle; EM-411 test-first briefs |
| 29 | **EM-401 slice 1 — the §4.1 hook skeleton and the pinned host contract** | **Done, merged** (`f8af1a9` as `db7c24f`, ff). `fail_soft` wraps every hook (timed, counted, over-budget at WARNING, exceptions swallowed with the type only) and is **fail-closed** on `on_pre_compress`/`initialize`/`save_config`/`backup_paths`; `ProviderState` holds the session-scoped fields; `em/provider/provider.py` is the §4.1 surface table with `on_delegation`→EM-405 and `identity_signature`→EM-402 deferred by name; the contract test enumerates `MemoryProvider` from the pinned hermes-agent (`tests/harness/pinned_memory_provider.json`, re-derived against the real host when reachable); the harness drives every §4.1 hook and proves from the metrics that each ran and none failed. The class itself stays in `plugins/entropicmem/__init__.py` — the move is the next slice |

| 30 | **`save_config` blank-home fix + the two hygiene corrections the EM-401 run surfaced** | **Done, merged** (`6646351`). `save_config(values, "")` resolved `Path("")` to `Path(".")` and merged `plugins.entropicmem` into the CWD's `config.yaml`, rewriting that file; it now refuses a blank home and raises (the fail-closed shape §4.1 asks for; the host always passes `str(get_hermes_home())`, so this is defence in depth). `.gitignore` covers `uv*.lock` so `git add -A` cannot sweep a stray lock file in again. `AGENTS.md`'s mutation rule records that a mutation must be restored from a **copy**, never `git checkout -- <file>`. 2 new tests; **2223 / 5 / 3** bare and **2225 / 3 / 3** with numpy on 3.10 and 3.12; ruff clean; 3 mutation checks red |
| 31 | **EM-401 slice 2 — the provider moves into `em/provider/provider.py`** | **Done, merged** (`b8e170a`). `plugins/entropicmem/__init__.py` is a **145-line** host shell: `register` + a `MemoryProvider` subclass over `_HermesHost`, which injects the path/config resolvers, the P0a shadow read, the context-propagating thread factory, the host's bounded tool-error formatter and `RecallStatus`. `em/provider/provider.py` holds `EntropicMemProvider` (the whole provider; EM-404 later splits `tools.py`) plus the `ProviderHost` ABC. `em` imports no host and no plugin package — an AST guard pins that, another pins the 150-line shell. Six source-scanning guards now read the implementation. 3 new tests; **2226 / 5 / 3** bare and **2228 / 3 / 3** with numpy on 3.10 and 3.12; ruff clean; 8 mutation checks red |
| 32 | **EM-402 — ScopeContext & identity (§3.5 scoping per turn)** | **Done, merged** (`7104bed` + docs `618c180` + the windows fix `2706a86`, ff-merged to `main` as `2706a86`; all 22 check-runs green on that SHA). `em/policy/scopes.py` resolves one `ScopeContext` from the init kwargs + config (`scope_mode`; EM-118's owner rule unchanged; `with_author` re-buckets per turn; bot authors never create user-scoped memories; `scope_key` for caches); the provider opens every engine under `to_scope()`/`write_scope()` — all reads/writes through one seam; `open_engine`/`V3Engine` accept the resolved `Scope`; the prefetch cache keys on `scope_key` + query (the cross-author block-replay leak is closed); `identity_signature()` lands (config-file only, mtime-cached, uninitialized-safe) and `HOOK_SURFACE`'s deferred set shrinks to `on_delegation`. **AC:** the group-chat harness (3 authors + bot) proves attribution and no cross-author leak including through the cache; the `multi_user` eval category reads **1.0** on its own isolation surface (`evals/datasets_multi_user/`, `as_user` turns; baseline `v3-multi-user.json`) — the frozen hard suite is byte-identical and its multi_user stays 0.90 lexical / 0.933 vector as recorded evidence (owner's isolation reading, 2026-10-13). 53 new tests; **2279 / 5 / 3** bare, **2281 / 3 / 3** with numpy, **2282 / 2 / 3** with the digest list; ruff clean; 21 mutation checks red |
| 33 | **EM-403 slice 1 — `PrefetchService`, §4.2's synchronous core** | **Done, merged** (code `fde8f36` + docs `9f9ba0c`, ff-merged to `main` as `9f9ba0c`; all 22 check-runs green on that SHA). `em/provider/prefetch_service.py` (new) serves one turn per §4.2: the cache keyed `(session_id, scope_key, sha1(query), write_generation)` (in-process counter + the persistent read connection's `PRAGMA data_version` — measured: that pragma is per-connection, so the read connection must live across calls), the deadline with §4.2's generator priority order and `Retrieval.partial`, the per-generator **watchdog** on the service's one worker thread (a stuck generator is abandoned, so the 1.5 s hard cap holds for any generator; busy worker ⇒ fail-fast `partial`), §4.2's dedup rule exactly (6-turn window; score ≥ 0.8 re-shows after > 2 turns; pinned rows every 10), the `min(token_budget*4, 9000)` char cap, and the five `prefetch.*` metrics with a latency distribution. Also lands §3.6's IDF cache (`VocabularyCache`, keyed by `write_generation` — the recorded EM-301 gap) and `bm25`'s single bounded query (its paged form re-scored every FTS match per page: 78 ms vs 20 ms at 50k). **Nothing called the service when this chunk landed** — the wiring is slice 3, whose first half (`f674146`) is now on `main` (see below). **AC green (harness):** forced-slow generator 1.26 s partial; ≤ 9,000 chars; 50 turns replay 5,536 ≤ 13,500 tokens; cache-hit p95 0.04 ms; warm p95 **43 ms @ 50k**. 39 new tests; **2318 / 5 / 3** bare, **2320 / 3 / 3** with numpy, **2321 / 2 / 3** with the digest list; ruff clean; 29 mutation checks red |
| 34 | **EM-403 slice 2 — `PrefetchService`'s async half** | **Done, merged** (code `8b30aa9`, lint `31053df` on branch `em-403-prefetch-async`; ff-merged to `main` as `31053df`; docs `007bb22`; **11/11 check-runs green on each exact SHA, `identity-guard` included**). `precompute` builds the candidate pool (pipeline top rows as `PackItem`s, `CANDIDATE_POOL_SIZE` 60) cached by `(session_id, scope_key)`; the coalescing worker queue (`queue.Queue(maxsize=8)`, newest-per-session identity supersede, oldest-drop on full, all counted) runs it off the prefetch path on one daemon thread through the `spawn_thread` seam; session topic state (rolling 5-turn entity window + α=0.5 EMA) feeds the configurable `TOPIC_ENTITY_BONUS` (0.05) soft signal — zero with no topic, never in the query text; **the query embedding is computed in `precompute` on the worker, never on the agent/prefetch thread and never when one was supplied**; `close()` joins worker/queue threads with a 2.0 s timeout and counts expired joins. 22 new tests (slice-2 pair + isolation/invariants); the suite then read **2343 / 3 / 3** on 3.12 at the merge (CI at the later `3dcb35f`: **2347 / 3 / 3**); ruff clean |
| 35 | **EM-403 slice 3, second half — the provider's sync fact block routes through the service** | **Done, merged** (code `a5b613a` + docs on branch `em-403-slice3-wiring`, ff; **11/11 check-runs green on the exact SHA, `identity-guard` included**). `prefetch()` serves the fact block from `PrefetchService.prefetch()` when the gate says so — **v3 store AND `ENTROPICMEM_V3_RETRIEVAL=1`** (the gate decision, with reasons, is written on `_prefetch_service_for_turn`; the brief named the v3 store alone). **v2 byte-identical by construction** (the service is `None` there; golden captured from `e4fd865` in a detached worktree, flag ON); flag-off v3 keeps the old path (P0b's off shape); a service failure falls back to the v2 path; `queue_prefetch` shares the one gate. `_turn_scope()` hands the service the **effective** scope (profile from `_profile_id or "default"` — the service reads the store directly, so a raw `to_scope()` would query the wrong profile). **A defect the wiring's shutdown test found and this chunk fixed:** `close()` joined the worker before posting its `None` sentinel, so every v3 session end paid the 2 s join timeout (measured 2011 ms) with a warning — sentinel first now, stuck generators still counted+logged. Recorded gaps on the wired path: no `touch_on_inject` bump, no v2 dedup window, no config-level source/domain filters (store-level §3.5 scoping still applies — pinned by a two-author isolation test). **P0b's flag-on test was rewritten deliberately** (its interim contract is superseded; the off-path tests are unchanged). AC re-run through the wired provider: forced-slow **1.261 s**; **7,648** chars; 50-turn replay **5,504** ≤ 13,500; cache-hit **p95 0.09 ms**; warm **p95 40.58 ms @ 50k**. 18 new tests; suite **2288 / 16 / 3** bare on 3.11, CI **2365 / 3 / 3**; ruff clean; **7 mutation checks, all red** |

**EM-404 slice 1 is on `main` without a chunk number — recorded here so it is
neither forgotten nor mistaken for its card's whole.** `381197f` is the ff of
`3dcb35f` + `84a555f` (the owner chose merging `main` into the branch, 2026-10-15;
the only conflict, `CHANGELOG.md`, kept both entry sets verbatim). The seven
tool-schema constants move **verbatim** into `em/provider/tools.py` and are
re-exported, so `get_tool_schemas()`/`handle_tool_call()` keep their signatures and
behaviour is unchanged; `provider.py` slims by 105 lines; a new empty `em/util`
package is declared in `pyproject.toml` (nothing imports it yet — **not** slice 2's
home: that slice landed in `em/provider/tools.py`; `em/util` waits for the card's
validation work — recorded 2026-10-15; **fulfilled: the validation slice landed
`em/util/jsonschema_lite.py` at `5000942`**). The branch was deleted and PR #8 is
merged at the same SHA.

**EM-404 slice 2 is on `main` without a chunk number either — the handlers move,
and the card still has a remainder.** `e5e54ef` carries `get_tool_schemas`,
`handle_tool_call` (with its `fail_soft(fallback=_tool_call_failed)` belt) and the
seven handler bodies moved **verbatim** onto the new `ToolHandlers` mixin in
`em/provider/tools.py`; `INJECTION_WARNING`, `_tool_call_failed` and
`_screen_for_injection` moved with them (the provider imports the screen function
back — one implementation, pinned by identity), and the plugin shell imports the
marker from its new home. `provider.py` slims by 343 lines (2240 → 1897). 5 new
tests; suite **2293 / 16 / 3** bare (was 2288 / 16 / 3); 9 mutation checks, all
red, each restored from a copy. **The card's behavioural Spec/AC is not in these
slices — it is the validation slice, next:** argument validation with helpful
errors (`em/util/jsonschema_lite.py`), the legacy-name alias map, `forget`'s
confirmation-token flow, `search`'s `ids`/`kinds`/`sources`/`time_range`/
`include_history`/`limit` fields, and `reason_code: writes_disabled` (the current
code returns a message string). **Fulfilled — the validation slice landed as
`5000942`; its record follows.**

**EM-404's validation slice landed on `main` without a chunk number either — and it
completes the card.** `5000942` carries `em/provider/tools.py` rewritten to
Appendix B's nine tools
(`remember`/`search`/`update`/`forget`/`timeline`/`entity`/`profile`/`review`/
`stats`), `em/util/jsonschema_lite.py` (types and enums fatal with field-naming
messages; `maxLength`/`maxItems` capped; numeric bounds clamped; unknown args
dropped with a warning; JSON `null` read as "not provided"; bools never integers),
`LEGACY_ALIASES` (the five legacy names route for one minor version; every response,
errors included, carries `"deprecated_tool"`), the write gate (`reason_code:
writes_disabled` in non-primary contexts — the code returns the reason now, not a
message string), `forget`'s single-use `sha1(ids+session)[:10]` token (5 minutes;
the query preview lists candidates, applying forgets by id) and `search`'s four
sources (`memories|episodes|notes|shared`, including the composed-note and
shared-fact paths). 176 new tests (22 / 107 / 47); suite **2469 / 16 / 3** bare (was
2293 / 16 / 3) and **2470 / 15 / 3** with the digest list in place; `ruff==0.16.2`
clean; **17 of 18 mutation checks red**, each restored from a copy — the one
survivor (the query path's deleted-row filter, kept as the ranking→read race guard)
is recorded in the CHANGELOG, and the reachable ids path is pinned by
`test_forget_by_id_marks_deleted`. Deliberate contract updates to six existing test
files and `plugin.yaml` (`provides_tools` 7 → 9); `em/facade/contract.py`'s table
grew six recorded calls. **Two gaps recorded, not hidden:** the provider's system
prompt still names the legacy aliases (they route for one minor version; the
rewrite of that block is owed and **EM-409, System prompt: policy + core, is the
natural home**), and `allow_agent_consolidate`'s config-schema description still
says the tool can archive — it can only preview now — **fixed on EM-405's branch
(`e483d43`), whose record follows.**

**EM-405's lifecycle slice landed on `main` as `e483d43` — branch-first, and it
completes the card.** `em/provider/provider.py` implements `on_delegation`: one
redacted `delegation` episode (task ≤ 500 characters, result ≤ 1500; redaction
runs before the cap, so a truncated secret cannot slip past the detector) through
the facade's `add_episode`, which now takes an explicit `kind` for the episode
vocabulary; on a v3 store the hook then enqueues one `extract_session` job
(`source=extracted_llm`, `confidence_cap` 0.6), and the extraction handler itself
is the extraction card's. `HOOK_SURFACE`'s `on_delegation` row flips from
deferred to implemented and `plugin.yaml`'s `provides_hooks` grows **5 → 6**
(the dev-line manifest treatment EM-404 gave `provides_tools`; the catalog
re-pin stays release business). The rewound `on_session_switch` **only enqueues**
(30 ms budget): one `retract_turns` job (`{session_id, from_turn}`) and the
counter steps back one, so repeated `/undo` walks turn by turn. The new handler
(`em/store/retract.py`) runs `MemoryStore.retract_session`: the undone session's
live, turn-stamped rows (`source_turn >= from_turn`) go to `deleted` as
`retracted_by_undo`, audited and versioned on the existing edge; pending
candidates keep their TTL path; unstamped rows are not attributable; a malformed
payload is permanent (dead, never retried). The turn index is provider-owned:
`ProviderState.turn_index`/`turn_index_session`, bumped in `on_turn_start` and
persisted on v3 stores to `meta['turn_index:<sid>']`; `initialize` and session
switches restore it fail-soft through a read-only probe that deliberately
bypasses the per-instance `_v3_store()` cache (a probe before the store file
exists must not pin a session to the v2 path); v2 keeps the counter in memory and
its schema gains nothing. Writes are stamped with `source_turn` on the tool path
and on the facade's extraction quarantine, captured at `sync_turn` call time so
the background thread cannot pick up the next turn's number. `set_status` gains
the one reversal of a terminal status: `deleted → active` only when the row's
**latest** deletion record is `retracted_by_undo` and the reason is `restore` —
`LEGAL_TRANSITIONS` keeps `deleted` terminal, still pinned at
`tests/test_em_memories.py:260`; a forget stays terminal before and after a
retraction, and `review`'s `restore` can bring a retraction back. `shutdown`
checkpoints the WAL (`PRAGMA wal_checkpoint(PASSIVE)`) before closing the
prefetch store and stays within 2 s with a precompute in flight. Deliberate
contract updates, each at the changed surface's own claim: the facade contract
table records `kind`/`source_turn` — one call shape reaches both engines, and the
v2 engine accepts-and-ignores both (its episodes table has no kind column, its
rows no turn) — the harness drives `on_delegation` directly,
`test_audit_reports_a_real_problem` plants a deferred row now that the deferred
set is empty, `test_plugin_hardening`'s hook list gains `on_delegation`, and the
dead `allow_agent_consolidate` description now says what the tool is. 23 new
tests (`tests/unit/test_em405_retract.py`, `tests/unit/test_em405_lifecycle.py`);
suite **2492 / 16 / 3** bare (was 2469 / 16 / 3) and **2493 / 15 / 3** with the
digest list in place; `ruff==0.16.2` clean; **23 of 23 mutation checks red**,
each restored from a byte copy.

**EM-407's typed config landed on `main` as `2b21ad1` — branch-first (two
commits: `0f38fbf` the card, `2b21ad1` the windows-import test gate), and it
completes the card.** `em/config.py` grows from EM-306's scalar block into
Appendix A's **typed model**: sixteen dataclasses (the fourteen sections plus
`entities` and the root `timezone`), one frozen `Rule` per typed leaf (kind,
label, description, choices, minimum/maximum — kinds `text`, `select`, `bool`,
`integer`, `number`, `string_list`, `float_map`), `iter_leaf_keys()`, and a
bidirectional test that walks model and rules together. `load_config(sources=(),
*, overrides=None)` is §3.8's order exactly — defaults → the host's merged view
(`plugins.entropicmem` flat plus the preferred nested `memory.entropicmem`,
nested winning inside the source) → `$HERMES_HOME/entropicmem/config.json` (the
dashboard's `flat_json`) → `ENTROPICMEM_*` **paths only** → constructor
overrides — flattening nested sections to dotted keys; the one mapping leaf
(`gate.min_cosine`) stays whole, and the nine `LEGACY_KEY_MAP` entries (including
`prefetch_token_budget → prefetch.token_budget`, chars ÷ 4 clamped
`max(100, min(2000, …))`) apply before direct keys, so a nested/dotted spelling
beats a flat one inside a source. Invalid values are **collected, never raised**:
`ConfigError(key, value, message)` on `ConfigLoad.errors`, the default (or the
last valid value) standing, the list logged **once** at `initialize` ("config
value(s) rejected") and kept on the provider for the future `doctor`. The
gate/ranking defaults stay EM-306's calibrated pair — `0.30`/`0.34` and
`0.50/0.25/0.10/0.10/0.05`, not Appendix A's spec table — and `gate.min_cosine`
is a duplicated literal pinned equal to `GATE_MIN_COSINE` (stdlib-only, no
import). `get_config_schema()` renders the curated **24 dotted keys** with
`type`/`choices`/`minimum`/`maximum`/`default`, and there is deliberately **no
`post_setup`** (it would replace the host wizard and skip saving
`memory.provider`). `save_config` nests dotted keys into `memory.entropicmem`,
leaves every other section and plugin untouched, and writes atomically
(`.yaml.tmp` + replace); a write failure raises — the host sees a failed setup
(the hook is fail-closed, pinned). `plugins/entropicmem/config_schema.py` (new)
declares the dashboard's `flat_json` entry importing only
`plugins.memory.config_schema` (AST-pinned), defaults as literal strings
mirroring the model. **The point of the card:** the tuned scalars reach the
pipeline's `retrieve(gate_config=, rank_weights=)` seam — `initialize` builds one
`GateConfig`/`RankWeights` from the typed config (the paths overlay feeds
`resolve_paths`; the embeddings switch reads the typed key) and the search tool,
the `PrefetchService` (constructor and `_retrieval_kwargs`; both retrieve calls)
and the v3 facade (`V3Engine`/`open_engine` accept and forward; v2
accepts-and-ignores) all pass them. `cmd_init` prints the hourly cron line.
Deliberate contract updates, each at the changed surface's own claim: the schema
pin renamed and re-based on the typed model's defaults, the save drive switched
to a dotted key, and the EM-403 wired AC's comment records the clamp;
`tests/harness/pinned_memory_provider.json` is unchanged (the host contract did
not move). 49 new tests (`tests/unit/test_em407_config.py` 30,
`tests/unit/test_em407_wiring.py` 19); suite **2541 / 16 / 3** bare (was
2492 / 16 / 3) and **2542 / 15 / 3** with the digest list in place;
`ruff==0.16.2` clean; **16 of 16 mutation checks red**, each restored from a
byte copy. The first CI round on `0f38fbf` was **10/11**: `windows-import` runs
`tests/unit` with pytest alone (no PyYAML), where six of the new wiring tests
read or write `config.yaml` — they now carry the same `needs_yaml` marker the
identity tests use (`2b21ad1`: 13 passed / 6 skipped there), and the second
round was **11/11**.

**EM-403 slice 3's first half is on `main` without a chunk number — recorded here so
it is neither forgotten nor mistaken for the whole card.** `f674146` (code, +90 lines
in `em/provider/provider.py`) and `55f85ce` (its docs note) were committed onto `main`
and pushed **directly to `origin/main`**: CI ran after the push and was green on both
exact SHAs (`identity-guard` included), nothing red ever landed, and published history
is untouched — but the branch-first workflow was not followed for those two commits.
What it does: on a v3 store the provider lazily builds the `PrefetchService`
(`_ensure_prefetch_service` — `Store.reader`'s persistent connection, provider `_spawn`
seam, `prefetch_token_budget // 4 or 450` tokens, `prefetch_max_latency_ms` 1200
default; `None` on a v2 store), routes `queue_prefetch` into
`service.queue_precompute` **gated on `ENTROPICMEM_V3_RETRIEVAL=1` as well as the v3
store** (the brief named the v3 store alone — a recorded, conservative deviation that
keeps the enqueue dormant at the flag's default-off), and surfaces the five
`prefetch.*` metrics through `metrics()` as `PrefetchMetrics.snapshot()`'s keys;
shutdown closes service and store. What it does **not** do: the synchronous
`prefetch()`'s fact block still renders through the existing path on every store
(the P0b byte-identity golden is the reason), and it shipped **no tests, no CHANGELOG
line (backfilled in this reconciliation), and no AC re-run through the wired
provider**. The second half — route the sync fact block, wire-level tests, AC re-run —
**landed as chunk 35** (the ledger row above).
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

**Nothing — EM-412's query-embedding wiring landed on `main` as `637a269` by the
branch-first path (`30bcba5` tests + `2fce569` implementation + `637a269`
CHANGELOG; pushed, all 11 CI jobs green on the exact SHA, then
`git merge --ff-only`; the branch is deleted).** The tree was verified on this
box (bare **2623 / 16 / 3**; digest-list **2624 / 15 / 3**; CI-equivalent 3.12
**2701 / 2 / 3**; `ruff==0.16.2` clean). Its record is in §5, START HERE, and
the note above. **No chunk is queued** — the S4 sequence the owner set is
complete (EM-406 → EM-411 → EM-408 → EM-409 → EM-410 → EM-412) and the
recorded-owed candidates are the EM-303 prune follow-up (drafted in
`docs/plan/PRUNE_CARD_DRAFT.md`), `_shadow.py`'s printed-caveat one-liner
(fixed in `26265ef`) and the adapter/eval gate (rides the cutover). P0c's
data still waits on the owner's host.**

**`main` carries the chunk-35 merge (`a5b613a` + docs; 11/11 green on the code SHA)
and, on top, the EM-404 landings — slice 1 (`381197f`), slice 2 (`e5e54ef`) and the
validation slice (`5000942`) — then the EM-405 lifecycle slice (`e483d43`), the
EM-407 pair (`2b21ad1` typed config, `dc3c77a` hardening pull), the
guard-visibility follow-up (`56dc588`) and EM-406 (`6e86c98`; §5 has all the
records).** Chunks 33,
34 and the whole of EM-403 slice 3 are on it: on a v3 store the
provider builds the `PrefetchService` lazily, serves the **synchronous** fact block
through `PrefetchService.prefetch()`, enqueues `queue_prefetch` into `precompute`, and
surfaces the five `prefetch.*` metrics — all gated on `ENTROPICMEM_V3_RETRIEVAL=1` as
well as the v3 store (the gate decision and its reasons are in the ledger row and in
`NEXT_CHUNK.md` Part A), so the wiring is dormant at the flag's default-off. v2 stores
are byte-identical by construction (golden captured from `e4fd865` in a detached
worktree), a service failure falls back to the v2 path, and shutdown closes service and
store. Recorded gaps on the wired path: no `touch_on_inject` bump, no v2 dedup window,
no config-level source/domain filters (store-level §3.5 scoping still applies — pinned
by a two-author isolation test). The card's AC is green through the wired provider
(warm p95 40.58 ms @ 50k).

**P0's code is complete: P0a (the shadow read) and P0b (a v3 store serving prefetch
from S3 behind `ENTROPICMEM_V3_RETRIEVAL`) are both merged, P0c's **readout** landed
(`94dd3c7`), the **ceiling split the owner ruled on 2026-10-08 landed
(`3c8b301`)**, and **EM-306 (`4a2b25e`) armed the miss side from its holdout** —
fabrication stays a hard ceiling (`max_v3_only = 0`), and the miss ceiling is now
`0.107143`, so a clean sample can conclude. The divergence-definition question that
readout raised is therefore **settled, not open**. **What remains of P0 is the data
itself**, and it is blocked on the environment rather than on a decision: this box does
not run the plugin at all (no `memory.provider` key, `plugins.enabled` lists only
`homeassistant`, no `~/.hermes/plugins/entropicmem`), so no turn reaches a write path
and the live store stays empty. Real turns need a host where the plugin is installed
and enabled — the owner's act.

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
  `em/config.py` scalars (**wired to the call sites by EM-407, `2b21ad1`** — the
  expectation that EM-401–403 would wire them did not hold; the typed config landed
  the seam); the same holdout executed the
  pre-registered arming rule, so `_shadow`'s promotion observable is fully armed and
  **P0's code is complete**.
- **EM-307 landed (2026-10-09, `7d6a22e`): the token packer and §3.6 renderer, and a
  gated retrieval can be rendered.** `render_retrieval` produces the sectioned block
  (superseded notes, episodes, follow-ups) under a 450-token budget. **The eval adapter
  still emits full-id bullets; the provider's served block is §3.6's render on the
  wired path (chunk 35, full-id citations) and v2's bullets otherwise** — switching
  the adapter is a separate, measured change.
- **EM-303's first slice landed (2026-10-09, `7d6a22e`): stored embeddings can be
  searched.** A stdlib cosine ranker over one joined query, the 50%-coverage gate, and
  the gate's cosine condition behind `retrieve(query_vector=, embedding_model=)`. The
  live paths pass no query vector, so scores are unchanged — **still true after the
  rest of EM-303 landed** (the entries below): the vector path is complete in code
  and never fed on a live turn (the open embedding gap, 2026-10-15).
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
- **EM-402 landed (2026-10-13, `2706a86` merged — code `7104bed`, docs `618c180`,
  windows fix `2706a86`): §3.5's scoping is live, per turn, through one seam.** `ScopeContext`
  resolves the session's scope from the host's init kwargs + config and re-buckets
  per turn by the author trio (bot authors never create user-scoped memories);
  `_open_engine` is the single seam every read and write goes through; the prefetch
  cache keys on `scope_key`, closing a cross-author block-replay leak; and
  `identity_signature()` reads the config file only, cached by mtime. The
  `multi_user` eval category reads 1.0 on its own isolation surface; the frozen
  suites are byte-identical. One finding recorded, not changed: a `sensitive`-tier
  row is owner-only even to its own user under the pinned `row_is_owner_only`.
- **EM-401 and EM-403 landed (2026-10-13 → 2026-10-15): the provider is the new
  implementation, and §4.2's service is wired.** `plugins/entropicmem/__init__.py`
  is a 145-line host shell over `em/provider/provider.py` (hooks, scopes, tools);
  every §4.1 hook is `fail_soft`-wrapped (and four fail-closed); on a v3 store
  **with** `ENTROPICMEM_V3_RETRIEVAL=1` the synchronous fact block is served by
  `PrefetchService.prefetch` (its cache, dedup, hard cap and five `prefetch.*`
  metrics) and `queue_prefetch` feeds the service's worker — v2 stores byte-identical
  by construction, flag off by default. **The query embedding is the piece this
  series left unwired** (see the open-gap bullets below): the provider never calls
  `ensure_embedding_model` and embeds nothing, so even the wired path scores
  lexical/entity/episodic.
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
cost. Nothing about the live store has moved. **One more decision rides this cutover,
per the owner (2026-10-16):** the adapter-defaults unification — the eval adapter's
`None` default taking EM-306's calibration — with both holdout numbers: **mrr 0.86508
under the spec defaults vs 0.88095 under the calibrated values** (dev 0.918477/0.91667
vs 0.919087/0.9187; recall and noise equal in both). It is explicitly **not** S4 work;
the split's pin test stays in force.

**The shadow's own honesty, so its numbers cannot be over-read:** the copy lags, so
divergence is a **lower bound**; v3's path has no query embedding wired, so its
scores run lexical/entity/episodic only and it is not an apples-to-apples quality
comparison; and the promotion observable was fixed in
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

**EM-412 is merged (`637a269`, all 11 CI jobs green on the exact SHA — the
branch-first landing of `em-412-query-embedding`: tests first, implementation,
CHANGELOG, push, check-runs, `git merge --ff-only`, branch deleted), closing the
recorded query-embedding gap, on top of
EM-410's cron & worker (`874b3d4`), EM-409's system prompt (`a472748`), EM-408's CLI mount (`def39cc`), EM-411's
window capture (`fe5e53b`, with its same-day floor correction
`em-411-floor-correction`), the EM-406
checkpoint v2 (`6e86c98`, merged the same day), the EM-407 pair (`2b21ad1` typed config — Appendix A's typed model, §3.8's
loader and the typed schema/save pair on `main`, with **the tuned
`gate.*`/`ranking.*` scalars reaching every call site** — and the hardening pull
`dc3c77a`), the guard-visibility follow-up (`56dc588`), the EM-405 lifecycle
slice (`e483d43`, which completes that card), the EM-404 validation slice
(`5000942`, which completes that card — the nine v3 tools of Appendix B on both
stores, the five legacy names routing for one minor version), the slice-2
landing (`e5e54ef`), the slice-1 landing (`381197f`) and the chunk-35 merge
(`a5b613a`). **EM-406, EM-407, EM-408, EM-409, EM-410, EM-411 and EM-412 are complete.**

1. **EM-412 landed (`637a269`) — the query-embedding wiring card completes.**
   One fail-soft `QueryEmbedder` seam (built only when `embeddings.enabled` is
   on and the store is v3) at the three v3 read sites — the tool search path,
   `PrefetchService`, and the facade's flag-on `recall_with_relevance` via
   `open_engine` — `ensure_embedding_model`/the model-switch `embed_backfill`
   at initialize, the per-owner-type diagnostics in `Retrieval.diagnostics`
   and the search payload, per-session counts with a shutdown summary; a
   raise/timeout/unavailable service returns no vector and the caller serves
   lexical; flag-off and v2 paths byte-identical; 15 new tests; **7 mutation
   checks all red**. The owner's
   2026-10-16 S4 order ran EM-406 → EM-411 → EM-408 → EM-409 → EM-410 → EM-412
   (all landed; `637a269` is the latest), and **no chunk is queued** — the
   recorded-owed candidates are the EM-303 prune follow-up (it did not ride
   EM-412 — the card carries no prune), `_shadow.py`'s printed-caveat
   one-liner, and the adapter/eval gate (rides the cutover). **P0c's data**
   (item 2 below) still
   waits on the owner's host. Whatever is chosen, follow the branch-first
   workflow end to end: tests + CHANGELOG, push, check-runs on the exact SHA,
   `git merge --ff-only`, delete.

**EM-403's AC, verified through the wired provider (chunk 35):** warm p95
**40.58 ms** @ 50k (p50 39.44, max 42.07); cache-hit **p95 0.09 ms**; forced-slow
generator **1.261 s** with `partial` and earlier rows served; block **7,648** chars;
50-turn replay **5,504** ≤ 13,500 tokens. Live retrieval now embeds the query when
a backend is configured — **EM-412 landed (`637a269`); the seam is hard fail-soft,
so even a backend-less box's wired path serves lexical/entity/episodic**; **nothing
embeds a *memory* on the agent/prefetch thread** (the read paths' query embedding is
EM-412's deliberate exception); `ENTROPICMEM_V3_RETRIEVAL` stays off; CI's eval
gate stays v2 (the adapter's own defaults are the spec; EM-407 wired the provider's
call sites, not the adapter). EM-411's enqueues stay inert (mode off, empty
handler set) until EM-502's caps exist. The cutover stays with the owner. P0's observable stays armed at `0.107143`.

**Known gaps, recorded rather than hidden — the wired (v3 + flag) path:** **the
query embedding is wired — closed 2026-10-16 (EM-412, `637a269`): the seam at
the three v3 read sites, `ensure_embedding_model` at initialize, and the vector
handed to `retrieve`; hard fail-soft, so a backend-less box still serves
lexical/entity/episodic.** Also: the
service owns caching and dedup, so the v2 fact-block cache and its window do not run;
`touch_on_inject`'s background `last_accessed` bump does not run; and the provider's
config-level `prefetch_denied_sources`/domain filters are not applied by the service.
§3.5 scoping *is* applied (the service reads through the turn's scope, pinned by a
two-author isolation test).

**P0c's data is blocked on the environment, and the reason is now measured rather than
assumed.** This box is not running EntropicMem at all: `~/.hermes/config.yaml` has **no
`memory.provider` key** (so the host uses its built-in memory), `plugins.enabled` lists
only `homeassistant`, there is **no `~/.hermes/plugins/entropicmem`** and no
`entropicmem-live-2.8.1` clone, no vault, and `index.db` holds 0 notes. Every table in
`~/.hermes/entropicmem/memory.db` is empty — `facts`, `pending_facts`, `episodes`,
`audit_log`, `triples`, `sync_outbox` — at `user_version=0`. **So the zero-fact state is
expected: no turn ever reaches the plugin.** It is not a broken write path, and it will
not fix itself by accumulating. Real turns need a host running the **dev-line** plugin
— the released 2.8.1 carries no shadow code (verified with `git ls-tree origin/release/2.8.x`), so the owner's active 2.8.1
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
3. **Pre-flight:** the counts, each the command's own output — CI's `test` job
   (3.12): `pytest -q tests/` → **2705 passed / 4 skipped / 3 xfailed** (read
   2026-10-16 from the job log at `ae525b6`, with the extra set
   fastapi/httpx/cryptography/pyyaml, numpy, and the private digest list as the
   repository secret); this box bare: `.venv311/bin/python -m pytest -q` →
   **2629 / 16 / 3**; with the digest list in place:
   `ENTROPICMEM_PRIVACY_DIGESTS_FILE=… .venv311/bin/python -m pytest -q`
   → **2630 / 15 / 3**; CI-equivalent 3.12 with the extras and the digest file
   → **2707 / 2 / 3** — the environment, not the tree. The 77-passed gap is
   per-module accounted in NEXT_CHUNK's pre-flight (67 fastapi + 7 cryptography
   + 2 numpy + 1 privacy). `git merge-base --is-ancestor 4eb8097 HEAD` proves
   the base.
4. **Two commits** (code, then docs), then **check-runs on the exact SHA** — not
   `run list`, which can hand back a stale green.
5. **The cutover decision is (a)+(b) complete and back with the owner.** Bring the
   evidence and the recommendation; do not switch the live store. One decision rides
   it: the **adapter-defaults unification** — holdout mrr **0.86508 spec** vs
   **0.88095 calibrated** — explicitly not unified in S4.

### What is next — the owner's priority order

The owner set the order explicitly; do not reorder it without asking.

| # | Work | Why now | State |
|:--|:--|:--|:--|
| **1** | **P0c — collect the shadow data and read it against the frozen observable** | It is the gating empirical step for the cutover; the readout landed in `94dd3c7`, the **data has not** | **Readout DONE, observable fully armed, data outstanding** — needs ≥200 real turns on a host running the **dev-line shadow** (the owner's active machine is the candidate) |
| **2** | **P2 / EM-306 — calibration harness** (`evals tune`, `em/config.py`, and the armed miss ceiling) | It was the next buildable chunk and it unblocks P0c's reading | **DONE (`4a2b25e`)** — holdout reported, defaults committed, ceiling armed at `0.107143` |
| **3** | **EM-307 — packer and renderer** | §3.6's block, fed by a real retrieval | **DONE, merged (`7d6a22e`).** A gated retrieval renders; the adapter does not call it, and the provider's served block **is** this render on the wired path (chunk 35). EM-303 shipped after it |
| **4** | **EM-303 — vectors: the gate's cosine condition, MMR's embedding path** | The remaining quality lever behind the gate, and the only thing that moves `hard/ageing` off 0.733 | **DONE, merged (`3439b77`):** backends, jobs, model identity, cache (50k p95 3.86 ms); follow-ups `42e16c7`, precision `6d9bf3b`, observability `60f0d67`. **The vector path is complete and never fed a live query — row 5's note** |
| **5** | **EM-401–403 — the provider layer (hooks, scopes, the wired `PrefetchService`)**, then EM-406 → EM-412 | Moves the v3 core onto the live path behind the flag; EM-406 (checkpoint v2) and EM-411 follow it | **All complete and merged** (`db7c24f`+`b8e170a`; `2706a86`; `9f9ba0c`+`31053df`+`a5b613a`). **What the series expected and did not deliver, recorded 2026-10-15: the query embedding** — the provider never calls `ensure_embedding_model` and embeds nothing, so live retrieval stays lexical even wired; **that wiring landed as `EM-412` (`637a269`, 2026-10-16; the fail-soft `QueryEmbedder` seam, initialize's `ensure_embedding_model`, the vector into `retrieve`, the diagnostics).** **EM-406 landed (`6e86c98`, checkpoint v2 complete); EM-411 landed (`fe5e53b` — the window capture, gated off until EM-502's handler and caps); EM-408 landed (`def39cc` — the `hermes entropicmem …` mount and the shared tree's `stats` shortcut); EM-409 landed (`a472748` — Appendix D's policy, the conditional tool lines, Core within `core.token_budget`); EM-410 landed (`874b3d4` — the provider's prefetch-gated `JobWorker` over the shared `em/jobs/registry.py` builder, completing the cron & worker card); EM-412 landed (`637a269`) — the series' one open gap, closed** |
| **—** | **P3 — the cutover** | Both re-decision conditions are met in code | **Held: the owner decides; the agent brings it** |

**The owner's order was re-set on 2026-10-08** (this table): P0c first as the gating
empirical step — now blocked only on a host, with the observable armed — then EM-306
(**done**), then EM-307 (**done, merged**), then EM-303 (**closed and merged
`3439b77`**: search, MMR, backends, jobs and the cache). Since then EM-404
(validation, `5000942`), EM-405 (lifecycle, `e483d43`) and EM-407 (the typed
config, `2b21ad1` — the chunk that seated EM-306's scalars at the call sites)
landed, the hardening pull (`dc3c77a`) with its guard-visibility follow-up
(`56dc588`), EM-406 (`6e86c98`), EM-411 (`fe5e53b`), EM-408 (`def39cc`),
EM-409 (`a472748`), EM-410 (`874b3d4`) and EM-412 (`637a269` — the
query-embedding wiring, closing the recorded gap). **No chunk is queued now: the
S4 order the owner set ran EM-406 → EM-411 → EM-408 → EM-409 → EM-410 → EM-412,
all landed; the recorded-owed candidates (the EM-303 prune follow-up,
`_shadow.py`'s one-liner, the adapter/eval gate) are the owner's to slot.** P1 is done and P3
stays with the owner. Do not reorder without
asking.

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
* **The `_shadow.py` report's own printed caveat is stale and needs a one-line fix card (found 2026-10-15, docs pass):** it says "no vectors or cosine until EM-303", but EM-303 merged — the reason the shadow's v3 scores carry no vectors is that the *shadow* feeds its v3 side no query embedding (the provider's wiring landed as EM-412, `637a269`; `_shadow.py` was deliberately out of that card's scope). The substance ("not an apples-to-apples quality comparison") still holds — the shadow's v3 scores stay lexical/entity/episodic by construction, because its v3 side is fed no query embedding (EM-412's wiring stops at the live read path). The printed caveat was **fixed in `26265ef`** to say so; divergence is still a lower bound because the copy lags.
* **`vector` is complete (EM-303, merged `3439b77`; follow-ups merged `42e16c7`).**
  Search, MMR, backends, jobs, model identity and the cache
  are merged. The follow-ups: `EpisodeStore` enqueues `embed` jobs and the jobs
  and backfill cover episodes; the v3 eval adapter embeds documents and the query
  when `disable_embeddings=False` (the frozen suites stay lexical); CI installs
  numpy so the cache tests and the 50k AC run there. **What was still absent — closed 2026-10-16 (`EM-412`, `637a269`):** the **provider** did not embed a query. EM-401–403 all landed without wiring it (`ensure_embedding_model` had no caller outside `em/embeddings/jobs.py`; `_ensure_prefetch_service` built the service with no `embed_query`; the served path passed no `query_vector`), so even the wired v3+flag path scored lexical/entity/episodic. **EM-412 wired all three** — the fail-soft `QueryEmbedder` seam, `ensure_embedding_model` at initialize, and the vector handed to `retrieve` — behind `embeddings.enabled`.
  The cache's one recorded caveat: a raw-SQL same-length rewrite is not re-read
  until reset (all `put_embedding` writes are seen).
* **§3.6's `query_rewrite` has no call site (EM-301; the IDF cache landed with
  EM-403 slice 1)** — `query.VocabularyCache` now keys on the service's
  `write_generation`, so the vocabulary is cached; but nothing implements a
  rewrite or calls one, and the typed config's `prefetch.query_rewrite` (EM-407,
  default `none`) is the switch with nothing behind it yet. Recorded in
  V3_FOUNDATIONS; the rewrite itself needs its own card.
* **The full temporal grammar is EM-310's** — EM-301 handles an ISO date, "since",
  "before", "between" and "last N days/weeks/months/years"; month names,
  weekdays, "earlier this week" and the `timezone` config are EM-310's.
* **`ranking.*` reaches the provider's call sites now (EM-407, `2b21ad1`); the
  eval adapter's defaults remain the spec (EM-304 / EM-306).**
  `fusion.RankWeights` carries §3.6's numbers as its default; the provider builds
  the weights from the typed config (EM-306's calibrated
  `0.50/0.25/0.10/0.10/0.05`) and passes them into `retrieve`. `superseded_note` is emitted
  by EM-305; `render_retrieval` prints it when the pipeline kept a predecessor,
  and since chunk 35 **the wired path does too** — the service feeds
  `retrieval.predecessors` into `load_pack_items` and renders `updated …; was: …`
  via `pack_chosen`/`render` (the chain is in place; no test drives a real
  supersession end-to-end through the provider, recorded 2026-10-15). The
  v2/off path keeps v2's renderer, which has no such note.
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
  a config key instead of an env var is still open: EM-407 landed the typed config
  (`2b21ad1`) so the key now has a home, but making the flag config-driven (and
  flipping the default) stays owner-facing.
* **`gate.*`/`ranking.*` are wired to the provider's call sites (EM-306 → EM-407,
  `2b21ad1`)** — `initialize` builds the `GateConfig`/`RankWeights` from the typed
  config, and the search tool, the `PrefetchService` and the v3 facade pass them
  into `retrieve`; the eval adapter's defaults are still the spec, so the CI eval
  gate stays v2 by EM-306's call. `extra_stopwords` remains
  EM-301's parameter.
* **Supersession has no end-to-end test through the provider (recorded
  2026-10-15; **card it before EM-502/EM-503 build on it**).** The wired path
  feeds `retrieval.predecessors` into `load_pack_items` and renders
  `updated …; was: …`, but the chain is asserted piecewise — no test drives a
  real supersession end-to-end through `prefetch()` or the search tool. EM-502
  (extraction) and EM-503 (reconciliation) are the producers of supersessions, so
  the end-to-end test should land first. Card drafted in
  [plan §6.4](docs/plan/REMAINING_PLAN.md).
* **Recorded gaps to card separately:** §3.6's `query_rewrite` has no call site
  (wire it or mark the config key deferred); `recent`'s "current session" half
  needs a session id `RetrievalContext` does not carry; EM-211's seven CLI
  refusals each name the card that lifts them. Draft cards in
  [plan §6.4](docs/plan/REMAINING_PLAN.md).

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
| Tests | `python -m pytest -q` | **2705 passed / 4 skipped / 3 xfailed** (CI, 3.12 at `ae525b6`) |
| Lint | `ruff check .` under the CI pin `ruff==0.16.2` | clean |
| Evals | `evals run --suite ci --compare evals/baselines/v2.8.0-ci.json` | no gated metric regressed |
| Performance | `evals.perf --sizes 1000 --probes 20` | prefetch warm p95 ≤ 20 ms |
| Identity | CI `identity-guard` | every commit a noreply address |

Run the suite with `ENTROPICMEM_MEMORY_DB`, `ENTROPICMEM_VAULT_PATH` and
`ENTROPICMEM_INDEX_DB` unset. **The 2705 / 4 / 3 figure is CI's** (extras + numpy +
the private digest list as the repository secret) and is the reference a pre-flight
run is checked against. This box's scratch venv (`.venv311`, no fastapi/httpx/
cryptography/numpy) reads **2629 passed / 16 skipped / 3 xfailed** — the missing
extras change what is collected and skipped, which is the environment, not the tree
(0 failures locally; the 50k AC's reds — on `3dcb35f` and the 2026-10-15 3.13 leg —
are now fixed by statistic: the guard reads the best of five windows, `dc3c77a`).
**The CI skip count is 4 — 3 plus the new host-static pin, which skips where the
hermes-agent checkout is absent; this box reads 16 skips without the private digest
list and 15 with it** — read the pair, not either number alone.
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
`em/store`'s scope helpers are not imported by it.) **A different test joined the
list on 2026-10-16**: EM-406's main-push run at `6e86c98` tripped `test (3.10)`'s
`test_warm_p95_at_50k_is_under_150ms` — warm p95 **153.35 ms** with **all 25
samples at 117–158 ms**. That is the *opposite* tell from perf-smoke's, and from
the 2026-10-15 3.13-leg numpy-guard flap: a **uniformly inflated** distribution (a
contended runner), not a stall tail — on the prefetch AC test, not the embedding
guard. The same SHA's branch run and the rerun of the failed job were both green.
**A second, Windows-only test joined the list the same day**: EM-411's push at
`fe5e53b` tripped `windows-import`'s
`test_em405_retract.py::test_the_rewind_budget_is_not_a_stall` at **0.250 s** —
1 ms over the 250 ms enqueue budget, on a cold Windows runner (the path is the
EM-405 rewind enqueue; EM-411 adds nothing to it); the rerun of the failed job
was green.
The way to tell a flake from a
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
  the catalog. *(Note 2026-10-15: the dev line's v3 surface names the tool
  `entropicmem_profile`, with `entropicmem_patch_core` as its one-minor-version
  alias — EM-404, `5000942` — so the catalog ask is in the owner's hands for the
  next re-pin. The same note covers the dev line's manifest breadth:
  `provides_tools` is 9 and `provides_hooks` 6 on `main` (EM-404's 7 → 9; EM-405's
  5 → 6, `e483d43`) while the live entry matches the 2.8.1 tag's 7/5 by design.)*
- **F-004 — full per-user isolation is not implemented; the v3 cutover must not
  proceed with it open unless the owner records the acceptance in writing.**
  `tests/regressions/test_findings_v27.py::test_f004_cross_user_isolation` is a
  strict xfail: two users sharing a profile can see each other's memories (S1's
  interim is EM-118's owner/guest guard only). v3's §3.5 scoping (EM-402) buckets
  per turn by the author trio, but F-004's acceptance criterion is Sprint 4's
  *full* isolation. Cutting the live store over with a known cross-user read path
  is a privacy and correctness risk — **resolve it, or have the owner accept it
  explicitly, before the cutover.** (Also §9 item 9.)
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
  sees until the owner-gated v3 cutover.
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
