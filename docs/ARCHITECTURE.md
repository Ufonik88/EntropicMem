# Architecture

EntropicMem is a standalone, stdlib-first agent memory system with three runtime surfaces: the engine modules (library), the CLI (thin argparse wrapper), and the Hermes MemoryProvider plugin (integration layer). Everything resolves to three persistent stores under `~/.hermes/entropicmem/` (or `$HERMES_HOME/entropicmem/`): `memory.db`, `index.db`, and `vault/`.

## Layout and self-containment

All engine code lives under `plugins/entropicmem/scripts/`, inside the plugin directory. The plugin is therefore self-contained: `hermes plugins install entropicmem` delivers the MemoryProvider, the engine, and the CLI in one package with no cross-package path assumptions. The skill `skills/entropicmem/` carries only agent instructions (`SKILL.md`), the bootstrap checklist (`SETUP.md`), reference docs, and the seed vault templates consumed by `init`. CLI invocations use `python3 ~/.hermes/plugins/entropicmem/scripts/entropicmem.py`.

## Component map

| Component | Location | Role |
|-----------|----------|------|
| Memory engine | `plugins/entropicmem/scripts/memory_engine.py` | Fact CRUD, FTS5, dedup, version snapshots, audit log, pending quarantine, episodes, triples, embeddings integration |
| Write policy | `plugins/entropicmem/scripts/policy.py` | Sensitivity tiers, secret blocking, quarantine decisions, prefetch redaction |
| PII | `plugins/entropicmem/scripts/pii.py` | Detection + redaction on the write path |
| Injection screen | `plugins/entropicmem/scripts/injection_screen.py` | Local prompt-injection screening on retrieval and prefetch payloads |
| Embeddings | `plugins/entropicmem/scripts/embeddings.py` | 384-dim `all-MiniLM-L6-v2` vectors, cosine search, hybrid fusion (optional dep, **opt-in**: `embeddings_enabled: true` in the provider config or `ENTROPICMEM_EMBEDDINGS=1` for the CLI; the model downloads on first use) |
| Temporal | `plugins/entropicmem/scripts/temporal.py` | Natural-language date parsing for `recall`/`timeline` |
| Session digest | `plugins/entropicmem/scripts/session_digest.py` | Extractive session digests + standing-constraints extraction (stdlib, no LLM) |
| Vault | `plugins/entropicmem/scripts/vault.py` | Markdown notes, CoreMemory (Persona/User Profile), path resolution with containment |
| Index | `plugins/entropicmem/scripts/index.py` | Vault FTS5 + `graph_edges` over `index.db`, incremental rebuild |
| Retrieval | `plugins/entropicmem/scripts/retrieval.py` | Composed stack: hot cache, FTS5, wikilink expansion, optional semantic rerank |
| Triple extraction | `plugins/entropicmem/scripts/triple_extract.py` | Rule-based subject, predicate, object extraction |
| Graph export | `plugins/entropicmem/scripts/graph_export.py` | D3 HTML template (with markdown sanitize pass) + json/dot/canvas export |
| CLI | `plugins/entropicmem/scripts/entropicmem.py` | 35 top-level commands over the modules above |
| Plugin | `plugins/entropicmem/` | Hermes `MemoryProvider`: 7 tools, 5 lifecycle hooks, config schema |
| Graph server | `scripts/graph_server/server.py` | FastAPI: `/refresh` (always token-gated), `/api/note/{id}`, `/api/note/by-title/{title}`, `/api/search`, `/api/path`, `/health`; loopback bind enforced, Host allowlist, CSP, static or per-run token |
| Static graph server | `plugins/entropicmem/scripts/graph_static.py` | stdlib server behind `graph serve`: `graph.html`/`graph.json` only, same bind rule, Host allowlist and CSP, no token |

## The v3 storage core (`em/`, on `main`, not live yet)

Beside the 2.8.x provider above, `main` carries the 3.0 development line
(`3.0.0.dev0`): a second, stdlib-only package under
`plugins/entropicmem/scripts/em/`, with its own schema and migrations. **Nothing
in it is wired into the plugin yet** — the provider still runs the engine in the
component map above. The wiring is EM-211 (a legacy facade over `em.store`),
whose facade `V3Engine` now implements the whole provider-facing contract; what
remains is the entity-linker job and then switching the provider over. Every
module is listed in `[tool.setuptools] packages`, and `em.__version__` is the
single version source for the whole repo.

