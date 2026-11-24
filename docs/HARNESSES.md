# EntropicMem across agent harnesses

EntropicMem ships **one MCP stdio server** — the `entropicmem-mcp` console
script — that exposes the provider's nine `entropicmem_*` tools to any
MCP-capable harness. Nothing harness-specific ships with it: the server is
standard-library only, makes no network call, and every harness below
connects to the same process the OpenBot bridge uses.
[docs/OPENBOT.md](OPENBOT.md) covers that bridge in depth (protocol era,
paths, safety behaviour, the marketplace listing); this page is the map for
everything else you might run.

**How this map was made (2026-11-24):** every harness's config format below
was checked against that harness's own current documentation on that date,
and both launch forms the fragments name — the installed `entropicmem-mcp`
command and the checkout `python3 -m em.mcp_server` form — were smoke-started
on this box and answered `initialize` + `tools/list` with the nine tools.
The per-harness sessions themselves (asking Claude Code or Codex to call a
tool from inside a real project) were not run here; the server's MCP
behaviour is pinned end to end by
[tests/test_mcp_server.py](../tests/test_mcp_server.py), which drives the
real subprocess through the handshake, the tool listing and a
remember/search round trip — and [tests/test_harness_snippets.py](../tests/test_harness_snippets.py)
keeps this page and its fragments honest against that server.

## The matrix

