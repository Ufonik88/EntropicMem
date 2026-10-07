# EntropicMem: next steps (one chunk at a time)

**Updated:** 2026-10-07, Chunk 16 (the v3 eval adapter, P1) merged to `main`; **P0 — wire S3's read path into the provider — is the next piece.** **Read first:** `MASTER_TODO.md`, then `docs/plan/REMAINING_PLAN.md` (its §3 rules apply to everything here), then `AGENTS.md` and `docs/V3_FOUNDATIONS.md`.

**Owner decisions in force:**
- **The cutover is deferred, with an explicit re-decision point: reconsidered when (a) the provider reads through S3, and (b) the v3 adapter has produced one end-to-end eval number — not before.** **(b) is met** (ci parity, hard recall@5 0.933 with lower noise). **Do not switch the live store without the owner's explicit go.**
- **Priority order P0 → P1 (done) → P2 → P3.** P0 is the provider wiring; P2 is EM-306.
- **Chunk 13's visibility change is ratified and internal only.** It **cannot be a 2.8.x patch** — `release/2.8.x` carries no `em/` at all (verified with `git ls-tree`) — so its only vehicle is 3.0. It does **not** need to land before the cutover, and it must not be bundled with it: a security-relevant change should not be hostage to a migration decision.
- **EM-305's gate must not depend on EM-301's intent table** (92.9% on 42 samples).

**Plan exactly one chunk.** When a chunk ends, replace this file with the plan for the next single chunk; never more than one ahead.

**Two commits per chunk is the target:** code+tests+CHANGELOG, then the docs commit with the reconciliation folded in.

