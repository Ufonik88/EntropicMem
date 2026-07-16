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
| `note [title]` | Stdin → permanent note |
| `research "<q>"` | Research brief in inbox |
| `lint` | Vault health |
| `moc` | Domain indexes |
| `hotcache` | Rebuild Wiki-Cache |
| `graph export` | json/dot/html/canvas |
| `graph serve` | HTTP serve export dir |
| `open <id>` | Open note in editor |

Env: `ENTROPICMEM_VAULT_PATH`, `ENTROPICMEM_INDEX_DB`, `ENTROPICMEM_MEMORY_DB`
