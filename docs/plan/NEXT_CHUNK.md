# EntropicMem: next steps (one chunk at a time)

**Updated:** 2026-10-07, Chunk 12 (EM-301, the `QueryAnalyzer`) merged to `main`; **Chunk 13 (§3.5's `visibility` fix) is the next piece**. **Read first:** `MASTER_TODO.md`, then `docs/plan/REMAINING_PLAN.md` (its §3 rules apply to everything here), then `AGENTS.md` and `docs/V3_FOUNDATIONS.md`.

**Decisions already taken 2026-10-07 (plan §9):** the §3.5 `visibility` gap is **approved for fixing**, and the **v3 cutover is deferred** (the live store has zero facts, the CLI still refuses seven commands on v3, and S3 is mid-flight). Neither needs the owner again.

**Plan exactly one chunk.** When a chunk ends, replace this file with the plan for the next single chunk; never more than one ahead.

**The master plan is at `~/Documents/EntropicMem Dev docs/EntropicMem_v3_Master_Plan.md`** (the owner's document, deliberately not committed). EM-302's and EM-301's cards plus §3.6 are transcribed into `REMAINING_PLAN.md` §6.2. **Before starting a card whose text is not there, read that file** — and if it is unreachable, stop and report rather than inventing fields.

---

## Part A: what has landed

Only the recent chunks; the full ledger with SHAs is `REMAINING_PLAN.md` §5.

### Chunk 12 — EM-301, the `QueryAnalyzer`. **DONE, MERGED (2026-10-07, `85afea4`)**

- `em/retrieval/query.py` now has `analyze(text, *, conn, scope, now, extra_stopwords, max_terms) -> AnalyzedQuery`: `<memory-context>` stripped, `\w+` tokens, stopwords and 1-character tokens dropped, **up to 12 terms chosen by IDF**, intent classified, entities resolved, temporal window detected. EM-302's generators finally have a real producer.
- **Two findings that would each have been a silent bug:**
  - **The vocabulary view holds porter *stems*.** `memories_fts` is `tokenize='porter unicode61'`, so `memories_vocab` carries `stage`, not `staging`; a raw-token IDF lookup would miss for every stemmed word, report df 0, and collapse IDF into a *length* ordering — the IDF would look implemented and be inert. The view stays the base map (§3.6's source); each term it lacks is counted with an FTS5 `MATCH`, which applies the same tokenizer.
  - **An all-stopword query needs a fallback §3.6 does not specify.** `"who am I"` is the `profile` intent's own example and every word in it is a stopword. v2's EM-104 rule is carried forward so an identity question still retrieves something.
- **The intent table is measured against 42 real phrasings**, including **three the heuristic genuinely misses** and two that match more than one pattern (pinning the declared precedence). 39/42 = 92.9% against the AC's ≥ 30 queries / ≥ 90%; the three misses are declared by name rather than deleted from the table.
- Entity detection is one profile-scoped indexed `IN` probe over normalised n-grams up to 4 tokens, longest first — the profile join is deliberate, because `entity_aliases` alone is keyed by alias and two profiles' "Acme" would collide.
- **Migration `0004`** creates `memories_vocab`. The plan says "0003"; that number is taken. `em/retrieval/stopwords.py` is **the same 180-word list v2 uses**, pinned identical by a test.
- Gaps recorded, not invented: `write_generation` (nothing defines the counter §3.6's IDF cache would key on) and `query_rewrite` (no config module, no hook); the full temporal grammar is EM-310's.
- 37 new tests; **1832 passed / 3 skipped / 3 xfailed on Python 3.10 and 3.12**; 19 mutation checks. **One escaped and was worth keeping:** the first "rare term beats common term" test tied on length, so it passed with IDF entirely unwired — the replacement makes the *common* term longer, so only a working document frequency puts the rare one first.

### Chunk 11 — EM-302, the candidate generators. **DONE, MERGED (2026-10-07, `33b2b31`)**

- Five generators, each `(ctx: RetrievalContext) -> list[Candidate]`: `bm25` (`memories_fts`, §3.6's `bm25(memories_fts, 1.0, 0.5, 0.3, 0.1)` column weights), `entity` (`memory_entities`, then one hop via `relations` at ×0.5), `episodic` (`episodes_fts` + time window, `owner_type='episode'`), `recent` (48 h, gated to `temporal`/`lookup`), `pinned`. `Candidate` is exactly §3.6's ranked `(owner_type, owner_id, raw_score)`. **`vector` is EM-303's.**
- Deadline discipline is structural: checked *before* any SQL and between pages, so an expired generator issues no query and one that expires mid-scan returns a partial list.
- `scope_sql` gained §3.5's chat dimension, retiring a drift where `MemoryStore.list` filtered `scope_chat` and `_in_scope` did not.

**S3's retrieval base is in place, and EM-304 (fusion) is unblocked.**

---

## Part B: Chunk 13 — §3.5's `visibility` half

**Approved 2026-10-07 (plan §9 item 3).** This is a correctness fix, and the *direction* of the fix is the whole point — read that item before touching anything.

### The finding

`MemoryDraft.visibility` defaults to `'user'` and **no call site anywhere sets it**, so every `MemoryStore.add` — the facade's `remember` included — stamps `'user'` whether the row is profile-wide or user-scoped. §3.5 pairs `'user'` with a *user-scoped* write (`scope_user=<user>`) and profile-wide with `'profile'`; the v2→v3 migration also stamps `'profile'` for migrated facts. So a profile-wide row carrying `'user'` is self-contradictory, and §3.5's owner rule makes **exactly that combination** owner-only.

### The trap

**Implementing the read clause alone is the wrong fix and would be a visible regression.** Every profile-wide memory in existence carries `visibility='user'`, so the read clause by itself would hide *all* of them from non-owners — the opposite of §3.5's intent that profile-wide `public`/`internal` rows are shared knowledge. The write path is the real bug; the read clause is the defensive half.

### What the chunk does

1. **Write path.** `MemoryDraft.visibility` gains a "derive from scope" default: a profile-wide write (`scope.user == ''`) is stamped `'profile'`, a user-scoped write `'user'`, and an explicit value passed by a caller is preserved. Whatever mechanism you choose, `MemoryDraft` currently cannot distinguish "explicitly `'user'`" from "defaulted to `'user'`" — that is why the default has to change rather than the call sites.
2. **Read path.** `_in_scope` and `scope_sql` implement §3.5's second owner-only condition: a *profile-wide* row with `visibility='user'` is owner-only. They must keep sharing one definition per dimension, the way `may_read_owner_only` and `chat_in_scope` already work — the cross-check in `tests/unit/test_em_retrieval_scope_sql.py` is what proves it, and its row matrix should grow a `visibility` column.
3. **`MemoryStore.list`.** It keeps profile+user only (a recorded gap since Chunk 7.2, and it does not filter tiers). Either bring it under the same rule or record why not — do not leave the divergence implicit.

### Acceptance

* a profile-wide write is stamped `visibility='profile'`, and a non-owner **still** sees a profile-wide `public`/`internal` row (the regression guard — this is the test that matters);
* a user-scoped write is stamped `'user'`;
* an explicit `visibility='user'` on a profile-wide write is owner-only on read, in both the predicate and the SQL form;
* an explicit `visibility='profile'` on a profile-wide write is readable by the profile;
* the existing `_in_scope`/`scope_sql` cross-check still passes with `visibility` in the matrix.

### Size guards — stop and report if

* the fix turns out to require a **migration** (restamping existing rows). It may not: v3 stores are unreleased and unreachable, so existing rows are test fixtures. If it does, that is an owner decision, not a silent schema change.
* the regression guard cannot pass without weakening it — that would mean §3.5's two clauses are being read the wrong way round, so stop rather than adjust the test.

### Pre-flight

1. `main` must be at `85afea4` or later: Chunk 12 merged there. `git merge-base --is-ancestor TBD_SHA main` proves it.
2. **Baseline:** `pytest -q` gives **1832 passed, 3 skipped, 3 xfailed** on **both Python 3.10 and 3.12**.
3. **Re-measure from the code**, not from this file: `MemoryDraft.visibility` and every `MemoryDraft(` call site; `_insert`'s use of `draft.visibility`; `_in_scope`; `MemoryStore.list`; the migration's `visibility='profile'` stamp; and `scope_sql`. Confirm the "no call site sets it" claim still holds — if the facade has started passing one, the analysis changes.

### Document control (before and after)

Per `AGENTS.md`: reconcile `MASTER_TODO.md`, `REMAINING_PLAN.md` and this file **before** starting and **again before finishing**. Merge state counts as truth.

### End of chunk

1. Push, green CI on the exact SHA, `git merge --ff-only`, delete the branch.
2. Update `MASTER_TODO.md` and `REMAINING_PLAN.md` §2/§5/§6.2/§9/§11.
3. **Replace this file's Part A with this chunk and Part B with the next piece** — EM-304 (`fusion`), which is unblocked.
