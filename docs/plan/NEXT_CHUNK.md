# EntropicMem: next steps (one chunk at a time)

**Updated:** 2026-10-07, Chunk 15 (EM-305, the gate, collapse and MMR) merged to `main`; **the owner's cutover decision is now due**, and **Chunk 16 (EM-306, calibration) is the next piece**. **Read first:** `MASTER_TODO.md`, then `docs/plan/REMAINING_PLAN.md` (its §3 rules apply to everything here), then `AGENTS.md` and `docs/V3_FOUNDATIONS.md`.

**Owner decisions in force:**
- **The visibility change (Chunk 13) is ratified and internal only** — no release, no marketplace, until the owner explicitly approves a release.
- **EM-305's gate must not depend on EM-301's intent table** (92.9% on 42 samples). If tuning shows it does, widen the table first.
- **EM-306 is the fix for that thin margin, not a nice-to-have.**
- **The cutover decision is the owner's, and it is due now** (see below).

**Plan exactly one chunk.** When a chunk ends, replace this file with the plan for the next single chunk; never more than one ahead.

**The master plan is at `~/Documents/EntropicMem Dev docs/EntropicMem_v3_Master_Plan.md`** (the owner's document, deliberately not committed). EM-301's…EM-306's cards plus §3.6 are transcribed into `REMAINING_PLAN.md` §6.2. **Before starting a card whose text is not there, read that file** — and if it is unreachable, stop and report rather than inventing fields.

---

# OWNER DECISION NOW DUE: the v3 cutover

The owner set the milestone: **"revisit only after EM-305, and bring me the decision
rather than making it."** EM-305 is merged, so it is due. **The agent does not take
this decision.**

The evidence, measured rather than asserted:

| Fact | Where it comes from |
|---|---|
| **S3's retrieval pipeline is complete** — analyzer, generators, fusion, gate, collapse, MMR | chunks 11–15, all merged |
| **…and nothing calls it.** Prefetch still uses v2's scoring; the facade's read half serves a v3 store | `em/retrieval/__init__.py`'s gap list |
| **The CLI refuses seven v2-only commands on v3**, `publish`/`pull` among them; nothing drains the sync outbox on v3 | Chunk 10.3 |
| **`embed`/`vector` do not exist** (EM-303), so the vector generator, the gate's cosine condition and MMR's embedding path are all inert on v3 | chunks 14–15 |
| **No v3 eval adapter**, so the v3 pipeline has never been scored end to end | `evals/__main__.py` |
| **The live store holds zero facts** and has not moved across any session | `stat` on `~/.hermes/entropicmem/memory.db` |
| **Chunk 13's `visibility` change is unreleased** and changes what a non-owner may read | plan §9 item 3 |

**The agent's recommendation (the owner accepts or refuses): defer past EM-306, and
wire S3's read path into the provider first.** The reasoning is one line: the cutover
is irreversible and owner-present, and doing it while the retrieval layer is complete
but *unwired* lands the owner on a v3 store whose new capability nothing calls yet.
The counter-argument is equally real — the live store is empty, so a cutover costs
nothing to undo *today* and would start exercising v3 on real turns.

**If the owner says go:** verified backup → migrate a **copy** → verify against the
parity suite → swap, with `ENTROPICMEM_ALLOW_LIVE_MIGRATION=1` set only for that act
(plan §6.3).

---

## Part A: what has landed

Only the recent chunks; the full ledger with SHAs is `REMAINING_PLAN.md` §5.

### Chunk 15 — EM-305, the gate, supersession collapse, MMR. **DONE, MERGED (2026-10-07, `50601b3`)**

- `em/retrieval/gate.py`: §3.6's four support conditions (coverage ≥ 0.34, cosine ≥ `gate.min_cosine[model]`, an entity hit, pinned) then `score ≥ 0.30`. **Pinned bypasses outright**, per §3.6's own generator table. `GateResult` exposes `empty` and `keeps_only_pinned` so a block containing nothing but pinned constraints is a decision the renderer can see.
- **The "post-stem" coverage trap is resolved exactly.** §3.6 wants coverage "post-stem" and the stdlib has no porter stemmer, so a Python-only comparison under-counts on every hidden stem (`preferences`/`preferred`, `runs`/`running`) — and the gate is a **hard filter**, so it would silently abstain on answers the generators had found. Coverage is measured with **the same tokenizer**: a transient in-memory FTS5 declared identically to `memories_fts`, one `MATCH` per query term, which also keeps the cost at one table build plus ≤ 12 probes regardless of candidate count.
- `em/retrieval/diversity.py`: the collapse and MMR. **§3.6's "exact-hash duplicates across scopes" cannot use the hash** — `_content_hash` mixes the scope into the digest — so it groups on the loaded text and prefers the narrower scope. A live chain (a `restore` leaving two active members) keeps the successor. A predecessor changed < 30 days adds the `superseded_note` flag and comes back on `CollapseResult` for the renderer. MMR is λ = 0.7 over the top 20 on Jaccard, with the cosine path off until EM-303.
- Gaps recorded: `gate.*` config (EM-407, same as `ranking.*`), the cosine condition and MMR's embedding path (EM-303), and the `include_history` flag (the provider's — this layer supplies the predecessors, and `MemoryStore.history()` already walks the chain).
- 50 new tests; **1966 passed / 3 skipped / 3 xfailed on Python 3.10 and 3.12**; **23 mutation checks, all caught on the first pass** — but only after fixing three tests I had got wrong: the diversity mappings were keyed by bare id instead of `Ranking.key` (so every text lookup returned `""` and the tests passed for the wrong reason), the chain guard dropped the successor rather than the ancestor, and one abstention label asserted a match porter itself does not make (`deployment` → `deploy`), where abstaining is correct.

