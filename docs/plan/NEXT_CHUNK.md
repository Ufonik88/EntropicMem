# EntropicMem: next steps (one chunk at a time)

**Updated:** 2026-10-07, end of session. P0a (the v3 shadow read) is merged and verified end to end, including the id-space fix the end-to-end run found; **P0b — a v3 store serving prefetch *from* S3 — is the next piece and has not been started.** The repo is at a clean resting point: all gates green, nothing in flight, the live store and the Marketplace entry untouched. **Read first:** `MASTER_TODO.md`, then `docs/plan/REMAINING_PLAN.md`, then `AGENTS.md` and `docs/V3_FOUNDATIONS.md`.

**Owner decisions in force:**
- **The cutover is deferred until (a) the provider reads through S3 and (b) the v3 adapter has produced one end-to-end eval number.** **(b) is met.** **(a) is half-met:** P0a's shadow reads S3 off the turn path over a copy, but on a v3 store prefetch still uses the v2 scoring the facade borrows. **Do not switch the live store without the owner's explicit go.**
- **Priority order P0 → P1 (done) → P2 → P3.** **The owner decides the cutover; the agent brings it.**
- **Chunk 13 is forward-only, ratified, and internal only.** No data needs repairing (the migration stamps `visibility='profile'`; the live store is v2/`user_version=0`), and its only release vehicle is 3.0 — `release/2.8.x` carries no `em/` at all.
- **EM-305's gate must not depend on EM-301's intent table** (92.9% on 42).

**Plan exactly one chunk.** Two commits: code+tests+CHANGELOG, then docs with the reconciliation folded in. **`MASTER_TODO`'s `In flight` no longer names a commit** — that was the drift; `Last reconciled` carries the SHA.

**The master plan is at `~/Documents/EntropicMem Dev docs/EntropicMem_v3_Master_Plan.md`.** EM-301…EM-306 plus §3.6/§4 are transcribed into `REMAINING_PLAN.md` §6.2.

---

## Part A: what has landed

### Chunk 17 — P0a, the v3 shadow read. **DONE, MERGED (2026-10-07, `f0a7c70`)**

- `plugins/entropicmem/_shadow.py`: enabled only by `ENTROPICMEM_SHADOW_V3=<path>` (**unset = inert**). v2 serves the turn; S3 runs **post-turn, off the turn path**, over a **v3 copy**; one divergence line per turn.
- **Asserted, not inspected:** the **full provider response** is byte-identical with the shadow on and off (system prompt, context query, first prefetch, *cached* second prefetch, an abstaining query); and the shadow is **not on the turn path**, proven by blocking its thread on an event and showing the response still returns. Plus a test that the flag actually enables the work, because byte-identity is meaningless otherwise.
- **Both biases travel with every number:** `copy_age_s` / `copy_refreshed` / `stale` (the copy **lags**, so divergence is a **lower bound**), and a `caveat` (no cosine until EM-303, so **not** an apples-to-apples quality comparison against v2).
- **Promotion observable fixed before collecting:** ≥ 200 turns, copy within 900 s, divergence ≤ 10%, **`v3_only` never non-zero**, off-turn p95 ≤ 150 ms. Agent proposal, owner may adjust.
- **Live store never written** (read-only refresh; a test asserts bytes+mtime unchanged). The copy is **migrated** on refresh, so the cutover path runs often on throwaway data.
- **`em/retrieval/pipeline.py` extracted** so the eval adapter and the shadow share **one** pipeline. Proven behaviour-preserving: 40 of 45 ci metrics byte-identical, the five being `latency_ms`.
- **Two real findings kept:** `test_f005_uses_spawn_context_thread` (a *passing* regression test) rejected a bare `threading.Thread` — F-005b/H3 requires every background thread to come from `_spawn`, and the shadow now does; and `test_plugin_imports.py`'s loader never registered its own module, so `from . import _shadow` failed for a module sitting right there — the loader now registers itself as a real import does.
- 15 new tests. **1995 passed / 3 skipped / 3 xfailed on 3.10 and 3.12**; v2 eval gate green; v3 ci numbers unchanged.

### Chunk 16 — the v3 eval adapter (P1). **DONE, MERGED (`ff0d3c3`)**