| Module | What it holds |
|--------|---------------|
| `em.clock` | Freezable UTC (`freeze`, `utc_now`), ISO helpers, and ULID ids (`new_id`, `short_id`). Time and ids come from here and nowhere else (invariant 4) |
| `em.store.db` | `open_db` (WAL, `busy_timeout`), `Store` with `transaction()` / `writer()`, `BEGIN IMMEDIATE` for writes |
| `em.store.locking` | The portable advisory lock (`fcntl` on POSIX, `msvcrt` on Windows). The only module allowed a platform import |
| `em.store.memories` | `MemoryStore`: add, update, supersede, set_status, get, list, history, touch, purge, over `memories` + `memory_versions` |
| `em.store.episodes` | Episodes and content-addressed transcript chunks |
| `em.store.entities` | Entities, aliases and typed relations, with two-sighting support |
| `em.store.audit` | The hash-chained `audit_log`, appended inside the caller's transaction (invariant 3) |
| `em.store.jobs` | `JobQueue`: enqueue / claim / complete / fail, `dedupe_key`, leases, dead-letter |
| `em.store.backup` | `BackupManager`: `create`, `verify`, `rotate`, and a guarded `restore` |
| `em.store.migrations` | The migration framework, migrations `0001`–`0004`, and `assert_safe_db_path` |
| `em.jobs.worker` | `JobWorker` + `HandlerRegistry`: claim, run outside the write transaction (invariant 2), lease heartbeat, retry with backoff |
| `em.jobs.cli` | `entropicmem worker run`: the job entry point a cron can call |
| `em.formation.entity_linker` | The two-sighting linker **and** `make_link_handler`: it runs as a `link:<memory_id>:<version>` job, never inside a write (invariant 2) |
| `em.facade.contract` | The provider contract derived by AST scan over the provider source; `tests/parity/` is its gate. `PROVIDER_ATTRIBUTES` is empty, so the provider reaches the engine only through methods both engines implement |
| `em.facade.engine` | `V3Engine`: the whole `LegacyEngine` API over `em.store` — reads, writes and the mirror call. Complete as a library, **not wired in**; see the facade rules in [`V3_FOUNDATIONS.md`](V3_FOUNDATIONS.md) |
| `em.retrieval.query` | EM-301's `QueryAnalyzer`: text normalisation, IDF term selection, intent, entity detection, and the common temporal shapes |
| `em.retrieval.temporal` | The `TimeRange` a query may carry (the full temporal grammar is EM-310) |
| `em.retrieval.candidates` | EM-302's candidate generators (`bm25`, `entity`, `episodic`, `recent`, `pinned`), `Candidate`, `RetrievalContext`, and `scope_sql` — the §3.5 rule as SQL |
| `em.retrieval.fusion` | EM-304's weighted RRF, feature rerank, deterministic tie-break and explanation, plus the scoped feature loader |
| `em.retrieval.gate` | EM-305's abstention gate: the four support conditions, then the score threshold |
| `em.retrieval.diversity` | EM-305's supersession/duplicate collapse and MMR diversity |

The ten invariants in [`V3_FOUNDATIONS.md`](V3_FOUNDATIONS.md) are the rules for
this package: transactions belong to the caller, no slow work inside a write
transaction, one audit row per change in the same transaction, time and ids from
`em.clock`, every read scoped, `purge` removes everything derived, applied
migrations immutable, development never touches the live store, every
subpackage listed in `pyproject.toml`, and portable code.

The v3 store is not live. `entropicmem worker run` and the migration commands
refuse any path outside a test tree unless `ENTROPICMEM_ALLOW_LIVE_MIGRATION=1`
is set, and the cutover is the owner's call.

**Where this sits in the plan:** the released line is 2.8.1 (tag `7e02412` on `release/2.8.x`, catalog-pinned) and `main` is the 3.0 development line. What is built, what is next, and the rules for changing either, live in [`plan/REMAINING_PLAN.md`](plan/REMAINING_PLAN.md) (§2 is the state, §11 is the cold-start page) and [`plan/NEXT_CHUNK.md`](plan/NEXT_CHUNK.md), which holds exactly one chunk ahead.

## Storage layout

```
~/.hermes/entropicmem/
├── memory.db          # facts, facts_fts, episodes, triples, embeddings,
│                      # audit_log, pending_facts, facts_archive, versions
├── index.db           # notes_meta, notes_fts, graph_edges
├── vault/             # Markdown notes: <Domain>/Title.md, Wiki-Cache.md, Core/
└── backups/           # timestamped pre-op backups + encrypted daily archives
```

The two DBs are deliberately split: `memory.db` is the fact engine; `index.db` is the vault's search and graph index. The graph server reads `index.db`; the plugin reads both. `graph_edges` of kind `triple:*` are mirrored into both DBs so the visual graph shows knowledge triples.

## Data flow

**Write (durable fact):**

```
remember() -> sanitize -> policy (block secret / quarantine auto) -> PII redact
           -> INSERT facts + facts_fts + embedding -> snapshot version -> audit
           -> optional vault note projection -> index refresh
```

**Read (hybrid recall):**

```
recall() -> FTS5 match (+ vector similarity when embedder present)
         -> relevance scoring -> temporal filter -> top-k facts
```

**Vault retrieval (`query`):**

```
query() -> hot cache orientation -> index FTS5 -> wikilink expansion (1 hop)
        -> optional semantic rerank -> snippets + graph context + citations
```

Prefetch (system-injected `<memory-context>`) runs the same retrieval pipeline under relevance filtering, dedup, token budget, and the prompt-injection screen.