### Chunk 14 — EM-304, fusion. **DONE, MERGED (2026-10-07, `14552be`)**

- Weighted RRF over the generators that ran, §3.6's feature rerank, the deterministic tie-break, the explanation, and the scoped feature loader. The `G_active` trap is pinned both ways (1.0 for a bm25-only hit; the wrong denominator shown to give 0.270, under the 0.30 gate). 53 tests; 22 mutation checks; two escaped first pass and both were real test gaps.

### Chunks 11–13 — EM-302, EM-301, and the `visibility` fix. **DONE, MERGED**

- EM-302's generators, EM-301's analyzer (the porter-stem vocabulary finding; the all-stopword fallback), and §3.5's visibility half (owner-ratified, internal only). Details in `REMAINING_PLAN.md` §5.

**S3's retrieval pipeline is complete end to end and unwired. EM-306 is next.**

---

## Part B: Chunk 16 — EM-306, the calibration and tuning harness

### The card (master plan §5, verbatim)

**EM-306 — Calibration & tuning harness · M**
- **Depends on:** EM-301–305, EM-002.
- **Spec:** split scenarios into `dev` (70%) / `holdout` (30%) by id hash. `python -m evals tune --params gate.min_score,gate.min_coverage,ranking.w_* --grid …` optimising `0.4*recall@5 + 0.3*mrr + 0.3*abstain_correct − 0.2*noise_rate`. Write chosen defaults into `em/config.py` with a comment linking the result file. Per embedding model cosine thresholds calibrated separately.
- **AC:** holdout metrics reported in PR; defaults committed; §6.3 gates updated to the new baseline.

### Two prerequisites that do not exist yet — measure them first, they change the plan

**Re-measured on 2026-10-07, not assumed:**

