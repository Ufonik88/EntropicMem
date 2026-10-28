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

> **Security hardening — 2026-10-19, landed.** A security hardening review against
> `main` at `2079bd3` was applied end to end and committed on top of `2079bd3` in
> ten commits, then landed on `main` (`363ff10` … `5a297ec`; `main` matches
> `origin/main`).
> Fifteen areas needed a code/config patch, three are accepted risks with a
> documented mitigation, and one item was already fixed and no longer applies.
> Committed: private POSIX modes for vault notes, new domain directories,
> `index.db` and encryption artefacts, plus `security fix-permissions`; staged
> all-or-nothing encrypt/decrypt; folder containment on `list_notes`/
> `search_notes` and `moc`; a fail-closed graph bind policy, a liveness-only
> `/health`, and vendored (not CDN-loaded) graph libraries; an explicit
> `--trust-unverified` capsule import; one outbound scheme/host/DNS validator
> with a response cap; type-only tool errors; a random, pruned `forget` token;
> a once-only WARNING for an unavailable injection screen plus its state in
> `stats`; guest-mode visibility in `stats`; raised dependency floors; and
> SHA-pinned, read-only CI on Python 3.10–3.14.
> **Verification:** the measured suite figures are in `docs/plan/BASELINE.md`
> (the one record — an earlier hand-typed figure in this block is retired);
> `ruff check .` clean; the full suite also ran green under a throwaway Python
> 3.14.6 venv. `tests/test_master_todo.py` 13 passed at the time. The CPython
> 3.14.8 upgrade is an ops action outside the repo; the no-lockfile policy
> remains an accepted risk (direct CI pins added). **The next development chunk
> is EM-607, ingest v2** — EM-605 and EM-606 are COMPLETE and landed (`73bed69`; see "In flight"),
> **and EM-607 is now COMPLETE and LANDED on `main` at `5f0670c`** (2026-10-21; built at
> `af0cf98` on `em-607-ingest-v2`, all 13 check-runs green on the branch tip, branch deleted
> after the ff-merge). With it the six-card S6 list
> (`EM-602`…`EM-607`) is complete; the next piece is not agent-owned by default — S7
> security, EM-806 packaging and S9's drills/release stay behind their own gates.
> **2026-10-23: the owner said "continue with the next chunk of development". Per §6.6
> (the agent decides whether S5–S9 are worth continuing; the owner can veto at any time),
> the agent opened S7's two buildable cards as one chunk — EM-703 (write-path injection
> screening & trust policy) and EM-705 (`purge` also removes embeddings and vault
> projections) — and both are LANDED on `main` at `17684d9` (`859f12d` + `b570065`): 13/13
> green check-runs on that exact SHA and again on `main`'s push (the build tip's own run
> `39951235609` was red on the figures-guard pair alone, the expected pre-stamp shape; the
> record pass `f7fb7a1` landed the figures before the landing ran). Detail in
> `docs/plan/NEXT_CHUNK.md` Part A.**
>
> **2026-10-27: the owner said "continue with the next available chunk". With S6 complete and
> S7's two buildable cards landed, the only card left that is code rather than a release act
> is **S8's EM-806 — packaging** — and it is **LANDED on `main` at `ceb70cb`** (opening docs
> `1e683c1`, build `bf2e267`, record pass `ceb70cb`; 13/13 check-runs green on that exact SHA
> and again on `main`'s post-landing push).** The card closed two measured defects: the wheel shipped `em.*` and
> `em_internal.*` but **none of the flat engine modules** they import (`memory_engine`,
> `pii`, `textutil`, …), so `import em.graph` from an installed wheel failed inside
> `em_internal.index` (recorded, not fixed, by chunk 43); and nothing declared the host's
> `hermes_agent.memory_providers` entry point or shipped the plugin shell as an importable
> package, so `pip install entropicmem` installed an engine no host could load. It also gave
> `plugin.yaml` the two manifest fields a pip install needs (`requires_hermes`,
> `pip_dependencies`) and documented the optional extras. **The AC's runtime half ran in CI:**
> the new `plugin-validate` pip-install smoke step installed the wheel and loaded the provider
> through the host's own entry-point loader. Build record in Part A of
> `docs/plan/NEXT_CHUNK.md`; the figures of record are in `docs/plan/BASELINE.md`.
> **S9's drills (EM-901) and the 3.0 release (EM-904) stay behind the owner's release gate,
> and the v3 cutover remains the owner's call.**
>
> **2026-10-28: the owner asked for anything outstanding that is still autonomous, and to
> do it now.** The sweep found three things. (1) **Three unmerged remote branches** —
> `chore/deps-entropicmem-2026-10-20` (dependency floor raises that also track a `uv.lock`,
> which chunk 30's `.gitignore` policy deliberately keeps out, and an ruff floor that
> conflicts with CI's `0.16.2` parity pin), `docs/dependency-update-2026-10-20` (the same
> chore commits plus docs records the `b99437a` merge already carried), and
> `wt/t_1951f54d` (a stale-base branch whose EM-603 reindex fix is superseded by PR #11 and
> whose graph loading-state feature edits the deleted `graph_export.py`). All are the
> owner's own sessions' work — **reported, not touched**. (2) `prefetch.query_rewrite`'s
> known-gaps line is reconciled: V3_FOUNDATIONS already marks the key deferred with the
> ruling and its owner (a prefetch-side card, never a drive-by) — the gap was the pointer.
> (3) **EM-601's one deferred spec promise — month paging for `Memories/Unfiled.md` past
> 200 rows — is opened as the chunk**: it is the last outstanding item in S5–S9 that is
> code and not behind a gate, it is the card's own Spec text, and the deferred design
> question ("which file is current when a month stops being current") has an answer the
> agent can make and record. S9 stays behind the owner's release gate.
> **Chunk 48 is now COMPLETE and LANDED on `main` at `d84f5f8`** (2026-10-28; build
> `c1749c8`, record pass `f91c55a`, read pass `6441c32`; 13/13 check-runs green on `f91c55a`
> and 26/26 on the merge tip — the branch run and `main`'s post-landing push on the same
> SHA — `identity-guard` included; the build tip's own run was red on the figures-guard
> ancestry test alone, the documented pre-stamp shape). With it the last ungated code item
> in S5–S9 is closed and the remainder is S9 (the owner's release gate) again. **The owner
> then ran the review round-trip through Hermes: APPROVE, no code defects; its box's two
> 50k warm-p95 gate failures were machine speed only (CI green on the exact SHA); and its
> branch recommendations — deps REWORK without the lockfile, the other two DELETE — are
> recorded in §6.6's fourth use for the owner's ruling.**
>
> **2026-10-28, later: the owner ruled — "delete both, rework the deps, hold S9" — and all
> three are done or in flight.** The two ruled branches (`docs/dependency-update-2026-10-20`,
> `wt/t_1951f54d`) are deleted from the remote; their supersession is §6.6's record and the
> remaining remote refs (`test/split-reachability-fix`, three `wt/t_*`) are **zero-delta**
> (every commit reachable from `main`) and stay for their own lifecycle. S9 stays held.
> **The deps rework is chunk 49 and it is a safety correction, not a rubber-stamp:** CI pins
> exact versions (`pytest==9.0.3`, `fastapi==0.143.0`, `cryptography==50.0.2`,
> `ruff==0.16.2`), so the chore branch's floors for fastapi 0.154 / pytest 9.1.1 /
> fastembed 0.9 would demand versions the suite has never exercised — refused. The rework
> aligns the manifest with what is verified: `cryptography>=50.0.2` (the floor carries the
> security fix, as the manifest's own comment claims) and `ruff>=0.16.2` (the lint-parity
> version the rules are written against), everything else deferred with reasons. No
> `uv.lock` ever.
> **Chunk 49 is COMPLETE and LANDED on `main` at `830ffee`** (2026-10-28; build `8593e7a`,
> record `487dcee`, read `e463d3c`, re-stamp `830ffee`; 13/13 check-runs green on `487dcee`
> and 26/26 on the merge tip — the branch run and `main`'s push on the same SHA; the build
> tip's own run was red on the figures-guard ancestry test alone, the documented pre-stamp
> shape). With it the superseded `chore/deps-entropicmem-2026-10-20` branch is deleted too:
> the remote now carries `main`, `release/2.8.x` and four zero-delta refs
> (`test/split-reachability-fix`, three `wt/t_*` — every commit reachable from `main`).
> Nothing is in flight; the remainder is S9, held.
>
> **2026-10-28, later still: the owner said "handle and automate and make the decisions;
> go to work." That un-holds the buildable piece of S9: EM-901's upgrade drills are opened
> as chunk 50** (the drills validate the upgrade path and change no release surface — the
> release ACT, EM-904, stays owner-gated end to end). The drill plan is Part B. **A review
> handoff went to Hermes in parallel** (fixture-faithfulness audit + an independent
> 2.8→3.0 break review; message `01M61D5VWN4GWEXFW956E424C4`); its findings fold into the
> drills and the UPGRADING report, and it hands back here when done.

---

## STOP HERE — S5 is complete (2026-10-17); EM-601 and EM-608 are complete (2026-10-18); the owner handed the gated calls to the agent the same day and they are made — chunk 38 (the content-ceiling fix), chunk 39 (EM-602, both slices) and chunk 40 (EM-603, the incremental index) are complete, and **chunk 41 (EM-604, opt-in ingestion of human vault edits) is COMPLETE (landed 2026-10-19 as `31a7323`); EM-603's 5k AC is de-flaked (landed 2026-10-19 as `adb1439`); EM-605 slice 1 (graph model / renderers / assets split) is COMPLETE (landed 2026-10-19 as `2fd7812`); **chunk 43, the slice-1 follow-up (packaging verified where it ships, figures measured not typed, the warm AC's absolute ceiling), is COMPLETE (landed 2026-10-19 as `5258b46`); **EM-605 slice 2.1 (entity nodes and typed relation edges) is committed locally at `69dc223` (2026-10-20), not pushed; slice 2.2 (the owner-only scope filter and its byte-level leak test) is committed locally at `1e5b739` (2026-10-20), not pushed — 13 mutation checks red and the leak test scans the whole JSON/HTML output — slice 2.3, the relation time window, is committed locally at `e08694a` (2026-10-20), not pushed — 17 mutation checks red — **slice 2.4, dashed superseded edges, is committed locally at `6936574` (2026-10-21), not pushed — 11 mutation checks red — slice 2.5, the 5k-node export AC, at `0c40385` (2026-10-21), not pushed — 5 mutation checks red — and **EM-606, graph server hardening round 2, at `575eb06` (2026-10-21), not pushed — 15 mutation checks red and one equivalent recorded — so the next card is EM-607 (ingest v2); nothing is pushed, and no CI run exists for any of it** *(That state was the 2026-10-21 morning: EM-605/EM-606 landed later that day at `73bed69`, and EM-607 — the card this paragraph calls next — is now landed too, at `5f0670c`.)*

**Development stopped at this point on 2026-10-17.** S5 (formation & consolidation) is complete on
`main`: **EM-501**, **EM-502** (both slices), **EM-503** (core + wiring), and the
**S5 exit criteria** — a preference learned in session 1 is served in session 2
with no explicit `remember`, on the rule path with no LLM configured. **Two
queued chunks opened (the owner's go) and landed the same day: the F-004
remediation — resolved and pinned at `c30aa54` — and the EM-303 prune card —
the promised destructive embedding-maintenance job, built and landed at
`99151d3` with no destructive run (real runs owner-signed later).**

**2026-10-18: the owner authorised EM-601** — the vault-projection card, both halves —
by naming it as the session's build (*"you make the logical calls on the build"*,
target "chunk 36 = EM-601 slice 1"); slice 2's go came explicitly the same day
("proceed with slice 2"). **That is one card, not a stage: S6's remaining cards
(EM-602…EM-607), S7 security, packaging and the 3.0 release stay gated** — an earlier
record read "S6 opened", which overclaimed and is retracted. **EM-601 is complete — both
halves landed the same day**: slice 1, the vault projection engine, at `bdc1e20` and
slice 2, the `project_vault` job, its debounce, the mode switch and `vault lint`, at
`e986059` (both branch-first, all 11 check-runs green on each exact SHA, `--ff-only`,
branches deleted). **The same day the owner slotted EM-608 — the 50k warm-p95 gate's
*statistic*** (`docs/plan/PERF_GATE_CARD_DRAFT.md`), the last agent-owned card that was
ready — **and it is now complete too** (built 2026-10-18, landed as `3b71cf0`: the gate
now reads the best of five 20-probe windows, the 150 ms budget untouched). **Nothing is in
flight.**

**2026-10-18, later: the owner handed the outstanding gated calls to the agent** — *"I do
not have any idea what these are or what I must do … can you not make a call on these and
make a choice for me?"* — and **they are made**: P0c's shadow data is **skipped** (it only
justifies the cutover), the v3 cutover is **no** (no user-visible benefit yet, not
released; the live store stays v2), the prune's destructive run has **nothing to run**
(there is no v3 store to prune), releases/tags/the catalog re-pin are **not now** (`main`
is `3.0.0.dev0` with half-wired features), the **ceiling card is slotted as the next chunk
(38) with the number 8,000** (a real silent-truncation data-loss bug), and the **S6 scope
question is answered yes** — EM-602…EM-607 are agent-owned, in the documented §6.5 order
after the ceiling fix. **Chunk 38 — the content-ceiling fix — is COMPLETE** (landed
2026-10-18 as `c53b182`), and so is **chunk 39 — EM-602, both slices —** (landed
2026-10-18 as `607d54f` + `c29addc`: the vault's frontmatter writer quotes and
escapes, a `---` in the body is no longer a delimiter, wikilinks parse as a grammar, the
v2 `em_internal.vault` is a shim over the new `em/vault/frontmatter`; and `note_id` is now
the full vault-relative path with an `index.db` `user_version` 2 migration that recomputes
ids from each row's path, remaps the wikilink edges, keeps triple edges and normalises
Windows-shaped ids to POSIX). **Chunk 40 — EM-603, the incremental index — is COMPLETE** (landed
2026-10-18 as `338ec2a`: `notes_meta` carries `mtime_ns`/`size` (`index.db`
`user_version` 3), a refresh reads only a note whose stat moved (a 5k vault with one
change: 26/31/32 ms on 3.11/3.12/3.10 against the 300 ms AC), `entropicmem index refresh`
runs it and the `reindex_vault` job refreshes the index after a projection). **Chunk 41 — EM-604,
the opt-in ingestion of human vault edits — is COMPLETE (landed 2026-10-19 as `31a7323`)**:
`vault.ingest_human_edits` (default off) makes the `project_vault`
job read each entity page's human region back as `pending` `source=vault_edit` proposals
(before the projection re-adds anything), with a removed auto-section line recorded as a
`review` hint; 15 new tests, **11 mutation checks all red**, each restored from a byte copy;
CI's 3.12 count **2928 / 4 / 2** read green at `31a7323` (all four legs identical), 11/11
check-runs green on both SHAs and `identity-guard` included. **The next chunk is EM-605 —
graph export v3.** See
[docs/plan/STOP_HERE.md](docs/plan/STOP_HERE.md) for the full
stop-state: what is done, the evidence, and the exact counts.

