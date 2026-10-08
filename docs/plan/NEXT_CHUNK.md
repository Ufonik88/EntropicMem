# EntropicMem: next steps (one chunk at a time)

**Updated:** 2026-10-08, end of session. **P0b is merged: on a v3 store, `ENTROPICMEM_V3_RETRIEVAL=1` serves prefetch from S3** — code `be6352e` plus its docs commit, both merged `--ff-only` after green check-runs on the tip. The repo rests green: 2019/3/3 on both Pythons, `ruff` clean, the v2 eval gate unmoved, nothing in flight, the live store and the Marketplace entry untouched. **Both cutover re-decision conditions are now met; the decision is back with the owner.**

**Owner decisions in force:**
- **The cutover is deferred until (a) the provider reads through S3 and (b) the v3 adapter has produced one end-to-end eval number.** **(b)** was met by `ff0d3c3`; **(a)** is now met in code by P0a (`f0a7c70`, the shadow read) and P0b (`be6352e`, a v3 store serving from S3 behind a default-off flag, measured p95 9.32 ms). **The decision goes back to the owner; do not switch the live store without an explicit go.**
- **Priority order P0 → P1 (done) → P2 → P3.** **The owner decides the cutover; the agent brings it.**
- **Chunk 13 is forward-only, ratified, and internal only.** No data needs repairing (the migration stamps `visibility='profile'`; the live store is v2/`user_version=0`), and its only release vehicle is 3.0 — `release/2.8.x` carries no `em/` at all.
- **EM-305's gate must not depend on EM-301's intent table** (92.9% on 42). If tuning shows it does, **widen the table first**.

**Plan exactly one chunk.** Two commits: code+tests+CHANGELOG, then docs with the reconciliation folded in. **`MASTER_TODO`'s `In flight` does not name a commit**; `Last reconciled` carries a permanent ancestor. Verify CI with the **check-runs API on the exact SHA** (`ghx api repos/Ufonik88/EntropicMem/commits/<sha>/check-runs`), never `ghx run list --branch main --limit 1`, which can hand back a stale green.

**The master plan is at `~/Documents/EntropicMem Dev docs/EntropicMem_v3_Master_Plan.md`.** EM-301…EM-306 plus §3.6/§4 are transcribed into `REMAINING_PLAN.md` §6.2; EM-306's card is quoted in Part B below.

---

## Part A: what has landed

### Chunk 18 — P0b: a v3 store serves prefetch *from* S3. **DONE, MERGED (2026-10-08, `be6352e`)**