1. **There is no v3 adapter.** `evals/__main__.py` raises `unknown adapter: … (v3 lands with S2)` — the message is stale (S2 is merged), and `--adapter` still only accepts `v2`. **The v3 pipeline has therefore never been scored end to end.** Tuning it is impossible until it can be run, so the adapter comes first. It is plumbing, not retrieval code: every stage exists and is tested, so the adapter drives `analyze → GENERATORS → fuse → rank → apply_gate → collapse → mmr`.
2. **There is no `tune` command**, and no `em/config.py`. §3.6 puts the tuned defaults in `em/config.py` with a comment linking the result file, so **this chunk is where that module starts** — deliberately narrow (the keys this chunk tunes), not a config system. `ranking.*` (EM-304), `gate.*` (EM-305) and `extra_stopwords` (EM-301) are its first tenants, and EM-407 owns the rest.

**If the two together are too big for one chunk, split and say which half landed:** 16a the v3 adapter plus the corrected adapter message (and a first honest v3 baseline committed as an `evals/baselines/` file), then 16b the `tune` command, `em/config.py`, and the committed defaults. **Do not tune against numbers produced by a harness that does not exist.**

### The objective, and what "holdout" has to mean

`0.4*recall@5 + 0.3*mrr + 0.3*abstain_correct − 0.2*noise_rate`, maximised on **dev** and **reported** on **holdout** — splitting scenarios 70/30 **by id hash**, so the split is stable across runs and a scenario cannot drift between halves. The AC is that the *holdout* figures go in the PR: a default chosen on dev and confirmed on holdout is the entire point, and a default reported on the data it was chosen from is not evidence.

### The thin margin, and the owner's standing constraint

EM-301's intent table is **92.9% on 42 samples**, and the owner has ruled that **the gate must not depend on the intent table**. `fusion.weights_for` already selects weights from `intent`, so tuning `ranking.w_*` per intent is legitimate — but if the tuned result turns out to *depend* on the gate keying on intent, stop and widen the table first (more samples, not different labels; the three known misses are documented by name and stay declared). **EM-306 is where the margin gets fixed**, and this chunk is the only place that can say whether 42 samples was enough.

### Size guards — stop and report if

* **the v3 adapter needs a driver that does not exist.** It should compose existing, tested functions. If it needs prefetch, the provider, a config module beyond the narrow one above, or a write path, that is a cross-card dependency — report rather than building it here.
* **a threshold cannot be measured at all.** §3.6 says `gate.min_cosine[model]` is calibrated per embedding model and EM-303 does not exist, so the cosine grid is **empty**; say so plainly and calibrate the other parameters rather than inventing cosines.
* **the objective cannot improve on dev without gaming it.** The hard suite has 4 paraphrase misses that share no words with the stored fact (§6.2) — vectors are the fix and they are EM-303's. If the tuned numbers only move by loosening the gate, that is a noise-rate trade, not a calibration, and the holdout will say so. Report it.

### Pre-flight

1. `main` must be at `50601b3` or later: Chunk 15 merged there. `git merge-base --is-ancestor 50601b3 main` proves it.
2. **Baseline:** `pytest -q` gives **1966 passed, 3 skipped, 3 xfailed** on **both Python 3.10 and 3.12**.
3. **Re-measure from the code**, not from this file: `evals/__main__.py`'s adapter registry and gate table, `evals/runner.py`, `evals/dataset.py`'s scenario ids, whether an id-hash split helper exists, and the current `evals/baselines/` files.
4. **Verify CI with the check-runs API on the commit** (`ghx api repos/Ufonik88/EntropicMem/commits/<sha>/check-runs`), not `ghx run list --branch main --limit 1`, which can return a stale run and look green.

### Document control (before and after)

Per `AGENTS.md`: reconcile `MASTER_TODO.md`, `REMAINING_PLAN.md` and this file **before** starting and **again before finishing**. Merge state counts as truth. Chunk 13 stays internal; do not touch the Marketplace entry.

### End of chunk

1. Push, green CI on the exact SHA, `git merge --ff-only`, delete the branch.
2. Update `MASTER_TODO.md` and `REMAINING_PLAN.md` §2/§5/§6.2/§9/§11, **and §6.3's gates** — the AC says the new baseline is written down.
3. **Replace this file's Part A with this chunk and Part B with the next piece** — and re-state the cutover decision's status (still due, or taken).
