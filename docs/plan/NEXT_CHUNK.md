# EntropicMem: next steps (one chunk at a time)

**Updated:** 2026-10-16 (eighth pass — the EM-407 hardening pull: the owner's verification queue in four landed items, plus the query-embedding card drafted for approval). **`main` is at `dc3c77a` — the branch-first landing of `em-407-hardening` (Part A's last record has the detail: the 50k numpy AC guard now reads the best of five 20-probe windows — the 2026-10-15 3.13-leg flap (single-window p95 31.61 ms from one stalled window) is fixed by statistic, not re-recorded as a flake, and a real regression still inflates every window; `save_config` validates every key before anything touches disk (unknown keys refused; legacy spellings folded as the loader folds them), writes through a per-call `mkstemp` temp, cleans up on failure, and documents the Windows locked-destination contract; the spec/calibration default split is pinned as deliberate — adapter `None` = the pipeline's spec defaults, provider = EM-306's calibration (rrf 0.60→0.50, importance 0.15→0.25; gate identical); the 77-test count gap named per module; 8 new tests; all 11 CI jobs green on that exact SHA — CI's 3.12 count 2626/3/3, this box 2549/16/3 bare and 2550/15/3 with the digest list — then `git merge --ff-only`; branch deleted) — on top of the EM-407 typed-config landing (`2b21ad1`: Appendix A's typed model, §3.8's loader, the typed schema/save pair, EM-306's calibrated scalars at the call sites; 49 new tests; 11/11 green on the SHA), the EM-405 lifecycle slice (`e483d43`, which completes that card), the EM-404 validation slice (`5000942`, which completed that card), the slice-2 landing (`e5e54ef`), the slice-1 landing (`381197f`, the owner-chosen merge-into-branch path) and the chunk-35 merge (`a5b613a`). EM-403, EM-404, EM-405 and EM-407 are complete:** Chunk 33 (slice 1, `9f9ba0c`), Chunk 34 (slice 2, ff-merged as `31053df`, docs `007bb22`), **Chunk 35 (slice 3, second half, `a5b613a`)** — the synchronous fact block routes through `PrefetchService.prefetch` on a v3 store, gated on the v3 store **and** `ENTROPICMEM_V3_RETRIEVAL=1` (the decision and its reasons are in Part A); v2 stores are byte-identical by construction (golden captured from `e4fd865` in a detached worktree); the wire-level tests and the **AC re-run through the wired provider** are green (warm p95 40.58 ms @ 50k, cache-hit 0.09 ms, forced-slow 1.261 s partial, 7,648 chars, 50-turn replay 5,504 ≤ 13,500). The first half (`f674146` + `55f85ce`, pushed **directly to `main`, CI green post-push on both exact SHAs) is recorded in Part A with everything it deliberately did not do. **Nothing is in flight** (`em-407-typed-config` landed `2b21ad1`, `em-407-hardening` landed `dc3c77a`; both deleted). **Next chunk: EM-406 (checkpoint v2 / evidence archive) — the owner's S4 order: EM-406, then EM-411, then the rest by dependency (EM-408, EM-409, EM-410) — while the query-embedding wiring card (drafted 2026-10-16) awaits the owner's approval before any implementation; the candidates are laid out in Part B.** **Live retrieval is lexical — and stays lexical whatever the flag does: the query embedding is unwired (`ensure_embedding_model` has no live caller; the service is built with no `embed_query`; the served path passes no `query_vector`), an open gap whose card is drafted (2026-10-16) and awaits the owner's approval before any implementation — recorded in Part B; no semantic-retrieval claims before it.** **EM-411 (capture on idle & compaction)** follows EM-406, spec ready in plan §6.3, test-first and default off. P0c's data is still blocked on the owner's host. The cutover stays the owner's call.

**Owner decisions in force — the order was re-set on 2026-10-08** (`REMAINING_PLAN.md` §9 item 6):
1. **P0c — collect the shadow data.** The gating empirical step for the cutover. **Freeze before you look: do not fit a threshold to the sample, and report the raw distribution and the margin, not just a green light.** The observable is now fully armed, so a clean sample can conclude — it still needs the dev-line shadow on a host (the owner's machine is active).
2. **P2 / EM-306 — `evals tune`.** **DONE (2026-10-08, `4a2b25e`):** split by id hash, pre-declared grid, holdout reported, `em/config.py` committed, and the miss ceiling armed from the same holdout. **Hard constraint held: the gate does not depend on EM-301's 92.9%-on-42 intent table** (nothing intent-related is tuned).
3. **EM-307 — packer and renderer.** **Done, merged (`7d6a22e`).** A gated retrieval renders; the adapter does not call it.
4. **EM-303 — vectors.** **Closed and merged (`3439b77`); follow-ups merged (`42e16c7`); precision pass merged (`6d9bf3b`); observability pass merged (`60f0d67`).** Episodes embed, evals can embed, CI runs numpy, vector reads are version-checked, mode labels everywhere, vector baselines committed. **The chosen next chunk was EM-401–403 — and all three landed without wiring the query embedding, so the live path is still lexical; that wiring is now an open gap with no owning card (recorded 2026-10-15, Part B).** EM-411 follows.

**The ceiling ruling (§9 item 7), in force from `3c8b301` and executed by EM-306:** `max_v3_only = 0` is hard and non-negotiable — a fabricated hit is a correctness/safety failure. The miss side is its own ceiling, `max_v2_miss_rate`, **armed 2026-10-08 at `0.107143`** — `1 − recall@5` of the v2 adapter on EM-306's holdout split (`evals/results/tune-hard-4eb8097.json`), which is exactly what `_shadow.MISS_CEILING_RULE` pre-registered. **The rule states the relationship plainly: the shadow's rate is v3-vs-v2, the bound is v2-vs-truth applied to it — a policy choice, not an identity.** **Do not re-arm it from a synthetic sample** — that is evidence about the metric, not about turns. The un-armed shape (`None` → `not armed`, blocking `met`) still exists and is tested; a clean sample can now read `met`.

**Still in force:** **the cutover is the owner's call** — both re-decision conditions are met in code, and **"conditions met" is not "proceed"**. The **flag default flip is owner-facing**: staged, not pre-empted (the flip is one line plus the tests that pin default-off; the tuned scalars reached the provider's call sites with EM-407, `2b21ad1`). **CI's eval gate stays v2** — EM-306 made that call and wrote it on the `evals-ci` job: the adapter's own defaults remain the spec (EM-407 wired the provider, not the adapter — 2026-10-15; the split is pinned as deliberate since 2026-10-16, `dc3c77a` — `test_the_default_adapter_keeps_the_spec_and_the_runtime_ships_the_calibration` names both owners and the divergence: rrf 0.60→0.50, importance 0.15→0.25, gate identical), so a v3 gate today would enforce the spec defaults, not the calibration, and `tests/evals/test_adapter_v3.py` already protects v3 in the ordinary suite. **Chunk 13 is forward-only, ratified, internal only**; `release/2.8.x` carries no `em/`, so its only vehicle is 3.0. **Never write to the live store**; the readout and collector are read-only by construction and asserted so.

**Plan exactly one chunk.** Two commits: code+tests+CHANGELOG, then docs with the reconciliation folded in. `MASTER_TODO`'s `In flight` names no commit; `Last reconciled` names a permanent ancestor. **Verify CI with the check-runs API on the exact SHA** (`ghx api repos/Ufonik88/EntropicMem/commits/<sha>/check-runs`), never `ghx run list --branch main --limit 1`.

**The master plan is at `~/Documents/EntropicMem Dev docs/EntropicMem_v3_Master_Plan.md`.** EM-301…EM-306 plus §3.6/§4 are transcribed into `REMAINING_PLAN.md` §6.2.

---

## Part A: what has landed

### EM-306 — the calibration harness, and the miss ceiling it arms. **DONE, MERGED (2026-10-08, `4a2b25e`)**

- **The harness: `python -m evals tune`.** Split by id hash (`sha256(scenario_id)[:8] % 100 < 70` → dev; the rule and its concrete ids are recorded in the result file, so a rerun scores the same holdout), a grid declared in code before any run (`gate.min_score` × `gate.min_coverage` × three rerank-weight presets = 27 candidates), the card's objective on the **dev** split only, and a result file. Selection: highest dev objective; **ties prefer the candidate closest to the spec** — the first pass found a flat tie in the `min_score` band, so a flat objective must not move a threshold by accident.
- **One seam in the real pipeline, not a second pipeline.** `pipeline.retrieve` takes optional `gate_config`/`rank_weights` (defaults: the spec) and the v3 adapter threads them; tests pin that an override reaches the stage it names and that `None` is the spec.
- **What the run found.** 27 candidates, 44 dev scenarios / 126 turns; holdout 16 scenarios / 28 scored turns, never optimised. Gate thresholds **stayed at the spec's 0.30/0.34**; the rerank weights moved to `importance_heavy` (rrf 0.50 / importance 0.25 / recency 0.10 / confidence 0.10 / feedback 0.05) — dev mrr 0.917 → 0.919, **holdout mrr 0.865 → 0.881** with the same recall (0.869) and noise (0.115). Committed as `em/config.py` + `evals/results/tune-hard-4eb8097.json`; a test pins the two together.
- **The same holdout executes the pre-registered arming rule.** v2's recall@5 on it is 0.892857 → `max_v2_miss_rate = 0.107143`. The rule keeps the policy statement (v3-vs-v2 rate, v2-vs-truth bound, a policy choice not an identity), and a test pins the whole chain: holdout v2 recall → result file → `PROMOTION` → the rule text. **A shadow sample can now read `met`**; the cutover remains the owner's call.
- **Deferred, recorded in the result file:** per-intent `GENERATOR_WEIGHTS` tables (a 4×6 space the card does not name) and per-model cosine (grid empty until EM-303). **CI's eval gate stays v2**, decided here and written on the job (the tuned defaults reach the provider's call sites via EM-407, `2b21ad1`, but the adapter's own defaults remain the spec, so the gate still runs v2 — EM-401–403 landed without wiring them, recorded 2026-10-15).
- 18 new tests; **2090 passed / 3 skipped / 3 xfailed on 3.10 and 3.12**; `ruff==0.16.2` clean; v2 eval gate unmoved; **12 mutation checks, all as expected**.

### Chunk 20 — the ceiling split, by owner ruling. **DONE, MERGED (2026-10-08, `3c8b301`)**

- **The ruling, and why it was legitimate.** The symmetric `max_divergence_rate = 0.10` counted "v3 dropped a hit v2 had" exactly like "v3 invented one". Chunk 19's measured sample was **150 misses and 0 additions**, so the gate failed a system for being *more selective* — what EM-305's gate exists to do — while `v3_only_never`, the condition the observable calls decisive, passed on every line. The owner split it **before any real turn was read**, which is the only circumstance in which amending a frozen observable is not fitting it to the sample.
- **Fabrication stays hard:** `max_v3_only = 0`, and the render says on that line that a fabricated hit is a correctness failure, not a tuning one.
- **The miss side is its own ceiling and is `None` — NOT ARMED.** `max_v2_miss_rate` = ids v3 dropped / ids v2 injected (id-level, because a turn that kept 1 of 3 is a smaller failure than one that kept 0 of 3; the turn-level counts are printed beside it).
- **The arming rule is pre-registered in code**, as `_shadow.MISS_CEILING_RULE`: arm at **v2's own miss rate against a held-out reference** — `1 − recall@5` of the v2 adapter on **EM-306's holdout split** — committed with a comment linking the result file. (The first draft's "same corpus" wording was a category error, corrected in the trust pass below before any real turn: the bound is v2-vs-truth, the shadow's rate is v3-vs-v2.) The relative form was chosen over an absolute rate because no defensible absolute number exists before real turns, **and because it cannot be fitted to the shadow sample: it is measured on a different dataset.**
- **Un-armed is loud, never silent.** The miss rate is still reported, the arming rule is printed on every reading (render *and* `--json`), the verdict is `not armed`, and it **blocks `met`** — so the sample reads `cannot conclude`. An ungated dimension cannot be skimmed as a pass, which is exactly the accident the ruling forbade.
- **The retired number is still reported** (`context.divergence_rate_symmetric`) so the earlier finding stays comparable rather than restated: the same 240-turn sample now reads **38.46% id-level (150 of 390 ids), 90 of 240 turns, fabrication 0, verdict CANNOT CONCLUDE, exit 2**.
- **Mutation testing found a defect review did not.** The first id-level definition test used one id per turn, where id-level and turn-level rates are *numerically identical* — so two mutations (symmetric rate restored; silent switch to turn-level) **survived**. The fixture now injects 4/2/1 ids so the three candidate definitions disagree (4/7 vs 2/3) and the test asserts they are distinguishable. **26 mutation checks, all caught**, tree restored byte-identical.
- `tests/unit/test_provider_shadow.py`'s observable pin was updated **deliberately, not to get green**: it now asserts the split shape, that `max_v2_miss_rate is None`, that `max_divergence_rate` is gone for good, and that the arming rule is written down — with the ruling and its date in the docstring.
- 32 tests in `test_shadow_report.py` (rewritten around the split); **2061 passed / 3 skipped / 3 xfailed on 3.10 and 3.12**; `ruff==0.16.2` clean; v2 eval gate unmoved.

### Trust pass — the cited-SHA guard, the rule's policy wording, and repeated latency. **DONE, MERGED (2026-10-08, `085ab72` + `de495f2`)**

