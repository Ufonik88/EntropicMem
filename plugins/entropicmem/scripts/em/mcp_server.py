"""EntropicMem MCP stdio server (the OpenBot bridge).

A small, standard-library-only MCP server that exposes the provider's nine
memory tools to any MCP client. It speaks JSON-RPC 2.0 over newline-delimited
stdio, which is the MCP stdio transport: stdout carries protocol messages
only, every log line goes to stderr.

Why this lives in ``em`` and not in ``plugins/entropicmem``: the provider
layer (``em.provider.provider``) is already host-free, and the plugin shell is
the one place allowed to import Hermes. The MCP server needs the same
host-free provider, so it supplies its own tiny :class:`ProviderHost` instead
of importing the Hermes package. The engine stays stdlib-only and no code path
here makes a network call.

Run it after ``pip install entropicmem``::

    entropicmem-mcp

From a source checkout::

    PYTHONPATH=plugins/entropicmem/scripts python3 -m em.mcp_server

Defaults: home ``~/.entropicmem`` (``ENTROPICMEM_HOME``), with ``vault/``,
``memory.db`` and ``index.db`` inside it. The ``ENTROPICMEM_*`` path variables
the engine already honors still win, and ``--memory-db`` / ``--vault`` /
``--index-db`` override everything.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, TextIO, Tuple

from em import __version__
from em.provider.provider import EntropicMemProvider, ProviderHost

logger = logging.getLogger("em.mcp")

#: MCP revisions this server can answer. The client's requested revision is
#: echoed when it is in this list; otherwise the newest one is offered and the
#: client decides whether to continue (the protocol's own negotiation rule).
#:
#: Nothing newer than 2025-11-25 is listed on purpose. The 2026-07-28 revision
#: removed the ``initialize``/``notifications/initialized`` handshake, ``ping``,
#: ``logging/setLevel`` and the unversioned result shape, and requires a
#: ``server/discover`` RPC; this server implements the handshake era only, so
#: naming 2026-07-28 would promise a contract it does not honour. A client that
#: offers only a newer revision is answered with 2025-11-25 and decides.
PROTOCOL_VERSIONS: Tuple[str, ...] = (
    "2025-11-25",
    "2025-06-18",
    "2025-03-26",
    "2024-11-05",
)
LATEST_PROTOCOL_VERSION = PROTOCOL_VERSIONS[0]

SERVER_NAME = "entropicmem"
SERVER_TITLE = "EntropicMem"

INSTRUCTIONS = (
    "Local long-term memory. Call entropicmem_search before answering questions "
    "about the past, prior decisions or the user's preferences. Save durable facts "
    "with entropicmem_remember; correct them with entropicmem_update instead of "
    "saving a duplicate. Never store passwords, API keys or other secrets."
)

#: Tools that only read. ``entropicmem_forget`` is the one unambiguously
#: destructive call; the rest are writes with their own store-level gates.
_READ_ONLY_TOOLS = frozenset(
    {
        "entropicmem_search",
        "entropicmem_timeline",
        "entropicmem_entity",
        "entropicmem_stats",
    }
)
#: Tools whose read/write nature depends on the *action* argument. The
#: annotation is a static per-tool claim made in ``tools/list``, before the
#: client has chosen an action, so for these the server asserts no
#: ``readOnlyHint`` at all rather than one that is wrong for half the
#: actions: ``entropicmem_review`` reads on ``list_pending`` and
#: ``consolidate_preview`` and mutates on ``promote``/``discard``/
#: ``restore``/``feedback``.
_ACTION_MIXED_TOOLS = frozenset({"entropicmem_review"})
_DESTRUCTIVE_TOOLS = frozenset({"entropicmem_forget"})

#: JSON-RPC error codes. MCP uses the standard set.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


class _RecallStatus:
    """The provider's host-injected recall status label/count pair."""

    __slots__ = ("label", "count")

    def __init__(self, label: str, count: int) -> None:
        self.label = label
        self.count = count


