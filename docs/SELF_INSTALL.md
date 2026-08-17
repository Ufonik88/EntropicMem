# Self-Install (`/learn`)

The `/learn` flow installs EntropicMem from this repository into a running
Hermes Agent.

1. User: `/learn https://github.com/Ufonik88/EntropicMem`
2. Agent loads skill `entropicmem` (`SKILL.md`) and follows `SETUP.md`
3. `entropicmem init` — creates `~/.hermes/entropicmem/` (vault, `memory.db`,
   `index.db`) and appends the `ENTROPICMEM_*` env block to `~/.hermes/.env`
4. Smoke test: `lint`, `remember "install smoke test"`, `recall install`,
   `graph export --format html`

Dry-run acceptance is recorded when steps 3–4 succeed on a clean temp vault
(`init --dry-run` previews without writing).

> The skill and plugin directories in a live install are usually symlinked
> to this repo, so code updates take effect without reinstalling. After any
> change to `scripts/graph_server/server.py`, restart the graph server unit.
