# EntropicMem on OpenBot

EntropicMem runs as a **local MCP server** inside OpenBot. The server speaks the
MCP stdio transport, reuses the same nine tools as the Hermes provider, and
stores everything under a directory you choose. It adds no network call.

This page covers three things:

1. connecting it to OpenBot today as a custom MCP server;
2. what each tool does;
3. how the marketplace listing is prepared and what still has to happen before
   it can be submitted upstream.

## 1. Connect to OpenBot

### Install the command

The MCP entry point is the `entropicmem-mcp` console script:

```bash
pipx install https://github.com/Ufonik88/EntropicMem/releases/download/v3.0.3/entropicmem-3.0.3-py3-none-any.whl
# or, with git on the machine:
pipx install "git+https://github.com/Ufonik88/EntropicMem@v3.0.3"
# or, in a project venv:
python3 -m pip install https://github.com/Ufonik88/EntropicMem/releases/download/v3.0.3/entropicmem-3.0.3-py3-none-any.whl
```

The wheel is attached to the release by `.github/workflows/release.yml`; the
package is not on PyPI, so the release URL is the install line. To work from a
checkout instead:

```bash
pipx install --force /path/to/EntropicMem
```

No extra is needed. The base package is standard-library only.

From a source checkout, without installing:

```bash
PYTHONPATH=/path/to/EntropicMem/plugins/entropicmem/scripts \
  python3 -m em.mcp_server --home ~/.entropicmem
```

### Add it as a custom MCP server

In OpenBot: **Settings → MCP servers → Connect to a custom MCP**.

| Field | Value |
|---|---|
| Name | `entropicmem` |
| Transport | stdio |
| Command | `entropicmem-mcp` (or the absolute path in the venv) |
| Arguments | none |
| Environment | optional, see below |

The server writes nothing to stdout except protocol messages; logs go to
stderr. If the command is not found, the install step above was not on the
`PATH` OpenBot uses — use the absolute path.

### Protocol and transport

The server speaks the `initialize`/`notifications/initialized` handshake era of
MCP and names **2025-11-25** as its newest revision (`2025-06-18`,
`2025-03-26` and `2024-11-05` are also accepted). A client that offers only a
newer revision is answered with `2025-11-25` and decides whether to continue,
which is the protocol's own negotiation rule. The `2026-07-28` revision is
deliberately not claimed: it removed the handshake, `ping`, `logging/setLevel`
and the unversioned result shape in favour of `server/discover`, and this server
does not implement that contract.

stdin and stdout are forced to UTF-8 whatever the host locale is, so a non-ASCII
memory and a non-ASCII request work on a Windows code page or a C-locale POSIX
box. One JSON-RPC object per line; nothing else is written.

### Paths and configuration

| Setting | Default | Meaning |
|---|---|---|
| `--home`, `ENTROPICMEM_HOME` | `~/.entropicmem` | The directory holding `memory.db`, `vault/` and `index.db`. |
| `--memory-db` | `<home>/memory.db` | SQLite store. |
| `--vault` | `<home>/vault` | Markdown vault. |
| `--index-db` | `<home>/index.db` | Vault full-text index. |
| `ENTROPICMEM_MCP_LOG_LEVEL` | `WARNING` | stderr log level. |

The engine's existing `ENTROPICMEM_MEMORY_DB`, `ENTROPICMEM_VAULT_PATH` and
`ENTROPICMEM_INDEX_DB` variables still work. Optional typed config lives in
`<home>/config.json` (JSON, not YAML, so the server stays stdlib-only). A broken
file is ignored with a warning; each bad value keeps its default.

A **new** home is created as a v3 store, so all nine tools work from the first
call. An **existing** store is served exactly as it is. A v2 store is never
migrated automatically: that cutover stays an explicit act.

To point OpenBot at an existing Hermes store, use its directory:

```bash
entropicmem-mcp --home ~/.hermes/entropicmem
```

Stop the Hermes gateway first if both processes would write the same store.

### Health check

```bash
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  | entropicmem-mcp --home /tmp/entropicmem-smoke
```

The second line lists nine tools. A log line on stderr is fine; stdout must stay
JSON.

## 2. The tools

The server exposes the provider's v3 surface unchanged. Names keep the
`entropicmem_` prefix so a prompt written for Hermes keeps working.