---

**Last reconciled:** 2026-10-28, against branch `main` at `830ffee` (chunk 49, the
dependency-floor rework — build `8593e7a`, record `487dcee`, read `e463d3c`, re-stamp
`830ffee`; 13/13 green on `487dcee` and 26/26 on the merge tip; the rework branch and the
superseded `chore/deps-entropicmem-2026-10-20` deleted; the two owner-ruled branch
deletions done before it). The previous
reconciliation was the same day against `d84f5f8` (chunk 48 — EM-601's
deferred month paging: build `c1749c8`, record pass `f91c55a`,
read pass `6441c32`, re-stamp `d84f5f8` — 13/13 green on `f91c55a` and 26/26 on the merge
tip; branch deleted after the ff-merge), then 2026-10-27 against `1d2f631` (the EM-806 S8
packaging landing `ceb70cb` — opening docs `1e683c1`, build `bf2e267` — plus the read pass
`bdd2ecb` and the docs-only re-stamp `2df0cee`, then `2ff11c2` and `da86e59` + `1d2f631`
— all docs-only, each green on `main`'s push on its exact SHA). The previous
reconciliation was the read pass that closed the EM-703 + EM-705 landing's figures — landed
as `17684d9` from code `859f12d` + `b570065` on `em-703-705-security`, deleted after the
ff-merge; before that the EM-607 ingest-v2 landing at `5f0670c`, and before that 2026-10-19
against `2079bd3`. (security
hardening applied in the working tree; see the note above) — **EM-605 slice 1 (the
graph model / renderers / viewer-assets split) landed (`2fd7812`, all 11 check-runs green on
the exact SHA), and EM-603's 5k AC is de-flaked (landed `adb1439`, reconciled as `e6647e7`);
chunk 41, EM-604,
the opt-in ingestion of human vault edits, is complete (landed `31a7323`), after chunk 40
(EM-603, the incremental index — `338ec2a`), chunk 39 (EM-602,
both slices — `607d54f` + `c29addc`) and chunk 38 (the `remember` content ceiling,
`c53b182`); the next chunk is EM-605 (graph export v3).** Before them
the same day, **EM-608 is complete:
the 50k warm-p95 gate now reads the best of five 20-probe windows (landed `3b71cf0`, the
150 ms budget untouched), and EM-601 is complete: both halves landed (slice 1 the vault
projection engine `bdc1e20`, slice 2 the job, debounce, mode switch and `vault lint`
`e986059`) — the owner's word authorised one card, not a stage, and the rest of S6's
cards are agent-owned by the owner's later instruction to make the outstanding calls.**
The expected figure of record lives in one
place: [`docs/plan/BASELINE.md`](docs/plan/BASELINE.md) — on top of **the EM-303 prune
card: the promised destructive embedding-maintenance job, built and landed** (branch-first on `em-303-prune`, all 11 check-runs green on that exact SHA, and all 22 after the merge re-ran them on `main` — nothing new existed to break the re-run; **no destructive run happened and none is scheduled: real runs stay owner-gated**, see Open blockers) atop the F-004 remediation (**`c30aa54`** — full per-user isolation resolved and pinned; branch-first, all 11 check-runs green on that exact SHA; the finding's strict xfail flipped onto a v3-store drive, the two-provider surface pinned beside the group-chat harness, **no product code changed**) atop the S5 completion (EM-503 wiring, the `sync_turn` transcript capture and
the exit harness, `d331c5e`) atop the EM-503 core on the
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
was verified on that tree on this box (**bare
2706 / 16 / 2**; with the digest list **2707 / 15 / 2**; CI-equivalent 3.12
**2784 / 2 / 2**, both locally measured; `ruff==0.16.2` clean) and `main`
fast-forwarded to that exact SHA after **all 11 check-runs green on it** (the
post-merge push re-ran the suite on `main`: 22 runs, all success);
that tree's CI 3.12 count
was **2782 / 4 / 2** (read from the job log at `99151d3` — the +12 prune guard
tests; the prior read was 2770 / 4 / 2 at `d92503d`, and `c30aa54`'s own
read 2769 / 4 / 2). **The current figures are the Gates table's: CI 3.12 **2928 / 4 / 2**
(read at `31a7323`), bare **2852 / 16 / 2**, digest **2853 / 15 / 2**, CI-equivalent
**2930 / 2 / 2**.** Before it: **the branch-first landing of EM-410's cron & worker** (`em-410-cron-worker`:
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
and **EM-601 was authorised 2026-10-18 (the owner's word, one card) and is complete —
slice 1 the projection engine as chunk 36 (`bdc1e20`), slice 2 the job, debounce, mode
switch and `vault lint` as `e986059`; EM-608 then fixed the 50k warm-p95 gate's
statistic as chunk 37 (`3b71cf0`) — the last agent-owned card that was ready, now
landed, so nothing is in flight** (the
recorded-owed candidates that remain: `_shadow.py`'s one-liner, the
adapter/eval gate; the prune follow-up closed 2026-10-17 as `99151d3`).

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

| 36 | **EM-601 slice 1 — the vault projection engine (S6's first card)** | **Done, merged** (code `bdc1e20` on branch `em-601-projection`; ff-merged to `main` as `bdc1e20`; **11/11 check-runs green on that exact SHA, `identity-guard` included**, and the merge's 11 re-ran them on `main` to success; branch deleted). `em/vault/` (new package, listed in `pyproject.toml`): `project(conn, root, scope, modes)` renders `Entities/<Name>.md`, `Journal/<date>.md` and `Memories/Unfiled.md` from the v3 store; `lint(root)` reports projected files whose auto-sections are unsafe. **Only auto-section bodies are replaced** — frontmatter, the human region, the gaps between blocks, the trailing text and any section this run does not own are byte-preserved (a hand edit survives ten runs in *both* directions); a file whose markers the user deleted is left exactly as it is and reported by `lint`, never recreated over their prose; an unchanged render writes nothing (no mtime move, no temp file); writes are mkstemp + `os.replace` with the temp unlinked on any failure. **Forgetting erases rather than hides:** a fully-forgotten entity is still *visited* so its page is rewritten down to what remains (an entity with nothing and no page is not created), the unfiled page and a day's journal page behave the same, and a relation renders only while its source memory is live. **Deliberate strengthening:** §3.5's owner-only tiers never reach a plaintext file regardless of scope; the read clause is otherwise `MemoryStore.list`'s own (F-004). **Recorded, not built:** the `project_vault` job + 60 s debounce + the provider's enqueue, the `vault.projection` config → `modes` switch (`legacy` stays v2), `Unfiled.md` month paging past 200 rows, an unbounded journal — **slice 2 landed the same day as `e986059`**. 31 new tests; **10 mutation checks, all red**, each restored from a byte copy; bare **2737 / 16 / 2**, digest **2738 / 15 / 2**, CI-equivalent 3.12 **2815 / 2 / 2**, CI **2813 / 4 / 2** read at `bdc1e20`; ruff clean, 3.10 leg green |

| 37 | **EM-608 — the 50k warm-p95 gate's statistic (a measurement fix, not a budget move)** | **Done, merged** (code `3b71cf0` on branch `em-608-perf-gate`; ff-merged to `main` as `3b71cf0`; **11/11 check-runs green on that exact SHA, `identity-guard` included**, all on `headSha=3b71cf09`; branch deleted). The two warm-p95 ACs each took **one** p95 over 25 probes, so the gate's verdict moved with the runner: on unchanged SHAs it flapped to p95 153.35 ms (`6e86c98`, `test (3.10)`, all 25 samples 117–158 ms) and 151.09 ms (`bdc1e20`, `test (3.13)`, run `39112375641` / job `117631038052`), each green on a rerun of the same SHA. **The fix is EM-407's, generalised:** the new `tests/harness/perf_stats.py` carries `window_p95` (the gate's own nearest-rank definition, unchanged), `timed_windows(run, windows=5, probes=20)` and `best_window_p95`; both ACs now time five 20-probe windows and require the **best** window's p95 to hold **150.0 ms — the budget is untouched**. A transient contention cannot inflate all five windows; a genuine regression inflates every one and still fails. Each AC emits every window's p95 as a warning on green runs too (drift under the assertion stays visible), and `timed_windows` hands each probe its own index so all 100 queries stay distinct. 8 new tests (`tests/harness/test_em608_perf_stats.py`, incl. a structural pin that both ACs still call the statistic and are not back to one 25-probe window); **6 mutation checks, all red**, each restored from a byte copy; bare **2766 / 16 / 2**, digest **2767 / 15 / 2**, CI-equivalent 3.12 **2844 / 2 / 2**, CI **2842 / 4 / 2** read at `3b71cf0` (all four legs identical); ruff (`0.16.2`) clean; 3.10 leg green; **no product code changed**. |

| 38 | **The `remember` content ceiling — raised to 8,000, and a refusal instead of a truncation (the silent-data-loss fix)** | **Done, merged** (code `c53b182` on branch `chunk-38-content-ceiling`; ff-merged to `main` as `c53b182`; **11/11 check-runs green on that exact SHA, `identity-guard` included**, all on `headSha=c53b182c`; branch deleted). The defect (found 2026-10-17 by a live incident): `jsonschema_lite.validate_arguments` implemented `maxLength` as *clamp-with-a-warning*, and the clamped value was then **persisted** — a 4,314-character summary was stored `active/created` with its tail destroyed, so a clipped fact was permanently indistinguishable from a complete one. **The fix moves two fields only:** `CONTENT_MAX_CHARS = 8_000` in `em/provider/tools.py` feeds both the `remember` and `update` schemas' `maxLength`, and a new keyword-only `fatal_length_keys` mode on `validate_arguments` makes an over-long named value **raise** `ArgumentError`; `handle_tool_call` names `remember`/`update` `content` in `FATAL_LENGTH_KEYS`, so the refusal rides the existing `invalid_arguments` branch **before any store write** (a refused call leaves no memory row and no audit entry). Every other string cap still warns and clamps — the validator's default call is byte-identical. Both `content` descriptions gain the guidance sentence the model reads; the two `maxLength` values and the two descriptions are the **recorded Appendix B deviation**. **16 new tests** (`tests/unit/test_em_content_ceiling.py` 12, `test_em404_jsonschema_lite.py` +4, incl. the packer's skip-never-cut behaviour and a 20k × ~2,000-char containment measurement); **8 mutation checks, all red**, each restored from a byte copy; bare **2782 / 16 / 2**, digest **2783 / 15 / 2**, CI-equivalent 3.12 **2860 / 2 / 2**, CI **2858 / 4 / 2** read at `c53b182` (all four legs identical); ruff (`0.16.2`) clean; 3.10 leg green; privacy scan clean. Recorded on this box: fts+insert 1.05 s, index 90 MB, warm p95 62 ms at 20k × 2 KB, inside §4.2's 9,000-char block cap. |

| 39 | **EM-602 (both slices) — frontmatter & wikilink robustness, then the note-id rule and the `index.db` migration (the vault can no longer corrupt itself on a hand edit)** | **Done, merged** (slice 1 `607d54f` and slice 2 `c29addc` on branch `em-602-frontmatter` / `em-602-note-ids`; ff-merged to `main`; **11/11 check-runs green on each exact SHA, `identity-guard` and `windows-import` included**; branches deleted). **Slice 1** moved the vault's frontmatter/wikilink logic into the new shared `em/vault/frontmatter.py`, shimmed by `em_internal.vault`: the writer escaped `"`/`\`/newlines and quoted only what YAML requires, the reader took a delimiter only at file start and on its own line (a `---` in the body no longer truncated a note), PyYAML is preferred with the subset parser as the fallback and the two are round-tripped against each other, a hand-written unquoted date stays a **string**, and wikilinks parse as a grammar with alias/heading/block stripped. **Slice 2** made `note_id` the **full vault-relative path** (it used to drop the top directory, so `A/Sub/Note` and `B/Sub/Note` shared one primary key) and added the **`index.db` `user_version` 2 migration**: ids are recomputed from each row's `path`, `notes_meta`/`notes_fts` are renamed in two passes, the `wikilink` edges are remapped, `triple:*` edges are left alone, and a Windows-shaped (backslash) id is normalised to POSIX. **36 new tests** (26 + 10); **13 mutation checks, all red** (7 + 6), each restored from a byte copy, plus a **green control** proving the subset parser carries the behaviour with PyYAML disabled; **2 deliberate repoints recorded** and **one Windows CI fix recorded** (the fixture's legacy ids were platform-shaped; the product was right). Bare **2818 / 16 / 2**, digest **2819 / 15 / 2**, CI-equivalent 3.12 **2896 / 2 / 2**, CI **2894 / 4 / 2** read at `c29addc` (all four legs identical); ruff (`0.16.2`) clean; 3.10 leg green; privacy scan clean. **EM-602 is complete.** |

| 40 | **EM-603 — the incremental index: a refresh reads only what moved, and a projection schedules it** | **Done, merged** (code `338ec2a` on branch `em-603-incremental-index`; ff-merged to `main` as `338ec2a`; **11/11 check-runs green on that exact SHA, `identity-guard` and `windows-import` included**; branch deleted). `notes_meta` gains `mtime_ns`/`size` (`index.db` `PRAGMA user_version` 3, the ALTER migration; a v2 db backfills on its first refresh). A refresh compares `(st_mtime_ns, st_size)` and **does not open** an unchanged note; only a moved stat is read, and the content hash still decides whether the row changed — a bare `touch` refreshes the stat columns only. `Vault.iter_note_stats` does the walk in one `os.scandir` pass (no Path and no `resolve_path` per file) and **never follows a symlink**, so the path work is not the whole cost and a link cannot leave the vault. **AC met with a 10× margin:** 5k notes with one change in 26 / 31 / 32 ms (3.11 / 3.12 / 3.10) against 300 ms — the first push read 398 ms on the CI 3.12 runner, which the walk fixed. New surface: `entropicmem index refresh` (CLI reference + README) and the **`reindex_vault`** job (`KNOWN_JOB_TYPES` + shared registry), enqueued dedupe-keyed by the `project_vault` handler when the payload carries `index_db` (the provider passes `paths.index_db`); the handler imports the v2 index lazily and a missing path/root is a `PermanentJobError`. **19 new tests** (`tests/unit/test_em603_mtime_index.py`); **11 mutation checks, all red**, each restored from a byte copy; one recorded Windows fix (the CLI printed non-ASCII `→`/`—`, a `UnicodeEncodeError` on cp1252 — output is ASCII throughout); one deliberate repoint (`test_em602_note_ids` pins `NOTE_ID_VERSION`, not `SCHEMA_VERSION`). **The 5k AC's wall-clock budget was de-flaked the next day (2026-10-19):** it reads a same-run ratio with the card's 300 ms as its floor, and the walk's no-per-note-`resolve` half is pinned structurally (the CHANGELOG's Fixed entry). Bare **2837 / 16 / 2**, digest **2838 / 15 / 2**, CI-equivalent 3.12 **2915 / 2 / 2**, CI **2913 / 4 / 2** read at `338ec2a` (all four legs identical); ruff (`0.16.2`) clean; 3.10 leg green; privacy scan clean. **Chunk embeddings remain EM-308's and that card is not built — recorded, not invented.** |

| 41 | **EM-604 — opt-in ingestion of human vault edits (the projection's other direction)** | **Done, merged** (code `d8f643f` + docs `31a7323` on branch `em-604-vault-ingest`; ff-merged to `main` as `31a7323`; **11/11 check-runs green on the exact SHA, `identity-guard` included**; branch deleted). **One recorded flake, not a code fault:** the post-merge `main` push re-ran `windows-import` on the same SHA and EM-603's 5k refresh AC read 440 ms on a contended Windows runner (its cold phase took 59.8 s); the branch push on that SHA was green and a re-run of the failed job was green — the EM-603 test was not touched, weakened or skipped. `vault.ingest_human_edits` (default off) joins the typed config (the curated `SCHEMA_KEYS` entry + the `config_schema.py` mirror); when on, the `project_vault` payload carries `"ingest": True` and the handler runs a pass **before** `project()`. `em/vault/ingest.py` (new) reads each entity page's **human region** (outside every `entropicmem:auto` block) and turns each `- <statement>` line into a **`pending`** `source="vault_edit"` memory linked to that page's entity — the store's only pending route is the write policy, so `evaluate_write` gains the `vault_edit` quarantine branch. A line the user removed from an auto-section is recorded as a `review` hint (`user removed line for m-<short> - forget?`, ASCII) in one deduped `meta` key, keyed off a persisted per-page baseline of block refs; a gutted page is skipped, the first pass stays quiet, and the read is scope-bounded (F-004). Surface: `V3Engine.vault_review_hints()` feeds the `review` `list_pending` `vault_hints`, printed by CLI `cmd_pending`. Cuts named: no new CLI subcommand, no LLM over human lines. **15 new tests**; **11 mutation checks, all red**, each restored from a byte copy; local counts bare **2852 / 16 / 2**, digest **2853 / 15 / 2**, CI-equivalent 3.12 **2930 / 2 / 2**, CI **2928 / 4 / 2** read at `31a7323`; 3.10 leg green (143 passed); ruff clean. **The next chunk is EM-605 — graph export v3.** |
| 42 | **EM-605 slice 1 — the graph monolith split into a model, renderers and packaged viewer assets** | **Done, merged** (code `8946239` + docs `2fd7812` on branch `em-605-graph-split`; ff-merged to `main` as `2fd7812`; **11/11 check-runs green on the exact SHA, `identity-guard` and `windows-import` included**; the post-merge `main` push re-ran the eleven on the same SHA, all success; branch deleted). `graph_export.py` (2,122 lines) is **deleted, not shimmed**: the model — the palettes, `get_shape`, `detect_communities`, `body_coverage`, `assert_bodies_present`, `resolve_note_path`, and the payload builder lifted out of `export_json` — is `em/graph/model.py`, which writes no file and imports neither `json` nor `html`; the four renderers (`export_json`, `export_dot`, `export_canvas`, `export_html`) are `em/graph/export.py`, and `export_json` is a thin write over `build_graph_payload`; the viewer is three assets (`em/graph/assets/graph.html`, `graph.css`, `graph.js`) read through `importlib.resources` and **inlined** at export, so a written `graph.html` is still one self-contained file. **No behaviour change:** the assets reassemble to byte-for-byte the monolith's `_HTML_TEMPLATE`, and the body gate's error message still names the export path (the model takes the caller's name for it). `pyproject.toml` declares `em.graph` in `packages=` and the three globs in a new `[tool.setuptools.package-data]` block. `entropicmem.py`, `scripts/graph_server/server.py` and every graph test import from `em.graph.model` / `em.graph.export`; the six suites that scraped the template out of the Python source now read the assembled assets through one helper, `tests/harness/graph_assets.py`. **7 new tests** (`tests/unit/test_em605_graph_split.py`); **8 mutation checks, all red**, each restored from a byte copy; local counts bare **2860 / 16 / 2**, digest **2861 / 15 / 2**, CI-equivalent 3.12 **2938 / 2 / 2**, CI **2936 / 4 / 2** read at `2fd7812`; 3.10 leg green (135 passed); ruff clean. **One process incident, recorded:** the first local measurement ran before the seventh test existed, so the three local triples and the CI projection were each written one low — CI's own read caught the discrepancy and the figures above are the corrected ones. **At that point slice 2 of the card — entity nodes and relation edges, the time slider over `valid_from`/`valid_to`, the owner-only scope filter and dashed superseded edges — was the next chunk; it was then split into five slices, all five committed locally (2.1–2.5) with the card's build complete and unpushed; EM-606 followed it (`575eb06`, also local).** |
| 43 | **The EM-605 slice-1 follow-up: packaging verified where it ships, the figures measured not typed, and the warm AC's absolute ceiling** | **Done, merged** (`5258b46` on branch `em-605-followups`, ff-merged to `main`; **11/11 check-runs green on the exact SHA**; CI 3.12 **2954 / 4 / 2**, read from the job log with all four legs identical, `windows-import` 1762 passed). **P1, packaging:** the viewer assets are now a declared package (`packages=` gains `em.graph.assets`, the data globs key on it), which removes setuptools' "importable package absent from `packages=`" warning on the exact mechanism the wheel depends on; the wheel and sdist build clean, `unzip -l` lists all three assets byte-identical to the tree, and **the export was run from the installed wheel in a clean venv outside the repo** (88,785-byte `graph.html`, 2 nodes/2 edges, zero unresolved placeholders, no source-tree path in the output). 5 new tests + 5 mutation checks all red. **A pre-existing gap found and recorded, not fixed:** the wheel omits the flat engine modules (`memory_engine.py`, …), so `import em.graph` from an installed wheel fails on `em_internal.index` — it predates the split (the deleted `graph_export.py` made the same import) and belongs to EM-806; the catalog's directory-copy install is unaffected. **P2, the figures:** `scripts/record_suite_figures.py` measures the three local variants (plus 3.10) from pytest's summary lines, refuses a red run or out-of-order counters, refuses figures that break the host-pin and digest arithmetic, and writes `docs/plan/suite_figures.json`; `tests/test_suite_figures.py` fails when BASELINE's rows, ladder, read-as-at SHA, the CI run id, the CHANGELOG's CI figure or **any triple in the five documents** disagrees — the incident's shape. 13 new tests, 5 of them on the parser (`failed` prints before `passed`, so a naive scan reads a red run as green), and **6 mutation checks all red** (a row drifting by one, the record drifting from BASELINE, a ladder that stops adding up, the read-as-at SHA drifting, the ordering rule leaving the legend, the CHANGELOG's CI figure drifting). **P3, the ceiling:** the EM-603 budget is now `min(max(300 ms, 5% of cold), 2000 ms)` — the ratio cannot see a slowdown that hits both phases, and the ceiling is the only bound that can; timings now print on every run via `warnings.warn`. 3 new tests + 4 mutation checks all red. **P5, the gaps:** BASELINE now names the two host-pin tests CI never runs and records that closing it needs a scheduled host job; Python 3.10's **full suite** is measured (2954 / 4 / 2) rather than the touched files. Counts bare **2878 / 16 / 2**, digest **2879 / 15 / 2**, CI-equivalent 3.12 **2956 / 2 / 2**, 3.10 **2954 / 4 / 2**, CI **2954 / 4 / 2** projected. **Not started, recorded:** EM-605 slice 2's five feature slices (entity/typed-relation model, owner-only scope filter with the leak test, time slider, dashed superseded edges, the 5k AC) are the next chunk — see `NEXT_CHUNK.md` Part B. |
| 44 | **EM-605 slice 2.1 — entity nodes and typed relation edges from both stores** | **Committed locally, not pushed** (`69dc223`, 2026-10-20; no CI run exists, so the CI figure is projected). One read-only loader (`em/graph/source.py`) over `memory.db` with an **explicitly required** `scope_profile` (no default, so "all profiles" cannot arrive by omission; a missing or foreign DB is `available=False` with a path-free reason, and the file is never created); entity ids prefixed `entity:` so the two id spaces cannot join (a fixture where an entity id *is* a note id stays two nodes — `memory_entities` links memories, not notes); typed node colours by kind and stable SHA-256 predicate colours (not salted `hash()`); every non-edge relation (literal object, closed interval, out-of-profile endpoint, cap-trimmed endpoint) counted in `meta.entities`; the model re-checks both endpoints even for a hand-built graph; `body_coverage` counts notes only, so `--include-bodies` keeps its gate. `graph export --entities` is opt-in, html/json only, dot/canvas exit 2; the owner-only filter and byte-level leak test are slice 2.2, and until then the flag exports the whole named profile. 19 new tests (both stores real), **12 mutation checks red**, one absorbed by design (the model's second endpoint guard, the loader having already closed the set). Counts bare **2911 / 19 / 2**, digest **2912 / 18 / 2**, CI-equivalent 3.12 **2993 / 2 / 2**, 3.10 **2991 / 4 / 2**, CI **2991 / 4 / 2** projected; the figures record is refreshed at `69dc223` with `ci_run: ""`, and the guard now rejects a record older than the newest suite-surface commit. |
| 45 | **EM-605 slice 2.2 — the owner-only scope filter with a byte-level leak test** | **Committed locally, not pushed** (`1e5b739`, 2026-10-20; no CI run exists, so the CI figure is projected). Entities and relations have no user column, so ownership is attributed through the store: an entity survives `scope="owner"` when at least one `memory_entities` link points at a profile-wide memory in its profile, or when it has no memory link at all (an entity row is profile-wide; an unattributed manual entity is owner data); a relation survives when its `memory_id` is empty and both endpoints are visible, or when it resolves to a profile-wide memory in the same profile. A user-scoped, missing or cross-profile source fails closed; a guest-sourced edge between two owner entities is hidden; a hidden endpoint hides the relation. Filtering runs before degree and the entity cap, so a hidden row neither consumes a slot nor lends degree. `meta.entities` counts `hidden_entities` / `hidden_relations` by number only — no id, name, alias, predicate or endpoint — while shape/cap losses stay in `dropped_relations`; aliases ride only the survivors. `graph export --entities` gains `--scope {owner,all}` (default `owner`); `--scope all` is the explicit opt-in and the loader refuses any other value. The viewer's stats line reports the scope and filters nothing. The leak test builds a same-profile owner/guest fixture and scans the whole JSON and HTML output (embedded JSON and the sibling `graph.json`), plus a viewer-asset baseline check, for every guest id, label, alias, predicate, endpoint, memory id and the guest user id, with the owner side present as a positive control. 12 new tests (31 in the slice suite); **13 mutation checks red, none survived** — the node filter removed alone and with the relation filter, the no-link clause removed, the relation-memory filter removed, cross-profile fail-open, the endpoint loss miscounted and uncounted, hidden rows serialized, an unknown scope accepted, the CLI ignoring `--scope all`, the CLI defaulting to all, the scope key dropped from meta, and any-link attribution — each restored from a byte copy. Counts bare **2923 / 19 / 2**, digest **2924 / 18 / 2**, CI-equivalent 3.12 **3005 / 2 / 2**, 3.10 **3003 / 4 / 2**, CI **3003 / 4 / 2** projected; the figures record is at `1e5b739` with `ci_run: ""`. The bare privacy guard reads 6 passed / 1 skipped (the private list is absent at its default path); the digest run reads 7 passed. |
| 46 | **EM-605 slice 2.3 — the relation time window over `valid_from` / `valid_to`** | **Committed locally, not pushed** (`e08694a`, 2026-10-20; no CI run exists, so the CI figure is projected). Closed relations are no longer dropped at load: the read-only loader reads every relation in the chosen profile, open or closed. `em/graph/model.py` builds an inclusive rank axis from the surviving relation edges — `meta.entities.time` carries `available`, `min`, `max`, `stops` and `unparsed_relations`; every relation edge carries `time_span: [startRank, endRank]`. Null `valid_from` is −∞ (`-1`), null `valid_to` is +∞ (`len(stops)`), both null means no span (timeless and always visible), equal boundaries share one rank, and a bound that does not parse leaves the edge visible in every window while incrementing `unparsed_relations`. The viewer adds a two-handle `Time window`, defaults to the full axis and restores it on Reset; it filters relation edges only, so entities stay and note edges are never time-filtered. Window-hidden edges are counted by the viewer as `timeHidden` and displayed “N outside time window” — never added to the server-side `hidden_relations` scope count; the scope filter remains in Python, so client-side time hiding cannot reintroduce a non-owner row. 9 new tests (**40 in the slice suite**), including the rewritten 2.1 closed-interval test; **17 mutation checks red, none survived**, each restored from a byte copy. Counts bare **2932 / 19 / 2**, digest **2933 / 18 / 2**, CI-equivalent 3.12 **3014 / 2 / 2**, 3.10 **3012 / 4 / 2**, CI **3012 / 4 / 2** projected; the figures record is at `e08694a` with `ci_run: ""`. The bare privacy guard reads 6 passed / 1 skipped; the digest run reads 7 passed. |
| 47 | **EM-806 — S8 packaging: the wheel ships the engine, and a pip install loads the provider** | **Done, merged** (opening docs `1e683c1`, build `bf2e267`, record pass `ceb70cb` on branch `em-806-packaging`; ff-merged to `main` as `ceb70cb`; **13/13 check-runs green on that exact SHA, `identity-guard` included, and again on `main`'s post-landing push**) The card: the host's `hermes_agent.memory_providers` entry point (`entropicmem = entropicmem_plugin:register`), the plugin shell shipped as a **package** so the host still resolves `config_schema.py`/`cli.py` from its directory (`find_provider_dir` returns a directory only for a package), `py-modules` carrying the flat engine modules `em`/`em_internal` import — the chunk-43 finding that `import em.graph` from an installed wheel fails inside `em_internal.index` — `plugin.yaml`'s `requires_hermes: ">=0.21.3"` (the first host release with `spawn_context_thread` + `RecallStatus`) and `pip_dependencies: []`, the optional extras documented, and a pip-install smoke step in the existing `plugin-validate` CI job that installs the wheel and loads the provider through the host's own entry-point loader. **No runtime behaviour changes** — no tool, hook, schema, config key or store change — so the catalog-review surface is untouched. |


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

**Nothing is in flight.**

**EM-806 — S8 packaging — is COMPLETE: LANDED on `main` at `ceb70cb` (2026-10-27, chunk 47)** —
opening docs `1e683c1`, build `bf2e267`, record pass `ceb70cb`; **13/13 check-runs green on that
exact SHA and again on `main`'s post-landing push**, which includes the card's own new
`plugin-validate` pip-install smoke step (it installed the wheel, resolved the
`hermes_agent.memory_providers` entry point and loaded the provider through the host's loader).
The card, from the master plan's §S8: the provider is discoverable by a pip install
(`entropicmem = entropicmem_plugin:register`), the shell ships as a **package** (the host
resolves `config_schema.py` and `cli.py` from its directory, so a bare module would lose the
dashboard panel and `hermes entropicmem`), `plugin.yaml` carries `requires_hermes` (the first
host release with `spawn_context_thread` + `RecallStatus`, `0.21.3`) and an explicit empty
`pip_dependencies`, the wheel ships the **flat engine modules** the `em`/`em_internal` packages
import (chunk 43's gap: `import em.graph` from an installed wheel failed inside
`em_internal.index`), and the optional extras are documented. **No runtime behaviour change** —
no provider tool, hook, schema, config key or store change — so the catalog review's surface is
untouched. The build record is Part A of `docs/plan/NEXT_CHUNK.md`; the figures live in
`docs/plan/BASELINE.md`.

**Status of that build (2026-10-27):** one code commit, `bf2e267` — `py-modules` carrying the
derived nine-module closure, the `hermes_agent.memory_providers` entry point, the
`entropicmem_plugin` package (with `exclude-package-data` so the engine is not shipped
twice), `plugin.yaml`'s `requires_hermes`/`pip_dependencies`, both READMEs' extras sections
and the `plugin-validate` pip-install smoke step. **9 tests, 13 mutation checks all red,
none survived**, each restored from a byte copy; `ruff check .` clean; the wheel was built
and inspected (`uv build --wheel` → 9 flat modules, 5 shell modules, the entry point, the
assets) and installed into a throwaway venv where `import em.graph` works, `import
entropicmem_plugin` fails only on the absent host, and a stubbed host contract makes the
installed `register(ctx)` yield the provider. The figures of record (measured, in
`docs/plan/BASELINE.md`) are bare **3049 / 20 / 2**, digest **3050 / 19 / 2**,
CI-equivalent **3146 / 2 / 2**, 3.10 **3144 / 4 / 2**, and CI **3144 / 4 / 2** **read** from
run `40521965355`'s `test (3.12)` job log on `ceb70cb`.

**The S7 write-path security pair — EM-703 + EM-705 — is COMPLETE: LANDED on `main` at
`17684d9` (2026-10-23):** code `859f12d` (EM-703: `injection_screen.screen_text_windows`
screens every store write in overlapping windows, `evaluate_injection` turns flagged shapes into
the card's decision — extracted sources quarantine by the write policy's own reason, direct
sources are pending from birth, a drop is an audited refusal on both routes, and every unusable
policy member — or an unpackable policy — fails open to `flag`; the provider forwards the typed
trust policy to every write and carries it in every extraction enqueue) and `b570065` (EM-705:
`purge` also deletes the memory's vector rows and invokes an optional schedule-projection
callback inside the erase transaction, so a hard erase takes the embeddings with it and
schedules the vault's one regeneration). **43 new tests and 30 mutation checks, all red**, each
mutant restored from a byte copy. The figures of record live in `docs/plan/BASELINE.md` and
`docs/plan/suite_figures.json` — CI's figure is **read** there from the landing run
`39957746506`'s `test (3.12)` job log (13/13 jobs green on `17684d9`, and again on `main`'s
push), which is exactly what the host-pin relation projected from the CI-equivalent. The build
tip's own run `39951235609` was red on the figures-guard pair alone — the record then named
`e4910c7` and these figures were not yet in it, the documented pre-stamp shape — and the record
pass `f7fb7a1` landed the figures into the record before the landing ran. **The branch is
deleted once this record pass lands; nothing else is in flight.**

**EM-607 — ingest v2 — is COMPLETE and LANDED on `main` at `5f0670c` (2026-10-21)** — built at `af0cf98` on `em-607-ingest-v2`, fast-forwarded after 13/13 green check-runs on the branch tip (`5f0670c`), branch deleted. It is the last of S6's six cards, and its build is a replacement rather than an addition: the v2 `ingest` path wrote a literature note plus **one permanent note per capitalised phrase**, and that pass is gone. A source now makes **one chunked note under `Sources/`** (`note_type=literature`, `source=ingest`), and what it teaches becomes **`pending`** memories (`source=ingest`, the URL as `evidence`, `pending_reason=ingest_requires_review`) — the review queue EM-604's vault edits land in, so a fetched article never writes straight into durable recall. **New `em/ingest/`:** `html_text.py` is a stdlib `html.parser` pass that drops `script`/`style`/`nav`/`footer`, keeps headings and list items, decodes charrefs and survives malformed input; `article.py` holds the two caps (**2 MiB** refusal, **60,000-character** truncation at a paragraph boundary, recorded in the note), paragraph chunking (~4,000 chars, oversized paragraphs split at spaces), Appendix C.6 key points and claims through the EM-501 LLM seam per chunk (<=3 chunks, <=10 each, `evidence_quote` must be a verbatim substring) with a deterministic sentence scan as the fail-soft fallback, the note body, and `queue_claims` (store writes through `engine.remember(source="ingest")` -> the policy's new `ingest_requires_review` quarantine; mentions linked through **`EntityLinker`**, so a new phrase stays a proposal until a second memory and no mention ever becomes a note). The claim set *is* the key-point set, which is what makes "<= 10 pending" a property of one path. `cmd_ingest` gains `--no-llm`, keeps `--domain` (frontmatter + claims), and **never creates a memory store**: with none present it writes the note and says `source note only`. The v2-store path is kept (`pending_facts` via the same policy branch) because the owner's live store is v2. 30 new tests in `tests/unit/test_em607_ingest_v2.py` (the AC is one: a 50 KB article -> **1 source note, <= 10 pending, 0 entity rows and no note outside `Sources/`**), and the three `tests/test_phase2.py` ingest pins are repointed to the new contract instead of the atomic-note one (its runner also stopped inheriting `ENTROPICMEM_*`, which could reach the live store). **20 mutation checks, all red**, each restored from a byte copy. **CI:** the branch run `39666424863` on `e0f39a5` is **13/13 green** and its 3.12 job log reads **3092 passed, 4 skipped, 2 xfailed** — the read figure of record, matching the projection exactly; the build commit's own run `39661990213` was red on the figures guard alone (the ancestry assertion the re-stamp satisfies). One job needed a recorded re-run: `test (3.13)`'s numpy 50k search guard read best 27.97 ms against 25 ms on a contended runner (3.5 ms on this box, every window inflated); the re-run of the same SHA was green. **Landed branch-first:** four docs commits on `em-607-ingest-v2` after the code commit carry the record (the figures re-stamp, the run-id allowlist and the read CI figure), the tip `5f0670c` is **13/13 green** and was fast-forwarded into `main`, and this paragraph is the post-merge record. Two jobs across the landing needed a recorded re-run, both on tests this card does not touch: the numpy 50k search guard on `test (3.13)` (best 27.97 ms against 25 ms, every window inflated by the same ~8x; 3.5 ms on this box) and `windows-import`'s EM-405 rewind-budget pin (0.296 s against 250 ms, the second instance of the documented Windows-only flap); each re-run of the same SHA was green.

**Graph label typography, truncation and hover-to-expand — kanban task `t_113a29d5` (`frontend-fucker`):** merged to `main` in this merge (branch commit `0d02d96`) — Space Grotesk labels at a radius-scaled 10–14px below each node, measured-ellipsis truncation at the default node width, hover/focus expand to full title and collapse on blur, WCAG AA 13.67:1 dark / 11.37:1 light (expanded 17.70:1 / 15.48:1), real-browser verified with no console errors. **Graph pan with drag and momentum/inertia — kanban task `t_e7765a5e` (`frontend-fucker`), in flight on branch `wt/t_e7765a5e`:** empty-canvas drag pan with decay-based inertia on release, clamped bounds and clean teardown, implemented in `plugins/entropicmem/scripts/em/graph/assets/graph.js` (d3.zoom's wheel/programmatic zoom is extended, not replaced). **Edge strength → edge opacity/width — kanban task `t_29357af7` (`frontend-fucker`):** COMPLETE — per-edge stroke opacity (0.2–0.9) and width (1–2 px, below the node's 2.2 px selected border weight) map the model's per-edge `weight` via the pure helper in `em/graph/assets/graph-strength.js`, unit-tested in `tests/unit/graph-strength.test.js` covering min, max, equal and missing strength. No model, strength-data or layout change; real-browser verified in both themes with no console errors; graph suites pass. **Edge highlight on node hover — kanban task `t_ae0f95fe` (`frontend-fucker`), COMPLETE —** on node hover, every edge connected to that node is highlighted — stroke opacity boosted toward the top of the visible band while preserving strength ordering and keeping directional gradients visible — and non-connected edges dim slightly but stay visible. Short CSS transition (150ms), respects `prefers-reduced-motion`, restores on mouse leave / blur. No new palette tokens, no node styling or layout change. Layers on the strength-based opacity and directional gradient work from `t_29357af7` and `t_b32ee9d6`. Real-browser verified in both dark and light themes with no console errors; `node --check` clean; graph suites pass (74 tests). Nothing else is in flight. Chunk 43, the EM-605 slice-1 follow-up, landed 2026-10-19 (`5258b46`; 11/11 check-runs green on the exact SHA, CI 3.12 2954 / 4 / 2 read there):
**EM-606 — graph server hardening, round 2 — is COMPLETE: landed on `main` 2026-10-21 at `73bed69`, all 13 check-runs green on that exact SHA (and green again on the post-merge `main` push — 26/26 across both runs).** The card's four clauses, as they landed: **(1) reads are read-only** — every read endpoint opens `index.db` through a new `VaultIndex(..., readonly=True)` (`mode=ro`), so a GET can no longer create, migrate, chmod or WAL-write the file; a missing index raises instead of being created by a request, and a reader that meets an older schema refuses with the remedy. `/refresh` stays the one writer because rebuilding the index is its job, and the split is pinned per endpoint. **(2)** `/api/search` is rate limited by a one-key token bucket at the card's **10 rps** (burst = rate, continuous refill, 429 + `Retry-After`), placed after the token check and covering search only. **(3) sensitivity redaction** uses the write policy's own tier rule (`normalize_sensitivity`: Finance / People / Events sensitive by default) and its own `redact_for_prefetch`: `/api/note`, `/api/note/by-title` and search snippets serve the `[sensitive] …` summary, and `/refresh`'s export (`graph.json` and the bodies inlined into `graph.html`) is built with the new `redact_sensitive=True`, so the bytes a browser receives are redacted at the source. The static CLI export keeps full bodies deliberately (`--include-bodies` is its opt-in). **(4)** the per-run token already rotated on restart (EM-114) — pinned, not rebuilt. The card's scope clause is recorded as **not applicable to this server today** (it serves vault notes, which carry no `scope_user`; the memory-side scope is the exporting CLI's choice, and the loader's owner-only default is pinned in the EM-605 suite). 15 new tests; **15 mutation checks red and one equivalent recorded** — the equivalent is the tier guard replaced by `if True`, which cannot change a response because `redact_for_prefetch` is itself tier-aware. `tests/conftest.py` gains an autouse fixture giving each test a fresh search bucket (the limiter is per process). Figures at `575eb06`: bare **2943 / 20 / 2** (the new module is one fastapi skip in the bare venv), digest **2944 / 19 / 2**, CI-equivalent 3.12 **3040 / 2 / 2**, 3.10 **3038 / 4 / 2**, CI **3038 / 4 / 2** **projected**. **The next card is EM-607 — ingest v2**; nothing is pushed and no CI run exists for the local commits.

**Main moved while this line was built, and the two lines are merged now (`b99437a`).** Fourteen commits landed on `origin/main` in the meantime — the graph-UI work (relationship-strength stroke weight, directional gradient strokes, hover highlight, label typography, theming, the pan/rAF loop) and the EM-603 reindex-chain fix (`3a594e0`, `6edb431`, PR #11). Two conflicts were both-sides-appending records (`CHANGELOG`, `MASTER_TODO`: both kept, nothing dropped); the real one was `edgeColor`, where main's new gradient helper returned the muted token for every non-directional edge and so dropped the typed predicate colour a relation carries — reconciled to keep both (**gradient** for wikilink/triple edges, **`d.color`** for entity relations, `var(--edge)` otherwise) with the slice 2.1 pin repointed from the old one-line helper to that claim, and a CHANGELOG Fixed entry recording it. Figures re-measured on the merged tree at `b99437a`: bare **2960 / 20 / 2**, digest **2961 / 19 / 2**, CI-equivalent 3.12 **3057 / 2 / 2**, 3.10 **3055 / 4 / 2**, CI **3055 / 4 / 2** **projected** — +17 tests from main's work.

**The line is pushed for CI on `em-605-606-landing` (owner-approved 2026-10-21).** Run `39612171910` on `aa9a451` read **12/13 jobs green** — every test leg (3.10–3.14), `windows-import`, `lint`, `evals-ci`, `bench`, `perf-smoke`, `plugin-validate`, `semantic-st` — with CI's 3.12 count **3055 / 4 / 2**, exactly the projection. **CI caught one of this line's own tests:** the `/api/search` 429 test bet on wall-clock speed, so ten requests on a slow runner outlasted a token interval and the eleventh was allowed; the clock is now frozen in that test (the bucket's refill was already unit-tested with an injected clock), 40/40 locally including slow runs. **The one red was `identity-guard`, and it is not this line's:** the whole history contains exactly one non-noreply commit — `14925b3` (2026-10-20, author/committer `kanban-kat@localhost`), a kanban worktree merge already on `main`, whose tip `a46adda` was red on the same check (run `39465614611`). Published history is never rewritten, so the owner approved a **named exception by full SHA** in `scripts/check_commit_identity.sh`; `tests/test_identity_guard.py` pins both directions — a new commit from the same address still fails, and the entry must still be needed or it has to be removed. 7 new tests, **4 mutation checks red**. Figures re-measured at that commit: bare **2967 / 20 / 2**, digest **2968 / 19 / 2**, CI-equivalent 3.12 **3064 / 2 / 2**, 3.10 **3062 / 4 / 2**, CI **3062 / 4 / 2**, **read** from that run's 3.12 job log (not projected). **Landed 2026-10-21:** the branch was fast-forwarded into `main` as `73bed69`; on that exact SHA **all 13 check-runs are green** — `identity-guard` included, after the named exception — and the post-merge `main` push re-ran them green on the same SHA (26/26 across the two runs). One job needed a re-run and is recorded rather than hidden: `perf-smoke` read warm p95 **21.643 ms** against its 20 ms budget on its first attempt (p50 5.25 ms, two 164/295 ms outliers on a path this branch never touches — prefetch), the gate's own failure text names that flap class and instructs a re-run, and the re-run on the same SHA was green. The branch `em-605-606-landing` was deleted after the merge; **EM-605 and EM-606 are complete**.

**The cited-SHA guard now resolves a citation by reachability, not by object existence — landed on `main` at `06c39fd` as its own landing, split from the 2026-10-20 dependency round.** `tests/test_cited_shas.py` asked `git cat-file` whether a cited token named a commit, so a clone that still held an unreachable commit object (the rebased-away `cb88d47` that `docs/plan/BASELINE.md` uses as its worked example) would fail the guard even though the published repository never had that commit — a contributor who fetched before the force-push could turn a green citation red. The guard now asks which commits a reader of the repository could actually check out: reachability from any ref plus `HEAD`, and a shallow clone is refused with the remedy rather than silently scanning a partial history. CI read **13/13 jobs green** on the exact SHA — run `39640594895`, 3.12 leg **3062 / 4 / 2**, unchanged — and the post-merge `main` push re-ran them green on the same SHA (`06c39fd`). **Mutation-tested both directions:** a clone holding the dangling object fails the old existence-based resolution; a fresh clone is green. The honesty test `tests/test_cited_shas.py::test_the_allowlist_entries_are_still_cited_and_still_do_not_resolve` fails if an entry stops being cited or starts resolving.

**The drift found during slice 2.2's refresh, and the fix:** the security-hardening commits after `5258b46` added 17 tests (14 passing, 3 skipping) without re-measuring, so the pre-slice tree carried more tests than the record and the record's bare triple summed to 2896. The guard could not see it because it compares documents to the record, never the record to the tree. The refresh folds an ancestry check into the existing read-as-at test: the newest commit touching `tests/` (excluding `tests/test_suite_figures.py` itself), `conftest.py` or `pyproject.toml` must be an ancestor of the recorded SHA. The recorder also learned to clear an inherited CI run id (`--ci-run ""`), which a projected record needs, instead of silently citing the previous run against new figures.

**Chunk 43, the EM-605 slice-1 follow-up, landed 2026-10-19 (`5258b46`; 11/11 check-runs green on the exact SHA, CI 3.12 2954 / 4 / 2 read there):
the viewer assets declared as a package so the wheel ships them warning-free (and the
export verified from an installed wheel outside the repo), the figures of record now
measured by a script and checked by a guard instead of hand-typed into five places, and
an absolute ceiling on EM-603's warm AC so a uniform slowdown cannot hide behind the
ratio. Counts bare **2878 / 16 / 2**, digest
**2879 / 15 / 2**, CI-equivalent 3.12 **2956 / 2 / 2**, 3.10 **2954 / 4 / 2**, CI
**2954 / 4 / 2** projected. **At that point slice 2 of EM-605 — the entity/typed-relation model, the
owner-only scope filter with its leak test, the time slider, the dashed superseded edges
and the 5k AC — was the next chunk; it was split into five slices, all five now committed
locally (2.1–2.5), so the card's build is complete and unpushed.**

**EM-605 slice 1 — the graph monolith split into `em/graph/model.py`, `em/graph/export.py` and the three viewer assets — **landed
2026-10-19 (`2fd7812`, on `em-605-graph-split`, then ff-merged and the branch deleted;
11/11 check-runs green on the exact SHA, `identity-guard` and `windows-import` included, and
the post-merge `main` push re-ran the eleven green on the same SHA).** No behaviour change:
the assets reassemble byte-for-byte to the old `_HTML_TEMPLATE`, `graph_export.py` is
deleted rather than shimmed, and the wheel now declares `em.graph` and its assets. 7 new
tests, **8 mutation checks all red**; CI 3.12 **2936 / 4 / 2** read at `2fd7812`, local bare
**2860 / 16 / 2**, digest **2861 / 15 / 2**, CI-equivalent **2938 / 2 / 2**. **At that point slice 2 —
entity nodes and relation edges, the time slider over `valid_from`/`valid_to`, the
owner-only scope filter, dashed superseded edges — was the next chunk; 2.1–2.5 are now
committed locally, so the card's build is complete and unpushed.**

- Graph viewer theming (kanban t_152eada8) — COMPLETE: plugins/entropicmem/scripts/em/graph/assets/graph.css repaired on branch wt/t_566b902e-fix (additive [data-theme="light"] token block over intact origin/main; all pre-existing rules preserved; theme toggle wired in graph.html/graph.js). Committed as d39f20a4a9e80c4c02f63b6b7e118088b713be97 and pushed to origin/wt/t_566b902e-fix. Browser-verified in both themes over HTTP via the canonical export path; text contrast passes WCAG AA in both modes (13.67:1 dark / 11.37:1 light); thin edges below 3:1 in both modes is pre-existing stroke/opacity, flagged for t_b56c89dc. Children t_b56c89dc/t_113a29d5 unblocked.

**Chunk 41 — EM-604, the opt-in ingestion of human vault edits —
landed 2026-10-19 (`31a7323`, on `em-604-vault-ingest`, then ff-merged and the branch
deleted; 11/11 check-runs green on the exact SHA, `identity-guard` included; one recorded
`windows-import` re-run flake on the same SHA — EM-603's 5k AC, not EM-604 code).** 15 new
tests, **11 mutation checks all red**, each restored from a byte copy; CI's 3.12 count
**2928 / 4 / 2** read at `31a7323`, local counts bare **2852 / 16 / 2**, digest
**2853 / 15 / 2**, CI-equivalent 3.12 **2930 / 2 / 2**; the record is the Part A block in
`NEXT_CHUNK.md` and the CHANGELOG's `[Unreleased]`/Added entry. **EM-603's 5k AC is
de-flaked** (landed 2026-10-19 as `adb1439`, branch `em-603-deflake` deleted; 11/11
check-runs green on the exact SHA, `windows-import` included, and CI 3.12 reads
**2929 / 4 / 2** there): the AC now measures a same-run ratio with the card's 300 ms as its
floor, and the walk's no-per-note-`resolve` half is pinned structurally; +1 test, bare
**2853 / 16 / 2**, digest **2854 / 15 / 2**, CI-equivalent **2931 / 2 / 2**, 3 mutation
checks all red; the same commit makes the CI record unambiguous in `BASELINE.md` (a legend
and the CI-versus-local gap stated where the table is read). **Chunk 40 — EM-603, the
incremental index — landed 2026-10-18
(`338ec2a`), after chunk 39 (EM-602, `607d54f` + `c29addc`), chunk 38 (`c53b182`),
EM-608 (`3b71cf0`) and EM-601's both halves (`bdc1e20`, `e986059`) the same day; **the next
chunk is EM-605 slice 2, the graph's entity nodes, relation edges, time slider and scope
filter — slice 1 landed 2026-10-19 (`2fd7812`) and its follow-up (chunk 43: packaging,
figures, the warm ceiling) landed 2026-10-19 (`5258b46`).** Everything
below records what just landed.**

**EM-601 (vault projection, both halves) is COMPLETE — the owner's word, 2026-10-18**
("you make the logical calls on the build", target named as chunk 36 = EM-601 slice 1;
slice 2's go explicit the same day). **One card, not a stage — the rest of S6, S7,
security and packaging stay gated** (see the open scope question in `NEXT_CHUNK.md`):
dev-line work only, nothing touching the live store, every other
owner-gated item below still gated. It is the one gate `docs/plan/STOP_HERE.md`'s
ruling table deferred to the owner, and it has been given and discharged: **slice 1
`bdc1e20`, slice 2 `e986059`, both on `main`.**

**EM-601 slice 1 — the vault projection engine, S6's first card — LANDED (2026-10-18,
`bdc1e20`; branch `em-601-projection`, ff-merged, deleted; 11/11 check-runs green on
that exact SHA and the merge's 11 re-ran them on `main`).** The chunk ledger row above
carries the full state; in short:

- `em/vault/projection.py` (new package `em.vault`): `project(conn, root, scope,
  modes)` renders `Entities/<Name>.md`, `Journal/<date>.md` and `Memories/Unfiled.md`
  from the store, and `lint(root)` reports projected files whose auto-sections are
  unsafe. Only marker-to-marker bodies are ever replaced — frontmatter, the human
  region, the gaps, the trailing text and unowned sections are byte-preserved; a
  marker-less file is left untouched and reported, never recreated over the user's
  prose; an unchanged render writes nothing (mkstemp + `os.replace`, temp unlinked on
  failure).
- **Forgetting erases rather than hides:** a fully-forgotten entity is still visited so
  its page is rewritten down, a relation renders only while its source memory is live,
  and the unfiled page and a day's journal page follow the same rule.
- **Recorded deliberately:** §3.5's owner-only tiers never reach a plaintext file,
  regardless of scope (strengthening — CHANGELOG says so); the read clause is otherwise
  `MemoryStore.list`'s own (F-004); two names that sanitise to one filename are told
  apart by entity id, entities ordered by id so filenames never move; **one root per
  scope**.
- **EM-601 slice 2 — LANDED (e986059, on main; all 11 check-runs green on the exact SHA)** — `em/vault/schedule.py` (new) carries the `project_vault` job handler, the 60 s debounce with `MAX_WAIT_SECONDS` ceiling and the follow-up chain for mid-projection writes, and `modes_for()`; `vault.projection` default flips to `none`; the provider enqueues on `_remember_v3`, `_update` and `_forget_one` inside the write transaction; `KNOWN_JOB_TYPES` gains `project_vault`; `build_registry` registers it drift-free; the CLI gains `vault lint --root <path>`; `CLI_REFERENCE.md` and `README.md` move the count 36→37. **18 new tests** (`tests/unit/test_em601_slice2_schedule.py`), all green; **5 mutation checks, all red**; suite **2758 / 16 / 2** bare, **2759 / 15 / 2** with the digest list, **2836 / 2 / 2** CI-equivalent; `ruff` clean; privacy scan clean. **Deferred, recorded:** `Memories/Unfiled.md` month paging past 200 rows — a policy decision, not code.
- **Evidence:** 31 new tests (`tests/unit/test_em601_projection.py`), **10 mutation
  checks all red** (the tier predicate dropped; `forbid_tiers` default flipped;
  `sensitive` let through; the human region dropped; the trailing text dropped; a
  fully-forgotten entity never revisited; the relation's source-memory liveness guard
  removed; a marker-less file recreated over the user's prose; `lint` blind to
  projected files; the unchanged-on-disk comparison dropped), each restored from a byte
  copy; bare **2737 / 16 / 2**, digest **2738 / 15 / 2**, CI-equivalent 3.12
  **2815 / 2 / 2**, CI **2813 / 4 / 2** read from the job log at `bdc1e20` (all four
  legs identical); ruff (`0.16.2`) clean; the new package and its tests green on 3.10;
  the privacy word-hash scan of every changed file found no collision.

**EM-608 — the 50k warm-p95 gate's statistic (chunk 37) — LANDED (2026-10-18,
`3b71cf0`; branch `em-608-perf-gate`, ff-merged, deleted; 11/11 check-runs green on
`headSha=3b71cf09`).** The two warm-p95 ACs each took **one** p95 over 25 probes, so
the gate's verdict moved with the runner: on unchanged SHAs it flapped to p95
153.35 ms (`6e86c98`) and 151.09 ms (`bdc1e20`), each green on a rerun. The fix is
EM-407's, generalised into one shared helper (`tests/harness/perf_stats.py`):
`window_p95` (the gate's own nearest-rank definition), `timed_windows(run,
windows=5, probes=20)` and `best_window_p95`; both ACs now read the **best** of five
20-probe windows and must hold the same **150.0 ms** budget — a transient contention
is absorbed, a genuine regression still fails every window, and every window's p95
is emitted as a warning on green runs too. 8 new tests; **6 mutation checks, all
red**, each restored from a byte copy; **no product code changed**. The chunk ledger
row above carries the full state.

**Standing note carried forward (2026-10-17):** the OpenCode box's live v2 store was
found in real use (1 fact, 21 audit rows, same-day `backups/memory_*` to 15:48Z) —
runtime activity, provably not the suite, attribution still open with the owner.

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
- **EM-501 landed (2026-10-16, `2a6a892`): the formation LLM backend layer
  (§3.7).** `em/formation/llm.py` — four backends (the host's auxiliary client,
  an openai-compat urllib client, `none`, and `auto`'s selection order), the
  tiny-validator parse (malformed or schema-violating JSON is `None`), per-task
  timeouts, a 5-consecutive-failure/10-minute **circuit breaker** with one probe,
  and the sliding hourly **cost guard** (`formation.max_llm_calls_per_hour`).
  Hard fail-soft and counted; `wrap_transcript`/`UNTRUSTED_TRANSCRIPT_NOTE` carry
  §3.7's untrusted-data rule; the three host auxiliary-task keys register from
  the shell (guarded). 10 tests; 7 mutation checks red. Next: EM-502.
- **EM-502 slice 1 landed (2026-10-17, `2576dcc`): the deterministic extractor.**
  `em/formation/rules.py` + `extract.py` — first-person, correction and
  commitment rules; Appendix C.1's candidate shape (verbatim evidence, assistant
  claims capped at 0.6); ≤ 6,000-char segmentation with one-turn overlap; the
  evidence-substring guard both paths share; the model path on the EM-501 seam.
  `evals/datasets/extraction.jsonl` (55 synthetic transcripts) backs the
  **CI-gated rule-path precision ≥ 0.8**; the LLM F1 harness is measured, not
  gated. 11 tests; 6 mutation checks red. **Slice 2 next:** register the
  handlers, carry the turn's scope into the write, add the scope-consistency test.
- **EM-502 slice 2 landed (2026-10-17, `1f88e8f`): extraction runs as a job.**
  `em/formation/extract_jobs.py` + `EpisodeStore.read_chunks`; candidates are
  quarantined `pending` (both origins use the `auto_extracted` policy source, so
  an LLM delegation cannot bypass it); the provider carries its **effective turn
  scope** (`_turn_scope()`, not `agent_identity`) in the payload and the handler
  refuses a scope-less job; both types join `KNOWN_JOB_TYPES` and
  `BUILT_FORMATION_HANDLERS`, opening EM-411's capture gate. Scope-consistency
  test included. 8 tests; 6 mutation checks red. **Next: EM-503.**
- **EM-503 landed (2026-10-17, `597aac8`): reconciliation and the commit policy.**
  `em/formation/reconcile.py` — the deterministic decision engine (NOOP /
  SUPERSEDE by changed attribute / UPDATE by ≥ 0.92 cosine with equal
  numbers+negations / ADD), the C.2 model path (CONFLICT is the model's unsure
  verdict), the §3.7 step-3 commit policy, and `apply_decision` over the store's
  versioned writes; `MemoryStore.set_trust_flags` records conflicts. The rule
  path scores **≥ 0.9** on the `update` and `contradiction` categories of
  `evals/datasets/reconcile.jsonl` (29 synthetic cases). 9 tests; 6 mutation
  checks red. **Next: the wiring (top-5 neighbour retrieval + a reconcile pass
  over the pending queue), then the S5 exit criteria.**
- **S5 complete (2026-10-17, `d331c5e`) — and development stopped here** *(the
  owner opened the F-004 remediation within the day; it landed as `c30aa54` —
  see "In flight").*
  EM-501 (the LLM backend), EM-502 (extraction, both slices) and EM-503
  (reconciliation + commit policy, core + wiring) are on `main`, with the
  `sync_turn` transcript capture that completes the formation chain and the
  session-1 → session-2 learning harness that proves the exit criteria. Counts
  at the stop: bare **2679 / 16 / 3**, digest **2680 / 15 / 3**, CI-equivalent
  **2757 / 2 / 3**, CI **2755 / 4 / 3**. **No chunk was queued at the stop** —
  see
  [docs/plan/STOP_HERE.md](docs/plan/STOP_HERE.md); the rest is owner-gated.
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

**Nothing agent-owned is left to build: every card in S5–S8 has landed, and the file is
waiting on the owner's release call.** The last code card — S8's EM-806 packaging — landed
2026-10-27 (`ceb70cb`, recorded through `0482a49`; the branch and read-pass commits are in
§11). What §6.5 still holds is **S9**, and both of its cards are release acts:

- **EM-901 — the upgrade drills.** v2.3 / v2.5 / v2.7 / 2.8 fixture DBs and vaults → 3.0:
  `doctor` clean, eval parity, legacy ids resolvable, and sync between a 2.8 and a 3.0
  profile (publish/pull) either verified or documented as requiring both upgraded; the
  report is `docs/UPGRADING.md`.
- **EM-904 — the 3.0 release.** Version everywhere, migration notes, the `SKILL.md` bump,
  the tool rename with aliases, the catalog re-pin (a PR) and the announce.

The drills validate an upgrade path to a release the owner has not scheduled, and the
release itself is owner-gated end to end (§3.3; `docs/MARKETPLACE.md` has the procedure).
The v3 cutover is likewise the owner's call, the live store stays v2, and no destructive
embedding run is scheduled. **A fresh owner instruction is the usual go.** §11 is the
cold-start page, `NEXT_CHUNK.md` Part B records the same recommendation, and §6.6's third
use is the written one.

<details>
<summary>Historical: how this section read while S6 was still being built (not current)</summary>

**Chunk 38, the content-ceiling fix, is landed (`c53b182`), chunk 39, EM-602 in
both slices (`607d54f`, `c29addc`), and chunk 40, EM-603 the incremental index
(`338ec2a`) — and **chunk 41, EM-604 (opt-in ingestion of human vault edits), is complete
(landed 2026-10-19 as `31a7323`), so the next chunk is EM-605 slice 2 (the graph's entity
nodes, relation edges, time slider and scope filter); slice 1 landed 2026-10-19
(`2fd7812`) and chunk 43 (its follow-up) landed the same day (`5258b46`).** Chunk 38 fixed the silent `remember`
truncation
the 2026-10-17 incident exposed (one shared `CONTENT_MAX_CHARS = 8_000`, a fatal-oversize
refusal instead of a clamp); EM-602 hardened the vault's frontmatter and wikilink handling
(escaping writer, delimiter rule, PyYAML-or-subset reader, the new
`em/vault/frontmatter.py` shimmed by `em_internal.vault`) and made `note_id` the full
vault-relative path with the `index.db` `user_version` 2 migration; EM-603 made an index
refresh read only a note whose file stat moved (`index.db` `user_version` 3), added
`entropicmem index refresh` and the `reindex_vault` job a projection schedules — a 5k vault
with one change refreshes in ~30 ms against the card's 300 ms. Dev-line work;
the manifest and the catalog pin did not move. **EM-601 and EM-608 are complete** — EM-601's
slice 1 (the vault projection engine, `bdc1e20`) and slice 2 (the `project_vault` job, its
debounce, the mode switch, and `vault lint`, `e986059`), and EM-608 (the 50k warm-p95 gate
now reads the best of five 20-probe windows at the unchanged 150 ms budget, `3b71cf0`).
The **S6 scope question is answered yes** by the owner's 2026-10-18 instruction that the
agent make the outstanding calls: **EM-602…EM-607 are agent-owned**, taken in the
documented §6.5 order, with **EM-605 next** (EM-604 landed 2026-10-19; EM-605 slice 1 landed the same day as `2fd7812` and chunk 43, its follow-up, landed
the same day (`5258b46`); slice 2.1 landed locally at `69dc223`, 2.2 at `1e5b739`, 2.3 at `e08694a`, 2.4 at `6936574` and 2.5 at `0c40385`, all unpushed; **EM-606 (graph server hardening, round 2) landed with them at `73bed69`**, and
**EM-607 (ingest v2) landed at `5f0670c`** — with it the agent-owned S6 list is
finished, so the next piece is the owner's to name: S7 security, EM-806 packaging and S9's drills/release are all gated,
and the release needs the owner's want, not an agent's.

</details>

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

**Nothing is in flight; there is no build to start.** Every card in S5–S8 has landed — the
last was S8's EM-806 packaging on 2026-10-27 (`ceb70cb`, recorded through `0482a49`) — and
what remains is **S9**: the upgrade drills (EM-901) and the 3.0 release (EM-904), which are
release acts the owner owns end to end. The v3 cutover is the owner's call; the live store
stays v2; no destructive embedding run is scheduled. Read §11 for the state, `## What is
next` above for why nothing is queued, and `docs/plan/NEXT_CHUNK.md` Part B for the §6.6
recommendation. **A fresh owner instruction is the only thing that opens a new chunk.**

<details>
<summary>Historical: the S6 build order as it stood on 2026-10-19 (not current)</summary>

**Chunk 40 — EM-603, the incremental index — is merged (`338ec2a`, all 11
CI jobs green on the exact SHA, `windows-import` included — the branch-first landing of
`em-603-incremental-index`: the stat diff, the `os.scandir` walk, `index refresh` and the
`reindex_vault` job; tests first, CHANGELOG, push, check-runs,
`git merge --ff-only`, branch deleted), **and chunk 41 — EM-604, the opt-in ingestion of
human vault edits — landed the same day (2026-10-19, `31a7323`: 11/11 check-runs green on
the exact SHA, one recorded `windows-import` re-run flake), **EM-603's 5k AC was de-flaked
the same day (`adb1439`, all 11 check-runs green on the exact SHA, `windows-import`
included), and EM-605 slice 1 — the graph model / renderers / assets split — landed the same
day (`2fd7812`; 11/11 check-runs green on the exact SHA, `windows-import` included;
`graph_export.py` deleted, `em/graph/` in its place, the three
viewer assets packaged and inlined at export, no behaviour change), so the next chunk is
EM-605 slice 2 (the graph's entity nodes, relation edges, time slider and scope filter).** On top of chunk 39 (EM-602 in both slices, `607d54f` + `c29addc`),
chunk 38 (the `remember` content
ceiling, `c53b182`), EM-608 (`3b71cf0`, the 50k
warm-p95 gate's *statistic* via the shared `tests/harness/perf_stats.py`) and EM-601's
both halves the same day (slice 1 the vault projection engine
`bdc1e20`, slice 2 the `project_vault` job, its debounce, the mode switch and
`vault lint` `e986059`). Before them,
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
(`a5b613a`). **EM-406, EM-407, EM-408, EM-409, EM-410, EM-411, EM-412, EM-601 and EM-608 are complete.**

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
   (all landed), and **EM-601 is complete — slice 1 landed as
   `bdc1e20` and slice 2 as `e986059` — EM-608 (`3b71cf0`) after it, chunk 38, the
   `remember` content-ceiling fix (`c53b182`), after that, chunk 39, EM-602 in both
   slices (`607d54f`, `c29addc`), after that, and chunk 40, EM-603 the incremental index
   (`338ec2a`), after that** (the owner's word,
   2026-10-18, authorised one card each; the owner's later instruction to make the
   outstanding calls answered the S6 scope question yes) — the
   recorded-owed candidates were the EM-303 prune follow-up (**landed
   2026-10-17 as the prune card, `99151d3`**), `_shadow.py`'s printed-caveat
   one-liner (fixed in `26265ef`), and the adapter/eval gate (rides the
   cutover). **P0c's data** (item 2 below) still
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
   (3.12): `pytest -q tests/` → **2813 / 4 / 2** —
   **read green from the job log at `bdc1e20`** (the EM-601 slice 1 landing:
   +31 `tests/unit/test_em601_projection.py` guards over `99151d3`'s verified
   2782/4/2, itself the +12 prune guards over `d92503d`'s 2770/4/2 over
   `c30aa54`'s 2769/4/2), with the extra set
   fastapi/httpx/cryptography/pyyaml, numpy, and the private digest list as the
   repository secret; this box bare: `.venv311/bin/python -m pytest -q` →
   **2737 / 16 / 2** (measured at `bdc1e20`); with the digest
   list in place:
   `ENTROPICMEM_PRIVACY_DIGESTS_FILE=… .venv311/bin/python -m pytest -q`
   → **2738 / 15 / 2** (measured); CI-equivalent 3.12 with
   the extras and the digest file → **2815 / 2 / 2** (measured) —
   all three agreeing with the derivation. The xfail pair is 2 since the
   F-004 flip. The 77-passed gap is
   per-module accounted in NEXT_CHUNK's pre-flight (67 fastapi + 7 cryptography
   + 2 numpy + 1 privacy). `git merge-base --is-ancestor d92503d HEAD` and
   `99151d3`'s own tip position prove the base.
4. **Two commits** (code, then docs), then **check-runs on the exact SHA** — not
   `run list`, which can hand back a stale green.
5. **The cutover decision is (a)+(b) complete and back with the owner.** Bring the
   evidence and the recommendation; do not switch the live store. One decision rides
   it: the **adapter-defaults unification** — holdout mrr **0.86508 spec** vs
   **0.88095 calibrated** — explicitly not unified in S4.

</details>

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
query-embedding wiring, closing the recorded gap); the F-004 remediation
(`c30aa54`) landed — and **the EM-303 prune card landed later that day
(`99151d3`), closing the owed prune**. **EM-601 is complete — slice 1 (the vault
projection engine) landed 2026-10-18 as `bdc1e20` and slice 2 (the `project_vault`
job, its debounce, the mode switch and `vault lint`) the same day as `e986059` — and
**EM-608, the 50k warm-p95 gate's statistic**, landed
the same day as `3b71cf0`, **chunk 38, the `remember` content-ceiling fix**, the same
day as `c53b182`, and **chunk 39, EM-602 slice 1 (frontmatter & wikilink robustness)**, the
same day as `607d54f` — so nothing is in flight and the next chunk is EM-602 slice 2 (the
note-id change and the `index.db` migration; the owner's instruction to make the
outstanding calls made the S6 cards agent-owned).** The
recorded-owed list is emptied of the prune (the remaining candidates —
`_shadow.py`'s printed-caveat one-liner, already fixed in `26265ef`, and the
adapter/eval gate that rides the cutover — still slot with the owner; the
ceiling card is now built).** P1 is done and P3
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
* **Supersession end-to-end through the provider — CLOSED (2026-10-16,
  `9370ce6`).** `tests/unit/test_em_supersession_e2e.py` drives a real
  supersession through the `entropicmem_update` tool and asserts the wired
  `prefetch()` block's §3.6 `was:` note, with three mutation checks red. The chain
  EM-502/EM-503 will feed is now covered before they build on it.
* **Recorded gaps to card separately:** §3.6's `query_rewrite` has no call site
  (wire it or mark the config key deferred); `recent`'s "current session" half
  needs a session id `RetrievalContext` does not carry; EM-211's seven CLI
  refusals each name the card that lifts them. Draft cards in
  [plan §6.4](docs/plan/REMAINING_PLAN.md).
* **`diversity.render_superseded_note` had no product caller (found 2026-10-16 while
  mutation-testing the supersession e2e card) — DELETED 2026-10-27 (`ae08dd0`).** The
  provider renders its own `was:` note (`em/provider/render.py`) and that is the wording
  users see, so the diversity copy was dead weight — and the dead one was the
  **unescaped** one, interpolating a stored summary into a block while the shipped
  renderer wraps it in `escape_untrusted`. Deleting it leaves one renderer and one
  wording; the served-render test pins that diversity no longer mentions it and that the
  served note still escapes (3 mutation checks red). No behaviour change.

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
| Tests | `python -m pytest -q` | **Zero failed.** The expected counts, their legend and the four named CI skips live in **one place**: [`docs/plan/BASELINE.md`](docs/plan/BASELINE.md). The triple is `passed / skipped / xfailed`; **`failed` is always 0 on a green run.** This page states no figure of its own — a chunk updates `BASELINE.md` only. |
| Lint | `ruff check .` under the CI pin `ruff==0.16.2` | clean |
| Evals | `evals run --suite ci --compare evals/baselines/v2.8.0-ci.json` | no gated metric regressed |
| Performance | `evals.perf --sizes 1000 --probes 20` | prefetch warm p95 ≤ 20 ms |
| Identity | CI `identity-guard` | every commit a noreply address |

Run the suite with `ENTROPICMEM_MEMORY_DB`, `ENTROPICMEM_VAULT_PATH` and
`ENTROPICMEM_INDEX_DB` unset. **The expected triple, its legend, the four named
CI skips, and why the three local readings differ from CI (the two hermes-agent
host pins that pass on a dev box and skip in CI — the middle column moving, not
the total) live in [`docs/plan/BASELINE.md`](docs/plan/BASELINE.md); read the
figure there, this page keeps none of its own.** The extras change what is
collected and skipped, which is the environment, not the tree (0 failures
locally). **Every performance red so far is fixed by statistic or ratio, never by
weakening a budget:** the two 50k warm-p95 ACs read the best of five windows
(`dc3c77a`, `3b71cf0`), and EM-603's 5k-refresh AC reads a same-run ratio with the
card's 300 ms as its floor (the CHANGELOG's Fixed entry). The total rises with
every card; a mismatch against `BASELINE.md` means stop and report, not "assume
the older number is right".

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
was green. **A second instance landed on 2026-10-21:** EM-607's landing tip (`5f0670c`)
tripped the same pin at **0.296 s** against the 250 ms enqueue budget on a cold Windows
runner (the leg took 8:57); the re-run of the failed job on the same SHA was green.
**A third instance, 2026-10-18:** the main-push re-run of `bdc1e20` (EM-601
slice 1) tripped `test (3.13)`'s `test_warm_p95_at_50k_is_under_150ms` at p95
**151.09 ms** — 24 of 25 samples under the budget (135–159 ms, p50 144): the
same mildly inflated distribution, 0.7% over. The same SHA's branch run had
been green, both later docs commits' 3.13 legs (`00abbdc`, `8125126`) were
green, and the rerun of the failed job went green in ~4 minutes. **This AC sat within
1% of its budget on shared runners and flapped twice in two days — the tell stays a
uniformly inflated p50, not a stall tail.** **Both of these are now fixed by
statistic, not by rerun: EM-608 (`3b71cf0`) makes the prefetch AC read the best of
five 20-probe windows, so a single contended window no longer decides the gate, and a
genuine regression still fails every window. The 150 ms budget is untouched.**

**2026-10-18 — the defect, and its fix: `EM-608` (landed `3b71cf0`).** The
measurement *was* a tracked item, `docs/plan/PERF_GATE_CARD_DRAFT.md` (agent-owned,
one slot); the owner slotted it on 2026-10-18 and it is now **done**. Re-running a red
`main` job until it goes green was a workaround, not a fix: the gate's verdict
depended on which runner it landed on, so it did not gate. The card specified **a
statistic, not a rerun** (best-of-N windows — the exact fix EM-407 applied to the
numpy guard a test over), and it **forbade widening the 150 ms budget** — the fix
keeps the budget exactly and moves only the measurement. **Instances, with evidence:**
`test_warm_p95_at_50k_is_under_150ms` failed **twice** — 2026-10-16
(`6e86c98`, `test (3.10)`, p95 153.35 ms, all 25 samples 117–158 ms) and
2026-10-18 (`bdc1e20`, `test (3.13)`, p95 151.09 ms, run `39112375641`, job
`117631038052`). **A third was not found and cannot be**: re-running a failed
job **overwrites its log**, so a failure re-run to green leaves no artifact —
a sweep of every failed CI job's log from 2026-09-20 to 2026-10-19 returns zero
hits. **Record every instance when it happens; GitHub will not keep it.**
The 2026-10-15 3.13-leg flap was a *different* test (the numpy guard) and was
fixed by statistic, not rerun — the precedent EM-608 generalised to both warm-p95
ACs, tests and mutation checks in `tests/harness/perf_stats.py` and
`tests/harness/test_em608_perf_stats.py`. **2026-10-21 — the numpy guard again, and this one is a
contended runner, not a defect:** EM-607's docs re-stamp (`90d1fd0`) tripped
`test (3.13)`'s `test_50k_vectors_search_p95_under_25ms_with_numpy` with
**no window under 25 ms** — best **27.97 ms**, windows `[29.72, 28.6, 27.97,
29.88, 35.71]`, slowest probe 47.79 ms, on a leg that took 7:30. The tell is the
shape: **every** window inflated by the same ~8x while this box reads 3.5 ms in
all five (3.71/3.55/3.54/3.52/3.50), i.e. uniformly slow, not a stall tail — and
the best-of-five statistic was already doing its job, there was simply no good
window to find. The re-run of the failed job on the **same SHA** was green
(13/13 on `90d1fd0`). Recorded rather than silently re-run, per the note above.
The way to tell a flake from a
regression is a rerun of the **same** SHA. Never widen a budget, skip a test or mark
a job non-blocking to clear red.

---

## Open blockers (owner-only)

> **2026-10-18, later: the owner handed the outstanding calls to the agent, and they are
> made** (see the STOP HERE block at the top): P0c is **skipped**, the v3 cutover is
> **no**, the prune's destructive run has **nothing to run**, and releases/tags/the
> catalog re-pin are **not now**. The entries below remain the record of *why* each is
> irreversible or public — they are not open requests. The one live action is the
> content-ceiling fix (chunk 38), which is not an owner gate.

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
- **F-004 — full per-user isolation: RESOLVED and pinned (2026-10-17, `c30aa54`), no product code changed.** The finding's strict xfail
  `tests/regressions/test_findings_v27.py::test_f004_cross_user_isolation` is now a passing guard driving a v3 store (`_v3_store()`
  asserted on both providers), and `tests/harness/test_f004_shared_profile.py` pins the two-provider surface: write attribution,
  both-directions prefetch/search isolation, the five foreign-row refusals (update edit/supersede, forget by id and via the confirm
  token, the four review actions, search by ids), episode isolation, and the ruled profile-wide-sharing half. The audit found the v3
  line already bucket-clean — the leak the xfail documented was the v2 engine's, which has no scope columns and keeps pool semantics
  until the owner cutover. **The migration ruling (keep profile-wide) is pinned by the harness**; the ~1,700 migrated facts stay
  readable by the whole profile, and a single-user cut-over never needs a signed acceptance. **Recorded, not changed:** the episodes
  read rule is exact-bucket (no profile-wide half) — a profile-wide episode is under-read (never over-read) for a user-mode caller;
  its §3.5 semantic call rides the cutover card as a recorded decision item, never a silent default. **5 mutation checks ran red,
  two absorbed single-layer probes recorded; each restored from a byte copy.** (Also §9 item 9, `REMAINING_PLAN`.)
- **The EM-303 prune's first real destructive run.** The handler is now code
  (`99151d3`) and tests drive it only on tmp stores. Running `prune` (or the
  backfill that enqueues it) against a store that holds real vector rows —
  including the live migration's target — deletes those rows permanently.
  The owner signs that run separately; until then it never executes against
  anything real. **Also a proposed note the owner may want to act on:** the
  owner's one-word go for a first real prune should name the model set it
  prunes down to (the handler keeps current + previous; anything older is
  deletable once the grace has passed).
- **The live store on this box was found rebuilt and in live use
  (2026-10-17).** The September pair-proofs read 1627/1628 facts; the store
  now reads **1 fact** (created 13:21Z that day) with a 21-row audit trail
  (14 `remember`, 7 `forget`, actor `default`) and same-day
  `backups/memory_*` snapshots running to 15:48Z — including a
  remember→auto-backup→forget burst at 15:48:48Z. That is runtime (gateway
  principal) activity on this box, not suite activity: every
  `MemoryEngine` construction in the suite takes an explicit path, a
  structural guard bans default constructions, and this session's reads were
  `mode=ro&immutable=1`. The no-move pair (1 / 13:21:32) held across this
  session's suite runs. **Bottom line for future agents: never assume the
  store is empty or frozen — read the pair fresh before and after a run.**

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

- **2026-10-27 (EM-806 session): `2ff11c2` was pushed to `main` directly, before CI
  ran on it — a process slip, not a policy change.** It is a docs-only commit (the
  reconciled tip in this page and plan §11's Development line), and the push trigger
  then ran the full matrix on that exact SHA: **run `40528252379` is 13/13 green on
  `2ff11c2`**, so the gate holds in outcome. It is recorded rather than "fixed", because
  the only ways to make it look compliant are to rewrite published history (rule 9) or
  to pretend the branch existed. **The rule stands and every later commit in this
  session went through a branch with green check-runs on its exact SHA before the
  ff-merge.**

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
- **There is no live store data to read on this machine** was true through
  the September stops — **until 2026-10-17, when the store was found rebuilt
  and in live use** (see the Open-blockers re-up: 1 fact, a real remember/
  forget session, same-day backups). Do not trust this bullet's old shape;
  read the pair fresh.
- **No commit may carry a real email address.** Configure
  `Ufonik88@users.noreply.github.com` before committing, or `identity-guard`
  fails and a bad commit lands in published history.
