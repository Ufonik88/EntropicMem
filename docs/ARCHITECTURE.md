# Architecture

EntropicMem is a standalone, stdlib-first agent memory system with three
runtime surfaces: the **engine modules** (library), the **CLI** (thin
argparse wrapper), and the **Hermes MemoryProvider plugin** (integration
layer). Everything resolves to three persistent stores under
`~/.hermes/entropicmem/` (or `$HERMES_HOME/entropicmem/`): `memory.db`,
`index.db`, and `vault/`.

## Component map

| Component | Location | Role |
|-----------|----------|------|
| Memory engine | `skills/entropicmem/scripts/memory_engine.py` | Fact CRUD, FTS5, dedup, version snapshots, audit log, pending quarantine, episodes, triples, embeddings integration |
| Write policy | `policy.py` | Sensitivity tiers, secret blocking, quarantine decisions, prefetch redaction |
| PII | `pii.py` | Detection + redaction on the write path |
| Embeddings | `embeddings.py` | 384-dim BGE-small vectors, cosine search, hybrid fusion (optional dep) |
| Temporal | `temporal.py` | Natural-language date parsing for `recall`/`timeline` |
| Vault | `vault.py` | Markdown notes, CoreMemory (Persona/User Profile), path resolution |
| Index | `index.py` | Vault FTS5 + `graph_edges` over `index.db` |
| Retrieval | `retrieval.py` | Composed stack: hot cache → FTS5 → wikilink expansion → optional semantic rerank |
| Triple extraction | `triple_extract.py` | Rule-based subject–predicate–object extraction |
| Graph export | `graph_export.py` | D3 HTML template + json/dot/canvas export |
| CLI | `entropicmem.py` | 30 top-level commands over the modules above |
| Plugin | `plugins/entropicmem/` | Hermes `MemoryProvider` — 7 tools, prefetch injection, config schema |
| Graph server | `scripts/graph_server/server.py` | FastAPI: `/refresh` (token-gated), `/api/note/{id}`, `/api/note/by-title/{title}` |

## Storage layout

```
~/.hermes/entropicmem/
├── memory.db          # facts, facts_fts, episodes, triples, embeddings,
│                      # audit_log, pending_facts, facts_archive, versions
├── index.db           # notes_meta, notes_fts, graph_edges
├── vault/             # Markdown notes: <Domain>/Title.md, Wiki-Cache.md, Core/
└── backups/           # timestamped pre-op backups + encrypted daily archives
```

**The two DBs are deliberately split**: `memory.db` is the fact engine;
`index.db` is the vault's search/graph index. The graph server reads
`index.db`; the plugin reads both. `graph_edges` of kind `triple:*` are
mirrored into both DBs so the visual graph shows knowledge triples.

## Data flow

**Write (durable fact):**

```
remember() → sanitize → policy (block secret / quarantine auto) → PII redact
           → INSERT facts + facts_fts + embedding → snapshot version → audit
           → optional vault note projection → index refresh
```

**Read (hybrid recall):**

```
recall() → FTS5 match (+ vector similarity when embedder present)
         → relevance scoring → temporal filter → top-k facts
```

**Vault retrieval (`query`):**

```
query() → hot cache orientation → index FTS5 → wikilink expansion (1 hop)
        → optional semantic rerank → snippets + graph context + citations
```

## Concurrency & integrity

- **WAL mode** on both SQLite stores; `busy_timeout=30s` on every connection.
- **Cross-process write lock** — the engine takes an `fcntl` exclusive lock
  on `<db>.lock` for writes, so gateway, CLI, and cron writers serialize.
- **Auto-backup** before destructive operations (`forget`, `consolidate`).
- **Confirm gates** — destructive APIs require `confirm=True`.
- **Orphan guards** — `forget`/`consolidate` remove embeddings by plain SQL
  (schema-probed), never gated on optional dependency availability.

## Plugin boundary (what the plugin does NOT do)

The MemoryProvider returns a prefetch string and exposes tools over the
engine modules. It does **not** monkeypatch Hermes core, does not rewrite
`prompt_builder.py`/`system_prompt.py`, and `entropicmem_patch_core`
patches vault Markdown (Persona/User Profile) only — never Hermes Python
source. Hermes core errors should not be attributed to the plugin without
verification (see the two-bug masking pattern: trace the full data path
before concluding a single cause).

## Multi-profile isolation

All paths resolve from `HERMES_HOME`, so each Hermes profile gets its own
`{vault, memory.db, index.db}` set under `$HERMES_HOME/entropicmem/`.
Explicit `ENTROPICMEM_*` env vars override the profile defaults.

## Extension points

- **New CLI commands** — add a `cmd_*` function + argparse branch in
  `entropicmem.py`; keep the routes dict complete (unhandled branches fail
  silently otherwise).
- **New plugin tools** — add a schema entry + handler in
  `plugins/entropicmem/__init__.py`; the deferred-import AST test in
  `tests/test_plugin_imports.py` will verify every `from X import Y`
  resolves against the real modules.
- **New optional deps** — mirror the try/except availability-probe pattern
  used for `embeddings.py`; the engine must degrade gracefully.

## Explainable Recall (P1 D1)

Every recall path in `MemoryEngine` now populates a `why_retrieved` field on
`StoredFact`. The helper `_build_reasons()` constructs a deterministic list of
reason tokens from boolean flags:

```python
def _build_reasons(
    *,
    fts_match: bool = False,
    exact_match: bool = False,
    vector_match: bool = False,
    recency_applied: bool = False,
    importance_applied: bool = False,
    triple_boost: bool = False,
    domain_filtered: bool = False,
    like_fallback: bool = False,
) -> List[Any]:
```

| Recall method | How `why_retrieved` is populated |
|---------------|----------------------------------|
| `recall()` | `exact` for exact matches, `fts` for FTS5 hits, `fts` for LIKE fallback; `domain` when domain filter active |
| `recall_with_relevance()` | `fts` (always), `recency` when `decay_enabled=True`, `importance` (always), `domain` when domain filter active |
| `recall_hybrid()` | Delegates to `recall_with_relevance` for FTS path; `vector_match=True` for vector-only hits; `domain` when domain filter active |
| `_recall_like_fallback()` | `like_fallback=True` (emits `fts`), `importance_applied=True`, `domain` when domain filter active |

The plugin's `_recall()` handler includes `why_retrieved` in each result
dict (last field so existing parsers still see content first).