- **A guard for citations, because one was invented and only luck caught it.** A docs commit cited a SHA that did not exist (`7c2fdf9` records it); the document-control guard failed only because the token sat in the `Last reconciled` line. `tests/test_cited_shas.py` now scans every 7–40 char hex token in tracked markdown **and** in the messages of commits not yet on the base branch (`main`, then `origin/main`) and fails on any that does not resolve to a commit — with a closed, reasoned allowlist for the tokens that are cited on purpose and cannot resolve (the seven dead SHAs, the upstream fork commit, the tag-name date). The allowlist is itself pinned: an entry must stay cited and stay unresolvable, so it cannot become a place to park a real SHA. Published history is deliberately out of scope (never rewritten; cites dead and upstream SHAs). Sanity floors keep the scan from passing vacuously; 6 tests; **11 mutation checks all as expected**, including a blindness proof; one ruff find (an undefined name in the failure path) turned a crash into an assertion.
- **The arming rule now says what it always meant.** `MISS_CEILING_RULE`'s "same corpus" clause was wrong — the bound is measured on the eval holdout, the shadow's rate on real turns. The rule now names **v3-vs-v2** (the rate) and **v2-vs-truth** (the bound) and states that applying one as the other's ceiling is a **policy choice, not an identity**. **The threshold is unchanged: still `None`, still un-armed**, and every loud surface is unchanged.
- **The at-scale latency is a distribution now, not one number.** 11 read-only runs of 200 turns over the 1060-fact perf-bench fixture (source sha256 unchanged): **p95 2.59–2.74 ms in every run**; **every max is the copy-refresh turn** — 96.69–119.51 ms cold, 132.90 ms in the earlier single run — and **warm-run max is 3.83–4.52 ms**. The earlier lone "max 132.90" was the refresh, not a per-turn cost. This corpus is a **performance fixture only** and cannot support any quality claim.
- **The privacy collision check has now run locally, in place.** The list lives at `~/Documents/EntropicMem Dev docs/privacy-digests.txt` (10 × 64-hex digests); pointing `ENTROPICMEM_PRIVACY_DIGESTS_FILE` at it and running with `ENTROPICMEM_REQUIRE_PRIVACY_DIGESTS=1` gives **7 passed** — the first local run of the guard — and the full suite then reads **2073 / 2 / 3**. Nothing was copied into the repo, and with no list configured `REQUIRE=1` still **fails closed** (verified).
- 6 new tests; **2072 passed / 3 skipped / 3 xfailed on 3.10 and 3.12**; `ruff==0.16.2` clean; v2 eval gate unmoved (every gated ci metric identical).

### Chunk 19 — P0c's readout and collector. **DONE, MERGED (2026-10-08, `94dd3c7`)**

- **The readout lives beside the thresholds it uses.** `_shadow.evaluate / read_log / report / render / main` reads every value from `PROMOTION` **at report time** — tighten the dict and the verdict follows, which a copied literal could not. Same module, so the observable and its scoring cannot drift apart.
- **A green light has to mean something.** A short, **no-signal** or unreadable sample is never `met`: on a zero-fact store v2 injects nothing and v3 injects nothing, and a naive rate reads that as "0% divergence — promote". Conversely **a violation outranks a short sample** — one fabricated hit in three turns is `not met`, so "we need more data" can never dissolve a finding.
- **The writer's own fields are cross-checked, not trusted:** `stale` against the bound in *both* directions, `divergence`/`v3_only` against the ids recorded on the line. A disagreement refuses the reading instead of averaging it.
- **Distribution and margin, not just a verdict** (what the owner asked for): how much room each condition left (rates in points, not bare fractions), `p50/p95/max` together (the `perf-smoke` tell: a low p50 with a huge max is one noisy sample), the alternate denominators shown as context while the verdict uses the frozen one, the **miss/add decomposition**, and the first offending line numbers. **Findings cite line numbers and ids and never question text — in the render *and* in the `--json` body.**
- **`scripts/shadow_collect.py`: a real sample, no live write.** The source is opened `mode=ro` and copied with `sqlite3.Connection.backup`; the **real v2 engine** supplies `v2_ids`; the real S3 pipeline and the real migration run per turn. Asserted on **bytes *and* mtime** that the source does not move; the env it borrows is given back; a missing `--source` is refused rather than quietly degraded to an empty store. A test proves the ids *arrive*, because a stub returning `[]` would still exit 2 with "no signal" and look like a clean run.
- **Deliberate omission, recorded:** the runner is `python plugins/entropicmem/_shadow.py report`, **not** an `entropicmem shadow` CLI command. `plugins/entropicmem/__init__.py` imports `agent.memory_provider`, so the v2 CLI cannot import the provider package in a plain shell — and a test parses `_shadow.py` and fails if a module-level relative or host import is ever added there, since that would break the collector with no other symptom. Exit code: 0 met, 1 not met, 2 cannot conclude.
- **Measured, twice.** (1) The **actual live store** (zero facts, 12 turns): every condition reported, divergence `no signal`, verdict **CANNOT CONCLUDE**, p95 1.48 ms; the store's sha256 and mtime were identical afterwards. (2) A **temp store, 8 invented facts, 240 turns**: `turns` met (240/200), `copy staleness` met (max age 0.5 s), `v3_only` **met (0 lines)**, `p95` met (1.89 ms), `divergence` **not met — 37.5%** (90 of 240 turns).
- **The finding, and why nothing was tuned.** That 37.5% decomposes into **150 ids v3 missed and 0 ids it added**: v3 kept the strongest hit where v2 injected two or three. The condition the observable calls decisive passed on every line; the symmetric ceiling failed because it counts a miss like an addition — which is what EM-305's gate was built to do (the adapter measured noise 0.172 vs v2's 0.219 for the same reason). **The threshold was not moved.** The definition question goes back to the owner, **before real turns are read** (Part B, and plan §9 item 7).
- 36 new tests (26 + 10); **2055 passed / 3 skipped / 3 xfailed on 3.10 and 3.12**; `ruff==0.16.2` clean; v2 eval gate unmoved. **18 mutation checks: 17 caught first pass; one survived, and the survivor was a gap in my tests, not in the code** — the privacy mutation put the question text into the *findings*, and I had asserted only against the human render, not the `--json` that prints them. Both tests now check the serialised report and the mutation dies.
- **Also landed alongside:** a comment on the `evals-ci` job stating in the workflow itself that the gate runs **v2 only** by decision, that `--adapter v3` exists and scores, and that making v3 fail a build belongs with EM-306.

### Chunk 18 and earlier

