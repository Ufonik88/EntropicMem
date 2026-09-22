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
| Embeddings | `plugins/entropicmem/scripts/embeddings.py` | 384-dim BGE-small vectors, cosine search, hybrid fusion (optional dep) |
| Temporal | `plugins/entropicmem/scripts/temporal.py` | Natural-language date parsing for `recall`/`timeline` |
| Session digest | `plugins/entropicmem/scripts/session_digest.py` | Extractive session digests + standing-constraints extraction (stdlib, no LLM) |
| Vault | `plugins/entropicmem/scripts/vault.py` | Markdown notes, CoreMemory (Persona/User Profile), path resolution with containment |
| Index | `plugins/entropicmem/scripts/index.py` | Vault FTS5 + `graph_edges` over `index.db`, incremental rebuild |
| Retrieval | `plugins/entropicmem/scripts/retrieval.py` | Composed stack: hot cache, FTS5, wikilink expansion, optional semantic rerank |
| Triple extraction | `plugins/entropicmem/scripts/triple_extract.py` | Rule-based subject, predicate, object extraction |
| Graph export | `plugins/entropicmem/scripts/graph_export.py` | D3 HTML template (with markdown sanitize pass) + json/dot/canvas export |
| CLI | `plugins/entropicmem/scripts/entropicmem.py` | 34 top-level commands over the modules above |
| Plugin | `plugins/entropicmem/` | Hermes `MemoryProvider`: 7 tools, 5 lifecycle hooks, config schema |
| Graph server | `scripts/graph_server/server.py` | FastAPI: `/refresh` (token-gated), `/api/note/{id}`, `/api/note/by-title/{title}`, `/api/search`, `/api/path`; loopback bind enforced |

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
- Cross-process write lock: the engine takes an `fcntl` exclusive lock on `<db>.lock` for writes, so gateway, CLI, and cron writers serialize.
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
