# Changelog

All notable changes to EntropicMem are documented here. The format follows Keep a Changelog.

## [Unreleased]

### Added

- **Hermes host harness (`tests/harness/`).** `FakeHost` drives a memory provider exactly the way Hermes `MemoryManager` does — full `initialize()` kwarg set, `prefetch` on its own thread with the 8 s join and stuck-provider skip, `sync_turn`/`queue_prefetch` on a single FIFO worker, `<memory-context>` wrapping with 10k-char spill, byte-identical replay of prior blocks (cumulative prompt-token accounting), and the real hook order for normal turns, `/new`, `/undo`, compression (checkpoint API v2, fail-closed), delegation, and shutdown with the 5 s drain. Profile scoping is context-local (real `hermes_constants` override when importable, ContextVar simulation otherwise) and `HERMES_HOME` is poisoned with a decoy after `initialize`, so post-init env reads are caught. Ships the EM-003 acceptance tests: a 20-turn smoke run with metrics, and a two-profile bleed test (xfail strict until EM-102).
- **Performance bench (`evals/perf.py`, EM-005).** Seeded synthetic corpora (1k / 10k / 50k memories) measured through the real engine and provider paths: `remember` p50/p95 (no embedding), `prefetch` p50/p95 cold/warm, tool search p95, DB size per memory, and a concurrent-writer test (CLI writer process + provider reader) reporting prefetch p95 under write load. `python -m evals.perf --sizes 1000,10000` prints a table and stores `evals/results/perf-*.json`. Stdlib only; informational §6.4 budget flags (CI enforcement lands in EM-007).
- **Eval framework (`evals/`)** — scenario-driven measurement of the v2 retrieval pipeline (EM-001). JSONL datasets with `$N`/`$noise` refs, seeded deterministic noise, adapter interface (`load`/`search`/`prefetch`) with a real `engine_v2` adapter, per-query metrics (recall@5, mrr, ndcg@5, abstain_correct, noise_rate@prefetch, prefetch_tokens, latency_ms), suites `ci`/`full`/`hard`/`external`, `python -m evals run --suite ci --adapter v2 [--compare baseline]` writing `evals/results/<suite>-<sha>.json` plus a Markdown table. The `ci` suite forces the optional ML stack off (sys.meta_path blocker + engine flag patch) so it is stdlib-fast and deterministic even where sentence-transformers is installed; embeddings are exercised only by `full`. `benchmarks/` is unchanged. (EM-002 completion: `--suite hard` wires the 12-category `evals/datasets_hard/` scenario set through the same runner, embeddings off like `ci`; the tracked `evals/baselines/v2.7.0.json` baseline — S0 exit criterion #1 — is generated from the `rollback/pre-s1-20260924` tag's engine in a throwaway worktree, 180 turns / 12 categories.)

### Fixed
- **De-personalised product defaults (EM-115, G1).** `DEFAULT_DOMAINS` is the generic seven (Knowledge/People/Projects/Procedures/Preferences/Events/Infrastructure — the employer/campaign domains move to user config); `prefetch_denied_sources` is `["auto_extracted","test"]` only (test-scaffolding sources removed from product defaults); the secret-block policy message no longer names a specific secrets manager; region-specific PII (South African phone + 13-digit ID) moved to opt-in `locale_packs` (config `locale_packs: ["za"]`, default `[]` = generic patterns only), threaded from plugin config through `MemoryEngine(pii_locales=…)` into `scan_pii/check_pii/redact_pii(locales=…)`. New `tests/test_depersonalise.py` (8 tests); two existing tests adjusted to the new contracts (ZA phone now opt-in; denied-sources list is 2 entries). Full suite 834 passed / 2 skipped / 5 xfailed.
- **Mirror built-in replace/remove (EM-110, L3).** `on_memory_write` only mirrored `add`, so built-in `replace`/`remove` left stale mirror rows. `replace` now locates the mirror by `make_id(previous_content)` (fallback: substring match of `old_text` against facts tagged `mirrored`), forgets the old row and mirrors the new content; `remove` (empty content) locates and forgets the mirror via `forget(confirm=True)`; unmatched removes touch nothing. Writes with `write_origin == "background_review"` are skipped unless `mirror.background_review: true`. New `tests/test_mirror_lifecycle.py` (8 tests incl. the AC: add → replace → remove = 0 stale mirrors). Full suite 826 passed / 2 skipped / 5 xfailed.
- **Interim gateway privacy guard (EM-118, H1).** New config `owner_user_ids`: when the gateway supplies a `user_id` outside the (non-empty) owner list, the session runs in guest mode — prefetch excludes `sensitivity IN (sensitive, secret)` and `guest_hidden_domains` (default `["People","Finance"]`), Core Memory injects Persona only (never User Profile), `entropicmem_remember` writes are stamped `source=guest_tool` + tag `user:<id>`, and `entropicmem_patch_core` is refused. Owners are unaffected. Empty `owner_user_ids` with a gateway `user_id` logs a ONE-TIME warning naming the shared-pool limitation (full per-user scoping remains S4). New `tests/test_privacy_guard.py` (9 tests: guest exclusions + owner-unaffected, Persona-only core, guest write stamping, patch_core refusal, order-independent one-time warning). f004 (`test_f004_cross_user_isolation`) marker corrected: it pins FULL alice/bob isolation, which the S1 plan explicitly defers to S4 as a known limitation (its marker wrongly said EM-109). Full suite 818 passed / 2 skipped / 5 xfailed.
- **Core Memory out of per-turn prefetch (EM-116, L8).** `prefetch()` re-injected the full Core Memory block on every turn (linear token growth). New config `core_inject_mode`: `system_prompt` (default) — `system_prompt_block()` appends the screened `CoreMemory.injection_block()` capped at 2800 chars and records its sha256; prefetch then carries only a ONE-LINE delta when core changed since session start (baseline recorded by `system_prompt_block()` or the first prefetch). `prefetch` keeps the legacy full-block behaviour (two hardening tests re-pinned to it). `CoreMemory.patch` now writes atomically (tmp + `os.replace`) and keeps pre-patch snapshots under `Core/.history/`; `CoreMemory.__init__` creates its dir with `parents=True`. New `tests/test_core_inject.py` (9 tests). Xfail removed: `test_f008_core_memory_not_reinjected_every_turn` (its query was also re-paired with its fact so the non-empty-blocks guard is real now that core no longer pads it). Full suite 809 passed / 2 skipped / 5 xfailed.
- **Non-destructive cadence digests (EM-112, L5).** Cadence flushes all wrote the same `ep_sess_{sid}` episode id, so every 40-turn flush `INSERT OR REPLACE`d the previous one and only the last tail survived. Cadence flushes now write `ep_sess_{sid}_w{n}` with n monotonically increasing per session (`MemoryEngine.next_episode_wave` derives it from existing rows, so it survives restarts and deletions); the session-end digest keeps the single `ep_sess_{sid}` covering the tail (idempotent re-fire unchanged). Digest timestamps are now UTC (both the epoch conversion and the `end_ts` default were local naive). New `tests/test_cadence_digests.py` (4 tests: the 100-turn/cadence-40 AC (w1, w2, final, none overwritten), monotonic waves, session-end idempotence, UTC stamps). Full suite 799 passed / 2 skipped / 6 xfailed.
- **Extraction hygiene (EM-111, L4/G1).** (1) `quarantine_fact` now runs `_sanitize_fact_text` + `check_pii(mode="redact")` before storing (injection markers stripped, secret classes redacted; other PII is warn-only by the pii module's write-time policy). (2) The domain-specific `_EXTRACTION_PATTERNS` keyword lists (finance/alarm/hermes/obsidian/social/events) are deleted, replaced by three generic first-person patterns (`I/we <verb> ...`, `my X is ...`, `I/we <modal> ...`); no employer/campaign/product strings remain in `scripts/` (source-scan test). (3) Extraction now has a promotion path: `extract_and_store(promote=True)` (default) writes the candidate to durable facts when the write policy allows, while the pending row stays as the extraction record; background paths (session-end capture, auto-extract) pass `promote=False` and stay pending-only. (4) `pending` TTL purge: `prune_pending()` + CLI `entropicmem pending prune --older-than 30d` + automatic purge at session end (write-gated). (5) `promote_pending` keeps the pending row's domain-derived sensitivity (was hardcoded `internal`). New `tests/test_extraction_hygiene.py` (13 tests: positive+negative per pattern, promotion contracts, quarantine hygiene, sensitivity, TTL). Xfails removed: `test_f009_extraction_promotes_from_quarantine`, `test_f009_semantic_extraction_of_new_patterns`. Full suite 795 passed / 2 skipped / 6 xfailed.
- **Stop silent fuzzy overwrites (EM-109, L1).** Fuzzy dedup used to update the existing row in place whenever Jaccard ≥ 0.8, silently destroying the old value ("five minutes" → "ten minutes" left no trace). A fuzzy in-place update now requires ALL of: Jaccard ≥ 0.95, identical numbers/versions/IPs/dates (digit tokens and number words, including embedded ones like `alpha-seven.internal`), and identical negation tokens. Anything else inserts as a NEW fact and both ids are audited as `possible_duplicate`; an allowed fuzzy update is audited as `fuzzy_update` carrying the sha256 of the before-content. New `tests/test_fuzzy_dedup.py` (6 tests). Xfails removed: `test_f006_dedup_preserves_supersession_record`, `test_f006_recall_returns_superseded_with_reason`. Full suite 780 passed / 2 skipped / 8 xfailed.
- **Safe consolidate (EM-108, L2).** `consolidate()` candidate selection no longer runs on `created_at + access_count` alone (which archived importance-0.95 durable facts). A fact is now a candidate only when ALL hold: `importance < 0.6`, `domain` not in `evergreen_domains` (param, default `["People"]`), `source` not in (`built_in_memory`, `promoted`), no `pinned` tag, age from `max(updated_at, last_accessed)` (recently-touched facts are young even when created long ago) ≥ `max_age_days`, and `access_count <= min_access_count`. Candidates archive lowest-importance first (oldest first within a tier). The archive copy now preserves `sensitivity` (the `facts_archive` table gained the column — created with it for new tables and `ALTER TABLE`-upgraded for existing ones alongside the `profile_id`/`version` upgrades). New `tests/test_consolidate.py` (9 tests: each shield, age-from-activity, archive order, sensitivity round-trip, dry-run safety). Xfails removed: `test_f007_consolidate_respects_importance`, `test_f007_consolidate_archives_low_importance_first`. Regression helper fix: `_age_facts` now ages `updated_at` too (it was written for the pre-EM-106/108 created_at-only logic and left rows young under the new age rule). Full suite 770 passed / 2 skipped / 10 xfailed.
- **Prefetch packing fixes (EM-107, R6/R7).** (a) `context_query_mode` config, default `current`: the enhanced query no longer concatenates prior user turns into the retrieval query (F-006 — stale terms poisoned ranking); `concat` keeps the old behaviour. (b) `progressive_disclosure` config, default **off**: the old tiered caps collapsed every high-relevance set to 2 facts (F-007/R7 — the max-2 tier fired whenever any score was >= 0.7, which score inflation made always true); the tiers remain available opt-in. (c) `_apply_token_budget` packs by combined score (was importance-first) and never truncates mid-fact — an oversized fact is skipped whole and packing continues with smaller ones (the old path emitted `content[:remaining] + "..."` mid-word cuts). (d) `_format_block` drops its second 300-char truncation (the budget stage already caps the block). (e) Every bullet carries provenance: ` (domain · YYYY-MM-DD)` from `created_at`. New `tests/test_prefetch_packing.py` (10 tests) pins all five; six `tests/test_smart_context.py` tests re-pinned to the new contract (old paths still tested via the config flags). Xfail removed: `test_f001_progressive_disclosure_caps_results` (5 strongly-matching facts now all surface). Eval evidence — hard suite vs `v2.7.0.json`: `long_content` recall 1.0 / noise 0 / must_not 1.0 (AC met), abstain_correct 1.000, must_not_ok 1.000, noise_rate 0.303 -> 0.211; ci suite quality metrics all >= baseline. `prefetch_tokens` rises ~20/turn on hard (31 -> 51): whole facts now enter the block instead of 300-char stubs — the intended effect of (c)/(d); the 1500-char `prefetch_token_budget` still caps the block. Hard-suite noise_rate ticks up vs the EM-106 intermediate (0.167 -> 0.211) because disclosure-off admits up to `max_prefetch_results` (5) candidates instead of always-2; still well under the 0.303 baseline and abstention is unaffected.
- **Decay that cannot erase durable memory (EM-106, R3).** `recall_with_relevance` decay is no longer a raw exp decay off `last_accessed` (which crushed 120-day importance-0.9 facts to 0.062 and forgot long-term memory). New `_decay_factor`: 1.0 for durable facts (`importance ≥ 0.75`, `domain in evergreen_domains` (config, default `["People"]`), `source in (built_in_memory, promoted)`, or a `pinned` tag); otherwise `max(decay_floor, exp(-λ·age))` with `age = max(updated_at, last_accessed)` (most recent activity), `decay_floor` default 0.5 and half-life default 90 days (was 30). Serving semantics (f002 contract): `recall()` bumps `last_accessed` on returned facts via `_served()` (one batched UPDATE — actively-used facts stop decaying); `recall_with_relevance()` deliberately does NOT touch because it is the ranking API and touching there rescued weak candidates from decay mid-pipeline (observed: an eval `search()` call freshened a 180-day fact which the immediately following prefetch then injected, breaking an abstention turn). Prefetch injection bumps injected ids via the new provider `touch_on_inject` config (default true) as a batched background write through the EM-103 `_spawn` thread (`_touch_injected`). New config keys documented in README + schema: `decay_floor`, `evergreen_domains`, `touch_on_inject`; `decay_half_life_days` default 30 → 90. Xfails removed: `test_f002_old_important_fact_still_retrievable` (120-day importance-0.9 fact now scores 1.0 via durable rules + full coverage) and `test_f002_recall_updates_last_accessed` (recall() now touches). Eval evidence — ci suite vs `v2.7.0-ci.json`: ageing recall@5 1.000, all metrics ≥ baseline. Hard suite vs `v2.7.0.json`: ageing noise_rate 0.533 → 0.100, abstain_correct 1.000, overall noise_rate 0.303 → 0.167, no category regressed vs baseline except the known synonym-gap turns (ageing recall@5 stays 0.733 on hard — the 4 misses are disjoint-vocabulary paraphrases like "what city am I based in?" vs "The user lives in Cape Town", unreachable lexically and slated for S2 semantic retrieval; v2.7 only ever half-hid them via stopword-prefix luck).
- **Absolute relevance scoring + lexical coverage gate (EM-105, R1/R4).** `recall_with_relevance()` no longer min-max normalises bm25 ranks per result set (a lone hit always scored 1.0, so junk queries injected noise at full relevance). New scoring is absolute and explainable: `coverage(query_terms, text)` = stemmed query terms present / total terms (module-level `coverage`/`coverage_terms`, conservative suffix-strip stemmer: ing/es/ed/s/ly, stopword-free terms); `relevance = 0.75*coverage + 0.25*rank_bonus` with `rank_bonus = 1/(1 + 0.15*bm25_rank_index)`; `combined = clip(relevance * decay_factor * (0.85 + 0.3*importance), 0, 1)` — the old reinforcement/access-count multiplier is gone (reinforcement stays write-side via `reinforce()`). `min_relevance` filters `combined`, and the `min_relevance_score` default is now `0.35` (README + config schema updated) because the number is finally meaningful. `why_retrieved` keeps its existing tokens first and appends a `{"signal": "coverage", "value": <lexical>}` entry per hit. R4 ordering fix: `recall()` FTS branch orders `rank ASC, importance DESC` (bm25 relevance first, importance as tiebreak) instead of importance-first. Completing the R2 noise fix: the literal LIKE fallback is now gated to symbol/number queries (no ASCII letters) or FTS MATCH errors (`_like_fallback_ok`), so word queries never substring-sweep — `recall_with_relevance('a')` returns `[]` instead of 2 substring matches. EM-104 follow-up folded in: prefix `*` threshold relaxed 4+ → 3+ chars so derivational families (`use` → `used`/`user`) still match while 1-2 char tokens stay exact. Xfails removed: `test_f001_junk_query_returns_zero_relevance` (1/5-coverage partial hit now scores ~0.40, was 1.000), `test_f001_min_relevance_score_actually_filters` (min_relevance=0.5 now excludes the weak hit), `test_f001_single_token_query_does_not_match_everything` (now a passing regression guard). Eval evidence vs `evals/baselines/v2.7.0-ci.json`: abstain_correct 0.000 → 1.000, noise_rate 0.286 → 0.000, must_not_ok 0.714 → 1.000, mrr 0.900 → 1.000, no metric regressed. Eval evidence vs `evals/baselines/v2.7.0.json` (hard suite, 180 turns): abstain_correct 0.000 → 1.000, noise_rate 0.303 → 0.131, must_not_ok 0.928 → 1.000, mrr 0.850 → 0.894, ndcg 0.875 → 0.903, `paraphrase` holds 1.000 (noise 0.067 → 0.000), `long_content`/`entity`/`procedural`/`contradiction`/`update` all ≥ baseline. Recall@5 dips 0.961 → 0.939 on `hard` from turns whose expected facts only ever matched via stopword-prefix luck in v2.7 (`"we"*`, `"is"*`, `"in"*`); the remaining misses are true synonym gaps ("when is the wedding?" → "The event date is set for...") that need semantic retrieval (S2/S3) — documented, not papered over. Recall bench: precision@5 1.0, MRR 0.975. New `tests/test_scoring.py` pins the coverage primitives.
- **FTS query builder — stopwords, length rules, safe quoting (EM-104, R2).** The shared `build_fts_query()` no longer turns every `\w+` token into a prefix term: English stopwords (new stdlib-only `scripts/stopwords.py`, 180 words, frozenset `STOPWORDS`) and tokens under 2 characters are dropped, the prefix `*` goes on tokens of 3+ characters (1-2 char tokens are exact terms; the threshold was 4+ at landing and relaxed to 3+ in the EM-105 pass so derivational families like `use` → `used`/`user` keep matching), the `max_terms` cap selects non-stopwords first then longest first, and when every token was dropped (e.g. "who am I") the raw tokens come back with the length rules applied as far as possible without emptying the query — so junk queries stop matching trivially while identity questions still retrieve. `''` builder output now means 'no matches' on the recall paths (`recall()` serves exact matches only, `recall_with_relevance()` returns `[]`) instead of degenerating to a `LIKE '%%'` match-everything sweep; the episodes timeline and `index.search_fts` already treated `''` as empty. Pinned: `build_fts_query("what is a good way to do it") == '{title tags body}: "good"* OR {title tags body}: "way"*'`; new `tests/test_fts_query.py` covers the rules (junk-query regression, all-stopword fallback, hostile-punctuation MATCH validity against real FTS5, cap selection, `''` = no matches). (The F-001 repro strict xfails all remained at this point — their `engine` fixture called a non-existent `MemoryEngine.initialize()` and their bodies never ran; fixture and repros were rebuilt in the regression-suite rebuild commit.) Behaviour change outside the quick set: `test_engine_hardening.py::test_percent_and_underscore_match_literally` pins the retired "no FTS tokens → LIKE fallback" contract (query `"%"` now returns `[]` per the `''` = no-matches rule). Empty queries return no matches (never a `LIKE '%%'` sweep); the escaped literal-substring LIKE fallback survives only for symbol/number queries (no ASCII letters: `%`, `_`, `8080`) or when the FTS MATCH itself errored, so literal-symbol searches still match while word queries never substring-sweep.
- **Context-propagating background threads (EM-103, H3).** New `EntropicMemMemoryProvider._spawn()` routes every plugin background job through the host primitive `agent.memory_provider.spawn_context_thread` (contextvars-bound worker, so profile/secret scope crosses into the thread) with a single named-daemon-thread fallback inside `_spawn` for hosts without a compatible primitive (TypeError/ImportError/AttributeError). `_auto_extract` now spawns `entropicmem-extract` via `_spawn` instead of a bare `threading.Thread`, which started the worker with an empty context — in a multiplexed gateway it silently extracted facts under the default profile. Xfail removed from `test_f005_uses_spawn_context_thread` (its thread-name scan was a vacuous repro; rewritten as a source scan asserting the bare thread spawn exists only inside `_spawn`'s fallback) and the F-005 → EM-110 mapping corrected to EM-103; new behaviour tests cover `_auto_extract` → `_spawn` → host-primitive routing and the fallback path (a real named daemon thread finishes the extraction and releases the extract lock).
- **Config precedence & profile isolation (EM-102, H3/H4).** `register()`/`register_memory_provider()` now construct the provider with NO config — register-time config came from whatever profile the loader ran under and, passed as explicit constructor config, silently overrode the real profile's file config at `initialize()` (H4); `load_plugin_config` merges a host-native `memory.entropicmem` section OVER `plugins.entropicmem`; `MemoryEngine` gains `hermes_home` and the provider passes `profile_id` (from `initialize()`'s `agent_identity`) + `hermes_home` into every engine it opens; and `MemoryEngine.profile_id()`, `MemoryEngine.shared_path()`, `triple_extract._load_local_entities()`, and the `parity_audit` defaults no longer read `HERMES_HOME` from the environment — post-init env reads let a poisoned env var re-stamp another profile's rows (H3), so paths/profile now come from explicit args only (`scripts/entropicmem.py` and `vault.hermes_home_path()` keep env reads for CLI use). Xfail markers removed from `test_f004_per_profile_config_respected` and `test_two_profiles_do_not_bleed` (both now pass); `test_f005_no_os_environ_heremes_home_in_engine` extended to grep every `scripts/*.py` for env reads and a `memory.entropicmem`-over-`plugins.entropicmem` merge test added.
- **Multimodal-safe message normalisation (EM-101, H2).** New shared `scripts/textutil.py: message_text()` flattens any host payload (str, dicts with `text`/`input_text`/`output_text`, nested `content`, multipart lists, None, junk) to plain text without ever raising; `session_digest`, `sync_turn`, `_build_context_query`, and `_conversation_fingerprint` now all use it, so a single list-content message no longer kills prefetch with a swallowed TypeError (silent total memory-injection loss for the session). `sync_turn` stores normalised `{"role", "content": str}` history and accepts `turn_author` (stored on the turn entries, store-only). Test-infra repair folded in: the `home_a`/`home_b`/`make_provider` fixtures moved to `tests/conftest.py` (they were scoped to `tests/harness/` only, so the harness-based regression tests never actually ran — strict xfail was swallowing the setup errors), and the vacuous `test_f003`/`test_f004_per_profile`/`test_f008_*` repros were rewritten to genuinely exercise their defects (they invoked a non-existent `FakeHost.turn(extra_messages=...)` API or asserted nothing).
- **Host harness fidelity (review rounds 1–2).** `FakeHost.turn()` routes `/new`, `/undo`, and `/compress` to their real lifecycle boundaries instead of swallowing them as trivial turns; queued `sync_turn`/`queue_prefetch` work snapshots its turn's session id, messages, and author at submit time (previously read live state at execution, so undrained turns or a `new_session()` could re-attribute older work); a `new_session()` boundary rebuilds the frozen system block only after `on_session_switch` has run; `undo()` truncates the undone exchange from the transcript so compression evidence and replay never re-feed withdrawn turns; the decoy `HERMES_HOME` is deleted (or restored to its prior value) at shutdown even when it was unset before `start()`, so it can no longer leak into later tests in the same process; and the system-block rebuild in `new_session()`/`compress()` is fail-soft like every other hook call — a provider raising in `system_prompt_block()` is recorded in `host.errors` instead of crashing `compress()` or leaving `new_session()` waiting out its 30 s boundary timeout on a dead worker.
- **Regression suite (`tests/regressions/`)** — 23 `@pytest.mark.xfail(strict=True)` tests pinning every §2.4 headline finding (F-001…F-011), each mapped to its fixing EM task. Includes 2 findings surfaced by Teknium's marketplace review (F-010 namespace pollution, F-011 stale manifest declarations), tracked for S2 as EM-212 and EM-213.
- **Engine-based regression repros rebuilt against the real `MemoryEngine` API (EM-004 follow-up).** The 13 engine-level repros (`test_f001_*`, `test_f002_*`, `test_f006_*`, `test_f007_*`, `test_f009_*`) were written against an imagined API (non-existent `initialize()`/`age_days`/`sync_turn`, tuple results from `recall_with_relevance`, a `superseded_by` column, `consolidate` defaults that never archive) so strict xfail swallowed `AttributeError`/`TypeError` at fixture setup and none of their bodies ever ran. Rewritten against the real API (constructor-only engine, `StoredFact` results, `extract_and_store`/`add_episode`, `consolidate(dry_run=False, confirm=True)`, ISO-8601 `created_at`/`last_accessed` time travel) so each now exercises its documented v2.7 defect and fails via its own assertion. Task mapping corrected to canonical numbering: F-002/R3 decay → EM-106, F-001/R7 progressive disclosure → EM-107, F-007/L2 consolidate → EM-108, F-006/L1 fuzzy dedup → EM-109, F-009/L4 learning loop → EM-111, F-009/R8 episodes → S3 retrieval v3, F-004/H1 → EM-118 (map only; that test is untouched). `test_f001_junk_query_returns_zero_relevance` rewritten as the R1 normalisation repro (a pure-junk query now legitimately returns zero hits after EM-104, so it targets 1/5-term min-max inflation instead); `test_f009_semantic_extraction_of_new_patterns` switched from the secret-bearing 'API key every 90 days' statement to a generic thermostat constraint (secret words trip the write policy and pollute the repro). `test_f001_single_token_query_does_not_match_everything` stays xfail: the EM-104 FTS fix landed but the no-hit literal LIKE fallback still substring-matches 'a' inside unrelated words.
- **Correct export/import/backups (EM-113).** Export now live-copies `memory.db`/`index.db` through the SQLite backup API (consistent under concurrent writes), exports the vault from its resolved path, and writes a manifest v2 with schema versions plus a sha256 per exported file. Import is fail-closed: it refuses while `migration.lock` exists or the provider is running (write flock held), validates every archive member BEFORE extracting anything (regular files only — symlinks, hardlinks, device files, absolute paths and `..` components are rejected), extracts via tarfile's `filter="data"` (Python 3.12+) into a staging dir, verifies the manifest sha256s, and only then installs `memory.db`/`index.db`/`vault/**` at their resolved targets. `_backup()` gained the EM-113 retention policy (`_prune_backups`): keep the last 10 backups + 1 per day for the last 7 days. New `tests/test_export_import.py` (8 tests: export → wipe → import → recall-equal AC, `..`/symlink/absolute member rejection with nothing written outside, lock-file and running-provider refusal, manifest v2 sha256s match the archive, retention over aged backups). Full suite 842 passed / 2 skipped / 5 xfailed.

## [2.7.0] - 2026-09-22

Hardening release. The engine moved into the plugin directory and every content-trust surface (writes, retrieval, prefetch, the graph viewer, the graph server) got explicit policy.

### Security

- **Write policy** blocks secret and credential content. High-confidence `api_key` / `password` findings are auto-redacted before storage; other PII types are recorded as warn-only findings.
- **Local prompt-injection screen** runs on vault retrieval and on prefetch, `recall`, and `get` tool payloads. Flagged content keeps its place and payload but ships prefixed with a prominent warning marker. Flag-with-warning and fail-open by design: if the screen itself fails, text ships unmarked rather than breaking retrieval.
- **Vault path containment** is enforced on vault writes, so writes cannot escape the resolved vault root.
- **Graph viewer markdown is sanitized** against stored XSS. Output from the markdown renderer and lazy-fetched note bodies both pass a client-side sanitize pass before touching the DOM.
- **Graph server loopback enforcement.** A non-loopback bind is refused at startup unless `ENTROPICMEM_GRAPH_EXPOSE=1` explicitly opts in. When not loopback-bound, the body-bearing read endpoints require `ENTROPICMEM_GRAPH_TOKEN` via the `X-EntropicMem-Token` header; loopback stays tokenless as the local trust plane.
- **Destructive operations gated.** `forget` and `consolidate` require `--confirm` and auto-backup before running; `consolidate` defaults to dry-run.
- **Append-only audit log** records every write.

### Changed

- **Engine relocation.** All engine code now lives under `plugins/entropicmem/scripts/` (previously `skills/entropicmem/scripts/`), making the plugin directory self-contained for catalog installs (`hermes plugins install entropicmem`). The skill `skills/entropicmem/` now holds only `SKILL.md`, `SETUP.md`, and `references/` plus vault templates. CLI invocations use `python3 ~/.hermes/plugins/entropicmem/scripts/entropicmem.py`.
- **Test suite and CI.** 600+ tests on Python 3.10 to 3.12 with pytest pinned in CI. The recall benchmark floor (`precision@5 >= 0.50`, `MRR >= 0.50`) is asserted in CI, and `hermes plugins validate --install-deps plugins/entropicmem` runs as the catalog admission gate.

### Added

- **Lifecycle hooks (5 total).** `on_memory_write` mirrors built-in `memory` tool writes into the engine (primary agent context only). `on_session_switch` tracks session identity and resets per-session caches. `on_session_end` writes an extractive session digest episode (deterministic id, re-firing replaces instead of duplicating) and runs quarantine-first fact extraction into `pending_facts`. `on_turn_start` flushes a partial digest every `turn_cadence_flush_turns` turns for always-on sessions, at most once per `turn_cadence_min_interval_sec`. `on_pre_compress` returns a standing-constraints bullet list to the compression summary prompt and durably checkpoints it as an episode (checkpoint API v2 fail-closed semantics: a non-empty return guarantees the checkpoint is persisted). All digest extraction is deterministic and stdlib-only (no LLM).
- **Lifecycle config keys** under `plugins.entropicmem`: `session_end_capture`, `turn_cadence_flush_turns`, `turn_cadence_min_interval_sec`, `session_extract_pending`.
- **Explainable recall.** Every `recall()`, `recall_with_relevance()`, and `recall_hybrid()` hit carries a `why_retrieved` field: a deterministic list of reason tokens (`exact`, `fts`, `vector`, `recency`, `importance`, `triple`, `domain`) explaining why the fact surfaced. The `entropicmem_recall` tool exposes it in tool output.
- **Recall benchmark.** Frozen corpus (98 facts) with 20 probes, a single runner (`benchmarks/run_recall_bench.py`) reporting `precision@5` and MRR, and a CI floor of 0.50 on both.

### Fixed

- **Graph exports render again.** Exports showed an endless "Building graph" spinner because a node color helper referenced by the export template had been deleted; every export threw a `ReferenceError` before the simulation started. A template integrity test now scans for helpers called without a definition.
- **`lint` dead-link detection is order-independent.** Wikilink targets are collected before validation, so a link to a note that sorts after the linking note is no longer reported dead.
- **Graph export crash under `--max-nodes` re-ranking.** Edge dataclass objects were dereferenced as dicts (`TypeError`), failing exports and CI; fixed to dataclass attribute access.

## [2.6.0] - 2026-09-18

### Added

- Community detection over the wikilink graph (deterministic label propagation; stable community colors and ids across rebuilds), exported per node with community metadata.
- Cluster rendering: "Color by: Domain | Community" switch with a community legend and an optional centroid "Cluster islands" layout; display preferences persist to `localStorage`.
- In-graph vault search (`GET /api/search`) with a debounced panel box; hits inside the view zoom and focus, hits outside the export open through the lazy note fetch.
- Path tracing (`GET /api/path`): shift-click two nodes to highlight the shortest path with focus-mode dimming.
- Orphan highlight: degree-0 notes stay lit while connected notes fade; hygiene signal only.
- Incremental index refresh: `index rebuild` diffs against `content_hash` and rewrites only added or changed notes; refreshes preserve `triple:*` edges.

### Fixed

- Focus mode no longer dims the whole graph for nodes filtered out of the current view.
- Note reindexing replaces only `wikilink` edges, never `triple:*` edges.

## [2.5.0] - 2026-08-19

### Added

- Multi-profile sync layer: transactional outbox on every durable write, append-only shared event log (`shared-init`), and idempotent `publish` / `pull` between profiles.
- Tombstones: deletions propagate as delete events with a new version slot; deleted rows stay in the projection and are hidden from recall.
- Publish-side sensitivity filter: `secret` and `sensitive` tier facts never enter the outbox; `publish_scope` config (`none|shared|all`, env `ENTROPICMEM_PUBLISH_SCOPE`).
- `recall --scope own|shared|all` and `publish --backfill` (explicit opt-in for legacy facts; nothing auto-publishes).

## [2.4.0] - 2026-08-18

### Added

- Multi-profile provenance: `profile_id`, `fact_timestamp`, `version`, `deleted` columns on facts (idempotent migration for existing stores), plus `schema_info` and `profile_registry` tables.
- Every durable write stamps the owning profile slug; dedup updates bump `version`; the audit log actor defaults to the profile slug.
- Fail-closed migration mode: `entropicmem migrate` holds `migration.lock` (writes rejected while held); `migrate --status` reports per-store state.

## [2.3.2] - 2026-08-15

### Fixed

- **`entropicmem_query` tool was broken:** it imported a name the retrieval module never exported, so every call failed at tool runtime with an ImportError. The tool now calls `retrieve_composed()` and returns the full cited result. A regression test AST-scans every deferred import in the plugin against the real modules and exercises the tool end-to-end.
- `forget()` / `consolidate()` no longer leave orphan embedding rows; cleanup is plain SQL and both paths share the guard.
- Version drift: all version sites bumped in lockstep.

### Changed

- Vault index opens with a 30s busy timeout (parity with the memory engine) to avoid `database is locked` under concurrent writers.
- `docs/CLI_REFERENCE.md` rewritten from the live argparse surface.

## [2.3.1] - 2026-08-12

### Fixed

- Wikilinks to notes outside the export cap now resolve lazily (`GET /api/note/by-title/{title}`) instead of rendering as broken red links; they only turn red when the target genuinely does not exist.
- Opening a lazily-resolved note no longer dims the entire graph.

## [2.3.0] - 2026-08-11

### Added

- Graph UI overhaul: deltaMode-normalized wheel zoom (trackpad and mouse at the same rate), on-screen zoom controls with fit-to-view, collapsible panel / legend / minimap / stats with persisted state, inline SVG iconography, HiDPI PNG export, tooltip viewport flipping, modal Tab focus trap, loading and empty states.

## [2.2.0] - 2026-08-08

### Added

- Episodic memory: `episodes` table with FTS5, `episode add|list|stats`, `recall --type episodic --since --until` as a dated timeline.
- Knowledge triples: `triples` table with validity and confidence, `triple extract|list|stats|neighbors|path|inconsistencies`, and a rule-based (no LLM) triple extractor with negation awareness.
- Hybrid FTS5 + vector recall (`recall_hybrid`) with graceful fallback when embeddings are unavailable.
- `index rebuild|status` and `memory reindex` for vault index and FTS maintenance.
- Health-check coverage for embeddings, episodes, and triples.

## [2.1.9] - 2026-08-07

### Fixed

- `entropicmem init` environment block is idempotent (skips when any `ENTROPICMEM_*` key exists) and refuses to persist vault or index paths under temp directories.

## [2.1.8] - 2026-08-04

### Added

- CLI `entropicmem index rebuild|status` (periodic vault index refresh) and `entropicmem memory reindex` (rebuild `facts_fts` from `facts`, repairing orphan FTS rows).
- Graph server source in-repo under `scripts/graph_server/`; `POST /refresh` rebuilds the vault index before exporting.

### Fixed

- Health and stability checks use current-streak semantics, so an old passing streak can no longer mask a currently degraded system.

## [2.1.6] - 2026-07-28

### Security

- Sensitivity tiers (`public|internal|sensitive|secret`) with secret and credential blocking on the write path.
- Auto-extracted facts quarantine into `pending_facts`; `pending list|promote|discard` to review them.
- Append-only `audit_log` with `audit` CLI.
- `forget` / `consolidate` require explicit confirmation; consolidate is dry-run by default.
- Graph export metadata-only by default (`--include-bodies` to opt in); graph serving binds `127.0.0.1` with token auth on refresh.
- Filesystem modes enforced on DB paths (700/600); backups AES-256-CBC encrypted before upload.
- Plugin defaults: `auto_extract_enabled=false`, `core_memory_writable=false`; prefetch source denylist; memory-context and instruction-hijack markers stripped on write.
- SSRF protection on URL ingest (DNS resolution with private and link-local answers blocked).

## [2.1.0] - 2026-07-21

### Fixed

- Graph visualizer script-level syntax errors that blanked the page; node modal body lookup; full note bodies embed reliably in exports.

### Added

- Graph visualizer features: real per-type node shapes, focus mode, title search with zoom-to-node, edge encoding (solid wikilinks, dashed tag links, weighted stroke), clickable wikilink navigation in modals, tag chips that filter the graph, minimap with live viewport, PNG export, deep links, and accessibility (focusable nodes, dialog semantics, Escape handling).

## [2.0.0] - 2026-07-21

### Added

- Packaging (`pyproject.toml` with optional dependency groups) and CI expansion: multi-Python matrix (3.10 to 3.12) plus ruff lint.

## [1.6.0] - 2026-07-21

### Added

- Fuzzy deduplication (Jaccard similarity) for near-duplicate facts.
- Automatic FTS5 index rebuild on corruption; memory consolidation into `facts_archive`; timestamped auto-backups before destructive operations.

## [1.5.0] - 2026-07-21

### Fixed

- Thread-safety and correctness of background extraction, reinforcement return values, prefetch state locking, multi-word FTS parity, and Core Memory patching delegated to a single source of truth.

## [1.4.0] - 2026-07-21

### Fixed

- Multi-word FTS recall strategy unified across recall paths; Core Memory frontmatter handling; regex extraction garbage groups; prefetch cache invalidation on every turn; `forget()` return value.

### Changed

- `entropicmem_recall` uses decay and reinforcement aware scoring and returns `relevance_score`.

## [1.2.0] - 2026-07-17

### Added

- Smart Context Management: relevance scoring (FTS5 bm25 normalized), per-turn token budget, turn-level deduplication, domain filtering, progressive disclosure tiers, conversation-aware query enhancement, and conversation-aware prefetch caching.

## [1.1.0] - 2026-07-16

### Added

- Hermes MemoryProvider plugin (`plugins/entropicmem/`) with `entropicmem_remember`, `entropicmem_recall`, `entropicmem_query` tools and mirroring of built-in `memory` tool writes.

## [1.0.0] - 2026-07-16

### Added

- Standalone memory engine (`memory.db`), vault engine with ingest loop, graph visualizer, CLI (`remember`, `recall`, `forget`, `memory list`), and seed vault templates.
