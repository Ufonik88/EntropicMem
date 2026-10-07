# EntropicMem: next steps (one chunk at a time)

**Updated:** 2026-10-07, Chunk 13 (the §3.5 `visibility` fix) merged to `main`; **Chunk 14 (EM-304, fusion) is the next piece**. **Read first:** `MASTER_TODO.md`, then `docs/plan/REMAINING_PLAN.md` (its §3 rules apply to everything here), then `AGENTS.md` and `docs/V3_FOUNDATIONS.md`.

**Owner rulings in force (plan §9):**
- **The v3 cutover is deferred, and the owner revisits it after EM-305 — the owner decides, the agent brings the decision.** Do not switch the live store, and do not pre-empt the call.
- **Chunk 13's `visibility` change is internal only.** It was proposed by the implementing agent and *authorised for implementation* by the owner; the owner has **not** signed off on the behaviour change, and it must not reach the marketplace without an explicit release approval.

**Plan exactly one chunk.** When a chunk ends, replace this file with the plan for the next single chunk; never more than one ahead.

**The master plan is at `~/Documents/EntropicMem Dev docs/EntropicMem_v3_Master_Plan.md`** (the owner's document, deliberately not committed). EM-301's, EM-302's and EM-304's cards plus §3.6 are transcribed into `REMAINING_PLAN.md` §6.2. **Before starting a card whose text is not there, read that file** — and if it is unreachable, stop and report rather than inventing fields.

---

## Part A: what has landed

Only the recent chunks; the full ledger with SHAs is `REMAINING_PLAN.md` §5.

### Chunk 13 — §3.5's `visibility` half. **DONE, MERGED (2026-10-07, `fd9e06f`). Agent-proposed, internal only.**

- **The bug, measured:** `MemoryDraft.visibility` defaulted to `'user'` and **nothing anywhere set it**, so every `MemoryStore.add` — the facade's `remember` included — stamped `'user'` whether the row was profile-wide or user-scoped. §3.5 pairs `'user'` with a *user-scoped* write and makes a *profile-wide* row carrying it **owner-only** — so the store produced, for every write, exactly the shape its own plan calls private.
- **The direction was the point, and it is why the read clause could not ship alone:** the read clause by itself would have hidden every profile-wide memory from non-owners. The write stamp is the real fix; the read guard is the defence. `test_a_non_owner_still_sees_an_ordinary_profile_wide_row` is the regression guard.
- **Write:** the draft's default is now `''` = *derive from the scope* — `'profile'` profile-wide, `'user'` otherwise, an explicit value preserved and never overridden. A `str` default cannot distinguish "asked for `user`" from "nobody said", and the difference is load-bearing.
- **Read:** `em.store.types.row_is_owner_only` owns both owner-only conditions (the tier, and a profile-wide row stamped `'user'`); `_in_scope` and `candidates.scope_sql` both call it, so predicate and SQL cannot drift. The cross-check matrix gained the row shape **and** the semantics are asserted directly — a cross-check alone would pass if both implementations were wrong together.
- **A consequence found and fixed:** `_outbox` never checked sensitivity, despite its docstring; that was sufficient *by accident* because the old default meant profile-wide writes were never queued. v2's gate was `_publish_allowed(sensitivity)`, so v2 published every non-sensitive fact; the tier check is now explicit. Without it this chunk would have started sending profile-wide `sensitive` rows to the sync outbox.
- **`MemoryStore.list` investigated and left alone, reason recorded:** its `scope_user=?` is *exact*, so a scoped caller only ever receives rows already scoped to them — the Chunk 7.2 "not tier-filtered" note is not a leak.
- **Reversible:** no migration (`test_the_change_adds_no_migration`), no rewrite of existing rows.
- 30 new tests; **1862 passed / 3 skipped / 3 xfailed on Python 3.10 and 3.12**; 13 mutation checks, all caught.

### Chunk 12 — EM-301, the `QueryAnalyzer`. **DONE, MERGED (2026-10-07, `85afea4`)**

- `analyze()` → `AnalyzedQuery`: `<memory-context>` stripped, `\w+` tokens, stopwords dropped, ≤12 terms by IDF, intent, entities, temporal window. Two findings: the `memories_vocab` view holds **porter stems** (a raw-token IDF lookup would silently collapse into length ordering — bridged with an FTS5 `MATCH` count), and an all-stopword query (`"who am I"`) needs v2's fallback, which §3.6 does not specify.
- The intent table is **42 measured phrasings, 39/42 = 92.9%**, with three declared misses. Migration `0004` adds `memories_vocab`. 37 tests; 19 mutation checks.

### Chunk 11 — EM-302, the candidate generators. **DONE, MERGED (2026-10-07, `33b2b31`)**

- `bm25` (with §3.6's `1.0, 0.5, 0.3, 0.1` weights), `entity` (＋1 hop at ×0.5), `episodic` (`owner_type='episode'`), `recent`, `pinned`; `Candidate` = §3.6's ranked `(owner_type, owner_id, raw_score)`. **`vector` is EM-303's.** Deadline discipline is structural.

**S3's retrieval base is complete: an analyzer, generators, and a fixed scope model. EM-304 is unblocked.**

---

## Part B: Chunk 14 — EM-304, fusion, rerank and explainability

### The card (master plan §5, verbatim)

**EM-304 — Fusion, rerank, explainability · M**
- **Files:** `em/retrieval/fusion.py`. **Spec:** exactly §3.6 formulas; all weights in `ranking.*` config; `explain` structure; deterministic tie-break `(score desc, updated_at desc, id asc)`.
- **AC:** unit tests with synthetic ranks reproduce hand-computed scores to 1e-9.

### The §3.6 formulas it implements (verbatim)

**Fusion** (`em/retrieval/fusion.py`): weighted Reciprocal Rank Fusion
`rrf(d) = Σ_g w_g / (60 + rank_g(d))`; normalised `rrf_n(d) = rrf(d) / Σ_{g ∈ G_active} (w_g / 61)` ∈ [0,1], where `G_active` = generators that **ran and returned ≥ 1 candidate** for this query (normalising over all configured generators would cap a bm25-only hit at ≈ 0.25 and make `min_score` meaningless).

Default generator weights by intent:

| intent | bm25 | vector | entity | episodic | recent | pinned |
|---|---|---|---|---|---|---|
| lookup | 1.0 | 1.0 | 0.7 | 0.3 | 0.2 | 0.5 |
| profile | 0.6 | 0.8 | 0.6 | 0.1 | 0.1 | 1.0 |
| temporal | 0.7 | 0.6 | 0.5 | 1.0 | 0.8 | 0.3 |
| procedural | 1.0 | 1.0 | 0.5 | 0.4 | 0.2 | 0.5 |

**Feature rerank** — final score in [0,1]:
```
score = 0.60*rrf_n + 0.15*importance + 0.10*recency + 0.10*confidence + 0.05*feedback
recency  = 1.0                                         if decay_class == 'evergreen' or pinned
         = max(0.5, 0.5 ** (age_days / 180))           if 'standard'
         = 0.5 ** (age_days / 14)                      if 'volatile'
age_days = now - max(updated_at, last_accessed_at, valid_from)
feedback = clamp(0.5 + 0.1*(helpful - 2*unhelpful), 0, 1)
```
Weights and half-lives are config (`ranking.*`). `why_retrieved` becomes a list of `{"signal": "bm25", "rank": 3, "contrib": 0.12}` plus flags (`temporal_filter`, `entity:<name>`, `superseded_note`). Keep the legacy flat token list in `why_retrieved_tokens` for one minor version.

### What is already in the repo, so do not rebuild it

- `em/retrieval/candidates.py` has the five generators, `Candidate` (three fields), `RetrievalContext`, and `GENERATORS` (a name → function mapping, so the *generator name* is known to the caller and does not need to be on the candidate).
- `em/retrieval/query.py` has `AnalyzedQuery` with `intent`, so the weight table is selected from data.
- `em/facade/engine.py`'s read half already computes a `why_retrieved` list of flat tokens (the v2-compatible shape) and `memory_engine.py`'s helpers are the v2 reference for what the provider expects. Keep the legacy list working.

### Size guards — stop and report if

* **`ranking.*` config does not exist.** There is no `em/config.py` (it is EM-407), exactly as with EM-301's `extra_stopwords`. Take the weights and half-lives as parameters defaulting to §3.6's numbers, and **record the gap** — do not invent a config system.
* **the rerank features need a row fetch that has no home.** `Candidate` carries only `(owner_type, owner_id, raw_score)`, but rerank needs `importance`, `confidence`, `decay_class`, `pinned`, `updated_at`, `last_accessed_at`, `valid_from` and the feedback counters — for **both** memories and episodes, and filtered by scope. Decide where that load lives (a loader in `fusion.py`, or a helper on `RetrievalContext`), keep §3.5's scope rule on it, and **say which and why**. If it needs `MemoryStore` API that does not exist, that is a cross-card dependency — report rather than reaching into another card.
* the card needs the gate or MMR — those are **EM-305**; `fusion.py` ends at the ranked, explained list.

### Pre-flight

1. `main` must be at `fd9e06f` or later: Chunk 13 merged there. `git merge-base --is-ancestor fd9e06f main` proves it.
2. **Baseline:** `pytest -q` gives **1862 passed, 3 skipped, 3 xfailed** on **both Python 3.10 and 3.12**.
3. **Re-measure from the code**, not from this file: `em/retrieval/candidates.py`'s `Candidate`/`GENERATORS`, `query.py`'s `AnalyzedQuery`, whether anything already loads candidate rows for rerank, what the facade's `why_retrieved` currently contains, and whether `em/config.py` exists yet.
4. **The AC is a numeric reproduction**, so write the hand-computed expectations out first and let the test fail on the arithmetic — do not derive the expectation from the implementation.

### Document control (before and after)

Per `AGENTS.md`: reconcile `MASTER_TODO.md`, `REMAINING_PLAN.md` and this file **before** starting and **again before finishing**. Merge state counts as truth. Chunk 13's change stays **internal**; do not touch the Marketplace entry.

### End of chunk

1. Push, green CI on the exact SHA, `git merge --ff-only`, delete the branch.
2. Update `MASTER_TODO.md` and `REMAINING_PLAN.md` §2/§5/§6.2/§9/§11.
3. **Replace this file's Part A with this chunk and Part B with the next piece** — EM-305 (gate, supersession collapse, MMR), after which the cutover decision goes back to the owner.