## Concurrency & integrity

- WAL mode on both SQLite stores; `busy_timeout=30s` on every connection.
- Cross-process write lock: the engine takes an exclusive advisory lock on `<db>.lock` for writes, so gateway, CLI, and cron writers serialize. EM-202: the lock is portable — `fcntl.flock` on POSIX, `msvcrt.locking` on Windows — and lives in `em.store.locking` (no direct platform imports elsewhere). The v3 storage core (`em.store.db`) relies on SQLite's own serialisation instead: `BEGIN IMMEDIATE` + `busy_timeout` under WAL, with advisory locks reserved for what SQLite cannot see (migrations, capsule imports).
- Auto-backup before destructive operations (`forget`, `consolidate`).
- Confirm gates: destructive APIs require `confirm=True`.
- Orphan guards: `forget`/`consolidate` remove embeddings by plain SQL (schema-probed), never gated on optional dependency availability.

## Plugin boundary (what the plugin does NOT do)

The MemoryProvider returns a prefetch string and exposes tools over the engine modules. It does not monkeypatch Hermes core, does not rewrite prompt or system-prompt modules, and `entropicmem_patch_core` patches vault Markdown (Persona/User Profile) only, never Hermes Python source. Writes from subagent, cron, and flush agent contexts are skipped by contract. Hermes core errors should not be attributed to the plugin without verification; trace the full data path before concluding a single cause.

## Multi-profile isolation

All paths resolve from `HERMES_HOME`, so each Hermes profile gets its own `{vault, memory.db, index.db}` set under `$HERMES_HOME/entropicmem/`. Explicit `ENTROPICMEM_*` env vars override the profile defaults. Cross-profile sharing is opt-in through the provenance and sync commands (`migrate`, `shared-init`, `publish`, `pull`), see [BACKFILL_PROCEDURE.md](BACKFILL_PROCEDURE.md).

## Extension points

- New CLI commands: add a `cmd_*` function + argparse branch in `entropicmem.py`; keep the routes dict complete (unhandled branches fail silently otherwise).
- New plugin tools: add a schema entry + handler in `plugins/entropicmem/__init__.py`; the deferred-import AST test in `tests/test_plugin_imports.py` verifies every `from X import Y` resolves against the real modules.
- New optional deps: mirror the try/except availability-probe pattern used for `embeddings.py`; the engine must degrade gracefully.

## Explainable recall

Every recall path in `MemoryEngine` populates a `why_retrieved` field on `StoredFact`, a deterministic list of reason tokens built from boolean flags (`fts_match`, `exact_match`, `vector_match`, `recency_applied`, `importance_applied`, `triple_boost`, `domain_filtered`, `like_fallback`):

| Recall method | How `why_retrieved` is populated |
|---------------|----------------------------------|
| `recall()` | `exact` for exact matches, `fts` for FTS5 hits and LIKE fallback; `domain` when domain filter active |
| `recall_with_relevance()` | `fts` (always), `recency` when `decay_enabled=True`, `importance` (always), `domain` when domain filter active |
| `recall_hybrid()` | Delegates to `recall_with_relevance` for the FTS path; `vector_match=True` for vector-only hits; `domain` when domain filter active |

The plugin's `_recall()` handler includes `why_retrieved` in each result dict (last field so existing parsers still see content first).

## Lifecycle hooks

The plugin implements five Hermes memory-provider hooks, all deterministic (no LLM) and fail-soft (a hook failure logs and returns; it never breaks the host session):

| Hook | What it does | Config keys |
|------|--------------|-------------|
| `on_memory_write` | Mirrors built-in `memory` tool writes into the engine (primary agent context only). | (always on) |
| `on_session_switch` | Tracks session identity; resets prefetch caches and digest buffers on reset. | (always on) |
| `on_session_end` | Flushes an extractive session digest into `episodes` (`ep_sess_{session_id}`, `INSERT OR REPLACE` = idempotent), then runs the regex extraction path into `pending_facts` (quarantine only; nothing auto-promotes). | `session_end_capture`, `session_extract_pending` |
| `on_turn_start` | Partial digest flush every N turns, no more often than the min interval, for always-on gateway sessions where `on_session_end` is rare. | `turn_cadence_flush_turns` (0 disables), `turn_cadence_min_interval_sec` |
| `on_pre_compress` | Returns a standing-constraints bullet list for the compression summary prompt and durably checkpoints it as an `ep_precomp_{session_id}` episode tagged `source='pre_compress'`. Checkpoint API v2 fail-closed semantics: a non-empty return guarantees the checkpoint is persisted; on persist failure the error propagates so the host can keep the uncompressed transcript. Returns `""` when nothing salient. | (always on) |

Digest construction lives in `plugins/entropicmem/scripts/session_digest.py` (`extractive_digest`, `extract_constraints`): pure stdlib, head+tail sampling (first turns set context, recent turns carry state), bullets capped at 2,000 chars. Tool-role messages are skipped; empty or tool-only transcripts no-op.
