# CLI Reference

> Canonical reference: [`docs/CLI_REFERENCE.md`](../../../docs/CLI_REFERENCE.md)
> in the repo root. That file is kept in sync with the argparse surface.

Quick orientation (most-used commands):

| Command | Purpose |
|---------|---------|
| `query "<q>"` | Cited vault retrieval (hot cache → FTS5 → wikilinks) |
| `recall "<q>"` | Memory engine fact search (`--type fact\|episodic`) |
| `remember "fact"` | Durable fact → memory.db + vault |
| `forget --confirm <id>` | Delete fact + vault note (requires `--confirm`) |
| `episode add/list/stats` | Episodic memory |
| `triple extract/list/neighbors/path` | Knowledge triples |
| `embed --rebuild` | Rebuild fact embeddings (run under the embedder venv) |
| `graph export --format html` | Visual graph (bodies on by default) |
| `memory reindex` | Rebuild facts_fts, repair orphans |
| `index rebuild/status` | Vault index maintenance |

Env: `ENTROPICMEM_VAULT_PATH`, `ENTROPICMEM_INDEX_DB`, `ENTROPICMEM_MEMORY_DB`
(defaults resolve under `$HERMES_HOME/entropicmem/`).