**The master plan is at `~/Documents/EntropicMem Dev docs/EntropicMem_v3_Master_Plan.md`** (the owner's document, deliberately not committed). EM-301's…EM-306's cards plus §3.6 and §4 are transcribed into `REMAINING_PLAN.md` §6.2. **Before starting a card whose text is not there, read that file** — and if it is unreachable, stop and report rather than inventing fields.

---

## Part A: what has landed

Only the recent chunks; the full ledger with SHAs is `REMAINING_PLAN.md` §5.

### Chunk 16 — the v3 eval adapter (P1). **DONE, MERGED (2026-10-07, `ff0d3c3`)**

- `evals/adapters/engine_v3.py` drives **the real pipeline** (`analyze → GENERATORS → fuse → rank → gate → collapse → mmr`) over a migrated v3 store. `search` runs without the gate (ranking metrics measure ORDER — the v2 adapter's own `min_relevance=0.0` split); `prefetch` runs with it and returns `''` on abstention.
- **First end-to-end v3 numbers**, against v2 on the same runs:

  | suite | v3 | v2 |
  |---|---|---|
  | **ci** overall | recall@5 1.000 · abstain 1.000 · noise 0.143 · must_not_ok 1.000 | identical |
  | **hard** overall | **recall@5 0.933** · abstain 1.000 · **noise 0.172** · must_not_ok 1.000 | 0.939 · 1.000 · 0.219 · 1.000 |
  | hard/ageing | **0.733** | **0.733** |

  Parity on recall with **lower noise**, and `ageing` at 0.733 for both — §6.2's predicted lexical-only figure, because the four paraphrase misses share no words with the stored fact and vectors are EM-303's. Reproducing the *known* number exactly is a cross-check on the adapter.
- Baselines: `evals/baselines/v3-ci.json`, `v3-hard.json`. **CI's gate is deliberately unchanged** (still v2 against `v2.8.0-ci.json`) — making v3 fail a build is a decision about what CI enforces and belongs with EM-306.
- 10 tests in `tests/evals/test_adapter_v3.py`, which is also what runs the adapter in CI.

### Chunk 15 — EM-305, the gate, collapse and MMR. **DONE, MERGED (2026-10-07, `50601b3`, pins at `9f4b39b`)**

- The four support conditions then the score threshold; **pinned bypasses**. Coverage is measured with **the index's own tokenizer** (the "post-stem" trap resolved exactly), and the coupling is now **pinned by a test** that reads the schema — `gate.index_tokenizer` / `tokenizer_matches_index`.
- The collapse groups duplicates on **loaded text**, because `_content_hash` mixes the scope into the digest; it prefers the narrower scope and keeps the successor of a live chain. MMR λ = 0.7 over the top 20 on Jaccard. `diversity._require_texts` refuses a mapping keyed by anything but `Ranking.key` — the class, not the incident, behind the draft bug that passed for the wrong reason.
- 54 tests; **23 mutation checks all caught first pass**; two review-driven guards proven red by mutation.

### Chunks 11–14 — EM-302, EM-301, the `visibility` fix, EM-304. **DONE, MERGED**

Details in `REMAINING_PLAN.md` §5. **S3's retrieval pipeline is complete, scored end to end, and still unwired — which is exactly what P0 fixes.**

---

## Part B: P0 — wire S3's read path into the provider

**The owner's words:** *"Nothing else produces signal until this exists, and it's the precondition for any honest cutover."* And, on the empty store: *"it also means a cutover buys almost no real-turn signal… Consider a shadow read (read v3, serve v2, log divergence) behind a flag. That gets the real-turn signal the counter-argument wants without committing the store. Your call on implementation."*

### The proposed shape (a proposal — the implementation is the agent's, the risk posture is the owner's)

**P0a — the shadow read, behind a flag, default off.**

* `ENTROPICMEM_SHADOW_V3=<path>` (or a config key) names a **v3 copy** of the store.
* The turn is served by **v2 exactly as today**. Nothing about the live store, its schema, or the served answer changes when the flag is unset — and it is unset by default.
* **Post-turn and off the turn path**, S3 runs over `<path>` and the provider appends `{query, v2_ids, v3_ids, timings}` to a divergence log. Latency on the turn is untouched, which is the whole point: this must not become a synchronous v3 read on the agent thread (§4.2's rule, and the reason EM-403 exists).
* **The honest limitation:** without S5's sync wiring there is no way to keep a second store in step, so the copy **lags**. Refresh it on demand or from a cron, and record the refresh time in every divergence line so a stale copy cannot be mistaken for a live one.
* Exercising the migration on copies repeatedly is a **feature** of this design, not a side effect: it is the migration path itself, run often, on throwaway data, long before the real cutover.

**P0b — on a v3 store, prefetch reads through S3.**

* A v3 store already gets the facade; this makes the *retrieval* stage of prefetch use `em.retrieval` instead of the v2 scoring the facade borrows today.
* Behind the same kind of flag at first, so a v3 store can be compared v2-scoring-vs-S3 without a redeploy: `ENTROPICMEM_V3_RETRIEVAL=1`. The flag exists only on the v3 path, because engine selection is by `PRAGMA user_version` — **which is why the shadow (P0a) is the only form that gives real-turn signal without committing the store.**

### What is already in the repo, so do not rebuild it

* `plugins/entropicmem/__init__.py` — `_open_engine()` selects by `user_version`; `prefetch()` renders the block. The nine `MemoryEngine(` sites all route through the one selector.
* `em/facade/engine.py` — `V3Engine`'s `recall_with_relevance`/`recall_hybrid` currently borrow v2's scoring through a lazy `memory_engine` import; that is the seam P0b replaces.
* `em/retrieval/*` — the whole pipeline, and `evals/adapters/engine_v3.py` shows exactly how to drive it end to end. **Reuse that call sequence**; do not invent a second one.
* The render shape is parsed by `evals.runner.parse_injected_ids` (`- [id] text`), and §3.6/EM-307 own the real one.

### Size guards — stop and report if

* **the flag changes v2 behaviour when it is off.** The single most important property here. A test must drive a v2 store with the flag unset and assert the served block is byte-identical to today's.
* **the shadow needs the turn path.** If a divergence check cannot be deferred past the turn, say so — a synchronous v3 read on the agent thread is a different (and worse) design that belongs with EM-403's PrefetchService, not here.
* **P0b pulls in S4.** §4.1–§4.2's ProviderService, `ScopeContext` and the hook rewrite are EM-401–403. This chunk makes the *retrieval stage* read through S3; it does not restructure the provider.
* **the shadow's copy has no way to be truthful.** If the refresh cannot be made visibly timed (a stale copy silently passed off as live would be worse than no shadow at all), stop and report.

### Pre-flight

1. `main` must be at `ff0d3c3` or later: Chunk 16 merged there. `git merge-base --is-ancestor ff0d3c3 main` proves it.
2. **Baseline:** `pytest -q` gives **1980 passed, 3 skipped, 3 xfailed** on **both Python 3.10 and 3.12**.
3. **Re-measure from the code**, not from this file: `_open_engine` and the provider's `prefetch`, `V3Engine`'s read half, where `core_inject_mode` and the prefetch config keys live, and whether anything already writes a diagnostic log the divergence line can join.
4. **Verify CI with the check-runs API on the commit** (`ghx api repos/Ufonik88/EntropicMem/commits/<sha>/check-runs`), not `ghx run list --branch main --limit 1`, which can return a stale run and look green.

### After P0: EM-306 (P2)

Its card is unchanged and still ready: `dev`/`holdout` split **by id hash**, `python -m evals tune --params gate.min_score,gate.min_coverage,ranking.w_* --grid …` optimising `0.4*recall@5 + 0.3*mrr + 0.3*abstain_correct − 0.2*noise_rate`, defaults written into `em/config.py` (which does not exist yet — this is where it starts), per-model cosine calibrated separately (**the grid is empty until EM-303**). AC: holdout metrics reported, defaults committed, §6.3's gates updated. **Its first prerequisite — the v3 adapter — is now met; the second, `em/config.py`, is this chunk's own first step.** The owner's constraint stands: **do not let the gate depend on the 92.9%-on-42 intent table** — if tuning shows it does, widen the table first.

### Document control (before and after)

Per `AGENTS.md`: reconcile `MASTER_TODO.md`, `REMAINING_PLAN.md` and this file **before** starting and **again before finishing**, with the reconciliation folded into the docs commit. Merge state counts as truth. Chunk 13 stays internal; do not touch the Marketplace entry.

### End of chunk

1. Push, green CI on the exact SHA, `git merge --ff-only`, delete the branch.
2. Update `MASTER_TODO.md` and `REMAINING_PLAN.md` §2/§5/§9/§11.
3. **Replace this file's Part A with this chunk and Part B with the next piece** — EM-306, then **bring the cutover decision back to the owner** once (a) is met.