| Harness | Mechanism | Status |
|---|---|---|
| Hermes Agent | native memory provider (catalog or pip entry point) | yes — native, see the [README's install section](../README.md#install) |
| OpenBot | custom MCP server; marketplace listing prepared | yes — native bridge, [docs/OPENBOT.md](OPENBOT.md) |
| Claude Code | project `.mcp.json` / `claude mcp add` | yes — [config](#claude-code) |
| Codex (CLI, IDE, ChatGPT desktop) | `[mcp_servers]` in `config.toml` / `codex mcp add` | yes — [config](#codex) |
| OpenCode | `mcp.servers` in `opencode.json` / `opencode mcp add` | yes — [config](#opencode) |
| Gemini CLI | `mcpServers` in `settings.json` / `gemini mcp add` | yes — [config](#gemini-cli) |
| Cursor | `.cursor/mcp.json` or `~/.cursor/mcp.json` | yes — [config](#cursor) |
| VS Code (Copilot) | portable `.mcp.json` / `~/.copilot/mcp-config.json` | yes — [config](#vs-code-copilot) |
| grok CLI (Grok Build) | `[mcp_servers]` in `~/.grok/config.toml` / `grok mcp add` | yes — [config](#grok-cli) |
| OpenClaw | `mcp.servers` config / `openclaw mcp add` | yes — [config](#openclaw) |
| MausBot and OpenMausBot | Plugins → MCP servers (paste an `mcpServers` block) | yes — [config](#mausbot-and-openmausbot) |
| OpenAI dots | ChatGPT plugin system — remote Streamable HTTP only | partial, by delegation — [the dots note](#openai-dots) |
| Any other MCP client | the generic `mcpServers` block | yes — [config](#any-other-mcp-client) |

## One-time setup

The server comes with the package:

```bash
pipx install entropicmem        # or: python3 -m pip install entropicmem
```

From a source checkout, without installing:

```bash
PYTHONPATH=/path/to/EntropicMem/plugins/entropicmem/scripts \
  python3 -m em.mcp_server --home ~/.entropicmem
```

Every fragment below names the installed `entropicmem-mcp` command. To use a
checkout instead, swap in the second form wherever a fragment names a command:
make the command `python3`, the arguments `["-m", "em.mcp_server"]`, and add
the `PYTHONPATH` above to that fragment's environment fields (Claude Code and
the `mcpServers` shapes call it `env`, Codex and the grok CLI call it `env`,
OpenCode calls it `environment`, Gemini CLI calls it `env`).

### Where the memory lives

| Setting | Default | Meaning |
|---|---|---|
| `--home`, `ENTROPICMEM_HOME` | `~/.entropicmem` | Directory holding `memory.db`, `vault/` and `index.db` |
| `--memory-db` / `--vault` / `--index-db` | inside `--home` | Per-path overrides |
| `ENTROPICMEM_MCP_LOG_LEVEL` | `WARNING` | stderr log level |

A new home is created as a v3 store, so all nine tools work from the first
call; an existing store is served exactly as it is, and a v2 store is never
migrated automatically. To point a harness at the store Hermes already uses,
pass `--home ~/.hermes/entropicmem` — and stop the Hermes gateway first:
**one process per store**. SQLite WAL tolerates readers, but two writers on
one file is not a supported setup. Full detail in
[docs/OPENBOT.md](OPENBOT.md#paths-and-configuration).

### The thirty-second smoke test

Before wiring any harness, prove the command works in a shell — the same
check [docs/OPENBOT.md](OPENBOT.md#health-check) uses:

```bash
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  | entropicmem-mcp --home /tmp/entropicmem-smoke
```

Nine tools come back. A log line on stderr is fine; stdout must stay JSON.

### Protocol

The server speaks the `initialize`/`notifications/initialized` handshake era
of MCP and names **2025-11-25** as its newest revision; a client offering
only a newer revision gets `2025-11-25` back and decides whether to continue
(the protocol's own negotiation rule — full detail in
[docs/OPENBOT.md](OPENBOT.md#protocol-and-transport)). Every harness in the
matrix defaults to that era today. A client that *requires* the
`2026-07-28` revision (`server/discover`, no handshake) will not connect;
none of the harnesses below requires it by default, and OpenCode documents a
per-server `protocol` field whose default (`legacy`) is exactly this era —
leave it unset.

## Claude Code

Project scope, shared with the repo: save
[claude-code.mcp.json](../integrations/harnesses/claude-code.mcp.json) as
`.mcp.json` in the project root and approve the server on first use. User
scope, without a file:

```bash
claude mcp add --transport stdio entropicmem -- entropicmem-mcp
```

Verify with `/mcp` inside a session. Claude Code reads the server's
`instructions` field as guidance for its tools.
Sources: Claude Code MCP docs (code.claude.com/docs/en/mcp-quickstart),
checked 2026-11-24.

## Codex

Merge [codex.config.toml](../integrations/harnesses/codex.config.toml) into
`~/.codex/config.toml`, or into a trusted project's `.codex/config.toml`:

```toml
[mcp_servers.entropicmem]
command = "entropicmem-mcp"
args = []
```

Or: `codex mcp add entropicmem -- entropicmem-mcp`. The same config serves
the Codex CLI, the IDE extension and the ChatGPT desktop app. Verify with
`/mcp` in the TUI. Codex reads the server's `instructions` field as
server-wide guidance.
Sources: OpenAI's Codex MCP docs (developers.openai.com/codex/mcp), checked
2026-11-24.

## OpenCode

Merge [opencode.json](../integrations/harnesses/opencode.json) into your
`opencode.json` / `opencode.jsonc`:

```jsonc
{
  "mcp": {
    "servers": {
      "entropicmem": {
        "type": "local",
        "command": ["entropicmem-mcp"]
      }
    }
  }
}
```

Or: `opencode mcp add entropicmem -- entropicmem-mcp` (add `--global` for
every project). OpenCode's default `protocol` is `legacy` — the classic
initialize handshake this server speaks — so no per-server override is
needed. Verify with `opencode mcp list` or `/mcps`.
Sources: opencode.ai/docs/mcp-servers, checked 2026-11-24.

## Gemini CLI

Merge the `mcpServers` block from
[generic.mcp.json](../integrations/harnesses/generic.mcp.json) into
`~/.gemini/settings.json` (user scope) or `.gemini/settings.json` (project
scope):

```json
{
  "mcpServers": {
    "entropicmem": {
      "command": "entropicmem-mcp",
      "args": []
    }
  }
}
```

Or: `gemini mcp add entropicmem entropicmem-mcp` (the default scope is
project; add `-s user` for every project). Keep the server alias free of
underscores — Gemini's policy engine parses tool names as
`mcp_<alias>_<tool>` by the first underscore, so `entropicmem` is right.
Verify with `/mcp` in a session or `gemini mcp list`.
Sources: Gemini CLI configuration reference
(geminicli.com/docs/reference/configuration) and MCP docs, checked
2026-11-24.

## Cursor

Save [generic.mcp.json](../integrations/harnesses/generic.mcp.json) as
`.cursor/mcp.json` in the project (commit it to share with the team) or
`~/.cursor/mcp.json` for every project. Verify in the Customize panel's MCP
list. Sources: cursor.com MCP docs (cursor.com/docs/mcp), checked
2026-11-24.

## VS Code (Copilot)

The native Copilot destinations use the portable `mcpServers` shape: save
[claude-code.mcp.json](../integrations/harnesses/claude-code.mcp.json) as
`.mcp.json` at the workspace root (shared with the workspace) or into
`~/.copilot/mcp-config.json` (every workspace — Copilot Global). The older
`.vscode/mcp.json` / profile `mcp.json` files (top-level `servers` key) are
the deprecated Local harness's destinations. Verify with **MCP: List
Servers**. Sources: VS Code MCP configuration reference
(code.visualstudio.com/docs/agents/reference/mcp-configuration), checked
2026-11-24.

## grok CLI

Merge [grok.config.toml](../integrations/harnesses/grok.config.toml) into
`~/.grok/config.toml`, or into `.grok/config.toml` in the repo (project
scope, via `grok mcp add --scope project`):

```toml
[mcp_servers.entropicmem]
command = "entropicmem-mcp"
args = []
```

Or: `grok mcp add entropicmem -- entropicmem-mcp`. Verify with
`grok mcp doctor entropicmem`. Tools arrive namespaced
`entropicmem__<tool>`. A cold-start that outruns the default 30-second
startup timeout can raise `startup_timeout_sec`; this server starts
instantly, so the default is fine. The grok CLI also reads Claude Code's
and Cursor's MCP config if you have it there.
Sources: xAI's grok CLI MCP docs (docs.x.ai/build/features/mcp-servers),
checked 2026-11-24.

## OpenClaw

Merge [openclaw.config.json](../integrations/harnesses/openclaw.config.json)
into the OpenClaw config file's `mcp.servers` block, or use the CLI:

```bash
openclaw mcp add entropicmem --command entropicmem-mcp
openclaw mcp doctor entropicmem --probe
```

The Control UI's Settings → MCP page writes the same entry. Sources:
OpenClaw MCP docs (docs.openclaw.ai/tools/mcp), checked 2026-11-24.

## MausBot and OpenMausBot

Open **Plugins → MCP servers → Add server** and paste the contents of
[generic.mcp.json](../integrations/harnesses/generic.mcp.json) into the paste
box — MausBot accepts an `mcpServers` JSON block as-is, works out the name,
command and environment, and asks only for what the paste left out. Press
**Test**: it starts the command, completes the MCP handshake and lists the
tools; the server is turned on when it answers. Command (stdio) servers
reach every engine MausBot runs (Claude Code, Codex, ACP and API-model
bots). Sources: OpenMausBot's custom MCP servers doc
(docs/custom-mcp-servers.md), checked 2026-11-24.

## OpenAI dots

A dot cannot start a local stdio server. Dots reach tools through ChatGPT's
plugin system, which connects **remote** MCP servers over Streamable HTTP —
and EntropicMem's server is deliberately stdio and local-only, with no
network call. The working path today is delegation: a dot creates and
steers Codex tasks, and those tasks read the Codex `[mcp_servers]` config —
put the [Codex config](#codex) on the machine or cloud environment the dot
delegates to, and the delegated tasks get the memory tools. OpenAI's own
tracker records the gap between what a dot-created task and a local Codex
session can reach (openai/codex issue #55568, opened 2026-10-20); nothing in
this repo can close it. Status: **partial, by delegation** — not verified
from inside a dot on this box.

## Any other MCP client

Save [generic.mcp.json](../integrations/harnesses/generic.mcp.json) wherever
your client keeps its `mcpServers` block — the shape Claude Code, Cursor,
MausBot and VS Code's portable format all use. The server is a plain
JSON-RPC-over-stdio process: any client that speaks the initialize era and
can launch a local command can use it.

## The nine tools

The same surface as the Hermes provider — the full behaviour table,
including the safety rules, is [docs/OPENBOT.md](OPENBOT.md#2-the-tools)'s.

| Tool | What it does |
|---|---|
| `entropicmem_remember` | Save a durable fact, preference, profile entry, procedure, event, constraint or note. |
| `entropicmem_search` | Search memories, past episodes, vault notes and shared facts by query or by ids; every hit carries `why`. |
| `entropicmem_update` | Correct a memory; `supersede` (default) keeps history, `edit` fixes wording in place. |
| `entropicmem_forget` | Forget by id (recoverable), or preview matches by query and confirm with the returned token. |
| `entropicmem_timeline` | Episodes in a time window, optionally matched against a query. |
| `entropicmem_entity` | Everything known about a person, project, organisation, product or place. |
| `entropicmem_profile` | Read Core Memory (persona and user profile); patching is off unless explicitly enabled. |
| `entropicmem_review` | List, promote, discard or restore pending memory; report recall feedback; preview consolidation. |
| `entropicmem_stats` | Counts, domains, store path, pending work and recall health. |

## Shared notes

- **One writer per store.** The server starts a background job worker on a
  v3 store; it stops on EOF or `Ctrl-C`. Two processes writing one store
  (an OpenBot session and a Hermes gateway, say) is not a supported setup —
  point each at its own `--home`, or stop one first.
- **No secrets in any config.** The server needs no token: it reads only
  local files, so no fragment here carries one. Do not paste credentials
  into the memory tools either — the write policy refuses detected
  credentials rather than storing them ([docs/OPENBOT.md](OPENBOT.md#2-the-tools)).
- **Tool naming per harness.** Gemini prefixes `mcp_`, the grok CLI
  namespaces `<server>__<tool>`, OpenCode normalizes to
  `<server>_<tool>`; the underlying names are the nine above.
- **What the server does not expose.** Graph export, ingest and admin
  commands stay on the engine CLI; the MCP surface is the nine memory tools
  ([docs/OPENBOT.md](OPENBOT.md#5-limits-worth-knowing)).
