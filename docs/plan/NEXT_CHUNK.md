# EntropicMem: next steps (one chunk at a time)

**Updated:** 2026-10-07, Chunk 14 (EM-304, fusion) merged to `main`; **Chunk 15 (EM-305, the gate, supersession collapse and MMR) is the next piece**. **Read first:** `MASTER_TODO.md`, then `docs/plan/REMAINING_PLAN.md` (its §3 rules apply to everything here), then `AGENTS.md` and `docs/V3_FOUNDATIONS.md`.

**Owner rulings in force (plan §9):**
- **The v3 cutover is deferred and the owner revisits it after EM-305. The owner decides — the agent brings the decision, never takes it.** Do not switch the live store.
- **Chunk 13's `visibility` change is ratified and internal only**, and the marketplace entry does not move without an explicit release approval.

**Owner constraints on the next chunks:**
- **EM-305's gate must not depend on EM-301's intent table.** Its accuracy is 92.9% on 42 samples — a miss only costs ranking quality, but the gate is a hard filter, so if the gate ends up keyed on intent then widen the table first (that is EM-306's job) rather than shipping a gate on a thin signal.
- **EM-306 (the calibration harness) is the fix for that thin margin, not a nice-to-have.** Its AC is exactly this tuning.

**Plan exactly one chunk.** When a chunk ends, replace this file with the plan for the next single chunk; never more than one ahead.

**The master plan is at `~/Documents/EntropicMem Dev docs/EntropicMem_v3_Master_Plan.md`** (the owner's document, deliberately not committed). EM-301's, EM-302's, EM-304's and EM-305's cards plus §3.6 are transcribed into `REMAINING_PLAN.md` §6.2. **Before starting a card whose text is not there, read that file** — and if it is unreachable, stop and report rather than inventing fields.

---

## Part A: what has landed

Only the recent chunks; the full ledger with SHAs is `REMAINING_PLAN.md` §5.

### Chunk 14 — EM-304, fusion, rerank, explainability. **DONE, MERGED (2026-10-07, `14552be`)**

- `em/retrieval/fusion.py`: weighted RRF over the generators that ran, §3.6's feature rerank, a total deterministic tie-break, the per-hit explanation, and a scoped feature loader. Every number is hand-computed in the tests to 1e-9, which is the card's AC.
- **The `G_active` trap is pinned both ways:** a bm25-only rank-1 hit normalises to **1.0**, and the *wrong* denominator (all six configured generators) is shown to give 0.270 — under §3.6's `gate.min_score` of 0.30, which is why the plan warns about it.
- **A test-quality finding worth remembering.** `updated_at` also *feeds* `recency`, so varying it changes the score and the `(score desc, updated_at desc, id asc)` tie-break never runs — the first tie-break test proved nothing. `evergreen` (recency 1.0 whatever the timestamp) is what makes an exact tie reachable, and the test now asserts the scores are equal before asserting the order.
- `load_features` re-applies §3.5 through the same `scope_sql` and `status='active'`: this is the last point before a row's content would be shown, so a generator's scope mistake cannot surface here. A fused key with no features is dropped, never ranked.
- Episodes get **named** defaults (`EPISODE_DEFAULTS`) where the schema has no column, and `start_at` fills the `valid_from` slot the age formula wants — not silent zeros.
- Deliberately left: `ranking.*` config (EM-407), `superseded_note` (EM-305), and the `why_retrieved_tokens` wiring (the provider card).
- 53 new tests; **1916 passed / 3 skipped / 3 xfailed on Python 3.10 and 3.12**; 22 mutation checks. **Two escaped on the first pass and both were real test gaps:** a no-op denominator mutation (now removed for real, with a new all-zero-weight test), and the tie-break test above.

### Chunk 13 — §3.5's `visibility` half. **DONE, MERGED, OWNER-RATIFIED (2026-10-07, `fd9e06f`). Internal only.**

- Measured: `MemoryDraft.visibility` defaulted to `'user'` and **nothing set it**, so every profile-wide write carried the value §3.5 reserves for user-scoped rows — the shape §3.5 makes owner-only. **The direction was the point:** the read clause alone would have hidden every profile-wide memory from non-owners.
- Write: the draft default is `''` = derive from the scope, explicit preserved. Read: `row_is_owner_only` owns both owner-only conditions and `_in_scope`/`scope_sql` both call it.
- `_outbox` gained the sensitivity gate it never had (its docstring claimed it); v2 published every non-sensitive fact, so this restores v2. Investigated and answered: the only outbox consumer is v2's `publish()`, unreachable on v3, and nothing had been queued by the old path.
- `MemoryStore.list` was investigated and left exact, with a regression test pinning both directions.
- Reversible: no migration, no rewrite of existing rows.

### Chunk 12 — EM-301, the `QueryAnalyzer`. **DONE, MERGED (2026-10-07, `85afea4`)**

- `analyze()` → `AnalyzedQuery`. Two findings: the `memories_vocab` view holds **porter stems** (bridged with an FTS5 `MATCH` count), and an all-stopword query needs v2's fallback. Intent: 39/42 = 92.9% on a labelled table with three declared misses.

**S3's retrieval is three parts in: an analyzer, generators, and fusion. EM-305 completes the pipeline.**

---

## Part B: Chunk 15 — EM-305, the gate, supersession collapse and MMR

### The card (master plan §5, verbatim)

**EM-305 — Gate, supersession collapse, MMR · M**
- **Files:** `em/retrieval/gate.py`, `em/retrieval/diversity.py`. **Spec:** §3.6. Collapse also groups `status=active` memories linked by `superseded_by` chains (safety) and exact-hash duplicates across scopes (prefer narrower scope).
- **AC:** abstention scenarios ≥ 0.95 correct; `update` scenarios return only the latest version by default and both with `include_history=True`.

### The §3.6 text it implements (verbatim)

**Abstention gate** (`em/retrieval/gate.py`) — a candidate is *supported* iff at least one holds:
- lexical coverage ≥ `gate.min_coverage` (default 0.34) where coverage = matched non-stopword query terms (post-stem) / total query terms, computed in Python on the candidate text;
- vector cosine ≥ `gate.min_cosine[model]` (defaults: `bge-small-en-v1.5: 0.62`, `all-MiniLM-L6-v2: 0.38`, tuned in EM-306);
- an entity hit from the analyzer;
- `pinned`.
Then require `score ≥ gate.min_score` (default 0.30). If no candidate survives, the memory section is omitted entirely (only pinned constraints and core deltas may remain).

**Collapse & diversity:** drop `superseded` (but mark successor with `(updated <date>; was: <old summary>)` when the old one was a candidate or changed < 30 days ago). MMR with λ = 0.7 using embedding cosine (fallback: token Jaccard) over the top 20.

### The trap to expect first — coverage is "post-stem", and Python has no stemmer

This is the Chunk 12 finding arriving again on a harder surface. Coverage is *"matched non-stopword query terms (post-stem) / total query terms, computed in Python on the candidate text"*, but ``memories_fts`` is porter-tokenized and there is no porter stemmer in the standard library, so a naive substring/token comparison will under-count for exactly the words that matter (`staging` in the text, `staging` in the query, matching fine in FTS — but `run` vs `running`, `prefer` vs `preferences` will not). Since the gate is a hard filter, an under-count silently abstains on answers that were found. **Decide deliberately and say which**, in the same spirit as `vocabulary`:

* ask FTS5 (one `MATCH` per query term against a scratch expression, or reuse the same tokenizer) so coverage is measured with the tokenizer that actually matched; or
* compute it on raw tokens and **bound the error in a recorded deviation** with a test that shows which shapes under-count.

Do not ship a silent under-count.

### What is already in the repo, so do not rebuild it

- `em/retrieval/fusion.py` produces the `Ranking` list, in score order, each with `signals` (so the gate can see whether an `entity` hit was involved), `score`, `rrf_n` and `why`. `superseded_note` is deliberately not emitted — **this card emits it**.
- `em/retrieval/candidates.py` has `scope_sql`; `fusion.load_features` already re-applies §3.5 and can be extended (or given a sibling) for whatever this card needs. `Candidate` stays three fields.
- `em/retrieval/query.py`'s `AnalyzedQuery` has `terms` (the post-stopword tokens) and `entities` — coverage's numerator and the entity-hit support condition come from there.
- `fusion.legacy_tokens` consumes `why`, so a new flag flows through with no further change.

### Size guards — stop and report if

* **`gate.*` config does not exist** (EM-407), the same gap as `ranking.*`. Take the thresholds as parameters with §3.6's defaults and record it.
* **the vector half of the support test cannot run.** `gate.min_cosine[model]` needs an embedding backend and a model name, which is EM-303; a `Ranking` carries no cosine. Implement the lexical/entity/pinned conditions and a **documented, disabled** cosine hook rather than inventing a cosine — say so plainly.
* **`include_history=True` needs a read that does not exist.** The `update` AC needs both versions of a superseded pair; `MemoryStore.history()` exists (walks `superseded_by` backwards), so check it before building anything.
* MMR's "over the top 20" and the collapse's "changed < 30 days ago" are the only card-specific numbers; if either needs a field no row carries, report rather than guess.

### Pre-flight

1. `main` must be at `14552be` or later: Chunk 14 merged there. `git merge-base --is-ancestor 14552be main` proves it.
2. **Baseline:** `pytest -q` gives **1916 passed, 3 skipped, 3 xfailed** on **both Python 3.10 and 3.12**.
3. **Re-measure from the code**, not from this file: `fusion.Ranking`'s fields, whether anything already carries candidate *text*, `MemoryStore.history`, the `superseded_by`/`content_hash` columns, and whether `em/config.py` exists yet.
4. **Verify CI with the check-runs API on the commit**, not `ghx run list --branch main --limit 1`, which can return a stale run and look green (see `MASTER_TODO.md`).

### Document control (before and after)

Per `AGENTS.md`: reconcile `MASTER_TODO.md`, `REMAINING_PLAN.md` and this file **before** starting and **again before finishing**. Merge state counts as truth. Chunk 13 stays internal; do not touch the Marketplace entry.

### End of chunk

1. Push, green CI on the exact SHA, `git merge --ff-only`, delete the branch.
2. Update `MASTER_TODO.md` and `REMAINING_PLAN.md` §2/§5/§6.2/§9/§11.
3. **Replace this file's Part A with this chunk and Part B with the next piece — EM-306 (calibration), and bring the cutover decision to the owner**, who revisits it after EM-305.
