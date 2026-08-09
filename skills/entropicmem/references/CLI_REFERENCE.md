# CLI Reference

All commands: `python3 ~/.hermes/skills/entropicmem/scripts/entropicmem.py <cmd>`

| Command | Description |
|---------|-------------|
| `init` | Bootstrap vault, index, env vars |
| `ingest <source>` | URL/file/stdin → notes |
| `ingest-pile <dir>` | Batch ingest |
| `query "<q>"` | Vault search with citations |
| `recall "<q>"` | Memory engine fact search |
| `remember "fact"` | Fact → memory.db + vault |
| `forget <id>` | Remove from memory + vault note |
| `memory stats` | Engine statistics |
| `memory list` | List facts (`--domain`, `--limit`) |
| `memory project` | Materialize facts into vault |
| `memory reindex` | Rebuild `facts_fts` from facts; repairs orphan rows (v2.1.8) |
| `note [title]` | Stdin → permanent note |
| `research "<q>"` | Research brief in inbox |
| `lint` | Vault health |
| `moc` | Domain indexes |
| `hotcache` | Rebuild Wiki-Cache |
| `index rebuild` | Full vault index rebuild: every note + graph edges (v2.1.8) |
| `index status` | Index freshness report, no writes (v2.1.8) |
| `graph export` | json/dot/html/canvas |
| `graph serve` | HTTP serve export dir |
| `open <id>` | Open note in editor |

Env: `ENTROPICMEM_VAULT_PATH`, `ENTROPICMEM_INDEX_DB`, `ENTROPICMEM_MEMORY_DB`

Maintenance cron: `scripts/entropicmem_index_refresh.sh` (every 6h, silent when
fresh) keeps `index.db` aligned with the vault; it pins the env paths above
because stale entries in `~/.hermes/.env` can misdirect `resolve_vault_path()`.
