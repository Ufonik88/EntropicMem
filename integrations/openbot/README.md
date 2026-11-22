# OpenBot plugin listing

This directory is the submission bundle for the OpenBot Marketplace (Plugins
tab). It is not installed by OpenBot from this repo; it is the source shape that
gets copied into OpenBot's plugin catalog.

## What the listing starts

`plugin.json` declares one stdio MCP server named `entropicmem`:

```json
"command": "entropicmem-mcp",
"args": []
```

That console script is installed by the `entropicmem` Python package and starts
`em.mcp_server`, the local MCP bridge. It needs no key, no account and no
network call. The default home is `~/.entropicmem`; the first connection creates
a v3 store there (`memory.db`, `vault/`, `index.db`). An existing v2 store is
served without being migrated — that cutover stays explicit.

Install the command before connecting:

```bash
pipx install entropicmem
# or: python3 -m pip install --user entropicmem
```

From a source checkout, without installing:

```bash
PYTHONPATH=plugins/entropicmem/scripts python3 -m em.mcp_server --home ~/.entropicmem
```

`pip install` is the prerequisite, the same way the Paper listing needs Paper
Desktop installed. It is not something the marketplace installs for the user.

## Submitting to the OpenBot marketplace

Prepared here; **not submitted**. The upstream repository is
`nightly-labs/openbot`, and the catalog lives at
`marketplace/plugin-catalog/`.

1. Publish a release of this repo that contains `em/mcp_server.py`, so
   `pipx install entropicmem` gives users the `entropicmem-mcp` command.
2. Copy this bundle to
   `marketplace/plugin-catalog/plugins/entropicmem/plugin.json` in a fresh
   checkout of `nightly-labs/openbot`.
3. Add `"entropicmem"` to `marketplace/plugin-catalog/catalog.json` (`order`,
   and `featured` only if the catalog maintainers choose it).
4. Run `bun run marketplace:build:plugins` and commit the generated files with
   the source entry.
5. Open the pull request. The marketplace review checks the server shape, the
   absence of secret values, the name (`entropicmem` is not reserved), and the
   listing's claims against the code at the pinned release.

No secret value belongs in this directory. There are no `auth` fields because
the server reads only local files.

## Listing fields worth knowing

| Field | Value here | Why |
|---|---|---|
| `slug` / server `name` | `entropicmem` | Lowercase, matches the package and tool prefix. |
| `category` | `productivity` | The marketplace's closest category for agent memory. |
| `version` | `0.1.0` | The listing's own version, bumped when the listing changes. |
| `skills` | `[]` | Marketplace rules keep this empty until pinned skill versions exist. |
| `privacyPolicyUrl` / `termsUrl` | `null` | The project has no separate policy pages; the repo and MIT licence are the source. Do not invent URLs. |

The logo URL points at the repo's committed PNG on `main`. A marketplace entry
should pin an immutable URL if the catalog requires one.
