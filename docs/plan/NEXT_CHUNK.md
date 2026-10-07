# EntropicMem: next steps (one chunk at a time)

**Updated:** 2026-10-07, Chunk 11 (EM-302, the candidate generators) merged to `main` at `33b2b31`; **Chunk 12 (EM-301, the `QueryAnalyzer`) is the next piece**. **Read first:** `MASTER_TODO.md`, then `docs/plan/REMAINING_PLAN.md` (its §3 rules apply to everything here), then `AGENTS.md` and `docs/V3_FOUNDATIONS.md`.

**Decisions taken 2026-10-07 (delegated to the implementing agent, recorded in plan §9):** the §3.5 `visibility` gap is **approved for fixing as Chunk 13** (write path + read clause, right after this chunk), and the **v3 cutover is deferred** (the live store has zero facts, the CLI still refuses seven commands on v3, and S3 is mid-flight). Neither blocks this chunk.

**Plan exactly one chunk.** When a chunk ends, replace this file with the plan for the next single chunk; never more than one ahead.

**The master plan is at `~/Documents/EntropicMem Dev docs/EntropicMem_v3_Master_Plan.md`** (1,587 lines, the owner's document, deliberately not committed). EM-302's card and §3.6 are transcribed into `REMAINING_PLAN.md` §6.2. **Before starting a card whose text is not there, read that file** — and if it is unreachable, stop and report rather than inventing fields.

---

## Part A: what has landed

Only the recent chunks; the full ledger with SHAs is `REMAINING_PLAN.md` §5.

### Chunk 11 — EM-302, the candidate generators. **DONE, MERGED (2026-10-07, `33b2b31`)**

- The card text was **found**: the master plan is on this machine (see above). So this was built against the real card and §3.6, not the summary — and the card is now transcribed into plan §6.2 so it can never block again.
- **Five generators**, each `(ctx: RetrievalContext) -> list[Candidate]`: `bm25` (`memories_fts`, §3.6's `bm25(memories_fts, 1.0, 0.5, 0.3, 0.1)` column weights), `entity` (`memory_entities`, then one hop through `relations` at ×0.5), `episodic` (`episodes_fts` + the analyzed time window, `owner_type='episode'`), `recent` (the 48 h window, gated to `temporal`/`lookup`), `pinned` (`pinned=1` or `kind='constraint'`). `Candidate` is exactly §3.6's ranked `(owner_type, owner_id, raw_score)`.
- **`vector` is EM-303's, deliberately.** §3.6 gates it on an embedding backend and forbids re-reading vector blobs per query.
- **Deadline discipline is structural.** `RetrievalContext.out_of_time()` is consulted *before* any SQL and again between result pages. The "expired" half is proved deterministically with a recording connection (an expired generator issues **no query**); the "partial" half by driving `candidates._monotonic`, so no test races the machine.
- **`scope_sql` gained §3.5's chat dimension**, which retired a live drift: `MemoryStore.list` had always emitted `scope_chat=? OR scope_chat=''` while the row predicate `_in_scope` did not. Both now call `em.store.types.chat_in_scope`. A no-op until something sets `scope.chat` (nothing does), and the cross-check matrix now includes chat rows.
- Two new type-only modules so EM-301/EM-310 have somewhere to land: `em/retrieval/query.py` (`AnalyzedQuery`) and `em/retrieval/temporal.py` (`TimeRange`).
- 38 new tests; **1795 passed / 3 skipped / 3 xfailed on Python 3.10 and 3.12**; `ruff==0.16.2` clean; eval gate with no gated metric regressed. Fifteen mutation checks, each red for the right reason with the tree restored byte-identical.
- **Recorded gaps** (`V3_FOUNDATIONS.md`): `vector` → EM-303; §3.5's `visibility='user'` owner-only clause → its own card (**privacy**); `recent`'s "current session" half needs a session id the card's `RetrievalContext` does not carry; `raw_score` is made higher-is-better even though §3.6's fusion is rank-based.
- **Merged** to `main` at `33b2b31`; green on the exact SHA, first CI run.

### EM-302's first piece — `scope_sql`. **DONE, MERGED (2026-10-07, `0066fb5`, in `50c5310`)**

- `em.retrieval` created, with `scope_sql(scope) -> (clause, params)`: the §3.5 rule as SQL. `may_read_owner_only` moved into `em/store/types.py`, so `_in_scope` (predicate) and `scope_sql` (SQL) cannot drift about who the owner is. The tests cross-check the two forms over a real row matrix rather than restating the rule.
- 6 new tests; six mutation checks.

### Chunk 10.4 — the CLI routes. **DONE, MERGED (2026-10-07, `250320a`, in `c50d7b6`)**

- `_engine()` selects through the same `open_engine` the provider uses, so the CLI's ported commands run against a **v3** store and the v2-only ones still refuse by name (their guards run before `_engine()`). **EM-211's AC is met except for seven named refusals.**
- Fixed alongside: a latent v2 regression Chunk 9 introduced, where `profile_id` was made explicit and overrode the `hermes_home`-derived slug. `open_engine` now takes `profile_id=None` meaning "the engine decides".
- 20 new tests; 1751 passed / 3 skipped / 3 xfailed on 3.10 and 3.12; six mutation checks.

**EM-211 and EM-212 are code-complete, both engines serve a v3 store, and S3 is under way.** The cutover is the owner's call.

---

## Part B: Chunk 12 — EM-301, the `QueryAnalyzer` (§3.6)

**Ready and unblocked.** The card is in the master plan; its text is below. EM-302 already built the shape it fills in, so this is the last missing dependency of EM-304 (`fusion`, "exactly §3.6 formulas"), the next card on the critical path.

### The card (master plan §5, verbatim)

**EM-301 — QueryAnalyzer · M**
- **Files:** `em/retrieval/query.py`, `em/retrieval/stopwords.py`, `em/retrieval/temporal.py` (EM-310).
- **Spec:** as §3.6. `memories_vocab` = `CREATE VIRTUAL TABLE memories_vocab USING fts5vocab(memories_fts, 'row')` (migration 0003). IDF = `log((N - df + 0.5)/(df + 0.5) + 1)` with `N` = active memory count (cached per `write_generation`). Defensively strip `<memory-context>…</memory-context>` (the host already strips skill scaffolding — markers in `agent/skill_commands.py` — before calling the provider).
- **AC:** unit tests for term selection, intent detection table (≥ 30 labelled queries, ≥ 90% accuracy), entity detection.

### The §3.6 text it implements (verbatim)

**QueryAnalyzer** (`em/retrieval/query.py`) → `AnalyzedQuery(raw, text, terms, temporal: Optional[TimeRange], entities: list[entity_id], intent)`
- Input text = current user message only (strip Hermes skill scaffolding; strip `<memory-context>` blocks defensively). Prior turns are **not** concatenated; instead the *session topic vector/entities* from the prefetch service (§4.2) are passed as a separate soft signal.
- Terms: `\w+` tokens, casefold, drop stopwords (built-in English list ~180 words + config `extra_stopwords`), drop tokens `len < 2`. Prefix match (`"tok"*`) only for `len ≥ 4`; otherwise exact. Max 12 terms, selected by **IDF** from `memories_fts` vocab (`fts5vocab` table `memories_vocab` 'row' type) then length as tiebreak.
- Temporal: extend `temporal.py` — ISO dates, "since X", "before X", "between", "last N days/weeks/months" (a *range*, not a day), "in <month> <year>". Temporal filters apply to `COALESCE(valid_from, created_at)`.
- Entities: alias lookup against `entity_aliases` (normalised n-grams up to 4 tokens).
- Intent (heuristic): `profile` (who am I / my preferences), `temporal` (when / last time), `procedural` (how do I / steps), `lookup` (default). Intent adjusts generator weights.
- Optional: `query_rewrite: hermes` → `plugins.memory.query_rewrite.rewrite_memory_query` (only in the background precompute path, never blocking `prefetch`).

### What is already in the repo, so do not rebuild it

- `em/retrieval/query.py` holds `AnalyzedQuery` with those six fields in that order, `terms`/`entities` as tuples, `intent` defaulting to `lookup`, plus `INTENTS`. **Add the analyzer; do not change the shape** — EM-302's tests construct it.
- `em/retrieval/temporal.py` holds `TimeRange(start, end)`, both optional. EM-310 owns the parser; this card may add the ISO/"since"/"before"/"last N"/"between" subset §3.6 lists here, or leave the parsing to EM-310 and only route the query text — **say which and why.**
- `em/retrieval/candidates.py` has `match_expression(terms)`, which already renders EM-301's chosen terms for FTS5 (`\w+` runs, `len < 2` dropped, prefix `*` for `len ≥ 4`, cap 12). Do not duplicate that rule; the analyzer chooses terms, this renders them.
- `em.store.entities.EntityStore.find_entity(alias)` and `entity_aliases` exist — use them for entity detection rather than a new lookup path.

### Size guards — stop and report if

- the vocabulary migration cannot be added without touching an applied migration (it must be a **new** one — see below);
- the intent table cannot reach 90% on 30 honest labelled queries without fudging the labels (state the achieved figure instead);
- the card needs the config module (`em/config.py`) but it does not exist yet — §3.6 references `extra_stopwords` and `query_rewrite`. If config is not yet a real module, take the parameters with defaults and **record the gap**, do not invent a config system (that is EM-407).

### Pre-flight

1. `main` must be at `33b2b31` or later, with EM-302 merged. `git merge-base --is-ancestor 33b2b31 main` proves it.
2. **Baseline:** `pytest -q` gives **1795 passed, 3 skipped, 3 xfailed** on **both Python 3.10 and 3.12**.
3. **Re-measure from the code**, not from this file: `em/retrieval/query.py` and `temporal.py` as they now stand; `em/store/migrations/__init__.py`'s registration and the highest applied number (**`0003` is taken by `0003_audit_append_only`, so the vocabulary table is `0004`** — the plan says 0003); whether `memories_fts` is declared with `content='memories'` (it is) so `fts5vocab(memories_fts, 'row')` works; and whether any config module exists.
4. The stopword list must be honest: §3.6 says ~180 English words. Use a real published list and say where it came from; do not invent one and call it 180.

### Document control (before and after)

Per `AGENTS.md`: reconcile `MASTER_TODO.md`, `REMAINING_PLAN.md` and this file **before** starting and **again before finishing**. Merge state counts as truth — "committed, not merged" is not "landed".

### End of chunk

1. Push, green CI on the exact SHA, `git merge --ff-only`, delete the branch.
2. Update `MASTER_TODO.md` and `REMAINING_PLAN.md` §2/§5/§6.2/§9/§11.
3. **Replace this file's Part A with this chunk and Part B with the next piece** — most likely EM-304 (`fusion`), now that its dependencies exist. Name the next card and say why.
