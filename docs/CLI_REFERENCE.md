# CLI Reference

All commands: `python3 ~/.hermes/skills/entropicmem/scripts/entropicmem.py <cmd>`
(or the `entropicmem` wrapper if installed on PATH).

## Vault & knowledge loop

| Command | Description |
|---------|-------------|
| `init` | Bootstrap vault, index, env vars (`--dry-run` to preview) |
| `ingest <source>` | URL/file/stdin → notes |
| `ingest-pile <dir>` | Batch ingest |
| `query "<q>"` | Vault search with citations (FTS + wikilink expansion, `--domain`, `--semantic`) |
| `note [title]` | Stdin → permanent note |
| `research "<q>"` | Research brief in inbox |
| `lint [--pii]` | Vault health |
| `moc` | Build/repair domain Index.md + backlinks |
| `hotcache` | Rebuild Wiki-Cache.md |
| `open <id>` | Open note in system editor |

## Memory engine (facts)

| Command | Description |
|---------|-------------|
| `remember "<fact>"` | Store durable fact (`--domain`, `--importance`, `--source`) |
| `recall "<q>"` | Fact search (`--type fact\|episodic`, `--since`/`--until` episodic-only) |
| `forget --confirm <id>` | Delete fact + vault note (requires `--confirm`) |
| `memory stats` | Engine statistics |
| `memory list` | List facts (`--domain`, `--limit`) |
| `memory project` | Materialize facts into vault |
| `memory reindex` | Rebuild facts_fts from facts, repair orphan rows |
| `extract` | Regex fact extraction from conversation text (no LLM) |
| `reinforce <id>` | Boost a fact's access count and timestamp |
| `history <id>` | Show fact version snapshots |
| `consolidate [--dry-run] --confirm ...` | Archive old, low-access facts to `facts_archive` |

**Explainable recall:** The `entropicmem_recall` plugin tool (and `MemoryEngine.recall()` / `recall_with_relevance()` / `recall_hybrid()`) returns a `why_retrieved` field on every hit — a deterministic list of reason tokens (`exact`, `fts`, `vector`, `recency`, `importance`, `triple`, `domain`, `fts` for LIKE fallback) explaining why the fact was surfaced. See [MEMORY_MODEL.md](MEMORY_MODEL.md) for the token reference.

## Episodic memory & triples

| Command | Description |
|---------|-------------|
| `episode add` | Add an episodic record |
| `episode list` | List episodes chronologically |
| `episode stats` | Episode counts |
| `triple extract` | Extract triples from facts + vault notes (rule-based) |
| `triple list` | List triples with optional filters |
| `triple stats` | Triple counts |
| `triple neighbors <entity>` | All relations touching an entity |
| `triple path <a> <b>` | Path between two entities |
| `triple inconsistencies` | Conflicting relations (same subject+predicate, different objects) |

## Index & graph

| Command | Description |
|---------|-------------|
| `index rebuild [--include-archive]` | Full rebuild: reindex every vault note + graph edges |
| `index status` | Report index freshness without touching anything |
| `graph export` | Export visual graph (json/dot/html; bodies on by default, `--no-bodies` for lean shell) |
| `graph serve` | HTTP serve export dir (defaults `--bind 127.0.0.1`) |
| `graph show <target>` | Show connected notes for a target |

## Vectors, timeline, security

| Command | Description |
|---------|-------------|
| `embed [--rebuild]` | Manage vector embeddings (run under the embedder venv) |
| `timeline [--from --to --domain --limit]` | Facts chronologically |
| `security enable\|disable\|status` | Offline encryption at rest (whole-file Fernet; not for live Hermes path) |
| `patch-core` | Surgically update Core Memory (Persona/User Profile) |
| `export` / `import` | Memory capsule (tar.gz: memory.db + optional vault + manifest) |
| `audit [--limit N]` | Recent security audit log |
| `pending list\|promote <id>\|discard <id>` | Manage quarantined auto-extract facts |

Env: `ENTROPICMEM_VAULT_PATH`, `ENTROPICMEM_INDEX_DB`, `ENTROPICMEM_MEMORY_DB`
(defaults resolve under `$HERMES_HOME/entropicmem/`).

## Recall Benchmark (P1 D2)

A frozen benchmark suite validates recall quality in CI:

- **Corpus:** `benchmarks/corpus.jsonl` — 98 facts across Knowledge, Infrastructure, Acme Corp, Workflows, Finance, Content-Growth, Projects domains
- **Probes:** `benchmarks/probes.json` — 20 queries with expected substrings
- **Runner:** `benchmarks/run_recall_bench.py` — runs `recall_with_relevance()` against the corpus, computes `precision@5` and Mean Reciprocal Rank (MRR)
- **Output:** `benchmarks/last_run.json` — machine-readable metrics for CI
- **CI floor:** `precision@5 >= 0.50`, `MRR >= 0.50` (pinned from first run: 0.98 / 0.975)

Run locally:

```bash
PYTHONPATH="skills/entropicmem/scripts" python3 benchmarks/run_recall_bench.py
```

Tests: `tests/test_recall_bench.py` (7 tests — runner exit code, metric validity, CI floor).