- `evals/adapters/engine_v3.py` over a migrated v3 store; `search` without the gate (ORDER), `prefetch` with it (abstention). **ci at full parity with v2; hard recall@5 0.933 vs v2's 0.939 with noise 0.172 vs 0.219; `ageing` 0.733 for both** (§6.2's predicted lexical-only figure). Baselines `evals/baselines/v3-{ci,hard}.json`. **CI's gate deliberately still v2.**

### Chunk 15 and earlier

EM-305 (gate/collapse/MMR, with the tokenizer coupling and the key-shape guard mutation-proven), EM-304, EM-301/302, the `visibility` fix. `REMAINING_PLAN.md` §5.

---

## Part B: P0b — serve prefetch from S3 on a v3 store

**What is missing, precisely:** a v3 store already gets `V3Engine`, and `V3Engine`'s read half borrows **v2's** scoring through a lazy `memory_engine` import (`em/facade/engine.py`). So even on a v3 store, what reaches the model is v2's ranking. P0b replaces that stage with `em.retrieval` — and that is what makes cutover re-decision condition **(a)** true.

### Shape

* **Behind a flag first** — `ENTROPICMEM_V3_RETRIEVAL=1` (or a config key). A v3 store must be comparable both ways without a redeploy, and the flag defaults **off**.
* **The seam is `V3Engine`'s recall path**, not the provider: the provider already asks the engine, so the engine is where "which ranking" belongs. Reuse `em.retrieval.pipeline.retrieve` — the same one the adapter and the shadow call. **Do not write a fourth pipeline.**
* **The flag only exists on the v3 path.** That is not a shortcut; it is why P0a had to be a shadow over a copy.

### Size guards — stop and report if

* **the flag changes behaviour when off.** A test must drive a v3 store both ways and assert the un-flagged output is byte-identical to today's — the same discipline P0a's full-response test used.
* **the response shape drifts.** `em.retrieval` returns rankings and rows; the provider needs a rendered block in v2's shape (`- [id] text`, `(domain · date)`). The packer and §3.6's render are **EM-307's** — so if P0b needs a renderer, keep it minimal, say so, and do not let it become EM-307.
* **prefetch latency regresses.** P0a was off-turn; P0b is *on* it. The shadow's `shadow_ms` (p95 ≤ 150 ms) is the pre-declared budget and §4.2's; measure before and after.
* **it needs the provider rewrite.** §4.1/§4.2's ProviderService, `ScopeContext` and the hook set are EM-401–403. P0b changes the *ranking stage*; if it starts restructuring the provider, stop.

### After P0b

1. **P0c — read the shadow data** against the pre-declared observable (above), with the staleness bound beside every number. Do not lower a threshold to fit the sample.
2. **P2 — EM-306**, unchanged: `dev`/`holdout` split **by id hash**, `python -m evals tune --params gate.min_score,gate.min_coverage,ranking.w_* --grid …` for `0.4*recall@5 + 0.3*mrr + 0.3*abstain_correct − 0.2*noise_rate`, defaults into `em/config.py` (**which does not exist yet — this is where it starts**), per-model cosine last (**the grid is empty until EM-303**). AC: holdout metrics reported, defaults committed, §6.3's gates updated. **Until the CI gate on v3 lands, `tests/evals/test_adapter_v3.py` is v3's only regression protection — it runs in the default suite (it is in the 1995).**
3. **Bump `README.md`'s test count** when it next moves (`1,900+` is still true at 1995).

### Pre-flight

1. `main` must be at `f0a7c70` or later. `git merge-base --is-ancestor f0a7c70 main` proves it.
2. **Baseline:** `pytest -q` gives **1995 passed, 3 skipped, 3 xfailed** on **both Python 3.10 and 3.12**.
3. **Re-measure from the code**, not this file: `em/facade/engine.py`'s read half and its lazy v2 import; `em/facade/select.py`'s `open_engine`; `plugins/entropicmem/__init__.py`'s `_build_fact_block`/`_format_block`; `em/retrieval/pipeline.retrieve`.
4. **Verify CI with the check-runs API on the commit**, not `ghx run list --branch main --limit 1`, which can return a stale run and look green.

### Document control

Per `AGENTS.md`, with the reconciliation folded into the docs commit. `In flight` does not name a commit. Chunk 13 stays internal; do not touch the Marketplace entry. **Never write to the live store** — P0b is read-only, and the shadow only ever writes its own copy.