class StandaloneHost(ProviderHost):
    """The host seam for a process with no Hermes agent around it.

    Paths are explicit, config is stdlib JSON, and the shadow/recall hooks are
    inert. ``resolve_scripts_dir`` returns this package's ``scripts/`` root so
    the provider can put the engine modules on ``sys.path`` exactly as it does
    inside Hermes.
    """

    def __init__(
        self,
        home: Path,
        *,
        memory_db: Optional[Path] = None,
        vault_path: Optional[Path] = None,
        index_db: Optional[Path] = None,
    ) -> None:
        self.home = Path(home).expanduser().resolve()
        self._memory_db = Path(memory_db).expanduser() if memory_db else None
        self._vault_path = Path(vault_path).expanduser() if vault_path else None
        self._index_db = Path(index_db).expanduser() if index_db else None
        # em/mcp_server.py -> em -> scripts
        self._scripts_dir = Path(__file__).resolve().parent.parent

    def hermes_home_from_kwargs(self, kwargs: dict) -> Path:
        # The provider calls this "hermes_home" for historical reasons; in this
        # process it is simply EntropicMem's home.
        return self.home

    def load_plugin_config(self, hermes_home: Path) -> dict:
        """Read ``{home}/config.json`` (the typed config, without PyYAML).

        A broken file is a warning and an empty mapping: a config typo must not
        stop the memory server from starting. The engine's own validation then
        keeps the default for any rejected value.
        """
        path = Path(hermes_home).expanduser() / "config.json"
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            logger.warning("ignoring unreadable config at %s (%s)", path, type(exc).__name__)
            return {}
        if not isinstance(data, dict):
            logger.warning("ignoring config at %s: expected a JSON object", path)
            return {}
        # Accept the Hermes-shaped wrapper too, so one file can serve both.
        memory = data.get("memory")
        if isinstance(memory, dict) and isinstance(memory.get("entropicmem"), dict):
            return dict(memory["entropicmem"])
        return dict(data)

    def resolve_paths(self, hermes_home: Path, config: dict) -> Tuple[Path, Path, Path]:
        home = Path(hermes_home).expanduser()
        base = home

        def pick(explicit: Optional[Path], key: str, env: str, default: Path) -> Path:
            if explicit is not None:
                return explicit
            value = config.get(key) or os.environ.get(env)
            return Path(value).expanduser() if value else default

        vault = pick(self._vault_path, "vault_path", "ENTROPICMEM_VAULT_PATH", base / "vault")
        index_db = pick(self._index_db, "index_db", "ENTROPICMEM_INDEX_DB", base / "index.db")
        memory_db = pick(
            self._memory_db, "memory_db", "ENTROPICMEM_MEMORY_DB", base / "memory.db"
        )
        return vault, index_db, memory_db

    def resolve_scripts_dir(self, hermes_home: Path) -> Optional[Path]:
        return self._scripts_dir

    def ensure_scripts_on_path(self, scripts_dir: Path) -> None:
        path = str(scripts_dir)
        if path not in sys.path:
            sys.path.insert(0, path)

    @property
    def spawn_context_thread(self):
        # No host factory: the provider's _spawn falls back to threading.
        return None

    def recall_status(self, label: str, count: int) -> Any:
        return _RecallStatus(label, count)

    def tool_error(self, message: str) -> str:
        return json.dumps({"ok": False, "error": message})

    def shadow_path(self) -> Optional[Path]:
        return None

    def shadow_injected_ids(self, block: str) -> List[str]:
        return []

    def run_shadow(self, live_db: str, *, profile: str, query: str, v2_ids: List[str]) -> Any:
        return None


