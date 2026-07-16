# Hermes Integration

## Install
```
/learn https://github.com/Ufonik88/EntropicMem
```

## Agent workflow
1. `skill_view(name='entropicmem')`
2. Follow `SETUP.md`: `entropicmem init`
3. Use `terminal` to run CLI commands

## Write path
Promote durable conclusions with `remember`. Capture sources with `ingest`. Do not store secrets.

## Read path
`query` for linked knowledge; `recall` for stored facts; `hotcache` for orientation.

## Maintenance
End heavy knowledge sessions with `lint` and optional `hotcache`.

## Phase 6 — MemoryProvider (optional)

Deep Hermes integration via `plugins/entropicmem/`:

```bash
ln -sf /path/to/EntropicMem/plugins/entropicmem ~/.hermes/plugins/entropicmem
```

`~/.hermes/config.yaml`:

```yaml
memory:
  provider: entropicmem
```

Tools: `entropicmem_remember`, `entropicmem_recall`, `entropicmem_query`.  
Built-in `memory` tool writes are mirrored into the memory engine.  
See `plugins/entropicmem/README.md`.
