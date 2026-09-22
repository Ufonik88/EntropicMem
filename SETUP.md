# EntropicMem: First-Run Setup

> Agent-facing bootstrap checklist for `/learn` or catalog install. The engine lives under `~/.hermes/plugins/entropicmem/scripts/`; the skill `skills/entropicmem/` holds instructions, references, and the seed vault templates.

---

## 1. Resolve Vault Path

Order of precedence:

1. `ENTROPICMEM_VAULT_PATH` env var (explicit override)
2. `OBSIDIAN_VAULT_PATH` env var (CLI human-wiki tools only; the plugin never reads this)
3. `~/Documents/Obsidian Vault` when `AGENTS.md` exists there
4. Default: `~/.hermes/entropicmem/vault`

---

## 2. Environment Variables

`init` writes the canonical block to `~/.hermes/.env` automatically (idempotent, it skips when any `ENTROPICMEM_*` key already exists). Manual creation is only needed if init's append is unavailable:

```bash
cat >> ~/.hermes/.env <<ENVENTRY
# EntropicMem: added by bootstrap
ENTROPICMEM_VAULT_PATH="${HOME}/.hermes/entropicmem/vault"
ENTROPICMEM_INDEX_DB="${HOME}/.hermes/entropicmem/index.db"
ENTROPICMEM_MEMORY_DB="${HOME}/.hermes/entropicmem/memory.db"
ENVENTRY
```

> The heredoc is unquoted so `${HOME}` expands at write time. A quoted heredoc writes literal `${HOME}` strings that dotenv does not expand, breaking path resolution.

---

## 3. Bootstrap

```bash
python3 ~/.hermes/plugins/entropicmem/scripts/entropicmem.py init \
  --vault "$ENTROPICMEM_VAULT_PATH"
```

`init` seeds the vault skeleton (domains, inbox, note templates, `AGENTS.md`, `SCHEMA.md`, `index.md`, `log.md`), creates `index.db`, and appends the env block above. `memory.db` is created on first use by the memory engine.

---

## 4. Verification

```bash
python3 ~/.hermes/plugins/entropicmem/scripts/entropicmem.py lint
python3 ~/.hermes/plugins/entropicmem/scripts/entropicmem.py hotcache
python3 ~/.hermes/plugins/entropicmem/scripts/entropicmem.py memory stats
python3 ~/.hermes/plugins/entropicmem/scripts/entropicmem.py remember "install smoke test"
python3 ~/.hermes/plugins/entropicmem/scripts/entropicmem.py recall "install smoke test"
python3 ~/.hermes/plugins/entropicmem/scripts/entropicmem.py graph export --format html --max-nodes 500
ls -la export/graph.html
```

`memory stats` reports the engine state, `recall` must return the smoke-test fact.

---

## 5. Hermes Integration (optional)

```yaml
# ~/.hermes/config.yaml
memory:
  provider: entropicmem
```

This enables the 7 `entropicmem_*` tools, the 5 lifecycle hooks, and prefetch injection. Configuration keys: [README.md](README.md). Full guide: [skills/entropicmem/references/HERMES_INTEGRATION.md](skills/entropicmem/references/HERMES_INTEGRATION.md). Install, verification, and uninstall detail: [docs/SELF_INSTALL.md](docs/SELF_INSTALL.md).

---

## 6. Optional Dependencies

```bash
python3 ~/.hermes/plugins/entropicmem/scripts/entropicmem.py --check-deps
```

| Feature | Package |
|---------|---------|
| Semantic re-rank | `sentence-transformers` |
| DOT export | `graphviz` |
| Graph server (`graph serve`) | `fastapi`, `uvicorn` |
