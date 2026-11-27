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

Install the command before connecting — the wheel attached to the release:

```bash
pipx install https://github.com/Ufonik88/EntropicMem/releases/download/v3.0.3/entropicmem-3.0.3-py3-none-any.whl
# or: python3 -m pip install --user https://github.com/Ufonik88/EntropicMem/releases/download/v3.0.3/entropicmem-3.0.3-py3-none-any.whl
```

The package is not on PyPI, so `pipx install entropicmem` does not work yet.
`.github/workflows/release.yml` builds the wheel and the sdist and attaches both
to the published release, which is what makes the URL above stable.

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

1. Publish a release of this repo that contains `em/mcp_server.py`; its
   release workflow attaches the wheel, so the listing's install line gives
   users the `entropicmem-mcp` command. The icon URL and the install URL both
   name that tag, so the tag has to exist before the catalog PR.
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
| `version` | `3.0.3` | The release the listing's claims are true at; a re-pin moves it with the tag. |
| `skills` | `[]` | Marketplace rules keep this empty until pinned skill versions exist. |
| `privacyPolicyUrl` / `termsUrl` | `null` | The project has no separate policy pages; the repo and MIT licence are the source. Do not invent URLs. |

Both `iconUrl` fields point at the repo's committed PNG through the release
tag (`/v3.0.3/docs/assets/logo.png`), not `main`: a `main` URL moves under the
review and the icon would change without a commit. `tests/test_mcp_server.py`
fails if either URL goes back to `main` or stops naming the packaged version.