- **The seam is the facade's read half, not the provider.** `V3Engine.recall_with_relevance` gains a second mode; the provider is untouched. `ENTROPICMEM_V3_RETRIEVAL` is strictly `"1"` (the `ENTROPICMEM_ALLOW_LIVE_MIGRATION` shape), read per call, **default off**, and can only exist on a v3 store.
- **One pipeline, not four.** The on path calls `em.retrieval.pipeline.retrieve` (**with** the gate) — the same sequence the eval adapter and the shadow call — and maps its memory rankings back to v2 `StoredFact`s, so the provider's renderer and config keep working. `legacy_id` remains the id, so dedup and `touch` resolve what was injected.
- **The off path is byte-identical to pre-P0b, proven twice.** A golden pins the full provider response (system prompt, context query, first prefetch, *cached* second prefetch, abstaining query) and the engine result against output captured before the flag existed; the fixture re-run in a detached worktree of the base commit differed only in its per-run ULID diagnostics. Independently, a `retrieve` that raises is never called with the flag off.
- **Two recorded differences on the on path:** **episodes are skipped** (the pipeline ranks them; a v2 fact has no episode shape and §3.6's render is EM-307's) and v2's `min_relevance`/decay/evergreen knobs are **not** applied over S3's gate (`domain` is a post-filter; it can return fewer than `top_k`).
- **The renderer did not grow.** No new renderer: the exact bullets are `- [id] text (domain · date) [score:x]`, pinned as lines, with a test asserting nothing EM-307 owns leaks in.
- **Latency, against the pre-declared p95 ≤ 150 ms** (1000-memory store, cache off, engine construction included): prefetch **4.18 → 9.32 ms** (p50 3.75 → 8.89); engine call **1.01 → 6.14 ms**. Budget untouched.
- **A defect the end-to-end run found: the gate read only the `pinned` column**, so a `kind='constraint'` row its own pinned generator surfaced was filtered instead of bypassing (REMAINING_PLAN §6.2's table: "bypasses gate"). Fixed in `gate.load_rows`, pinned at the loader and at `apply_gate`; no scored dataset uses the kind.
- 21 new tests; **2019 passed / 3 skipped / 3 xfailed on 3.10 and 3.12**; **13 mutation checks, all caught first pass**; v2 eval gate green.

### Chunk 17 — P0a, the v3 shadow read. **DONE, MERGED (`f0a7c70`)**

- `plugins/entropicmem/_shadow.py`: enabled only by `ENTROPICMEM_SHADOW_V3=<path>` (**unset = inert**). v2 serves the turn; S3 runs **post-turn, off the turn path**, over a **v3 copy**; one divergence line per turn. Full-response byte-identity asserted; off-turn proof by blocking the shadow thread.
- Every line carries `copy_age_s` / `copy_refreshed` / `stale` (**divergence is a lower bound**) and a `caveat` (**no cosine until EM-303**; not apples-to-apples).
- **Promotion observable fixed before collecting:** ≥ 200 turns, copy within 900 s, divergence ≤ 10%, **`v3_only` never non-zero**, off-turn p95 ≤ 150 ms. Agent proposal; do not lower a threshold to fit the sample.
- `em/retrieval/pipeline.py` was extracted so adapter and shadow share **one** pipeline; P0b added the third caller rather than a fourth copy.

### Chunk 16 and earlier

The v3 eval adapter (P1, `ff0d3c3`, with its first end-to-end numbers and baselines), EM-305, EM-304, EM-301/302, the `visibility` fix. `REMAINING_PLAN.md` §5.

---

## Part B: next — P0c (collect the shadow data), then P2/EM-306

**Two candidate next steps, in the owner's order. P0c is data collection and needs real turns on the owner's host; EM-306 is the buildable code chunk. If P0c's data is not yet at 200 turns, build EM-306.**

### P0c — read the shadow data against the pre-declared observable

- **What to do:** run the provider with `ENTROPICMEM_SHADOW_V3=<v3 copy path>` on real turns (the owner's host, not this dev box), then read the divergence log against the observable — **≥ 200 turns, copy within 900 s, divergence ≤ 10%, `v3_only` never once non-zero, off-turn p95 ≤ 150 ms** — exactly as fixed before collection in `_shadow.PROMOTION`.
- **Do not lower a threshold to fit the sample**, and do not read a line without its `copy_age_s`/`stale` (divergence is a **lower bound**) or its `caveat` (no vectors until EM-303, so it is **not** an apples-to-apples quality comparison).
- **What this is not:** it does not promote anything. The observable is a report; any change to defaults or to the flag's default value is the owner's call, brought with the evidence.
- **Live store:** read-only, as P0a already pins; the copy is migrated on refresh, so this exercises the cutover path on throwaway data.

### P2 / EM-306 — calibration and tuning harness (**the buildable chunk**)

**Card, from the master plan:** *Calibration & tuning harness · M. Depends on EM-301–305, EM-002.*
*Spec:* split scenarios into `dev` (70%) / `holdout` (30%) **by id hash**; `python -m evals tune --params gate.min_score,gate.min_coverage,ranking.w_* --grid …` optimising **`0.4*recall@5 + 0.3*mrr + 0.3*abstain_correct − 0.2*noise_rate`**; write chosen defaults into `em/config.py` with a comment linking the result file; per-model cosine thresholds calibrated separately. *AC:* holdout metrics reported; defaults committed; §6.3 gates updated to the new baseline.

- **`em/config.py` does not exist yet — this is where it starts.** Keep it minimal: the tuned scalars from this card (`gate.*`, `ranking.*`), not EM-407's typed nested `Config` (Appendix A, loader precedence, setup integration). If it starts growing a loader, validation surface or schema emission, stop — that is EM-407.
- **The split is by id hash, not by order**, so a rerun scores the same holdout set; report **holdout** metrics, not the dev numbers the grid optimised.
- **The gate must not depend on EM-301's intent table.** If tuning shows it does, widen the intent table first (more labelled queries), never tune around the miss.
- **Per-model cosine last: the grid is empty until EM-303** (no embedding backend means `cosine_enabled` is off and MMR stays on Jaccard). Record that as deliberately deferred in the result file, not skipped silently.
- **CI's gate stays v2** until someone deliberately makes v3 fail a build; §6.3's gates move only with holdout evidence. **Until then `tests/evals/test_adapter_v3.py` is v3's only regression protection — it runs in the default suite.**
- **`gate.*`/`ranking.*` plumbing:** today they are dataclass defaults on `GateConfig`/`RankWeights`; the provider does not pass them. EM-306 commits *tuned defaults*; wiring config into the provider's call sites is the provider cards' (EM-401–403). Say which parts of that remain open in the PR.

### Size guards — stop and report if

- **EM-306 starts restructuring the provider or the facade.** It measures and defaults; it does not wire config through call sites.
- **P0c's reading needs a threshold moved.** That is not a reading.
- **either chunk needs EM-303's vectors to be meaningful.** The grid is empty without them; do not invent a cosine path.

### Pre-flight

1. `main` must be at `be6352e` or later. `git merge-base --is-ancestor be6352e main` proves it.
2. **Baseline:** `pytest -q` gives **2019 passed, 3 skipped, 3 xfailed** on **both Python 3.10 and 3.12** (3 skips on a box without the private digest list; CI runs with it).
3. **Re-measure from the code**, not this file: `em/facade/engine.py` (`v3_retrieval_enabled`, `_recall_from_v3`), `em/retrieval/pipeline.py`, `em/retrieval/gate.py` (`load_rows`' pinned input), `plugins/entropicmem/_shadow.py`, `evals/` (`runner`, `adapters/engine_v3.py`, `metrics.py`).
4. **Verify CI with the check-runs API on the commit**, not `ghx run list --branch main --limit 1`.

### Document control

Per `AGENTS.md`, with the reconciliation folded into the docs commit. `In flight` does not name a commit. Chunk 13 stays internal; do not touch the Marketplace entry. **Never write to the live store.**