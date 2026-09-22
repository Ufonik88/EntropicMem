# Self-Install

EntropicMem installs two ways: from the Hermes plugin catalog, or through the `/learn` skill flow. Both end at the same state: plugin registered, engine under `~/.hermes/plugins/entropicmem/scripts/`, vault bootstrapped, provider wired.

## Option A: plugin catalog

```bash
hermes plugins install entropicmem
```

This installs `plugins/entropicmem/` (MemoryProvider + engine + CLI) under `~/.hermes/plugins/entropicmem/`. The catalog admission gate is `hermes plugins validate --install-deps plugins/entropicmem`, which CI runs on every change.

## Option B: `/learn` skill flow

1. User: `/learn https://github.com/Ufonik88/EntropicMem`
2. Agent loads skill `entropicmem` (`skills/entropicmem/SKILL.md`) and follows `skills/entropicmem/SETUP.md`
3. The plugin directory is linked or copied to `~/.hermes/plugins/entropicmem`, and the skill to the Hermes skills directory

## Plugin configuration

Optional settings live under `plugins.entropicmem` in `~/.hermes/config.yaml` (paths, smart-context tuning, lifecycle keys). Full key table: [../README.md](../README.md). The provider reads `vault_path`, `index_db`, `memory_db`; everything else falls back to defaults from the config schema in `plugins/entropicmem/__init__.py`.

## Bootstrap: `entropicmem init`

```bash
python3 ~/.hermes/plugins/entropicmem/scripts/entropicmem.py init
```

Creates `~/.hermes/entropicmem/` with the vault skeleton and `index.db`, and appends the `ENTROPICMEM_*` env block to `~/.hermes/.env` (idempotent). `memory.db` is created on first use. `init --dry-run` previews without writing. Detail: [../SETUP.md](../SETUP.md).

## Verification

```bash
python3 ~/.hermes/plugins/entropicmem/scripts/entropicmem.py memory stats   # engine up, shows counts + DB path
python3 ~/.hermes/plugins/entropicmem/scripts/entropicmem.py remember "install smoke test"
python3 ~/.hermes/plugins/entropicmem/scripts/entropicmem.py recall "install smoke test"   # must return the fact
python3 ~/.hermes/plugins/entropicmem/scripts/entropicmem.py lint           # vault health
```

With the provider wired, also check `entropicmem_stats` from an interactive Hermes session.

## Hermes memory.provider wiring

```yaml
# ~/.hermes/config.yaml
memory:
  provider: entropicmem
```

This activates the 7 `entropicmem_*` tools, the 5 lifecycle hooks, and `<memory-context>` prefetch injection. Contract and rules: [../skills/entropicmem/references/HERMES_INTEGRATION.md](../skills/entropicmem/references/HERMES_INTEGRATION.md).

## Uninstall / disable

```bash
hermes plugins disable entropicmem     # keep files, stop loading
hermes plugins remove entropicmem      # remove the plugin (alias: uninstall)
```

Then:

1. Remove `memory.provider: entropicmem` (or the whole `memory:` block) from `~/.hermes/config.yaml`, otherwise Hermes has no memory provider.
2. Optionally delete the data directory `~/.hermes/entropicmem/` (vault, `memory.db`, `index.db`, backups). Export first with `python3 ~/.hermes/plugins/entropicmem/scripts/entropicmem.py export capsule.tar.gz` if you want a portable copy.
3. Remove the `ENTROPICMEM_*` block from `~/.hermes/.env` if present.

Re-enabling: `hermes plugins enable entropicmem`, restore the `memory.provider` line, done (data was never touched).
