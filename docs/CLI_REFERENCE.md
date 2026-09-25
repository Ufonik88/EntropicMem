# CLI Reference

All commands: `python3 ~/.hermes/plugins/entropicmem/scripts/entropicmem.py <cmd>` (below shown without the prefix). Global flags: `--version`, `--check-deps` (print optional dependency status). Verified against the argparse definitions in `plugins/entropicmem/scripts/entropicmem.py`: 34 top-level commands.

## Vault & knowledge loop

| Command | Description |
|---------|-------------|
| `init [--vault PATH] [--index-db PATH] [--force] [--dry-run]` | Bootstrap vault + index + env vars (`--dry-run` previews, `--force` overwrites seed files with `.bak` copies) |
| `ingest [source] [--domain D]` | URL/file/stdin to notes (default domain `Knowledge`) |
| `ingest-pile <dir> [--domain D]` | Batch ingest a directory |
| `query "<q>" [--top-k N] [--semantic] [--domain D]` | Vault search with citations (FTS + wikilink expansion; `--semantic` enables re-rank) |
| `note [title] [--domain D] [--tags T]` | Stdin to permanent note |
| `research "<q>" [--rounds N]` | Research brief in inbox (default 3 rounds) |
| `lint [--domain D] [--pii]` | Vault health; `--pii` scans facts for PII |
| `moc [--domain D]` | Build/repair domain Index.md + backlinks |
| `hotcache` | Rebuild Wiki-Cache.md |
| `open <note_id>` | Open note in system editor (`Domain/Name` or `vault://Domain/Name`) |

## Memory engine (facts)

| Command | Description |
|---------|-------------|
| `remember "<fact>" [--domain D] [--tags T]` | Store durable fact (policy + PII sanitized) |
| `recall "[<q>]" [--top-k N] [--domain D] [--scope own\|shared\|all] [--type fact\|episodic] [--since YYYY-MM-DD] [--until YYYY-MM-DD] [--related ENTROPIC_ID] [--reflect]` | Fact search. `--type episodic --since/--until` gives a dated timeline; `--related` walks the triples graph; `--reflect` adds an agent reflection summary |
| `forget --confirm <entropic_id>` | Delete fact + vault note (requires `--confirm`, auto-backup first) |
| `memory stats` | Engine statistics |
| `memory list [--domain D] [--limit N]` | List facts |
| `memory project` | Materialize facts into vault notes |
| `memory reindex` | Rebuild `facts_fts` from `facts`, repair orphan rows |
| `extract [--text T] [--session-id S] [--source SRC] [--min-confidence F]` | Regex fact extraction from conversation text (no LLM; defaults to stdin, source `auto_extracted`, threshold 0.4) |
| `reinforce <entropic_id>` | Boost a fact's access count and timestamp |
| `history <entropic_id>` | Show fact version snapshots |
| `consolidate [--max-age-days N] [--min-access-count N] [--dry-run] --confirm` | Archive old, low-access facts to `facts_archive` (default 90 days; `--confirm` required to archive) |

**Explainable recall:** `recall` (and the `entropicmem_recall` plugin tool) returns a `why_retrieved` field on every hit, a deterministic list of reason tokens (`exact`, `fts`, `vector`, `recency`, `importance`, `triple`, `domain`). See [MEMORY_MODEL.md](MEMORY_MODEL.md).

## Episodic memory & triples

| Command | Description |
|---------|-------------|
| `episode add <title> <summary> [--start ISO] [--end ISO] [--session S] [--link-facts IDS] [--importance F] [--domain D] [--source SRC]` | Add an episodic record |
| `episode list [--from YYYY-MM-DD] [--to YYYY-MM-DD] [--domain D] [--limit N]` | List episodes chronologically |
| `episode stats` | Episode counts |
| `triple extract` | Extract triples from facts + vault notes (rule-based) |
| `triple list [--subject S] [--predicate P] [--object O] [--source SRC] [--limit N]` | List triples with optional filters |
| `triple stats` | Triple counts |
| `triple neighbors <entity>` | All relations touching an entity |
| `triple path <start> <end>` | Path between two entities |
| `triple inconsistencies` | Conflicting relations (same subject+predicate, different objects) |

## Index & graph

| Command | Description |
|---------|-------------|
| `index rebuild [--include-archive]` | Full or incremental rebuild: reindex vault notes + graph edges |
| `index status` | Report index freshness without touching anything |
| `graph export [--format json\|dot\|html\|canvas] [--output-dir DIR] [--max-nodes N] [--domain D] [--min-importance F] [--include-bodies\|--no-bodies]` | Export visual graph (default `html`, `./export`, 500 nodes; bodies on by default, `--no-bodies` for a lean shell) |
| `graph serve [--port 8069] [--bind 127.0.0.1] [--dir DIR]` | Serve `graph.html`/`graph.json` from DIR (non-loopback bind refused unless `ENTROPICMEM_GRAPH_EXPOSE=1`; Host allowlist + CSP; no token, see [VISUALIZER.md](VISUALIZER.md)) |
| `graph show <target> [--depth N]` | Show connected notes for a target (default depth 1) |

## Vectors, time, security

| Command | Description |
|---------|-------------|
| `embed [--rebuild]` | Manage vector embeddings (run under the embedder venv) |
| `timeline [--from YYYY-MM-DD] [--to YYYY-MM-DD] [--domain D] [--limit N]` | Facts chronologically |
| `security enable\|disable\|status` | Offline encryption at rest (whole-file Fernet; not for the live Hermes path) |
| `patch-core <persona\|user_profile> --patch "<find>" [--replacement "<text>"]` | Surgically update Core Memory (Persona / User Profile; opt-in via `core_memory_writable`) |
| `export [output]` | Memory capsule (tar.gz: memory.db + optional vault + manifest; default `capsule.tar.gz`) |
| `import <input>` | Import memory capsule |
| `audit [--limit N]` | Recent security audit log |

## Provenance & sync

| Command | Description |
|---------|-------------|
| `migrate [--schema-version N] [--phase N] [--status]` | Provenance migration (fail-closed, idempotent; `--status` reports without migrating) |
| `shared-init` | Bootstrap the shared sync store (idempotent) |
| `publish [--backfill]` | Drain the local outbox into the shared log (`--backfill` is the explicit legacy opt-in) |
| `pull` | Apply new shared events into the local `shared_facts` projection |

## Governance

| Command | Description |
|---------|-------------|
| `pending list [--limit N]` | List quarantined auto-extract facts |
| `pending promote <id>` | Promote a pending fact to durable memory |
| `pending discard <id>` | Discard a pending fact |

Env: `ENTROPICMEM_VAULT_PATH`, `ENTROPICMEM_INDEX_DB`, `ENTROPICMEM_MEMORY_DB` (defaults resolve under `$HERMES_HOME/entropicmem/`).

## Recall benchmark

A frozen benchmark suite validates recall quality in CI:

- **Corpus:** `benchmarks/corpus.jsonl`, 98 facts across the shipped domains
- **Probes:** `benchmarks/probes.json`, 20 queries with expected substrings
- **Runner:** `benchmarks/run_recall_bench.py`, runs `recall_with_relevance()` against the corpus, computes `precision@5` and Mean Reciprocal Rank (MRR)
- **Output:** `benchmarks/last_run.json`, machine-readable metrics for CI
- **CI floor:** `precision@5 >= 0.50`, `MRR >= 0.50`

Run locally:

```bash
PYTHONPATH="plugins/entropicmem/scripts" python3 benchmarks/run_recall_bench.py
```

Tests: `tests/test_recall_bench.py` (runner exit code, metric validity, CI floor).
