# EntropicMem — First-Run Setup

> Agent-facing bootstrap checklist for `/learn` install.

---

## 1. Resolve Vault Path

Order of precedence:

1. `ENTROPICMEM_VAULT_PATH` env var (explicit override)
2. `OBSIDIAN_VAULT_PATH` env var (CLI human-wiki tools only; the plugin
   never reads this)
3. `~/Documents/Obsidian Vault` when `AGENTS.md` exists there
4. Default: `${HOME}/.hermes/entropicmem/vault`

---

## 2. Environment Variables

`entropicmem init` writes the canonical block to `~/.hermes/.env`
automatically (idempotent — it skips when any `ENTROPICMEM_*` key already
exists). Manual creation is only needed if init's append is unavailable:

```bash
cat >> ~/.hermes/.env <<ENVENTRY
# EntropicMem — added by bootstrap
ENTROPICMEM_VAULT_PATH="${HOME}/.hermes/entropicmem/vault"
ENTROPICMEM_INDEX_DB="${HOME}/.hermes/entropicmem/index.db"
ENTROPICMEM_MEMORY_DB="${HOME}/.hermes/entropicmem/memory.db"
ENVENTRY
```

> Note the heredoc is unquoted: `${HOME}` must be expanded at write time.
> A quoted heredoc writes literal `${HOME}` strings that dotenv does not
> expand, breaking path resolution.

---

## 3. Bootstrap

```bash
python3 ~/.hermes/skills/entropicmem/scripts/entropicmem.py init \
  --vault "$ENTROPICMEM_VAULT_PATH"
```

`init` creates the vault skeleton, initializes `index.db`, and appends the env block above. The `memory.db` is created on first use by the memory engine.

---

## 4. Smoke Test

```bash
entropicmem lint
entropicmem hotcache
entropicmem graph export --format html --max-nodes 500
ls -la export/graph.html
```

---

## 5. Optional Dependencies

```bash
entropicmem --check-deps
```

| Feature | Package |
|---------|---------|
| Semantic re-rank | `sentence-transformers` |
| DOT export | `graphviz` |