| Tool | What it does |
|---|---|
| `entropicmem_remember` | Save a durable fact, preference, profile entry, procedure, event, constraint or note. Applies the write policy and PII handling. |
| `entropicmem_search` | Search memories, past episodes, vault notes and shared facts by query or by ids. Every hit carries `why`. |
| `entropicmem_update` | Correct a memory. `supersede` (default) keeps history; `edit` fixes wording in place. |
| `entropicmem_forget` | Forget by id (recoverable), or preview matches by query and confirm with the returned token. |
| `entropicmem_timeline` | Episodes in a time window, optionally matched against a query. |
| `entropicmem_entity` | Everything known about a person, project, organisation, product or place. |
| `entropicmem_profile` | Read Core Memory (persona and user profile). Patching is off unless `core.writable_by_agent` is enabled. |
| `entropicmem_review` | List, promote, discard or restore pending memory; report recall feedback; preview consolidation. |
| `entropicmem_stats` | Counts, domains, store path, pending work and recall health. |

Safety behaviour is the engine's, not a new layer:

- a memory over the content ceiling is refused, never silently truncated;
- a detected credential is **refused, never stored**: the write policy's gate
  catches `=`/`:` assignments, natural phrasing ("my password is …") and raw
  AWS access key ids (`AKIA`/`ASIA` plus 16 characters), and answers with its
  secrets-manager reason. Refusing is the deliberate policy for this class —
  a flagged credential would still be a plaintext credential at rest, while
  the flag-through path belongs to screened *injection* text, which is inert
  when marked;
- `entropicmem_forget` by query needs the one-time confirm token;
- profile patching is opt-in;
- only a primary agent context writes. The MCP server declares itself primary;
- `tools/list` marks the pure reads (`search`, `timeline`, `entity`, `stats`)
  read-only and `forget` destructive. `entropicmem_review` carries **no**
  read-only claim at all: its `list_pending` and `consolidate_preview`
  actions read while `promote`/`discard`/`restore`/`feedback` mutate, and the
  annotation is a static claim made before the client has chosen an action.

## 3. Marketplace listing

The prepared bundle is [`integrations/openbot/plugin.json`](../integrations/openbot/plugin.json),
with an explanation in [`integrations/openbot/README.md`](../integrations/openbot/README.md).
It follows the shape OpenBot's catalog expects: one app, a `stdio` server with
`command` and `args`, no `workingDirectory`, no secret value, and no `auth`
fields because the server reads only local files.

The listing is **not submitted**. To submit it:

1. publish a release that includes `em/mcp_server.py` and carries the wheel its
   release workflow attaches, so the listing's install line provides
   `entropicmem-mcp`;
2. copy the bundle into
   `marketplace/plugin-catalog/plugins/entropicmem/plugin.json` in
   `nightly-labs/openbot`;
3. add `entropicmem` to `marketplace/plugin-catalog/catalog.json`;
4. run `bun run marketplace:build:plugins` and commit the generated files;
5. open the pull request.

The marketplace review checks the listing against the code at the release it
names. Until the release exists, a merged listing would install a command users
do not have.

## 4. Verification

```bash
python3 -m pytest -q tests/test_mcp_server.py
ruff check plugins/entropicmem/scripts/em/mcp_server.py \
  plugins/entropicmem/scripts/em_internal/policy.py tests/test_mcp_server.py
```

The smoke tests start the real subprocess and cover `initialize`, `tools/list`,
a remember/search round trip, the JSON-RPC error paths, that an existing v2
store is not migrated, that a credential is refused however it is phrased, and
that the read-only hints match what each call does.

The server was also added to OpenBot itself as a temporary custom stdio server
(absolute console-script path, a throwaway `--home`). OpenBot's connection test
returned `ready` with all nine tools; the temporary entry was removed after the
check.

## 5. Limits worth knowing

- One process per store is the safe shape. SQLite WAL allows readers, but two
  writers (OpenBot and a Hermes gateway) on one file are not a supported setup.
- The server starts a background job worker on a v3 store. It stops on EOF or
  `Ctrl-C`.
- Embeddings are opt-in. With `embeddings.enabled` on, an embedding backend may
  download a model or call a configured endpoint; that is the only network path
  and it is not enabled by default.
- The MCP server does not expose the CLI's graph export, ingest or admin
  commands. Use the CLI for those.