class McpServer:
    """The JSON-RPC dispatcher over one initialized provider."""

    def __init__(self, provider: EntropicMemProvider) -> None:
        self.provider = provider
        self.initialized = False

    # -- request dispatch --------------------------------------------------

    def handle(self, message: Any) -> Optional[Dict[str, Any]]:
        """Return the response object for *message*, or ``None`` for a notification."""
        if not isinstance(message, dict):
            return _error(None, INVALID_REQUEST, "Invalid Request")
        has_id = "id" in message
        request_id = message.get("id")
        method = message.get("method")
        if message.get("jsonrpc") != "2.0" or not isinstance(method, str):
            return _error(request_id if has_id else None, INVALID_REQUEST, "Invalid Request")

        params = message.get("params")
        if params is not None and not isinstance(params, dict):
            return _error(request_id, INVALID_PARAMS, "params must be an object")

        try:
            if method == "initialize":
                result = self._initialize(params or {})
            elif method == "notifications/initialized":
                self.initialized = True
                result = None
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = self._tools_list()
            elif method == "tools/call":
                result = self._tools_call(params or {})
            elif method == "logging/setLevel":
                # No server logs are emitted on stdout; accept the setting.
                result = {}
            elif method.startswith("notifications/"):
                result = None
            else:
                return _error(request_id, METHOD_NOT_FOUND, f"Method not found: {method}")
        except _ProtocolError:
            raise
        except Exception as exc:  # noqa: BLE001 - one bad call must not kill the server
            logger.exception("MCP request %s failed", method)
            return _error(request_id, INTERNAL_ERROR, f"Internal error ({type(exc).__name__})")

        if not has_id:
            return None
        if result is None:
            result = {}
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    # -- methods -----------------------------------------------------------

    def _initialize(self, params: Mapping[str, Any]) -> Dict[str, Any]:
        requested = params.get("protocolVersion")
        version = (
            requested
            if isinstance(requested, str) and requested in PROTOCOL_VERSIONS
            else LATEST_PROTOCOL_VERSION
        )
        self.initialized = True
        return {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {
                "name": SERVER_NAME,
                "title": SERVER_TITLE,
                "version": __version__,
            },
            "instructions": INSTRUCTIONS,
        }

    def _tools_list(self) -> Dict[str, Any]:
        tools: List[Dict[str, Any]] = []
        for schema in self.provider.get_tool_schemas():
            name = str(schema.get("name") or "")
            annotations: Dict[str, Any] = {
                "destructiveHint": name in _DESTRUCTIVE_TOOLS,
                "openWorldHint": False,
            }
            if name not in _ACTION_MIXED_TOOLS:
                annotations["readOnlyHint"] = name in _READ_ONLY_TOOLS
            tool: Dict[str, Any] = {
                "name": name,
                "description": str(schema.get("description") or ""),
                "inputSchema": schema.get("parameters") or {"type": "object", "properties": {}},
                "annotations": annotations,
            }
            tools.append(tool)
        return {"tools": tools}

    def _tools_call(self, params: Mapping[str, Any]) -> Dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(name, str) or not name:
            raise _ProtocolError(INVALID_PARAMS, "tools/call needs a tool name")
        if not isinstance(arguments, dict):
            raise _ProtocolError(INVALID_PARAMS, "tools/call arguments must be an object")
        known = {str(s.get("name") or "") for s in self.provider.get_tool_schemas()}
        if name not in known:
            raise _ProtocolError(INVALID_PARAMS, f"Unknown tool: {name}")

        output = self.provider.handle_tool_call(name, arguments)
        text = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)
        is_error = False
        try:
            payload = json.loads(text)
            is_error = isinstance(payload, dict) and payload.get("ok") is False
        except Exception:
            pass
        return {"content": [{"type": "text", "text": text}], "isError": is_error}

    # -- transport ---------------------------------------------------------

    def serve(self, stdin: TextIO, stdout: TextIO) -> None:
        """Read newline-delimited JSON-RPC until EOF, writing one response per line."""
        for raw in stdin:
            line = raw.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except Exception:
                _write(stdout, _error(None, PARSE_ERROR, "Parse error"))
                continue
            try:
                response = self.handle(message)
            except _ProtocolError as exc:
                request_id = message.get("id") if isinstance(message, dict) else None
                response = _error(request_id, exc.code, exc.message)
            if response is not None:
                _write(stdout, response)