P0b (`be6352e` — a v3 store serving prefetch from S3 behind `ENTROPICMEM_V3_RETRIEVAL`, with the gate's `kind='constraint'` bypass fix), P0a (`f0a7c70`), the v3 eval adapter (`ff0d3c3`), EM-305/304/301/302, the `visibility` fix. `REMAINING_PLAN.md` §5.

---

## Part A (continued): EM-307's library. **DONE, MERGED (2026-10-09, `7d6a22e`; code `6cd0943`)**

- **`em/retrieval/packer.py`.** `estimate_tokens` is `ceil(len/4)`. `pack` is greedy by score (tie: `owner_id` ascending). A row is kept in full when the rendered block fits, else its summary, else skipped. Default budget 450, passed in — `em/config.py` is not read.
- **`em/provider/render.py`.** §3.6's heading and five sections, empty sections omitted, empty selection is `""`. Citations are `[m·…]` / `[e·…]` via `em.clock.short_id`. A `was` field renders `(kind · updated <date>; was: <old>)`. `<memory-context` and `</memory-context` are broken with U+200B; a line whose first non-space is `#` gains a backslash. Flagged rows get the provider's injection warning; `on_flagged="drop"` exists and is not the default.
- **Deliberately not called.** Short ids would make `parse_injected_ids` miss stored ids. `pipeline.retrieve` still does not return collapse predecessors. P0b's served block is unchanged.
- **The tiktoken AC was measured and missed.** 222 characters of ordinary prose: cl100k/o200k/p50k/r50k all counted 42 tokens, the estimate said 56 (~33% high). A repetitive short-sentence sample was ~19% high. Conservative, so left in place. Not "fixed" with tiktoken or with a stopword sample that lands inside 15%.
- 13 new tests. **2103 passed / 3 skipped / 3 xfailed on 3.10 and 3.12** with CI's extras (fastapi, httpx, cryptography, pyyaml). `ruff==0.16.2` clean on the new modules. Five mutations went red (summary fallback, tag break, heading escape, score order, section order). **The v2 eval gate was not re-run** — the adapter was not touched. **Merged `7d6a22e`; all 12 check-runs green on that SHA.**

## Part A (continued): EM-307 wiring. **DONE, MERGED (2026-10-09, `7d6a22e`; code `a674383`)**

- **`Retrieval.predecessors`** is filled only on the gated path, and only for keys still present after MMR. An ungated `search` still has an empty map.
- **`load_pack_items`** reads `content` and `summary` as separate columns (the gate's concatenated text is for coverage, not the bullet), quotes the newest predecessor as `was`, and emits one follow-up row per open loop at a slightly lower score than the episode.
- **`render_retrieval`** packs that. Default citation is short. `cite="full"` is the seam that keeps `parse_injected_ids` honest. It is not what the adapter uses.
- **The adapter is pinned not to call it** (`tests/unit/test_em_retrieval_render.py` reads the adapter source). Served prefetch is unchanged.
- 7 new tests. **2110 passed / 3 skipped / 3 xfailed on 3.10 and 3.12.** `ruff==0.16.2` clean. Three mutations went red. **The v2 eval gate was not re-run**; the adapter's prefetch text did not change. **Merged `7d6a22e`; all 12 check-runs green on that SHA.**

## Part A (continued): EM-303, first slice — search stored embeddings. **DONE, MERGED (2026-10-09, `7d6a22e`; code `9d5a72b`)**

- **`em/store/embeddings.py`.** `pack_vector`/`unpack_vector` in native float32 (the layout v2 already writes); `cosine` is the plain normalised dot product — a zero or mismatched vector is 0.0, never a pretended similarity; `load_memory_vectors` is **one** joined query over active, in-scope rows; `count_active_memories` is the same-scope denominator. A corrupt blob is skipped, not raised.
- **`candidates.vector`.** Runs only with both a query vector and a model on the context, and only when `len(loaded) / active ≥ VECTOR_MIN_COVERAGE` (0.5). Ranks by cosine, ties on `owner_id`, caps at `k`. **Does not embed**; with no query vector it returns `[]` and issues no SQL.
- **The pipeline seam.** `retrieve(..., query_vector=…, embedding_model=…)` passes both to the generators and, **only when no `gate_config` was given**, enables the gate's cosine condition for that call. An explicit config is obeyed, including `cosine_enabled=False`. An unknown model gets no threshold — §3.6 names two, and the gate does not invent one.
- **What this slice is not, recorded:** no backends (`fastembed`/`sentence_transformers`/`openai_compat`/`none`), no `embed` job, no model-switch backfill, no numpy matrix cache (one read per search, not per candidate), no MMR cosine path (still token Jaccard). The eval adapter and the provider do not pass a query vector.
- 11 new tests. **2121 passed / 3 skipped / 3 xfailed on 3.10 and 3.12.** `ruff==0.16.2` clean. Three mutations went red: the coverage floor removed, cosine unnormalised, and the pipeline failing to enable cosine for a supplied vector. **Merged `7d6a22e`; all 12 check-runs green on that SHA (4 Pythons, lint, evals, perf, Windows import, plugin validate, identity).**

## Part A (continued): EM-303 — MMR's embedding path. **DONE, MERGED (2026-10-09, `000a268`; code `156370e`)**

- **`diversity.mmr`** takes `similarities: Optional[Callable[[Key, Key], float]]`, called as `similarities(candidate, chosen)` for every pair; the value is the redundancy penalty in `[0, 1]`. `None` — the default, and what every previous caller gets — is the token-Jaccard fallback. `texts` stays required either way, because the fallback is per-pair.
- **`pipeline._pairwise_similarity(vectors, texts)`** is the closure the pipeline passes in vector mode: cosine when **both** candidates have a stored vector, token Jaccard otherwise, and a negative cosine is clamped to `0.0` — an opposed pair must not earn a bonus. The pipeline loads the in-scope vectors for the model once (a second query; the cache card will fold this together) only when `query_vector` and `embedding_model` were both given.
- **Default path byte-identical:** no query vector means `similarities=None`, and every existing MMR test is unchanged.
- 4 new tests. **2125 passed / 3 skipped / 3 xfailed on 3.10 and 3.12.** `ruff==0.16.2` clean. Three mutations went red: the pipeline's similarity suppressed, the clamp removed, and `mmr` ignoring a supplied callable. **Merged `000a268`; all checks green on that SHA.**

## Part A (continued): EM-303 closed out — backends, jobs, model identity, cache. **DONE, MERGED (2026-10-09, `3439b77`; code `e8997d8`)**

- **Backends + selection.** Four backends, lazily importing their optional stacks; `auto` order fastembed → sentence_transformers → openai_compat; explicit-but-unavailable falls back to `none`. `openai_compat` posts via stdlib urllib with env config; `none.embed` raises rather than returning a misleading empty list.
- **Service.** Batches of ≤ 64; `summary or content` ≤ 2,000 (memories), `title + summary` (episodes); `warm()` idempotent; `embed_texts` refuses without a backend.
- **Jobs.** `embed` re-checks the row version **inside the write transaction** (a lease-expired duplicate that read v1 and embedded while v2 landed cannot clobber). `embed_backfill` pages 64, heartbeats, and records `meta.embedding_model` only on completion; `ensure_embedding_model` dedupes one job per model. Backend-less runs are clean no-ops, never dead jobs. The worker CLI registers both types.
- **Cache + 0005.** Snapshot per `(db, model, scope, mode)`; fingerprint `(count, max rowid, write generation)`, generation bumped by `put_embedding`. Numpy fast path or pure-Python fallback (identical ordering). Scope stays in `scope_sql` — the doc records why not masks. Migration 0005 adds `ix_embeddings_owner_model`.
- **Measured.** 50k × 128 warm search **p95 3.86 ms** (p50 3.68, max 3.88) against 25 ms; cold build 297 ms. The AC test and the numpy-agreement test skip without numpy (CI), like the fastapi tests without fastapi.
- **Recorded caveat.** A raw-SQL rewrite leaving count/max/generation untouched is not re-read until reset; pinned by a test.
- 34 new tests. **2157 passed / 5 skipped / 3 xfailed on 3.10 and 3.12.** `ruff==0.16.2` clean, repo-wide. Mutations red: selection order, batch cap, model record, write-time recheck, tie-break sort, fingerprint invalidation. Two first drafts survived and each was a real gap — the stale-job test lacked a race and the tie sort lacked an observable order — both fixed and re-run red. **Merged `3439b77`; all checks green on that SHA.**

## Part A (continued): EM-303 follow-ups — episode embeddings, evals query embedding, CI numpy. **DONE, MERGED (2026-10-09, `42e16c7`; code `51cdcb3`)**

- **Episodes are embedding owners.** `EpisodeStore.add_episode`/`upsert_episode` enqueue `embed` jobs `{owner_type: "episode", owner_id, stamp}`; `updated_at` is the version because episodes have no `version` column. The handler embeds `title + summary` and re-checks the stamp **inside the write transaction** (the same race guard the memory path gained). `embed_backfill` pages memories **and** episodes (`pending_embed_texts`); `meta.embedding_model` still records on completion only. The memory vector generator still ignores episode rows (they render through EM-307's sections).
- **Evals can embed.** `EngineV3Adapter(disable_embeddings=False)` — what `evals run` passes for any suite that is not `ci`/`hard` — embeds the scenario's documents at `load()` and the query in `_run()`, both into `pipeline.retrieve`. The frozen suites stay lexical byte-for-byte, and a `none` backend changes nothing.
- **CI installs numpy**, so `test_em_embedding_cache.py` (agreement, ties, fingerprint) and the 50k p95 < 25 ms AC run in the ordinary test job instead of skipping.
- **The owner-requested capture feature is planned as EM-411** (plan §6.3): compaction capture is the master plan's §4.6 step 4 ("enqueue `extract_window` over the persisted chunks") made real; idle capture is behavioural (`on_turn_start` gap ≥ `formation.idle_after_sec`), because **no host idle hook exists** in the pinned contract; both are gated by `formation.mode` and land after EM-406, before/with S5.
- 9 new tests. **2166 / 5 / 3** bare and **2168 / 3 / 3** with numpy on 3.10 and 3.12. `ruff==0.16.2` clean. Five mutations red: episode enqueue removed, both episode stamp guards removed, the backfill's episode branch removed, document embedding removed, query embedding removed. Two first drafts needed real fixes: the episode stale test now simulates the race (a replay is harmless because the handler re-reads), and the first mutation attempts hit the wrong call sites — both recorded. **Merged `42e16c7`; all checks green on that SHA.**

## Part A (continued): EM-303 precision pass — version-checked vectors, episode reads, mode labels. **DONE, MERGED (2026-10-09, `6d9bf3b`; code `e0b97da`)**

- **Version checks on every read.** Memory vectors serve only when `embeddings.content_hash` equals the memory's current `content_hash`; episode vectors only when their stamp equals `updated_at`; empty stored hashes are "unverified" (pre-EM-303 rows/fixtures) and kept. Reads filter to the query width, so a same-name artifact of another dimension is neither mixed nor a crash. `embed_backfill` writes real hashes/stamps.
- **Episode vectors are read.** `candidates.episodic` appends vector-ranked episodes under the same 50% coverage gate; the pipeline hands their cosines to the gate; `render_retrieval` prints them under "Recent episodes". Lexical and vector hits collapse to one row.
- **Backfill idempotence/resume pinned:** a replay rewrites nothing (`created_at` is the tell), and a mid-run failure leaves the first page intact with the second run completing without duplicates.
- **Mode labels:** `retrieval_mode` on every result (v2 and v3 adapters say what will actually run), `--compare` prints both modes and gates only within a mode, `tune` records its mode, and all six baselines carry `"lexical"` (ci/hard force embeddings off — by construction).
- **Status wording:** live retrieval is lexical until a query embedding is wired — EM-401–403 landed without it (recorded 2026-10-15), stated in `MASTER_TODO` and the plan.
- 12 new tests. **2178 / 5 / 3** bare and **2180 / 3 / 3** with numpy on 3.10 and 3.12. `ruff==0.16.2` clean. Seven mutations red (memory hash check, episode stamp check, width filter, episode recall, episode gate cosines, v3 mode label, cross-mode detection). **Merged `6d9bf3b`; all checks green on that SHA.**

## Part A (continued): EM-303 observability, promotion evidence, model hygiene. **DONE, MERGED (2026-10-09, `60f0d67`; code `514a6a5`)**

- Per-query `coverage`/`stale_excluded` logging on `em.retrieval.vectors` (WARNING when stale); stale→re-embed round trips pinned for memories and episodes; `tests/test_vector_ci_guard.py` keeps CI's numpy and both gated tests from vanishing.
- Vector-mode baselines committed (`v3-hard-vector.json`, `v3-ci-vector.json`) via the explicit `--embeddings` override; both comparisons cross-mode context-only. Old-model storage measured (≈2.1 KB/row, ≈21 MB/10k/set) and the prune policy decided (completed backfill + 7-day grace, EM-410 hosts it). Replay oracle = row count + whole-table sha256.
- 6 new tests; **2184 / 5 / 3** bare and **2186 / 3 / 3** with numpy; six mutations red. Full detail in plan §5.

## Part A (continued): EM-401 slice 1 — the §4.1 hook skeleton. **DONE, MERGED (2026-10-09, `db7c24f`; code `f8af1a9`)**

- **`em/provider/hooks.py` — `fail_soft`.** Every hook is wrapped: timed, counted (`hook.<name>` metrics), over-budget at WARNING, exceptions swallowed with the exception **type** logged and the detail at DEBUG only (a tool handler's message can carry the user's text). **Fail-closed on four hooks, a deliberate strengthening of the card:** `on_pre_compress` (§4.6 counts any non-raising return as a successful checkpoint), `initialize`, `save_config`, `backup_paths`. The card's hook that *should* fail soft does so in its own body — the skip and uninitialised paths already return `""` as §4.6 prescribes.
- **`em/provider/state.py` — `ProviderState`.** Session id, agent context, last recall count and the core baseline in one holder, with `writes_allowed()` holding the primary-context rule. The provider's `_session_id`/`_agent_context`/`_core_baseline` became properties over it, so no call site changed.
- **`em/provider/provider.py` — the §4.1 surface table.** Thread, budget and status per hook; `on_delegation`→EM-405 and `identity_signature`→EM-402 are the two deferred rows, each with a reason. `recall_status` and `unavailable_reason` are newly implemented, and the injected count now rides with the cached prefetch block.
- **The contract test (EM-401's AC).** `tests/test_provider_contract.py` + `tests/harness/pinned_memory_provider.json`: the host's `MemoryProvider` surface is pinned as a dated copy (CI has no host), re-derived and compared against the real host whenever it is reachable, and the provider is then checked against it — every method implemented or deferred, signatures still bind the host's calls, `pre_compress_checkpoint_api_version = 2`, and `provides_hooks` in `plugin.yaml` exactly the hook set the provider has.
- **The harness (EM-401's other AC).** `tests/harness/test_provider_hook_surface.py` drives the turn path through FakeHost with an author and the boundary/tool hooks directly, then reads the metrics: every implemented §4.1 hook ran, none recorded an error. `on_turn_start` now names the author trio, which is what makes the host pass it.
- **`_backend.bootstrap_scripts_path()`** puts the plugin's own scripts dir on `sys.path` at import time (same candidates as `resolve_scripts_dir`) so `em.provider.*` imports before `initialize()` has resolved a home.
- 37 new tests; **2221 / 5 / 3** bare and **2223 / 3 / 3** with numpy on 3.10 and 3.12; ruff clean; privacy guard clean in place; **13 mutation checks, all red**. Full detail in plan §5.

## Part A (continued): Chunk 30 — the `save_config` blank-home fix. **DONE, MERGED (2026-10-10, `6646351`)**

- **The defect.** `save_config(values, "")` computed `Path("") / "config.yaml"` — i.e. `./config.yaml` — and merged `plugins.entropicmem` into whatever `config.yaml` sat in the process working directory, then rewrote that whole file (comments and layout included). It now refuses a blank (or whitespace, or `None`) home and raises, matching the fail-closed shape §4.1 asks of `save_config`. **The host always passes `str(get_hermes_home())`**, which is never blank, so this is defence in depth rather than a live path — but guessing where to write a user's config is worse than not writing it.
- **Found by** driving EM-401's hook surface: the harness test called `save_config` with `""` ("no home needed") and dropped a `config.yaml` into the repository. The test now passes the fake home; the product fix came with it.
- **Two hygiene corrections from the same run.** `.gitignore` now covers `uv*.lock` — `git add -A` swept a stray `uv 2.lock` into a commit once (caught and amended before the push, never in history). And `AGENTS.md`'s mutation rule records the lesson: restore a mutation from a **copy**, never `git checkout -- <file>` — on a file with uncommitted work that discards the work, and on a new untracked file it fails and leaves the mutation applied. Both silent; the second contaminated EM-401's first mutation pass until copy-based backups replaced it.
- 2 new tests; **2223 / 5 / 3** bare and **2225 / 3 / 3** with numpy on 3.10 and 3.12; ruff clean; **3 mutation checks red** (guard removed; only `None` caught; guard moved after the path is computed).

## Part A (continued): EM-401 slice 2 — the provider moves. **DONE, MERGED (2026-10-10, `b8e170a`)**

- **The split.** `em/provider/provider.py` now holds `EntropicMemProvider` (every §4.1 hook, the seven tools, the post-v2 seam, the injection screen and the surface table) and `ProviderHost`, the ABC for the host glue. `plugins/entropicmem/__init__.py` is **145 lines**: `register` + a `MemoryProvider` subclass whose `_HermesHost` injects the plugin's path/config resolvers, the P0a shadow read, the host's context-propagating thread factory, its bounded tool-error formatter and `RecallStatus`.
- **`em` still imports no host and no plugin package** — `test_the_provider_implementation_imports_no_host` AST-scans the implementation, `test_the_plugin_package_is_a_thin_host_shell` pins the ≤150-line shell and that the class is not in it. The resolver seam still reads the shell's globals at call time, so the tests patching `plugins.entropicmem.resolve_scripts_dir` / `load_plugin_config` keep working through the split, and `spawn_context_thread` is resolved per call so the EM-103 fallback test still forces the named-daemon path.
- **Six source-scanning guards now read the implementation** — `PROVIDER_CALLS`, the raw-`MemoryEngine` drift guard, the deferred-import scan (now both files), the injection-marker text, the secure defaults, and the `_spawn`/threading rule. Each failed the moment the code moved; that is them working, and each was repointed deliberately rather than loosened.
- 3 new tests (2 layout guards, 1 tool-error seam); **2226 / 5 / 3** bare and **2228 / 3 / 3** with numpy on 3.10 and 3.12; ruff clean; privacy guard clean in place; **8 mutation checks, all red** (a host import in `em`; a 151-line shell; the class copied back into the shell; a bypassed config host; an unconsulted thread factory; tool errors skipping the host formatter; `recall_status` silent; an unconsulted shadow read).

## Part A (continued): Chunk 32 — EM-402 (ScopeContext & identity). **DONE, MERGED (2026-10-13, `2706a86`; code `7104bed`, docs `618c180`, windows fix `2706a86`, ff; 22/22 check-runs green on that SHA)**

### The chunk as built (planned here 2026-10-13; the plan below is kept as the record)

**Files:** `em/policy/scopes.py` (new `em.policy` subpackage — `ScopeContext` and the §3.5
resolution rules), `em/provider/identity.py` (`identity_signature()`'s config-file reader),
wiring in `em/provider/provider.py` + `em/provider/state.py`, the facade seam
(`open_engine`/`V3Engine` accept an optional `Scope`), and the new eval surface.

**What it builds (spec: §3.5, transcribed in the master plan at lines 455–468):**

- **`ScopeContext(profile, user, chat, chat_type, author, is_owner)`** — frozen dataclass,
  `from_init_kwargs(kw, config)` (reads the §4.1 init kwargs `agent_identity`, `user_id`,
  `chat_id`, `chat_type`), `with_author(author_id, is_bot)` per turn, `scope_key` (a stable
  sha256 over the six fields, for caches), `to_scope()` → `em.store.types.Scope`.
- **`scope_mode` resolution:** explicit config (`profile`|`user`|`chat`; an invalid value is
  logged once and falls back) > `user` when a gateway `user_id`/`chat_id` is present >
  `profile` (v2 behaviour preserved for CLI/primary sessions without gateway identity —
  the current default path writes profile-wide and must not move). In `user`/`chat` mode
  without a gateway identity the bucket is config `owner_user_id` (default `"owner"`) with
  `is_owner=True` — the plan's `meta.owner_user_id`, resolved from config because `em`
  reads no DB at resolution (recorded interpretation).
- **Per-turn author:** `on_turn_start`'s author trio drives `with_author`; a non-bot author
  is the user bucket for that turn's prefetch and for attribution of extracted memories;
  **bot authors never create user-scoped memories** (their writes go profile-wide).
- **`is_owner` stays EM-118's rule exactly** (guest iff `user_id` present *and*
  `owner_user_ids` non-empty *and* not a member; a profile-wide caller is the owner
  context). The owner rule widens only owner-only *rows*, never other users' rows.
- **All reads/writes go through the scope:** `_open_engine()` opens with the current
  `ScopeContext.to_scope()`, so every tool, hook and background write resolves through
  §3.5 in one seam; `MemoryStore` already stamps `draft.author_id or scope.author` and
  derives visibility from the scope (Chunk 13), so attribution rides the same channel.
  Chat mode stamps `scope_chat` (already plumbed: `chat_in_scope` + `scope_sql`) and
  derives `visibility='chat'` for chat-derived writes (§3.5's chat row).
- **The prefetch cache is keyed by `scope_key` + query.** Today `_cache_key` hashes the
  query alone, so in one group-chat session author B gets author A's cached memory block —
  measured as the leak the group-chat AC names. Fixed by construction here.
- **`identity_signature()` lands** (`em/provider/identity.py`): returns
  `{"provider":"entropicmem","schema":3,"scope_mode":<resolved>}`; reads **only the config
  file**, cached by `(path, mtime, size)` because the host calls it on every inbound
  message; cheap, no DB, safe on an uninitialized instance (no home → the default
  signature; unparseable config → defaults, never raises). `HOOK_SURFACE`'s row flips from
  deferred to implemented; the deferred set shrinks to `on_delegation` (EM-405).

**AC — reading settled by the owner on 2026-10-13 (the isolation reading):**

1. **Group-chat harness test (3 authors in one chat):** each author's memories are
   attributed to that author (`scope_user=<author>`, `visibility='user'`), a bot author
   creates no user-scoped memory, and no user-private memory ever reaches another author's
   prefetch — **including through the prefetch cache** (same query, two authors, two
   blocks).
2. **`multi_user` eval category = 1.0 on a new isolation surface**, not on the frozen hard
   suite: `evals/dataset.py` gains `Turn.as_user` (and `Memory.sensitivity`) as optional
   fields; `evals/adapters/engine_v3.py` loads `scope_user` and queries through the scope
   per turn (`AdapterBase.set_turn_scope`, called by `score_turn`); a new suite
   `evals/datasets_multi_user/` (category `multi_user`) measures §3.5's own definition —
   user X's private fact must not appear for user Y — with `expect_ids`/`must_not`/
   abstain turns; the committed baseline reads multi_user = 1.0.
   **Recorded deviation from the card's literal wording:** the frozen hard suite's
   `multi_user` (5 scenarios / 15 turns) scores recall@5 **0.90 lexical / 0.933 vector**
   (measured 2026-10-13), and its two misses are `multi_user_shared_01` turns 1 and 3 —
   *"when is the wedding?"* must retrieve *"The event date is set for June 1, 2030"*,
   which shares **zero terms** with the query (even `BAAI/bge-small-en-v1.5` misses that
   turn; the committed vector baseline agrees at 0.933). That is the cross-memory
   coreference class (like `ageing`'s lexical ceiling), a retrieval gap no scoping change
   can close; the frozen suite and its baselines stay untouched and the number is reported
   as-is. The frozen turns also carry no `must_not` and no asker, so as written the
   category cannot measure isolation at all — which is why the reading is the new surface.

**Guards to update:** `pyproject.toml` gains the `em.policy` subpackage (pinned by
`test_pyproject_lists_every_em_subpackage`); `tests/test_provider_contract.py`'s deferred
set shrinks to `on_delegation` and the stub that probes it; the six source-scanning guards
are repointed only if a signature they scan moves. `plugin.yaml`'s `provides_hooks` is
**not** touched (the catalog rule: no list changes outside a release that re-pins).

**Workflow:** test-first with mutation checks (restored from copies), `python -m pytest -q`
on 3.10 and 3.12, `ruff check .`, the privacy digest check in place, two commits (code +
tests + CHANGELOG under `[Unreleased]`/Added, then docs with reconciliation folded in),
branch push, check-runs on the exact SHAs via the API (`head_sha` read), `git merge
--ff-only`. Expected suite size moves from **2226 / 5 / 3** (bare) — the three pages'
counters are updated together in the docs commit.

**What the build found beyond the plan (2026-10-13):**

- **The frozen hard `multi_user` category cannot reach 1.0 and is not an isolation
  measure.** Its two misses (`multi_user_shared_01` turns 1, 3) need cross-memory
  coreference — *"when is the wedding?"* must retrieve *"The event date is set for
  June 1, 2030"* (zero shared terms; even `BAAI/bge-small-en-v1.5` misses it) — and
  its turns carry no `must_not` and no asker. Hence the owner's isolation reading and
  the new surface. Frozen files and baselines untouched (verified category-by-category
  against `v3-hard.json`).
- **The frozen suites' `scope_user` values no adapter ever honoured** (v2 and v3 both
  loaded profile-wide). Honouring them for asker-less scenarios would have silently
  rewritten every frozen number (hard multi_user 0.90 → 0.0), so `Scenario.scoped`
  opts a scenario into §3.5 buckets **only** when its turns name askers.
- **A `sensitive`/`secret`-tier row is owner-only even to its own user** under the
  pinned `row_is_owner_only` (stricter than §3.5's "non-owners see … plus their
  own"). Not changed: widening a privacy read rule is the owner's call (Chunk 13's
  precedent). Recorded in the CHANGELOG and plan §5.
- **One mutation survived first** — removing `initialize`'s `ScopeContext` resolution
  broke nothing, because every test re-bucketed through `with_author` or the setter
  seam. The fix was a test, not a mutation exemption: three initialize-resolution
  tests now pin the gateway bucket, `scope_mode: chat`, and the owner-list guest
  derivation.

## Part A (continued): Chunk 33 — EM-403 slice 1 (`PrefetchService`, the synchronous core). **DONE, MERGED (2026-10-13, `9f9ba0c`; code `fde8f36`, docs `9f9ba0c`, ff; 22/22 check-runs green on that SHA)**

### The chunk as built (planned in Part B below on 2026-10-13; that plan is kept as the record)

**Files:** `em/provider/prefetch_service.py` (**new** — `PrefetchService`,
`PrefetchMetrics`, `PrefetchResult`, `scope_key`, `normalize_query`),
`em/retrieval/pipeline.py` (the three execution seams + `GeneratorDeadline`),
`em/retrieval/query.py` (§3.6's IDF cache — `VocabularyCache`),
`em/retrieval/candidates.py` (`bm25`'s single bounded query),
`em/provider/render.py` (`pack_chosen`, split out of `pack_block`).
**Nothing calls the service yet** — the provider wiring is slice 3 (chunk 35).

**What landed, against §4.2:**

- The cache is §4.2's key exactly: `(session_id, scope_key, sha1(normalized_query),
  write_generation)`, with `write_generation` = `note_write()`'s in-process counter
  plus the persistent read connection's `PRAGMA data_version`. **The persistent
  connection is measured, not assumed:** `data_version` is per-connection — a fresh
  connection always reads `1` — so the cross-process half of §4.2 only works on a
  connection that lives across calls (verified empirically 2026-10-13).
- Deadline + partial: `pipeline.retrieve(..., deadline=, generator_order=,
  generator_runner=)` — optional seams, defaults byte-identical (the EM-306
  pattern). The service passes §4.2's priority order; expired deadline ⇒
  generators skipped, `Retrieval.partial` + `generators_skipped`.
- **The watchdog** — the recorded strengthening: each generator runs on the one
  worker thread (`spawn_thread` seam, F-005b) and is joined with the remaining
  deadline + 50 ms grace; an overrun is abandoned and the result discarded, so
  §4.1's 1.5 s hard cap holds for a **contract-violating** generator too. While
  the worker is stuck the next call fails fast to `partial` and recovers after.
- §4.2's dedup rule exactly (6-turn window; score ≥ 0.8 re-shows after > 2
  turns; pinned/constraint rows every 10 turns), applied to memories; a cache
  hit re-filters and re-renders rather than replaying a block; a partial build
  is never cached.
- Hard cap `min(token_budget*4, 9000)` chars, whole rows dropped from the tail.
- The five metrics with a real latency distribution (the histogram
  `em.provider.hooks` deferred to this card).

**The AC is green (harness, one test per line):** forced-slow generator returns
in 1.26 s (< 1.5) with `partial=True` and earlier rows served; block ≤ 9,000
chars; 50 turns replay **5,536** cumulative memory tokens ≤ 13,500
(50 × budget × 0.6); cache-hit p95 **0.04 ms** (≤ 10); warm p95 **43 ms** @ 50k
(p50 42, max 45 ≤ 150).

**What the build found beyond the plan (2026-10-13):**

- **The 50k AC first read 153 ms, and the profile named two wastes.** `analyze`
  re-read the whole `memories_vocab` view per call (**25 ms at 50k**) — exactly
  the recorded EM-301 gap this card's `write_generation` exists for, so §3.6's
  IDF cache landed here (`VocabularyCache`, keyed by generation; uncached for
  every caller that passes none) — and `bm25`'s `_fetch` pages re-scored and
  re-sorted every FTS match **per page** (78 ms for four 10-row pages vs 20 ms
  for one 40-row query). `bm25` now fetches its top-k in one bounded query;
  `_fetch`'s paging contract is untouched and its two tests now pin it
  **directly** (same claims: check-before-fetch, partial accumulation), with a
  new structural pin (`bm25` = one query) replacing the 4× regression silently.
  Recorded: `bm25` can no longer return mid-scan partials — top-k whole, at most
  one query's time past the deadline, which is the overrun any in-flight page
  query always had.
- **The replay AC's first corpus was too small to mean anything.** With rows
  filling ~54% of the budget per turn, dedup deleted entirely still passed
  (12,005 ≤ 13,500). The corpus now fills a turn's budget (asserted in the
  test) and is **cold** (score < 0.8): a hot row re-shows every 3 turns *by
  §4.2's own rule*, which makes the bound unsatisfiable by design — the hot
  escape valve is pinned by unit tests instead. Dedup-off now reads 16,954 and
  dies.
- **`PRAGMA data_version` is per-connection** (measured): a fresh connection
  reads `1` always, only a living connection sees another connection's commit.
  This is why the service owns persistent read connections — and why the
  generator worker must hold its own (an abandoned generator runs concurrently
  with the caller's next read).

39 new tests; **2318 / 5 / 3** bare, **2320 / 3 / 3** with numpy, **2321 / 2 / 3**
with the digest list, on 3.10 and 3.12; `ruff==0.16.2` clean; privacy guard
clean in place; **29 mutation checks, all red** (list in the CHANGELOG). One
first-battery survivor class, caught before the battery even ran: the replay AC
itself was weak (above) — fixed by fixing the fixture's *meaning*, not the
bound.

## Part A (continued): Chunk 34 — EM-403 slice 2 (the async half), and slice 3's first half (the provider wiring). **DONE, ON MAIN (2026-10-14, `31053df` code; `007bb22` docs tip)**

### Chunk 34 — slice 2, the async half (code `8b30aa9`, lint `31053df`, branch `em-403-prefetch-async`; ff-merged to `main` as `31053df`; docs `007bb22`; 11/11 check-runs green on each exact SHA, `identity-guard` included)

- **`precompute(query, *, scope, session_id, query_vector=, embedding_model=)`** builds the candidate pool — the pipeline's top rows turned into `PackItem`s under `CANDIDATE_POOL_SIZE` (60) — and caches it keyed by `(session_id, scope_key)`, so the wired provider (slice 3) can serve a turn from a pool built on the previous turn's `queue_prefetch`. The same call runs the query embedding through an optional `embed_query` callable **when the caller passed none**: the embedding is computed on this call, never on the prefetch thread, and never when one was supplied.
- **The coalescing worker queue is part of the service:** `queue_precompute` (aliases `enqueue_precompute`/`precompute_async`/`schedule_precompute`) hands the request to one daemon thread over a `queue.Queue(maxsize=8)`; a newer request for a session supersedes the older one by identity and `coalesce()` cancels the rest; enqueue/coalesce/drop/reject-after-close/eviction counters live in `precompute_stats`. `close()` joins the worker and queue threads with a 2.0 s timeout and counts/logs expired joins.
- **Session topic state:** a rolling entity set (5-turn window) plus, when a vector is given, an EMA (α=0.5) over the last turns, exposed via `topic_state`/`topics`. `prefetch()` applies the soft +`TOPIC_ENTITY_BONUS` (0.05, configurable) to any candidate sharing an entity with it — a hint, never query text, and zero when no topic exists.
- 22 new tests (the slice-2 pair plus isolation/invariants); the suite read **2343 / 3 / 3** on 3.12 at the merge (CI at the later `3dcb35f`: **2347 / 3 / 3**); `ruff==0.16.2` clean.

### Slice 3's first half — the provider wiring (`f674146` code +90 lines in `em/provider/provider.py`; `55f85ce` its docs note; both pushed **directly to `main`**)

- **What landed.** `_v3_store()` is a cached, read-only `PRAGMA user_version` probe (never migrates); `_ensure_prefetch_service()` builds the `PrefetchService` lazily on a v3 store — `Store.reader`'s persistent connection held for the service's lifetime (so `PRAGMA data_version` stays meaningful), token budget `prefetch_token_budget // 4 or 450`, `max_latency_ms` from `prefetch_max_latency_ms` (1200 default), the generator worker spawned through the provider's `_spawn` seam (F-005b) — and returns `None` on a v2 store, so v2 behaviour is unchanged by construction. `queue_prefetch` enqueues `service.queue_precompute(...)`; the new `metrics()` returns `PrefetchMetrics.snapshot()` (the five `prefetch.*` keys; `{}` on v2); shutdown closes both service and store.
- **The gate deviation, recorded.** The enqueue is gated on `ENTROPICMEM_V3_RETRIEVAL=1` **as well as** a v3 store; the brief (kept below as the record) named the v3 store alone. The flag gate is conservative and consistent with P0b — and the byte-identity pin needs the default-off behaviour — so the recommendation carried into the second half's chunk is to **keep it and say so in writing**, not to discover it later.
- **What deliberately did not land.** The synchronous `prefetch()`'s fact block still renders through the existing path on every store (the P0b byte-identity golden is the reason), so the service's synchronous serve path is proven at slice-leaf level (chunk 33) and reaches the provider only through `queue_precompute`. The wiring shipped **no tests, no CHANGELOG line (backfilled 2026-10-15), and no AC re-run through the wired provider**; the five metrics come back as `PrefetchMetrics.snapshot()`'s own keys via `metrics()` and are not merged into the host's `hook.*` namespace.
- **The process record, stated plainly.** Slice 2's first commit (`7be05dd`, plus lint `82637ae` and docs `50d7ebc`) was committed onto local `main` and **never pushed**; slice 3's code and its docs (`f674146`, `55f85ce`) were then committed onto `main` and **pushed directly to `origin/main`**, so CI ran *after* the push rather than before a merge. Every one of those SHAs came back green (`identity-guard` included), nothing red ever landed on `main`, and published history is untouched — but the branch-first workflow was not followed for `f674146`/`55f85ce`, and this record stands rather than being papered over. The re-committed slice 2 (`8b30aa9`, on branch `em-403-prefetch-async`, with the two new test files) then merged to `main` the documented way: branch push, green check-runs on the exact SHAs, `git merge --ff-only` to `31053df`, docs `007bb22`.
- **The slice-3 brief, kept as the record (written 2026-10-14 as `25a8d68`):** route `prefetch`/`queue_prefetch` to `PrefetchService` on a v3 store (`user_version >= 3`), leaving v2 stores on the existing path; surface the service's metrics through `PrefetchMetrics` as the card's five; re-run the AC harness against the wired provider and re-verify the AC; construct the service lazily from the store's reader (persistent connection) during `initialize`/first use; wrap all access with `fail_soft`; keep v2 byte-identical under the shadow flag; do not flip `ENTROPICMEM_V3_RETRIEVAL`'s default; do not wire `em/config.py`; only EM-404 (tool split) follows. **Built against that brief: the lazy service, the metrics, the `fail_soft` wrapping, v2 untouched; not built: the sync `prefetch` routing, the tests, the AC re-run.**

## Part A (continued): Chunk 35 — EM-403 slice 3, second half: the provider's sync fact block routes through `PrefetchService`. **DONE, MERGED (2026-10-15, `a5b613a` code; docs on top, ff; 11/11 check-runs green on the exact SHA)**

### What landed

- **The wiring.** `prefetch()` serves the fact block from `PrefetchService.prefetch()` whenever `_prefetch_service_for_turn()` says to: cache, dedup, hard cap and the five `prefetch.*` metrics then own the turn. `served` is True only for a service call that *returned* — an empty block from the service is an answer, not a failure. `queue_prefetch` shares the one gate. `_turn_scope()` hands the service the **effective** scope: the profile comes from `_profile_id or "default"`, exactly as `em/facade/engine.py` resolves it ("a passed scope can never make rows and reads disagree about which profile they belong to"), because the service reads the store directly and a raw `to_scope()` carries the usually-empty `agent_identity` — without this the wired path would query a profile no rows live in. The two halves share it, so the first half's `queue_precompute` scope is repaired by the same line.
- **The gate decision (the chunk's required write-up): the service path needs BOTH a v3 store AND `ENTROPICMEM_V3_RETRIEVAL=1`. The brief (`25a8d68`, kept in the record above) named the v3 store alone. Where this lands and why: keep the flag alongside the store version.** (1) **P0b consistency:** every other v3-read switch in the provider — the facade's ranking path — is flag-gated; a prefetch that moved on the store version alone would split the provider's v3 behaviour across two different triggers, so "what turned v3 on" would have two answers. (2) **The byte-identity pin needs default-off:** P0b's golden and chunk 35's v2 golden (captured from `e4fd865` in a detached worktree, flag ON) assert the *un-wired* output; a store-version-only gate would flip the served block for every v3 store the day it was migrated — the owner's cutover act — with no separate switch to verify it under. The cost is that the wiring stays dormant until the owner flips the flag, which is the direction this card should fail in. **The flag's default is untouched.**
- **v2 is byte-identical by construction.** The service is `None` on a v2 store, the old path runs, and the golden replays byte-for-byte; a second test blocks service construction on a v2 store outright (a raiser in `PrefetchService.__init__`) so the wiring is structurally unreachable there. A v3 store with the flag off takes the same old path (P0b's off shape) and its two goldens are unchanged and green.
- **Fail soft, not silent.** A service that raises degrades to the v2 smart-context path (P0b's off path, always available on a v3 store) rather than losing the turn; the block is still served, and the host records no error.
- **A defect the wiring's shutdown test found and this chunk fixes.** `PrefetchService.close()` joined its worker **before** posting the `None` sentinel — the loops block on `get()` with no timeout, so an idle worker could never be observed leaving and every close paid the full 2 s timeout (measured 2011 ms) plus a warning. Since the provider now closes a service on every v3 session end, that was a 2 s stall on every shutdown. The sentinel now goes out first; a genuinely stuck generator still times out, is counted, and is logged — the slice-2 invariant pin (`test_thread_join_timeout_counted_and_logged`) stays green — and a new pin asserts a clean shutdown is prompt and counts nothing.
- **One deliberate test rewrite.** `test_provider_v3_retrieval.py`'s flag-on test pinned P0b's *interim* contract — facade-mapped rankings rendered as v2 bullets with scores. This chunk supersedes that contract (§4.2's render with full-id citations), so the test was rewritten to pin the new one: same fixture, same gate, `### Constraints` + `### Relevant memories` sections, full-id citations, the second identical turn a service cache hit that dedups to empty. **Its two off-path tests — the pre-P0b byte-identity golden and the "retrieve never ran" pin — are unchanged and green.**
- **Recorded gaps on the wired path, not silently dropped:** the service owns caching and dedup, so the v2 fact-block cache and its window do not run; `touch_on_inject`'s background `last_accessed` bump does not run; and the provider's config-level `prefetch_denied_sources`/domain filters are not applied by the service. §3.5 scoping *is* applied — the service reads through the turn's scope, pinned by a two-author isolation test — and the owner-only/sensitive store rules ride the same scope.

### Evidence

- 13 wire-level tests (`tests/unit/test_em403_slice3_wiring.py`) + the card's AC re-run through the wired provider (`tests/harness/test_em403_slice3_wired_ac.py`): forced-slow generator **1.261 s** (< 1.5) with `partial` and earlier rows served; block **7,648 chars** (≤ 9,000); 50-turn replay **5,504** replayed tokens ≤ 13,500 (first turn 344 > 0.6 × budget); cache-hit **p95 0.09 ms** (≤ 10, 20/20 hits); warm **p95 40.58 ms** @ 50k (p50 39.44, max 42.07; ≤ 150).
- Suite **2288 / 16 / 3** bare on 3.11 (was 2270 / 16 / 3), CI **2365 / 3 / 3** on `a5b613a`; `ruff==0.16.2` clean; the privacy digest guard clean **in place** (2289 / 15 / 3). **7 mutation checks, all red, each restored from a copy:** the gate removed (4 unit + all 4 runnable AC tests), the gate inverted (8), `_turn_scope` back to the raw scope (4), the service built on v2 stores (3), the fallback removed (1), the close sentinel reordered (1, with the 2 s stall visible), and the AC harness re-run under the gate removal.

## Part A (continued): EM-404's validation slice — the nine-tool v3 surface (Appendix B) on both stores. **DONE, MERGED (2026-10-15, `5000942`; branch-first, 11/11 check-runs green on the exact SHA)**

### What landed

- **The nine tools, Appendix B verbatim.** `em/provider/tools.py` is rewritten:
  `remember`/`search`/`update`/`forget`/`timeline`/`entity`/`profile`/`review`/
  `stats`, schemas verbatim — the surface test pins exactly what the appendix pins
  (property sets, required lists, the description set; `search` has **no** `required`
  key and no descriptions on `query`/`ids`/`kinds`/`time_from`/`time_to`/`limit`,
  because the appendix gives none). `plugin.yaml`'s `provides_tools` goes **7 → 9**
  (manifest coherence, pinned).
- **The five legacy names route for one minor version** through `LEGACY_ALIASES`:
  `recall`→`search`, `get`→`search(ids=[…])`, `query`→`search(sources=["notes"])`
  with `top_k`→`limit`, `patch_core`→`profile(action="patch")`, `consolidate`→
  `review(action="consolidate_preview")` — the last is **forced**, so no stored tool
  call can archive (the real run stays CLI-only) and the ignored write-shaped args
  (`dry_run`/`confirm`/`max_age_days`) come back as warnings. Every response, errors
  included, carries `"deprecated_tool": "<old name>"`; legacy-only arguments come
  back as ignored-argument warnings.
- **§4.4's argument handling** lives in the new `em/util/jsonschema_lite.py`:
  types and enums are **hard errors** naming the argument, the expected shape and
  what arrived; `maxLength`/`maxItems` **cap** with a warning; `minimum`/`maximum`
  **clamp** with a warning; unknown arguments are **dropped** with a warning; JSON
  `null` reads as "not provided"; booleans are never integers. One deliberate
  deviation from the old `test_query_tool_empty_query_errors`: an empty query on the
  `query` alias returns `{"results": []}` (the renamed test pins the new answer).
- **The write gate and the token flow.** Writes in non-primary contexts answer
  `{"ok": false, …, "reason_code": "writes_disabled"}` before touching disk — the
  frozen reason-code set is `invalid_arguments | writes_disabled |
  confirmation_required | not_found | needs_v3_store | guest_forbidden |
  not_restorable | blocked`, and store reason codes pass through. `forget` by id is
  immediate (`set_status deleted`, reason `forget`); by query it previews candidates
  and returns `confirm_token = sha1(",".join(sorted(ids)) + session)[:10]` with
  `expires_in_seconds: 300`, **single-use** under the frozen clock; applying it
  forgets by id, an invalid or expired token answers `confirmation_required`, and
  the preview is allowed in a non-primary context while the apply is not. Deleted
  rows read as missing, never as results.
- **`search`'s four sources.** `memories` (scope + status through the store),
  `episodes` (`EpisodeStore.search_episodes`/`engine.recall_episodes`), `notes`
  (the composed vault retrieval) and `shared` (raw sqlite reads); `include_history`
  walks the bounded supersede chain (the new `MemoryStore.predecessors`) with
  `why: ["history"]`; results carry `id`, `short_id`, `kind`, `content`,
  `valid_from`/`valid_to`, `status`, `score`, `why` **plus** the one-minor-version
  legacy keys (`relevance_score`, `why_retrieved`, `entropic_id`, `note_id`,
  `snippet`) so existing consumers keep parsing. v2 stores answer `needs_v3_store`
  for `update`/`entity`/`review`'s `restore`/`feedback`.
- **Two store additions + the contract table.** `MemoryStore.predecessors` (the
  bounded chain walk) and `MemoryStore.record_feedback`;
  `em/facade/contract.py`'s `PROVIDER_CALLS`/`LegacyEngine` grew six recorded calls
  (`get_versions`, `list_episodes`, `list_pending`, `promote_pending`,
  `discard_pending`, `recall_episodes`).
- **Deliberately not rewritten, recorded instead:** the provider's system prompt
  still names the legacy aliases (they route for one minor version; the block's
  rewrite is owed — **EM-409, System prompt: policy + core, is the natural home**),
  and `allow_agent_consolidate`'s config-schema description still says the tool can
  archive — it can only preview now; a one-line tidy on EM-405's branch.

### Evidence

- **176 new tests** — `tests/unit/test_em404_jsonschema_lite.py` (22: every
  keyword and message shape), `tests/unit/test_em404_tool_surface.py` (107:
  Appendix B verbatim, `provides_tools` coherence, alias and reason-code contracts,
  the card's fuzz half), `tests/unit/test_em404_tool_behaviour.py` (47: both stores
  — writes, the four sources, history, forget tokens under the frozen clock, review
  actions, entity cards, profile patch, timeline, stats, screening).
- Suite **2469 / 16 / 3** bare and **2470 / 15 / 3** with the digest list in place;
  CI's 3.12 count **2546 / 3 / 3** on `5000942`; `ruff==0.16.2` clean. **17 of 18
  mutation checks red**, each restored from a copy; the one survivor — the query
  path's deleted-row filter — is unreachable black-box (`candidates.py` gates every
  memory generator on `status='active'`), stays as the ranking→read race guard, and
  the reachable ids path is pinned by `test_forget_by_id_marks_deleted`.
- Deliberate contract updates, each the changed surface's own claim: `plugin.yaml` +
  its hardening pin; the slice-2 layout pins; `test_plugin_hardening` (write spread
  by `reason_code`; recall/get read `search` rows); `test_plugin_imports` (citation
  fields, the empty-query answer); `test_explainable_recall` (via
  `handle_tool_call`); `test_consolidate` (preview-only); `test_privacy_guard`
  (engine-direct seeds; the secret tier stamped onto the stored row so the EM-118
  filter is genuinely exercised, not trivially passed by a blocked write).

## Part A (continued): EM-405's lifecycle slice — delegation, the rewound-turn retraction, the turn index. **DONE, MERGED (2026-10-15, `e483d43`; branch-first, 11/11 check-runs green on the exact SHA)**

**What landed.** Three §4.1 behaviours and the support they needed.
`on_delegation` records one redacted `delegation` episode — task ≤ 500 chars,
result ≤ 1500, redaction **before** the cap so a truncated secret cannot slip
past the detector — through the facade's `add_episode`, which now takes an
explicit `kind` for the episode vocabulary; on a v3 store the hook then enqueues
one `extract_session` job (`source=extracted_llm`, `confidence_cap` 0.6) and the
handler itself is the extraction card's. The rewound `on_session_switch` **only
enqueues** (30 ms budget): one `retract_turns` job (`{session_id, from_turn}`),
with the counter stepping back one so repeated `/undo` walks turn by turn; the
new handler (`em/store/retract.py`, `make_retract_handler`) runs
`MemoryStore.retract_session`, which soft-deletes the undone session's live,
turn-stamped rows (`source_turn >= from_turn`) as `retracted_by_undo` on the
existing audited, versioned edge — pending candidates keep their TTL path,
unstamped rows are not attributable, and a malformed payload is permanent (dead,
never retried). `set_status` gains the **one** reversal of a terminal status,
reason-gated rather than a table change: `LEGAL_TRANSITIONS` keeps `deleted`
terminal (still pinned at `tests/test_em_memories.py:260`) and `deleted → active`
is admitted only when the row's **latest** deletion record is `retracted_by_undo`
and the reason is `restore` — a forget stays terminal before and after a
retraction, and `review`'s `restore` can bring a retraction back. The turn index
is **provider-owned**: `ProviderState.turn_index`/`turn_index_session`, bumped in
`on_turn_start`, persisted on v3 stores to `meta['turn_index:<sid>']`, restored
at `initialize`/switches through a read-only probe that **deliberately bypasses
the per-instance `_v3_store()` cache** (a probe before the store file exists must
not pin a session to the v2 path), stamped as `source_turn` on the tool path and
on the facade's extraction quarantine (captured at `sync_turn` call time so the
background thread cannot pick up the next turn's number); v2 keeps the counter in
memory and its schema gains nothing. `shutdown` checkpoints the WAL
(`PRAGMA wal_checkpoint(PASSIVE)`) before closing the prefetch store and stays
within 2 s with a precompute in flight.

**Deliberate contract updates** (each at the changed surface's own claim): the
facade contract table records `kind`/`source_turn` — one call shape reaches both
engines and the v2 engine accepts-and-ignores both (its episodes table has no
kind column, its rows no turn); `HOOK_SURFACE`'s `on_delegation` row is
implemented (`in_manifest=True`), `plugin.yaml`'s `provides_hooks` grows
**5 → 6** (the dev-line treatment EM-404 gave `provides_tools`; the catalog
re-pin stays release business); the harness drives `on_delegation` directly;
`test_audit_reports_a_real_problem` plants a deferred spec now that the deferred
set is empty; `test_plugin_hardening`'s hook list gains the row; and the dead
`allow_agent_consolidate` description now says what the tool is (the gap the
EM-404 record left open).

**Evidence.** 23 new tests (`tests/unit/test_em405_retract.py` 11,
`tests/unit/test_em405_lifecycle.py` 12); bare **2492 / 16 / 3** (was 2469 / 16 /
3), digest-list **2493 / 15 / 3**; `ruff==0.16.2` clean; **23 of 23 mutation
checks red**, each restored from a byte copy — including the two strengthenings
the pass forced (`>=` catching every later turn; a restored-then-forgotten row
terminal again). Landed by the branch-first path: push, all 11 CI jobs green on
the exact SHA, `git merge --ff-only`, branch deleted.

## Part A (continued): EM-407's typed config — Appendix A's model, §3.8's loader, and the tuned scalars at the call sites. **DONE, MERGED (2026-10-15, `2b21ad1`; branch-first, 11/11 check-runs green on the exact SHA)**

**What landed.** `em/config.py` grows from EM-306's scalar block into Appendix
A's **typed model**: sixteen dataclasses (the fourteen sections plus `entities`
and the root `timezone`), one frozen `Rule` per typed leaf (kind, label,
description, choices, minimum/maximum — kinds `text`, `select`, `bool`,
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
`plugins.memory.config_schema` (AST-pinned); `cmd_init` prints the hourly cron
line.

**The point of the card.** The tuned scalars reach the pipeline's
`retrieve(gate_config=, rank_weights=)` seam: `initialize` builds one
`GateConfig`/`RankWeights` from the typed config (the paths overlay feeds
`resolve_paths`; the embeddings switch reads the typed key), and the search
tool, the `PrefetchService` (constructor and `_retrieval_kwargs`; both retrieve
calls) and the v3 facade (`V3Engine`/`open_engine` accept and forward; v2
accepts-and-ignores) all pass them. The eval adapter's own defaults remain the
spec; CI's eval gate stays v2.

**Deliberate contract updates** (each at the changed surface's own claim): the
schema pin renamed and re-based on the typed model's defaults; the save drive
switched to a dotted key; the EM-403 wired AC's comment records the clamp; and
`tests/harness/pinned_memory_provider.json` is unchanged (the host contract did
not move).

**Evidence.** 49 new tests (`tests/unit/test_em407_config.py` 30,
`tests/unit/test_em407_wiring.py` 19); bare **2541 / 16 / 3** (was 2492 / 16 /
3), digest-list **2542 / 15 / 3**; `ruff==0.16.2` clean; **16 of 16 mutation
checks red**, each restored from a byte copy. The first CI round on `0f38fbf`
was **10/11**: `windows-import` runs `tests/unit` with pytest alone (no PyYAML),
where six of the new wiring tests read or write `config.yaml` — they now carry
the same `needs_yaml` marker the identity tests use (in a no-PyYAML venv the
six skip and the file reads 13 passed / 6 skipped), and the second round on the
landing SHA (`2b21ad1`) was **11/11**. Landed by the branch-first path: push,
all 11 CI jobs green on the exact SHA, `git merge --ff-only`, branch deleted.

## Part A (continued): the EM-407 hardening pull — the owner's verification queue, landed. **DONE, MERGED (2026-10-16, `dc3c77a`; branch-first, 11/11 check-runs green on the exact SHA; branch deleted)**

**The queue.** After EM-407 landed (`2b21ad1`), the owner set four verification
items and drew three lines: the failing numpy AC had to be **fixed or shown to be
noise on recorded evidence — not filed as a flake**; the test-count gap had to be
**explained**, with every count tied to the command that produced it; the pre/post
default behaviour had to be **shown matching or the divergence documented
exactly**; and `save_config` (reachable from the dashboard) had to be reviewed for
its atomic write on Windows, concurrent writers, and validation-before-disk, with
tests for anything uncovered. Item 5 — the query-embedding wiring card — was to be
**written and brought back, not implemented**; after it, S4 in dependency order:
**EM-406, then EM-411, then the rest**.

**1. The 50k guard reads the best of five windows — the flap is fixed by
statistic, and recorded as what it was.** On 2026-10-15 the 3.13 leg (job
`116561640133`, run `38775407380`) read 13 samples at 8.97–13.10 ms and then a
stall tail to 113.11 ms; single-window nearest-rank p95 is `samples[18]` — the
second-worst sample — so the guard failed at **31.61 ms** while the same commit's
other legs passed. The single 20-probe window was the defect: the p95 of 20
samples cannot distinguish a contended runner moment from a regression. The test
now runs five 20-probe windows (fresh queries, same nearest-rank p95 per window)
and asserts the **best** window holds p95 < 25 ms: transient contention cannot
fail all five windows, and a genuine regression inflates every window and still
fails. The threshold and the AC are unchanged. Evidence: 5× green on the box;
replaying the recorded window under the old formula reproduces 31.61 ms (red),
the same window as one-of-five passes, and a 2.2× all-window regression fails
the best window. `perf-smoke` (20 probes → a real p95; its own entry in CHANGELOG
`Fixed`) is the precedent kept, not widened.

**2. The counts reconcile exactly, and each environment cites its command.**
CI's 3.12 count and the bare box's differ by **77 passed = 67 + 7 + 2 + 1**: the
three fastapi-dependent graph modules collect 67 tests in CI and **0** without
fastapi (`test_graph_server_v2_6.py` 14, `test_graph_server_security.py` 48,
`test_graph_server_titles.py` 5 — measured with `--collect-only` both ways);
cryptography gates 7 (`test_phase11.py` 2, `test_security_decrypt_guard.py` 5);
numpy gates 2 (`test_em_embedding_cache.py` 225 and 240); and the privacy digest
test passes only with a list (`tests/evals/test_no_personal_data.py`). The
run-total delta is **64 = 67 − 3** (three module-skip entries replace the 67
tests in a bare run). The skip delta is **13 = 14 local-extra − 1 CI-extra**:
locally the four families skip — the fastapi family as 4 entries (three
module-level + one inside `test_graph_static.py`), cryptography 7, numpy 2,
privacy 1 — while in CI only `tests/test_provider_contract.py` does (its pinned
hermes-agent file is not on the runner). The commands and counts: CI's `test`
job (3.12), `pytest -q tests/` → **2626 / 3 / 3**; this box,
`.venv311/bin/python -m pytest -q` → **2549 / 16 / 3**;
`ENTROPICMEM_PRIVACY_DIGESTS_FILE=… .venv311/bin/python -m pytest -q` →
**2550 / 15 / 3**; the scratch venv with CI's extras and the digest file on
3.12.13 → **2627 / 2 / 3**.

**3. The default-config divergence is exact, and each default has one owner.**
At default config, pre-EM-407 and post-EM-407 output differs **only** in the
rerank weights: `ranking.w_rrf` 0.60→0.50 and `ranking.w_importance` 0.15→0.25 —
every gate value is identical (0.30/0.34) and the cosine leg is off both ways.
That is EM-306's calibration; its record is
`evals/results/tune-hard-4eb8097.json` (best spec row vs chosen
`importance_heavy`: hard dev objective 0.918477 / mrr 0.91667 vs 0.919087 /
0.9187, recall and noise equal; holdout mrr 0.86508 / ndcg 0.85984 vs 0.88095 /
0.87174, recall and noise equal). The two roles now have one owner each, pinned
by `test_the_default_adapter_keeps_the_spec_and_the_runtime_ships_the_calibration`:
the eval adapter's `None` default **is** the pipeline's spec defaults
(`gate.DEFAULT_GATE` / `fusion.RankWeights()` — the frozen suites' and baselines'
numbers; the adapter keeps no private copy), while the provider ships
`em.config`'s calibrated scalars. Unifying them — the adapter default taking the
calibration — is a one-function change plus baseline re-capture, and is
**cutover work, not a drive-by**: it stays the owner's call, and the pin names
both sides so neither can drift silently.

**4. `save_config` validates first, writes atomically per call, and cleans up.**
Review found three gaps, all closed with tests: values were written **raw** (a
typo'd key landed under a key nothing reads); the atomic write used a **fixed**
`config.yaml.tmp` name (concurrent savers could tear each other's dump); and a
failed dump/`replace` left the temp behind. Now `em.config.validate_values`
validates every key against the typed rules — legacy flat spellings accepted with
the same folds the loader applies, unknown keys refused — **before anything
touches disk**, and a refusal raises `ValueError` naming every problem with the
file untouched; the write goes through a per-call `tempfile.mkstemp` temp in the
destination directory, preserves the destination's mode, `Path.replace`s (so
`os.replace` semantics — atomic on POSIX and Windows), and unlinks the temp on
any failure. The docstring records the Windows contract (a destination held open
by another process → `PermissionError`, original intact, the host sees a failed
setup) and whole-file last-write-wins under racing saves. Five new wiring tests
(refusal-before-write ×2, typed write + legacy fold, locked destination, racing
savers behind a barrier) plus two `validate_values` unit tests.

**5. The query-embedding card was drafted for approval; no implementation
started.** The card (scope, acceptance tests, mutation checks, rollback flag, the
notes on the optional backend stack and the paid OpenAI-compatible backend) was
brought to the owner on 2026-10-16; S4 proceeds in the owner's order — **EM-406,
then EM-411, then the rest by dependency** — while the card awaits approval.

**Evidence:** 8 new tests (the guard test was rewritten, not added); suite
**2549 / 16 / 3** bare and **2550 / 15 / 3** with the digest list on 3.11,
**2627 / 2 / 3** on CI-equivalent 3.12; CI **2626 / 3 / 3** on the landing SHA
with **11/11 checks green** (the 3.13 leg included); `ruff==0.16.2` clean on
CI's paths.

## Part B: next — **EM-406 (checkpoint v2 / evidence archive)** — the owner's S4 order stands: **EM-406, then EM-411, then the rest by dependency** (EM-403/404/405/407 complete; the query-embedding card is drafted and awaits the owner's approval)

**EM-403, EM-404, EM-405 and EM-407 are complete.** EM-403's slices 1 and 2 are merged (`9f9ba0c`,
`31053df`) and chunk 35 (`a5b613a`) closed slice 3: the synchronous fact block routes
through the service on a v3 store behind the v3-store **and** flag gate (the decision
and its reasons are in the Part A record), the wire-level tests and the AC re-run are
green, and v2 is byte-identical by construction — the card's AC, verified **through
the wired provider**: warm p95 40.58 ms @ 50k; cache-hit 0.09 ms; forced-slow 1.261 s
partial; 7,648 chars; 50-turn replay 5,504 ≤ 13,500. **EM-404 closed with the
validation slice (`5000942`):** the tool surface is the nine v3 tools of Appendix B
in `em/provider/tools.py`, the five legacy names route through the alias map for one
minor version, and the card's Spec/AC is pinned by 176 tests. **EM-405 closed
with its lifecycle slice (`e483d43`):** `on_delegation` implemented, `/undo`
retracting the undone turn's stamped memories, the turn index persisting per
session, and the WAL-checkpointed shutdown within 2 s — the Part A record above
has the full detail. **EM-407 closed with its typed-config slice (`2b21ad1`):**
Appendix A's typed model and §3.8's loader in `em/config.py`, the typed
`get_config_schema()` and the `memory.entropicmem`-nesting `save_config`, the
`plugins/entropicmem/config_schema.py` `flat_json` entry, and **the tuned
`gate.*`/`ranking.*` scalars reaching the call sites** — the Part A record above
has the full detail.

**Next, in order:**

1. **DONE (2026-10-15): the landing of `em-404-tools-split` (`84a555f`).** The owner
   chose (b): merge `main` into the branch. It landed as `381197f` — only
   `CHANGELOG.md` conflicted (both entry sets kept verbatim), the merged tree
   verified (bare **2288 / 16 / 3**; digest-list **2289 / 15 / 3**;
   `ruff==0.16.2` clean), all 11 CI jobs green on the exact SHA, `main` ff'd,
   branch deleted, PR #8 merged at the same SHA. Nothing was rebased or forced.
2. **DONE (2026-10-15): the landing of `em-404-handlers-split` (`e5e54ef`).** The
   second half of the split: `get_tool_schemas`, `handle_tool_call` (with its
   `fail_soft(fallback=_tool_call_failed)` belt) and the seven handler bodies move
   **verbatim** onto the new `ToolHandlers` mixin in `em/provider/tools.py`; the
   module-level `INJECTION_WARNING`, `_tool_call_failed` and `_screen_for_injection`
   moved with them because the screening is shared (the provider imports the screen
   function back — one implementation, pinned by identity), and the plugin shell
   imports the marker from its new home. `provider.py` slims 2240 → 1897. The six
   source-scanning guards were **repointed at both implementation files,
   deliberately**; 5 new tests (`tests/unit/test_em404_slice2_tools_split.py`);
   bare **2293 / 16 / 3** (was 2288 / 16 / 3), digest-list **2294 / 15 / 3**;
   `ruff==0.16.2` clean; **9 mutation checks, all red**, each restored from a copy —
   with the honest note that the fuzz alone could not catch the dropped `fail_soft`
   decorator (an uninitialized provider returns before touching args), so the belt
   pin was written to kill it, and does. Landed by the branch-first path: push, all
   11 CI jobs green on the exact SHA, `git merge --ff-only`, branch deleted. **Not
   the whole card — fulfilled by item 3 below:** the behavioural Spec/AC (argument
   validation, the legacy-name alias map, `forget`'s confirmation-token flow,
   `search`'s field set, `reason_code: writes_disabled`) landed as the validation
   slice.
3. **DONE (2026-10-15): the EM-404 validation slice (`5000942`) — the card
   completes.** The nine-tool surface of Appendix B on both stores,
   `em/util/jsonschema_lite.py`'s §4.4 argument handling, the alias map, the write
   gate, `forget`'s single-use token and `search`'s four sources; 176 new tests;
   bare **2469 / 16 / 3**, digest-list **2470 / 15 / 3**; **17 of 18 mutation checks
   red** (the survivor recorded); landed by the branch-first path (push, all 11 CI
   jobs green on the exact SHA, `git merge --ff-only`, branch deleted). Full record:
   the Part A section above.
4. **DONE (2026-10-15): EM-405's lifecycle slice (`e483d43`) — the card
   completes.** The `on_delegation` row; the rewound `on_session_switch`
   enqueueing one `retract_turns` job (`MemoryStore.retract_session` soft-deletes
   the undone session's live, turn-stamped rows as `retracted_by_undo`;
   `set_status` admits the one reason-gated reversal so `review`'s `restore` can
   undo, while `LEGAL_TRANSITIONS` keeps `deleted` terminal); the provider-owned
   `turn_index` persisted per session in `meta` as `turn_index:<sid>` and stamped
   as `source_turn` on both write paths; `shutdown` within 2 s with a running job.
   23 new tests; bare **2492 / 16 / 3**, digest-list **2493 / 15 / 3**; **23 of 23
   mutation checks red**; landed by the branch-first path (push, all 11 CI jobs
   green on the exact SHA, `git merge --ff-only`, branch deleted). Full record:
   the Part A section above.
5. **DONE (2026-10-15): EM-407's typed config (`2b21ad1`) — the card
   completes.** Appendix A's typed model and §3.8's loader in `em/config.py`
   (sixteen dataclasses, one frozen `Rule` per typed leaf, `iter_leaf_keys`), the
   typed `get_config_schema()` (24 dotted keys) and the
   `memory.entropicmem`-nesting `save_config` (atomic; fail-closed), the
   `plugins/entropicmem/config_schema.py` `flat_json` entry, and **the tuned
   `gate.*`/`ranking.*` scalars at the call sites** through the pipeline's
   `retrieve(gate_config=, rank_weights=)` seam (the eval adapter's defaults
   remain the spec). 49 new tests; bare **2541 / 16 / 3**, digest-list
   **2542 / 15 / 3**; **16 of 16 mutation checks red**; landed by the
   branch-first path (two commits — `0f38fbf` the card and `2b21ad1` the
   `windows-import` yaml gate; all 11 CI jobs green on the exact SHA,
   `git merge --ff-only`, branch deleted). Full record: the Part A section
   above.
6. **Next chunk — the owner's to place.** The candidates, all recorded: the
   **query-embedding wiring card** (the open gap below — it needs a card before
   it can be scheduled) and the remaining S4 cards — **EM-406** (checkpoint v2 /
   evidence archive; **EM-411 follows it**), **EM-408** (CLI), **EM-409**
   (system prompt — the natural home of the owed alias rewrite), **EM-410**
   (cron & worker integration). Whatever is chosen: branch-first, tests first,
   one CHANGELOG line, check-runs on the exact SHA, `git merge --ff-only`.

**Open gap recorded 2026-10-15 (surfaced by the reconciliation pass; no owning card):
the query embedding is still unwired.** EM-403 is complete and deliberately did not
embed; the EM-401–403 plan expected the provider cards to call `ensure_embedding_model`
at initialize and embed the query — **none did** — EM-407 included, which wired the
config, not the embedder. Verified in the tree:
`ensure_embedding_model` has no caller outside `em/embeddings/jobs.py`;
`_ensure_prefetch_service` builds the service with no `embed_query`; `prefetch` and
`queue_prefetch` pass no `query_vector`. So **even the wired v3+flag path scores
lexical/entity/episodic — flipping the flag will not change that** — and the
vector-mode numbers (hard recall 0.988 vs lexical 0.933) remain reachable only
through the eval adapter's own embedding. **The wiring — an `embed_query` for the
service, `ensure_embedding_model` at initialize, and a vector handed to `retrieve` —
needs its own card; placing it in the order is the owner's.** Related one-liner
recorded in the same pass: `_shadow.py`'s printed caveat still says "until EM-303"
while the real reason for its no-vectors line is this gap.

The owner's precision list stays in force: per-query vector observability must stay
wired, the runtime coverage fallback serves lexical rather than degrading silently, and
the stale→re-embed queue keeps running. **Guards that stay in force:** nothing embeds on
the agent/prefetch thread; a query with no caller-supplied vector keeps doing no vector
work; the eval adapter's defaults are the spec and CI's eval gate stays v2 (EM-407 wired
the provider's call sites, not the adapter); `EM-411`'s two test groups come
first when its card starts; `ENTROPICMEM_V3_RETRIEVAL`'s default stays off.

### EM-403 is sliced into three chunks (33–35)

An `L` card cannot be one reviewable chunk, and the slices follow the card's own
seams: the synchronous core (what the AC measures), the async half (§4.2's worker),
and the provider wiring (where every compatibility pin lives). **The card's AC lands
in chunk 33** — the harness drives `PrefetchService` directly over a real v3 store;
chunks 34–35 complete "§4.2 exactly" and re-run the AC through the wired provider.

| Chunk | Slice | What it lands |
|---|---|---|
| **33** | **1 — the synchronous core + the AC** | `em/provider/prefetch_service.py`: cache, deadline+partial, dedup, hard cap, the five metrics. **DONE, merged `9f9ba0c`** |
| **34** | **2 — the async half** | `precompute`, the coalescing worker queue, the candidate-pool cache, session topic state (+0.05 soft signal), the query embedding computed on the worker. **DONE, merged `31053df`** (record in Part A) |
| **35** | **3 — the provider wiring** | `prefetch`/`queue_prefetch` route through the service on a v3 store (v2 store unchanged), metrics surfaced, AC re-run wired. **First half on `main` (`f674146`, pushed directly); second half DONE, merged `a5b613a`** — the sync fact block routes through `PrefetchService.prefetch` (gate: v3 store **and** `ENTROPICMEM_V3_RETRIEVAL=1`, decision recorded in Part A), wire-level tests, AC re-run through the wired provider |

### Chunk 33 (planned 2026-10-13) — EM-403 slice 1: `PrefetchService`, the synchronous core

> **Landed 2026-10-13** — see the Part A record above for the chunk as built and
> what the build found. This plan is kept as the record; the only deviations are
> the two perf fixes (the IDF cache and `bm25`'s single query) and the replay
> fixture, all itemised there.

**Files:** `em/provider/prefetch_service.py` (**new**), `em/retrieval/pipeline.py`
(the deadline seam), `em/provider/render.py` (one seam so the service can see what
it injected), tests in `tests/unit/test_em_prefetch_service.py` +
`tests/harness/test_prefetch_service_ac.py`. **Nothing called the service when this
chunk landed** — the provider wiring was chunk 35 (the EM-307/EM-401-slice-1
precedent: a measured component lands first, the switch is its own change); its
first half is now on `main` as `f674146`, and its second half is the next chunk.

**What it builds (§4.2):**

- **`PrefetchService(connect=, spawn_thread=, token_budget=450, max_latency_ms=1200,
  dedup_turns=6, constraint_repeat_turns=10, is_trivial=, metrics=)`** with
  `prefetch(query, *, scope, session_id="", query_vector=None, embedding_model=None)
  -> PrefetchResult`. `connect()` supplies the service's **persistent read
  connection** — measured, not assumed: `PRAGMA data_version` is per-connection and a
  fresh connection always reads `1`, so §4.2's cross-process invalidation only works
  on a connection that lives across calls (verified empirically 2026-10-13). The
  generator watchdog's worker thread is created through the injected `spawn_thread`
  seam (F-005b: no bare `threading.Thread` outside `_spawn`) and holds its **own**
  connection, so an abandoned generator can never touch the caller's.
- **Cache:** key `(session_id, scope_key, sha1(normalized_query), write_generation)`
  exactly as §4.2 says. `write_generation` = an in-process counter bumped by
  `note_write()` **plus** the read connection's `data_version` (cross-process). The
  cached artifact is the turn-independent part (the packer's `PackItem` pool + the
  pinned set); the turn-level dedup filter and the render run **per turn, also on a
  hit**, so a cache hit can never replay a memory the dedup rule would have
  skipped — "Hit → return rendered block" is honoured as "render from cache", which
  is the only reading consistent with "(dedup working)".
- **Deadline + partial:** `pipeline.retrieve(..., deadline=, generator_order=,
  generator_runner=)` — three optional seams, defaults byte-identical to today
  (the EM-306 calibration-seam pattern: one shared sequence, no second pipeline).
  §4.2's priority order `pinned → bm25 → entity → vector → episodic → recent` is
  passed by the service (the global `GENERATORS` order is deliberately untouched —
  reordering it could shift fused float rounding under the frozen eval baselines).
  When the deadline passes, remaining generators are skipped and
  `Retrieval.partial=True` with `generators_skipped`. `GeneratorDeadline` is how a
  watchdog runner reports an abandoned call.
- **The watchdog (a deliberate strengthening of "when the deadline passes"):** each
  generator call runs on the service's single worker thread and is joined with the
  remaining deadline; a generator that ignores the deadline contract (a blocked
  SQLite read, a stuck disk page) is **abandoned** — result discarded, `partial`
  set — so the §4.1 hard internal cap (1.5 s) holds for any generator, not only a
  cooperative one. While the worker is still busy with an abandoned call the next
  prefetch fails fast to `partial` and returns promptly (the v2 host's own rule:
  "skipped until the stuck call returns"). Without this, "forced-slow generator →
  returns within 1.5 s" is unenforceable in Python, because no cooperative deadline
  can interrupt a blocked call.
- **Dedup across turns (memories only, exactly §4.2's rule):** a memory injected in
  any of the last `dedup_turns` (6) turns is skipped **unless** its score ≥ 0.8 and
  it was injected > 2 turns ago (the score is the fusion score, §3.6's `[0, 1]`
  `Ranking.score`); pinned/constraint rows (`RowInfo.pinned`) are re-shown only
  every `constraint_repeat_turns` (10) turns, since earlier injections remain in
  the replayed history. Episodes/follow-ups are not deduped (recorded: the spec
  says "a memory").
- **Output hard cap `min(token_budget*4, 9000)` chars** — rows are dropped from the
  end of the pack and the block re-rendered (never cut mid-row, EM-107(c)'s rule);
  the injected set is what survived the cap.
- **The five metrics** (`prefetch.latency_ms/cache_hit/partial/injected_count/
  tokens`) as `PrefetchMetrics` with a bounded per-call window: `latency_ms` is a
  real distribution (count/avg/p50/p95/max — the histogram `em.provider.hooks`
  explicitly deferred to this card), and the snapshot's keys are exactly those five
  names.
- **Guards kept:** no vector work without a caller-supplied `query_vector` (the
  seam accepts one and passes `None` through by default; nothing embeds anywhere in
  slice 1); `em/config.py` is not read (knobs are constructor parameters);
  `render_retrieval`'s "eval adapter does not call it" pin is untouched (the new
  service renders through `pack_chosen`/`render` with `cite="full"`, so the ids an
  injection screen parses are the stored ids).

**AC harness (`tests/harness/test_prefetch_service_ac.py`), one test per AC line:**
1. forced-slow generator — a contract-violating `time.sleep` generator — returns
   within 1.5 s with `partial=True` and the earlier generators' rows present;
2. the block never exceeds 9,000 chars even with a huge token budget and huge rows;
3. 50 turns × distinct queries over a shared hot set: cumulative **replayed**
   memory tokens ≤ 50 × budget × 0.6 (total injected reported as context);
4. cache-hit path ≤ 10 ms;
5. warm p95 ≤ 150 ms over a 50k-memory v3 store (distribution printed).

**Workflow:** test-first with mutation checks (restored from copies); `pytest -q`
on 3.10 and 3.12; `ruff==0.16.2`; the privacy digest check in place; two commits
(code+tests+CHANGELOG under `[Unreleased]`/Added, then docs with reconciliation);
branch `em-403-prefetch-core`; check-runs on the exact SHAs via the API
(`head_sha` read); `git merge --ff-only`; branch deleted. Suite size moves from
**2279 / 5 / 3** (bare) — the three pages' counters move together in the docs
commit.

### EM-401–403 — acceptance criteria (pasted before starting, per the owner)

**EM-401 — provider package & hook skeleton.** Files: `plugins/entropicmem/__init__.py` (≤ 150 LOC) + `scripts/em/provider/{provider.py,hooks.py,state.py}`. Spec: implements every hook in §4.1 with the listed signatures (`sync_turn(..., messages=None, turn_author=None)`, `on_turn_start(turn_number, message, *, author_id=None, author_name=None, author_is_bot=None, **kw)`, `on_delegation`, `recall_status`, `identity_signature`; deliberately **no** `post_setup`); each hook wrapped by `@fail_soft(budget_ms=…, metric="hook.<name>")`; `pre_compress_checkpoint_api_version = 2`.
**AC:** harness drives every hook; contract test enumerates `MemoryProvider` methods from the pinned hermes-agent and asserts each optional one is implemented or explicitly listed as intentionally unimplemented.

**EM-402 — ScopeContext & identity.** Files: `em/provider/identity.py`, `em/policy/scopes.py`. Spec: §3.5; `ScopeContext.from_init_kwargs(kw, config)`; `with_author(author_id, is_bot)` per turn; `scope_key`; all reads/writes go through the scope; `identity_signature()` reads only the config file, cached by mtime.
**AC:** `multi_user` eval category = 1.0; group-chat harness test (3 authors in one chat) attributes memories correctly and never leaks user-private memories to other authors.

**EM-403 — PrefetchService.** Spec: §4.2 exactly; metrics `prefetch.latency_ms`, `prefetch.cache_hit`, `prefetch.partial`, `prefetch.injected_count`, `prefetch.tokens`.
**AC:** harness: warm p95 ≤ 150 ms @ 50k, cache-hit path ≤ 10 ms; forced-slow generator → returns within 1.5 s with partial result; never exceeds 9,000 chars; cumulative replayed memory tokens over 50 turns ≤ 50 × budget × 0.6 (dedup working).

**Additional required here (owner's precision list, 2026-10-09):**
- **Per-query observability is already at the layer and must be kept wired:** `candidates.vector`/`episodic` log coverage and `stale_excluded` per query on `em.retrieval.vectors` (WARNING when any vector was excluded as stale). The page/service must not swallow those logs, and a runtime coverage fallback (< 50% or < the promotion gate) serves lexical for that query rather than degrading silently.
- **The stale→re-embed round-trip is already pinned at the layer** (`test_a_stale_memory_is_excluded_logged_and_restored_by_the_re_embed_queue`, same for episodes); the provider work keeps the queue running.

### Vector-mode results exist — **context only, not a live claim**

Produced 2026-10-09 on `main` `cc6672e` (+ observability-only working tree) with `fastembed`/`BAAI/bge-small-en-v1.5`, via the new explicit override `evals run --suite hard --adapter v3 --embeddings --compare <lexical baseline>`:

| run | recall@5 | mrr | ndcg@5 | abstain | noise | must_not_ok |
|---|---|---|---|---|---|---|
| hard **vector** (committed baseline `evals/baselines/v3-hard-vector.json`) | **0.988** | 0.946 | 0.957 | 1.000 | 0.172 | 1.000 |
| hard lexical (`v3-hard.json`, same suite) | 0.933 | 0.897 | 0.903 | 1.000 | 0.172 | 1.000 |
| hard/ageing **vector** | **1.000** | — | — | — | 0.167 | — |
| hard/ageing lexical | 0.733 | — | — | — | — | — |
| ci vector (`v3-ci-vector.json`) | 1.000 | 1.000 | 1.000 | 1.000 | 0.143 | 1.000 |

Both runs printed `retrieval mode: vector | baseline: lexical` and **“cross-mode comparison — metrics are context only”**: the regression gate never fired across modes. The per-run result files live in the gitignored `evals/results/`; the committed artifacts are the two vector baselines. **None of this is a semantic-retrieval shipment claim** — live retrieval is lexical: EM-401–403 landed without wiring the query embedding, so no query vector reaches any served path until a card wires it (open gap, 2026-10-15).

### The promotion gate (recommended; owner confirms before the live flip)

Before live retrieval moves off lexical-only, a vector-mode frozen-suite run **and its evidence** must meet all of:

1. **Coverage ≥ 95%** of active in-scope memories carry a fresh vector for the configured model at serve time, and **`stale_excluded == 0`** across the qualification sample (read from the per-query log line). Below 95%, EM-403 serves lexical for that query.
2. **hard overall recall@5 ≥ 0.95** (measured: 0.988; lexical baseline 0.933) — no regression against the lexical baseline allowed.
3. **hard/ageing ≥ 0.85** (measured: 1.000; lexical 0.733) — the paraphrase lever the vectors exist for; the plan's own S3 exit is ≥ 0.70 with vectors.
4. **abstain_correct ≥ 0.95; noise_rate ≤ 0.172** (no worse than lexical on the same suite); **must_not_ok = 1.0**.
5. **Turn-path p95 ≤ 150 ms at 50k warm** (the standal 150 ms budget is unchanged), with the EM-403 cache-hit path ≤ 10 ms.
6. The shadow observable stays as-is (`v3_only == 0`), and the numbers come from committed, mode-labelled result files compared cross-mode as context.

The measured hard-vector run already clears 1–5 on this box; what it cannot show is production traffic — hence the shadow data remains part of the decision, and the switch stays owner-gated.

### EM-411 before implementation (owner's instruction)

The build is held until EM-502's caps exist, default `formation.mode=off`. The **first implementation commit must be the two test groups** (spec in plan §6.3):
- **Shared window key:** cadence, idle and compaction seals of the same `[seq_start, seq_end]` range in one session enqueue **one** `extract:window:{session}:{start}-{end}` job — three near-simultaneous seals are simulated and the queue count is asserted at one.
- **Idle floor:** a gap ≥ `idle_after_sec` enqueues nothing when the sealed window has `< min_window_turns` turns and `< min_window_chars` chars, and exactly one job when either floor is met.

Also in the plan: **old-model rows are pruned by embedding maintenance** — decided policy: after a *completed* backfill for the new model (`meta.embedding_model == new`, zero pending) plus a **7-day grace** (so a rollback does not pay a full re-backfill), keep at most the current and previous model and delete the rest; measured storage is **≈2.1 KB/row all-in (1.5 KB blob), ≈21 MB per 10k memories per model set** — 10k→21 MB, 50k→106 MB per stale set. The prune runs as a job under EM-410's maintenance pass.

Guards that stay in force: **no drive-by `em/config.py` wiring** (EM-407 landed the provider wiring, `2b21ad1`; further changes need their own card); **the `ENTROPICMEM_V3_RETRIEVAL` flag stays off**; **CI's eval gate stays v2** and lexical; a query with no caller-supplied vector keeps doing no vector work; nothing embeds on the agent/prefetch thread.

### Step 1 — collect the real turns (**blocked on the environment, which is now measured**)

- **The ceiling question is settled and armed** — see Part A and plan §9 item 7. Do not reopen it, and do not re-arm `max_v2_miss_rate` from a synthetic sample: the pre-registered rule in `_shadow.MISS_CEILING_RULE` armed it from **EM-306's holdout** — v2's own miss rate against a held-out reference, `0.107143`.
- **The blocker is that this box does not run the plugin at all** (plan §9 item 8, measured read-only): `~/.hermes/config.yaml` has **no `memory.provider` key**, `plugins.enabled` lists only `homeassistant`, there is **no `~/.hermes/plugins/entropicmem`** and no live clone, no vault, `index.db` holds 0 notes, and every table in the live store is empty at `user_version=0`. So the zero-fact state is **expected**: no turn reaches the plugin, so no write path runs and nothing can reach the shadow. **It will not fix itself by accumulating.** Real turns need a host where the **dev-line** plugin is installed and enabled — the released 2.8.1 carries no shadow code (verified with `git ls-tree origin/release/2.8.x`), so the owner's active 2.8.1 deployment cannot collect as-is — with `ENTROPICMEM_SHADOW_V3` set. **Owner-reported 2026-10-08: the owner's machine (§2) is an active deployment with real data, so the host exists; the owner-facing step is enabling the shadow-capable line there.**
- **Collect, once such a host exists:** set `ENTROPICMEM_SHADOW_V3=<v3 copy path>` (the log defaults beside it; `ENTROPICMEM_SHADOW_LOG` overrides) and let real turns accumulate. **Read:** `python <plugin>/_shadow.py report` — it prints the distribution, the margin on every gated condition, the miss/add shape, the staleness bound, the no-vectors caveat and the arming rule, and exits 0/1/2 for met/not met/cannot conclude.
- **Plumbing smoke without waiting on traffic:** `python scripts/shadow_collect.py --source <a store with facts> --turns 200` (or `--empty`). It opens the source `mode=ro`, copies it, and never writes it. On a zero-fact store it correctly returns `CANNOT CONCLUDE` with `no signal`; on the 8-fact synthetic store it returns a real reading — **which is evidence about the metric, never about turns.**
- **Never lower a threshold to fit a sample**, and never read a miss or divergence number without its `copy_age_s`/`stale` (divergence is a **lower bound**) or its caveat (v3 is fed no query embedding, so its scores are lexical/entity/episodic — **not** an apples-to-apples quality comparison; the printed caveat string itself still says "until EM-303" and needs a one-line fix, recorded not fixed in the 2026-10-15 docs pass). The report carries both by default; a hand-written summary that drops them is the failure mode.
- **Measured at scale, read-only, repeated (11 × 200 turns over a 1060-fact synthetic perf-bench corpus; source sha256 verified byte-identical before and after):** fabrication **0** — the hard ceiling holds at scale. **p95 2.59–2.74 ms in every run** (five fresh-copy runs 2.59/2.60/2.62/2.70/2.65; six warm runs 2.64–2.74), against the pre-declared 150 ms off-turn budget. **Every run's max is the copy-refresh turn** — the copy+migration inside `shadow.run` on the first turn of a fresh copy: 96.69–119.51 ms cold, 132.90 ms in the earlier single run — while on warm runs (copy reused inside the 900 s bound) max is **3.83–4.52 ms**. The earlier lone "max 132.90" was the refresh cost, not a per-turn one, and it is now a distribution rather than one number. And **miss rate 100% (350 of 350 ids v2 injected, 75 of 75 turns)** because v3 abstained on every turn where v2 injected. **That is not evidence v3 is worse.** The corpus is benchmark filler with no correct answer for those queries, so v2's 350 ids are *noise* and v3 correctly declined them — 125 of 200 turns v2 also injected nothing. **This store is a performance fixture only; it cannot support any quality claim.**
- **The lesson for arming, and it is a real one:** the shadow's miss rate is a **v3-vs-v2** quantity, so it is only interpretable where v2's own injections are mostly *correct* — i.e. on a real store, not on filler. Note also the **unit mismatch** to state explicitly in whichever commit arms the ceiling: the bound is derived from a **v2-vs-truth** rate (`1 − recall@5` on the holdout) but applied to a **v3-vs-v2** ratio. That is a defensible policy ("v3 may drop no more of v2's hits than v2 itself misses against truth") but it is not an identity, and it must not be written as one.
- **The miss ceiling is armed now, so a clean sample can read `met`** — the `cannot conclude` shape was the un-armed era's expected reading; the report still names every dimension and its margin, and a violation still outranks a short sample.

### Step 2 — the next card: **the owner's to place** (EM-407 landed)

**The order is the owner's (2026-10-08; extended 2026-10-16): EM-401–403 first, EM-411 after EM-406, and S4 runs EM-406 → EM-411 → the rest by dependency.**
**EM-401–404, EM-405 and EM-407 are now complete and merged** (`b8e170a`;
`2706a86`; slices 1–3 at `9f9ba0c`, `31053df`, `a5b613a`; EM-404 at `381197f`,
`e5e54ef` and the validation slice `5000942`; EM-405 at `e483d43`; EM-407 at
`2b21ad1`, and the hardening pull at `dc3c77a` — Part B items 1–5).
**The next chunk is EM-406 (checkpoint v2 / evidence archive) — the owner's S4
order: EM-406, then EM-411, then the rest by dependency.** The
**query-embedding wiring card** (the open gap above) is **drafted (2026-10-16)
and awaits the owner's approval before any implementation**; after EM-411 the
rest of S4 follows by dependency — **EM-408** (CLI), **EM-409** (system prompt —
the natural home of the owed alias rewrite), **EM-410** (cron & worker
integration). Whatever is chosen: branch-first, tests first, one CHANGELOG
line, check-runs on the exact SHA, `git merge --ff-only`. EM-411 (capture on idle &
compaction, requested by the owner 2026-10-09) stays planned, test-first, default
off (plan §6.3).

### Step 3 — the pre-flight count guard. **DONE, MERGED (2026-10-08, hygiene chunk)**

Chunk 18's pre-flight said **1995** while `MASTER_TODO` and reality said **1998**: the drift is not
that a number was wrong once, it is that three pages state the suite size by hand and nothing
compared them. `tests/test_master_todo.py` now extracts the `passed / skipped / xfailed` triple from
`MASTER_TODO`'s gates table, this file's pre-flight and `REMAINING_PLAN.md` §11's verify block — one
anchored line each — and fails if they disagree, if an anchor stops matching exactly one line, or if a
page drops out of the comparison.

**Cross-file agreement only, deliberately.** Comparing against a live collection would need a nested
pytest run, which trades a silent drift for a flaky gate (and `--collect-only` cannot see
collection-time skips, so the number would not match anyway). The suite's own pre-flight run is what
checks the pages against reality; this guard makes sure that when the run disagrees, the pages cannot
*also* disagree among themselves.

**Why the comparison is a pure function:** the docs agree today, so a guard whose only input is an
agreeing tree cannot be mutation-proven — weakening its comparison slipped through green until
disagreement was handed to it directly. `_baseline_disagreement` takes the triples, and the tests feed
it drift, a drifted skip pair, and an implausible size. Nine mutation checks: **eight caught**; the one
survivor is a knowingly redundant in-doc probe that the synthetic tests already cover, and it is
labelled as such in the code rather than left looking load-bearing.

**The discipline this does not replace:** read the expected number from this file's pre-flight, run the
suite, and **stop and report on a mismatch** instead of assuming the older number is right.

### Size guards — stop and report if

- **a threshold needs moving to get a reading** — that is not a reading (this is Part B step 1's decision, and it is the owner's).
- **a step wires `gate.*`/`ranking.*` beyond the provider wiring EM-407 landed, or restructures the provider/facade** — the tuned defaults reach call sites via EM-407 (`2b21ad1`; EM-401–403 did not wire them), and a renderer is not a config system.
- **a step invents a cosine path outside stored vectors or embeds on the query thread** — the backends and the `embed` job are EM-303's remainder, and a query with no caller-supplied vector must keep doing nothing.
- **anything would write the live store, move the Marketplace entry, or touch a tag.**

### Pre-flight

1. `main` must be at `4eb8097` or later: `git merge-base --is-ancestor 4eb8097 main`.
2. **Baseline:** three commands, three counts — **each figure is the command's own output**, and the 77-passed gap between the first two is fully accounted: **fastapi** graph modules 67 (`test_graph_server_v2_6.py` 14 + `test_graph_server_security.py` 48 + `test_graph_server_titles.py` 5; 0 collected without fastapi) + **cryptography** 7 (`test_phase11.py` 2 + `test_security_decrypt_guard.py` 5) + **numpy** 2 (`test_em_embedding_cache.py` 225 and 240) + **privacy** 1 (`tests/evals/test_no_personal_data.py`; skips with no list configured) = 77. **CI's `test` job (3.12): `pytest -q tests/` → 2626 passed, 3 skipped, 3 xfailed** — measured 2026-10-16 at `dc3c77a`, with CI's extra set (fastapi, httpx, cryptography, pyyaml), numpy, and the private digest list as the repository secret; the three skips there are the two internal-ops script tests plus `tests/test_provider_contract.py` (its pinned hermes-agent file is not on the runner). **This box bare: `.venv311/bin/python -m pytest -q` → 2549 passed, 16 skipped, 3 xfailed with zero failures** — the missing extras change what is collected and skipped, which is the environment, not the tree; the 16 skips are the fastapi family (4 entries: three module-level + one inside `test_graph_static.py`) + cryptography 7 + numpy 2 + privacy 1 + the two internal-ops script tests. **With the digest list in place: `ENTROPICMEM_PRIVACY_DIGESTS_FILE=… .venv311/bin/python -m pytest -q` → 2550 passed, 15 skipped, 3 xfailed** (the privacy skip becomes a pass); the scratch venv carrying CI's extras and the digest file on 3.12.13 reads **2627 / 2 / 3** (only the internal-ops pair skips). The figure the three pages' counters state is CI's 3.12 pair, **2626 / 3 / 3**, and a pre-flight run is checked against it. The skip delta is **13 = 14 local-extra − 1 CI-extra**: locally the fastapi (4) + cryptography (7) + numpy (2) + privacy (1) families skip; in CI `test_provider_contract.py` does. The documented skip families are otherwise unchanged: the two internal-ops script tests (`test_v2_1_8.py`, `test_v2_2_0.py`), the two numpy-gated tests (pass with numpy, and `tests/test_vector_ci_guard.py` fails if that install or either gated test disappears), and the private digest-list privacy test (skips with no list configured, passes with one, and **fails closed** under `ENTROPICMEM_REQUIRE_PRIVACY_DIGESTS=1` with no list). The list is not at the default path on this box but **is** at `~/Documents/EntropicMem Dev docs/privacy-digests.txt`: point `ENTROPICMEM_PRIVACY_DIGESTS_FILE` at it **in place** (never copy it into the repo).
3. **Re-measure from the code, not this file:** `_shadow.py` (`PROMOTION`, `MISS_CEILING_RULE`, `evaluate`, `read_log`, `render`, `main`), `scripts/shadow_collect.py`, `em/facade/engine.py` (`v3_retrieval_enabled`, `_recall_from_v3`), `em/retrieval/pipeline.py`, `em/retrieval/candidates.py` (`vector`), `em/embeddings/` (`backends`, `service`, `jobs`, `cache`), `em/store/embeddings.py`, `em/config.py`, `evals/tune.py`, `em/retrieval/gate.py` (`load_rows`' pinned input), `evals/` (`runner`, `metrics`, `adapters/engine_v3.py`), `.github/workflows/test.yml`.
4. **Verify CI with the check-runs API on the commit**, and read `head_sha`.

### Document control

Per `AGENTS.md`, with the reconciliation folded into the docs commit. `In flight` names no commit; `Last reconciled` names the previous chunk's permanent ancestor. Chunk 13 stays internal; the Marketplace entry is untouched. **Never write to the live store** — and remember the two rules this chunk was shaped by: **run the thing once, on a real store** (that is how the `kind='constraint'` bug and the symmetric-ceiling finding surfaced), and **a test that asserts on a stopwatch measures the runner.**


## SLICE3 (2026-10-14 → 2026-10-15)

The slice-3 brief (`25a8d68`) and build note (written when `f674146` landed) now live
as the **Chunk 34 / slice-3-first-half record in Part A above** — the brief is kept
there verbatim as the plan-as-record, together with what was built against it, what
deliberately was not, and the process record for the two direct-to-`main` commits.
**Deliberately not repeated here:** duplicating them is how the two copies drifted in
the first place (the build note claimed slice 3 "done" while `MASTER_TODO` still said
the service was unwired — the contradiction this reconciliation removed).
