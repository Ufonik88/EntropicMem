# EntropicMem — First-Run Setup

> Agent-facing bootstrap checklist for `/learn` install.

---

## 1. Resolve Vault Path

Order of precedence:

```bash
# 1. Explicit override
ENTROPICMEM_VAULT_PATH="${ENTROPICMEM_VAULT_PATH:-}"

# 2. Default
DEFAULT_VAULT="${HOME}/.hermes/entropicmem/vault"
```

---

## 2. Environment Variables

```bash
cat >> ~/.hermes/.env << 'ENVENTRY'
# EntropicMem — added by bootstrap
ENTROPICMEM_VAULT_PATH="${HOME}/.hermes/entropicmem/vault"
ENTROPICMEM_INDEX_DB="${HOME}/.hermes/entropicmem/index.db"
ENTROPICMEM_MEMORY_DB="${HOME}/.hermes/entropicmem/memory.db"
ENVENTRY
```

---

## 3. Bootstrap

```bash
python3 ~/.hermes/skills/entropicmem/scripts/entropicmem.py init \
  --vault "$ENTROPICMEM_VAULT_PATH"
```

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
EOF