class _ProtocolError(Exception):
    """A JSON-RPC error raised where a result would otherwise be returned."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _error(request_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _use_utf8_stdio() -> None:
    """Force UTF-8 on stdin/stdout regardless of the host's locale.

    MCP frames are UTF-8 by definition, but Python decodes a pipe with the
    locale's preferred encoding. On a Windows host whose code page is not
    UTF-8 (or any C-locale POSIX box), a non-ASCII byte in a client request
    raised ``UnicodeDecodeError`` out of ``serve``'s loop — which ``main``
    reported as a startup failure, exiting the whole server — and a non-ASCII
    memory could not be written to the response at all.
    """
    for stream in (sys.stdin, sys.stdout):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:  # a StringIO under test
            continue
        try:
            reconfigure(encoding="utf-8", errors="strict")
        except Exception:  # noqa: BLE001 - a stream that cannot change is left alone
            logger.debug("could not force UTF-8 on %r", stream)


def _write(stdout: TextIO, payload: Mapping[str, Any]) -> None:
    # ensure_ascii=False keeps text readable for the client; the console stream
    # is UTF-8 (see ``_use_utf8_stdio``), and a stream that still cannot encode
    # a character must not kill the server mid-session.
    line = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    try:
        stdout.write(line)
    except UnicodeEncodeError:
        stdout.write(json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n")
    stdout.flush()


def build_provider(
    home: Path,
    *,
    memory_db: Optional[Path] = None,
    vault_path: Optional[Path] = None,
    index_db: Optional[Path] = None,
) -> EntropicMemProvider:
    """Build and initialize the provider the server exposes."""
    host = StandaloneHost(
        home, memory_db=memory_db, vault_path=vault_path, index_db=index_db
    )
    provider = EntropicMemProvider(config={}, host=host)
    provider.initialize(
        "openbot",
        hermes_home=str(host.home),
        agent_context="primary",
        agent_identity="default",
    )
    # A brand-new MCP home gets the v3 store, so the full nine-tool surface works
    # from the first call. An existing store is served exactly as it is: a v2
    # store is never migrated here, because that cutover is a deliberate act.
    #
    # The path comes from the provider, not from ``host.resolve_paths``: the
    # provider's typed loader also reads the nested ``paths.*`` form of
    # ``<home>/config.json``, which the flat pass below does not. Bootstrapping
    # the flat answer created a v3 file the provider never served, and the file
    # it did serve was then created by the v2 engine — so ``update``, ``entity``
    # and ``review restore`` refused on a home the docs call new.
    memory_path = provider._memory_db
    if memory_path is not None and not Path(memory_path).exists():
        from em.facade.engine import V3Engine

        engine = V3Engine(memory_path)
        engine.close()
        # Profile reads and remember's vault note need the directory to exist.
        # CoreMemory and Vault create their own files after that. An existing
        # store, including one with no vault, is left exactly as it was.
        if provider._vault_path is not None:
            provider._vault_path.mkdir(parents=True, exist_ok=True)
        if provider._index_db is not None:
            provider._index_db.parent.mkdir(parents=True, exist_ok=True)
        # ``initialize`` ran before the file existed, so its job-worker start
        # took the "not created yet" early return. Start it now that the store
        # is there: otherwise the projection and embed jobs a first session
        # enqueues wait for the next process. The call is idempotent.
        provider._start_job_workers()
    return provider


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="entropicmem-mcp",
        description="EntropicMem MCP stdio server (local memory tools for MCP clients).",
    )
    parser.add_argument(
        "--home",
        default=os.environ.get("ENTROPICMEM_HOME", "~/.entropicmem"),
        help="EntropicMem home directory (default: $ENTROPICMEM_HOME or ~/.entropicmem)",
    )
    parser.add_argument("--memory-db", default=None, help="Override the SQLite memory database path")
    parser.add_argument("--vault", default=None, help="Override the Markdown vault path")
    parser.add_argument("--index-db", default=None, help="Override the vault index database path")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    _use_utf8_stdio()
    logging.basicConfig(
        stream=sys.stderr,
        level=os.environ.get("ENTROPICMEM_MCP_LOG_LEVEL", "WARNING").upper(),
        format="%(levelname)s %(name)s: %(message)s",
    )
    provider: Optional[EntropicMemProvider] = None
    try:
        provider = build_provider(
            Path(args.home),
            memory_db=Path(args.memory_db) if args.memory_db else None,
            vault_path=Path(args.vault) if args.vault else None,
            index_db=Path(args.index_db) if args.index_db else None,
        )
        McpServer(provider).serve(sys.stdin, sys.stdout)
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # noqa: BLE001 - startup failure is a stderr line + exit
        logger.error("EntropicMem MCP server failed to start: %s", exc)
        return 1
    finally:
        if provider is not None:
            try:
                provider.shutdown()
            except Exception:
                logger.debug("provider shutdown failed", exc_info=True)


if __name__ == "__main__":  # pragma: no cover - the console script is the entry point
    raise SystemExit(main())
