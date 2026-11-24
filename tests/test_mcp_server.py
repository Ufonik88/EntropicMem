"""MCP stdio smoke tests for the OpenBot bridge.

The server is exercised as a real subprocess over stdin/stdout, which is the
transport OpenBot uses. The checks are deliberately small: initialize,
tools/list, one remember/search round trip, and the JSON-RPC error paths.
The store is a temporary home; no test reads or writes a live store.
"""

from __future__ import annotations

import io
import json
import logging
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

from em import mcp_server

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"

_TOOL_NAMES = {
    "entropicmem_remember",
    "entropicmem_search",
    "entropicmem_update",
    "entropicmem_forget",
    "entropicmem_timeline",
    "entropicmem_entity",
    "entropicmem_profile",
    "entropicmem_review",
    "entropicmem_stats",
}


def _clean_env() -> Dict[str, str]:
    env = os.environ.copy()
    for name in (
        "ENTROPICMEM_HOME",
        "ENTROPICMEM_VAULT_PATH",
        "ENTROPICMEM_INDEX_DB",
        "ENTROPICMEM_MEMORY_DB",
        "ENTROPICMEM_SHADOW_V3",
        "ENTROPICMEM_SHADOW_LOG",
    ):
        env.pop(name, None)
    env["PYTHONPATH"] = str(SCRIPTS)
    return env


def _run(tmp_path: Path, requests: List[Any]) -> Tuple[subprocess.CompletedProcess, List[dict]]:
    payload = "\n".join(json.dumps(request) for request in requests) + "\n"
    proc = subprocess.run(
        [sys.executable, "-m", "em.mcp_server", "--home", str(tmp_path)],
        input=payload,
        text=True,
        capture_output=True,
        cwd=str(REPO),
        env=_clean_env(),
        timeout=90,
    )
    assert proc.returncode == 0, proc.stderr
    lines = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    return proc, lines


def _request(request_id: int, method: str, params: Any = None) -> dict:
    message = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        message["params"] = params
    return message


def _text(response: dict) -> str:
    return response["result"]["content"][0]["text"]


def test_initialize_and_tools_list(tmp_path: Path) -> None:
    proc, lines = _run(
        tmp_path,
        [
            _request(
                1,
                "initialize",
                {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "pytest"}},
            ),
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            _request(2, "tools/list"),
        ],
    )
    # Every stdout line is protocol JSON; no log line leaked onto the transport.
    assert len(lines) == 2, proc.stdout

    init = lines[0]
    assert init["id"] == 1
    result = init["result"]
    assert result["protocolVersion"] == "2025-06-18"
    assert result["serverInfo"]["name"] == "entropicmem"
    assert result["serverInfo"]["version"]
    assert result["capabilities"]["tools"]["listChanged"] is False
    assert "entropicmem_search" in result["instructions"]

    listed = lines[1]["result"]["tools"]
    assert {tool["name"] for tool in listed} == _TOOL_NAMES
    for tool in listed:
        assert tool["description"]
        assert tool["inputSchema"]["type"] == "object"
        assert tool["annotations"]["openWorldHint"] is False
    search = next(tool for tool in listed if tool["name"] == "entropicmem_search")
    assert search["annotations"]["readOnlyHint"] is True
    assert "query" in search["inputSchema"]["properties"]


def test_remember_and_search_round_trip(tmp_path: Path) -> None:
    _, lines = _run(
        tmp_path,
        [
            _request(1, "initialize", {}),
            _request(
                2,
                "tools/call",
                {
                    "name": "entropicmem_remember",
                    "arguments": {"content": "The staging server runs on port 9090."},
                },
            ),
            _request(
                3,
                "tools/call",
                {"name": "entropicmem_search", "arguments": {"query": "staging server port"}},
            ),
        ],
    )
    remembered = json.loads(_text(lines[1]))
    assert remembered["ok"] is True
    assert remembered["id"]
    assert lines[1]["result"]["isError"] is False

    found = json.loads(_text(lines[2]))
    assert found["ok"] is True
    assert any(
        hit["content"] == "The staging server runs on port 9090." for hit in found["results"]
    )

    # A new MCP home is bootstrapped as v3, so update/entity/review work too.
    conn = sqlite3.connect(str(tmp_path / "memory.db"))
    try:
        assert int(conn.execute("PRAGMA user_version").fetchone()[0]) >= 3
    finally:
        conn.close()


def test_existing_v2_store_is_not_migrated(tmp_path: Path) -> None:
    from memory_engine import MemoryEngine

    db = tmp_path / "memory.db"
    engine = MemoryEngine(db)
    engine.close()

    _, lines = _run(
        tmp_path,
        [
            _request(1, "initialize", {}),
            _request(2, "tools/call", {"name": "entropicmem_stats", "arguments": {}}),
        ],
    )
    stats = json.loads(_text(lines[1]))
    assert stats["fact_count"] == 0
    assert stats["db_path"] == str(db)
    conn = sqlite3.connect(str(db))
    try:
        assert int(conn.execute("PRAGMA user_version").fetchone()[0]) == 0
    finally:
        conn.close()


def test_protocol_errors_are_reported(tmp_path: Path) -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "em.mcp_server", "--home", str(tmp_path)],
        input=(
            "not-json\n"
            + json.dumps(_request(1, "no/such/method"))
            + "\n"
            + json.dumps(
                _request(2, "tools/call", {"name": "entropicmem_nope", "arguments": {}})
            )
            + "\n"
        ),
        text=True,
        capture_output=True,
        cwd=str(REPO),
        env=_clean_env(),
        timeout=90,
    )
    assert proc.returncode == 0, proc.stderr
    lines = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    assert lines[0]["error"]["code"] == -32700
    assert lines[1]["error"]["code"] == -32601
    assert lines[2]["error"]["code"] == -32602


def test_listing_bundle_matches_the_server() -> None:
    """The catalog bundle cannot drift from the command or grow a secret."""
    bundle = json.loads(
        (REPO / "integrations" / "openbot" / "plugin.json").read_text(encoding="utf-8")
    )
    assert bundle["slug"] == "entropicmem"
    assert bundle["skills"] == []
    assert len(bundle["apps"]) == 1
    server = bundle["apps"][0]["server"]
    assert server["name"] == "entropicmem"
    assert server["transport"] == "stdio"
    assert server["command"] == "entropicmem-mcp"
    assert server["args"] == []
    assert "auth" not in server
    assert '"value"' not in json.dumps(bundle)


def test_the_console_script_is_declared() -> None:
    text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    assert 'entropicmem-mcp = "em.mcp_server:main"' in text


def test_startup_failure_is_a_clean_stderr_error(tmp_path: Path) -> None:
    """A broken home exits nonzero with a stderr line, not a hung server."""
    home = tmp_path / "not-a-directory"
    home.write_text("x", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "em.mcp_server", "--home", str(home)],
        input="",
        text=True,
        capture_output=True,
        cwd=str(REPO),
        env=_clean_env(),
        timeout=30,
    )
    assert proc.returncode != 0
    assert "EntropicMem MCP server failed to start" in proc.stderr


def test_a_nested_paths_config_is_the_store_that_gets_bootstrapped(tmp_path: Path) -> None:
    """The bootstrap and the served store must be the same file.

    The provider's typed loader reads the nested ``paths.memory_db`` form; a
    flat pass over the same file does not. When the two disagreed, a "new" home
    got a v3 file at the flat answer while the provider served the nested path,
    which the v2 engine then created — so the v3-only tools refused on a home
    the documentation calls new.
    """
    nested = tmp_path / "elsewhere" / "memory.db"
    (tmp_path / "config.json").write_text(
        json.dumps({"paths": {"memory_db": str(nested)}}), encoding="utf-8"
    )

    _, lines = _run(
        tmp_path,
        [
            _request(1, "initialize", {}),
            _request(2, "tools/call", {"name": "entropicmem_stats", "arguments": {}}),
            _request(
                3,
                "tools/call",
                {
                    "name": "entropicmem_update",
                    "arguments": {"id": "no-such-id", "content": "x"},
                },
            ),
        ],
    )
    stats = json.loads(_text(lines[1]))
    assert stats["db_path"] == str(nested)
    # A v3 store answers "not found"; a v2 store answers needs_v3_store.
    update = json.loads(_text(lines[2]))
    assert update.get("reason_code") != "needs_v3_store", update
    assert int(sqlite3.connect(str(nested)).execute("PRAGMA user_version").fetchone()[0]) >= 3
    assert not (tmp_path / "memory.db").exists(), "the flat answer must not be bootstrapped"


def test_a_non_utf8_stdout_still_serves_and_writes_unicode(tmp_path: Path) -> None:
    """A host locale must not decide whether the server starts or can answer.

    MCP frames are UTF-8. Python decodes a pipe with the locale's encoding, so
    on a non-UTF-8 code page a non-ASCII request byte raised out of ``serve``
    and ``main`` reported it as a startup failure — and a non-ASCII memory
    could not be encoded onto stdout at all.
    """
    payload = "\n".join(
        json.dumps(message, ensure_ascii=False)
        for message in [
            _request(1, "initialize", {}),
            _request(
                2,
                "tools/call",
                {
                    "name": "entropicmem_remember",
                    "arguments": {"content": "Staging is in 東京 — café ✓"},
                },
            ),
            _request(3, "tools/call", {"name": "entropicmem_search", "arguments": {"query": "東京"}}),
        ]
    )
    env = _clean_env()
    env["PYTHONIOENCODING"] = "cp1252"
    proc = subprocess.run(
        [sys.executable, "-m", "em.mcp_server", "--home", str(tmp_path)],
        input=payload.encode("utf-8") + b"\n",
        text=False,
        capture_output=True,
        cwd=str(REPO),
        env=env,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    lines = [json.loads(line) for line in proc.stdout.decode("utf-8").splitlines() if line]
    assert len(lines) == 3, proc.stdout
    remembered = json.loads(_text(lines[1]))
    assert remembered["ok"] is True
    found = json.loads(_text(lines[2]))
    assert found["ok"] is True
    assert any("東京" in hit["content"] for hit in found["results"]), found


def test_a_credential_is_refused_however_it_is_phrased(tmp_path: Path) -> None:
    """The remember gate must catch natural phrasing and raw key ids.

    Only the ``=``/``:`` shapes were caught, so "my password is hunter2" and a
    bare AWS access key id reached the store verbatim — active, unflagged —
    while "password=hunter2" was blocked. Both shapes are now policy blocks,
    the caller is told, and nothing lands in the store.
    """
    _, lines = _run(
        tmp_path,
        [
            _request(1, "initialize", {}),
            _request(
                2,
                "tools/call",
                {
                    "name": "entropicmem_remember",
                    "arguments": {"content": "my password is hunter2"},
                },
            ),
            _request(
                3,
                "tools/call",
                {
                    "name": "entropicmem_remember",
                    "arguments": {
                        "content": "the backup user runs with AKIAIOSFODNN7EXAMPLE"
                    },
                },
            ),
            _request(4, "tools/call", {"name": "entropicmem_stats", "arguments": {}}),
        ],
    )
    for index in (1, 2):
        blocked = json.loads(_text(lines[index]))
        assert blocked["ok"] is False, blocked
        assert blocked["reason_code"] == "policy_block", blocked
        assert lines[index]["result"]["isError"] is True
    stats = json.loads(_text(lines[3]))
    assert stats["fact_count"] == 0, "a refused credential must leave no row"


def test_read_only_hints_match_what_each_call_does(tmp_path: Path) -> None:
    """A static hint a client might auto-approve on must be true.

    ``entropicmem_review`` straddles: ``list_pending`` and
    ``consolidate_preview`` only read, while ``promote``/``discard``/
    ``restore``/``feedback`` mutate. The annotation is a per-tool claim made in
    ``tools/list``, before the client has chosen an action, so the server
    asserts no ``readOnlyHint`` for it at all rather than one that is wrong
    for half its actions. The pure reads keep theirs; ``forget`` keeps the
    destructive mark.
    """
    _, lines = _run(
        tmp_path,
        [
            _request(
                1,
                "initialize",
                {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "pytest"}},
            ),
            _request(2, "tools/list"),
        ],
    )
    listed = lines[1]["result"]["tools"]
    by_name = {tool["name"]: tool["annotations"] for tool in listed}

    for reader in ("entropicmem_search", "entropicmem_timeline", "entropicmem_entity", "entropicmem_stats"):
        assert by_name[reader]["readOnlyHint"] is True, reader
    review = by_name["entropicmem_review"]
    assert "readOnlyHint" not in review, review
    assert review["destructiveHint"] is False
    for writer in ("entropicmem_remember", "entropicmem_update"):
        assert by_name[writer]["readOnlyHint"] is False, writer
    assert by_name["entropicmem_forget"]["destructiveHint"] is True


def test_a_new_home_creates_the_vault_so_profile_read_works(tmp_path: Path) -> None:
    """f8f17e6's regression, pinned: a brand-new home serves profile read.

    The bootstrap used to create only the v3 database, so the first profile
    read answered "Vault not initialized" and a remembered fact stored no
    vault note. Both need the vault directory to exist on a new home.
    """
    _, lines = _run(
        tmp_path,
        [
            _request(1, "initialize", {}),
            _request(2, "tools/call", {"name": "entropicmem_profile", "arguments": {"action": "read"}}),
        ],
    )
    profile = json.loads(_text(lines[1]))
    assert profile["ok"] is True, profile
    assert (tmp_path / "vault").is_dir()


def test_protocol_versions_claim_only_the_handshake_era() -> None:
    """2026-07-28 removed the handshake, ``ping`` and ``logging/setLevel``.

    This server implements those, so naming the newer revision would promise a
    contract it cannot honour. A client that offers only a newer one is
    answered with the newest revision this server does implement.
    """
    from em import mcp_server

    assert "2026-07-28" not in mcp_server.PROTOCOL_VERSIONS
    assert mcp_server.LATEST_PROTOCOL_VERSION == "2025-11-25"
    server = mcp_server.McpServer.__new__(mcp_server.McpServer)
    answer = server._initialize({"protocolVersion": "2026-07-28"})
    assert answer["protocolVersion"] == "2025-11-25"
    answer = server._initialize({"protocolVersion": "2025-06-18"})
    assert answer["protocolVersion"] == "2025-06-18"


# --- in-process (MNT W48 coverage): the server's contracts, pinned directly ---
#
# The tests above drive ``python -m em.mcp_server`` as a subprocess — real
# end-to-end transport wiring, but a subprocess is invisible to the suite's
# own ``--cov=em`` measurement, so the module read 24.7% on the full-scope
# coverage scan (183 of 243 statements missed; only the import-time lines and
# ``_initialize`` ran in-process). These tests call ``McpServer``, the
# ``StandaloneHost`` seam, ``build_provider`` and ``main`` in-process so the
# dispatcher's refusal paths, the notification rules, the transport's
# parse/encode fallbacks, the host's path precedence and the bootstrap's
# v2-is-never-migrated rule are pinned against the code that ships. No
# production line changes: every behaviour asserted below is behaviour the
# module already ships, and the subprocess tests above stay exactly as they
# are.


class _StubProvider:
    """Just enough provider for the dispatcher: schemas plus one canned call."""

    def __init__(self, output: Any = '{"ok": true, "id": "mem_1"}') -> None:
        self.output = output
        self.calls: List[Tuple[str, Dict[str, Any]]] = []

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        return [
            {"name": "entropicmem_search", "description": "Search stored memories.", "parameters": {}},
            {"name": "entropicmem_remember", "description": "Store a durable fact.", "parameters": {}},
        ]

    def handle_tool_call(self, name: str, arguments: Dict[str, Any]) -> Any:
        self.calls.append((name, arguments))
        return self.output


def _server(provider: Any = None) -> "mcp_server.McpServer":
    return mcp_server.McpServer(provider if provider is not None else _StubProvider())


def _frame(method: Any, *, id: Any = 1, jsonrpc: str = "2.0", params: Any = None) -> Dict[str, Any]:
    message: Dict[str, Any] = {"jsonrpc": jsonrpc, "method": method}
    if id is not None:
        message["id"] = id
    if params is not None:
        message["params"] = params
    return message


# -- the dispatcher ---------------------------------------------------------


def test_malformed_frames_are_invalid_request_in_process() -> None:
    server = _server()
    response = server.handle("not-a-dict")
    assert response == {
        "jsonrpc": "2.0",
        "id": None,
        "error": {"code": mcp_server.INVALID_REQUEST, "message": "Invalid Request"},
    }
    # A dict frame that is not JSON-RPC 2.0 keeps its id in the error.
    for bad in ({"id": 7, "method": "ping"}, {"jsonrpc": "2.0", "method": 42, "id": 7}):
        response = server.handle(bad)
        assert response["id"] == 7, bad
        assert response["error"] == {"code": mcp_server.INVALID_REQUEST, "message": "Invalid Request"}
    # A frame whose params is not an object is its own refusal, id and all.
    response = server.handle(_frame("tools/call", params=[1, 2]))
    assert response["error"]["code"] == mcp_server.INVALID_PARAMS
    assert response["error"]["message"] == "params must be an object"


def test_ping_logging_setlevel_and_unknown_method_in_process() -> None:
    server = _server()
    assert server.handle(_frame("ping"))["result"] == {}
    assert server.handle(_frame("logging/setLevel", params={"level": "debug"}))["result"] == {}
    response = server.handle(_frame("no/such/method"))
    assert response["error"]["code"] == mcp_server.METHOD_NOT_FOUND
    assert "no/such/method" in response["error"]["message"]


def test_initialized_notification_flips_the_flag_and_a_plain_notification_is_silent() -> None:
    server = _server()
    assert server.initialized is False
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert server.initialized is True
    # Any other notification is accepted and answered with nothing, not an error.
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/whatever"}) is None
    # A notification method sent *with* an id is still a request: {} comes back.
    assert server.handle(_frame("notifications/initialized"))["result"] == {}


def test_tools_list_builds_annotations_in_process() -> None:
    listed = _server().handle(_frame("tools/list"))["result"]["tools"]
    by_name = {tool["name"]: tool for tool in listed}
    assert set(by_name) == {"entropicmem_search", "entropicmem_remember"}
    reader = by_name["entropicmem_remember"]
    assert reader["annotations"] == {
        "readOnlyHint": False,
        "destructiveHint": False,
        "openWorldHint": False,
    }
    assert reader["description"] == "Store a durable fact."
    assert reader["inputSchema"]["type"] == "object"
    assert by_name["entropicmem_search"]["annotations"]["readOnlyHint"] is True


def test_tools_call_passes_arguments_through_and_maps_ok_false_to_is_error() -> None:
    provider = _StubProvider(output='{"ok": false, "error": "nope"}')
    response = _server(provider).handle(
        _frame("tools/call", params={"name": "entropicmem_search", "arguments": {"query": "x"}})
    )["result"]
    assert provider.calls == [("entropicmem_search", {"query": "x"})]
    assert response["content"][0]["type"] == "text"
    assert json.loads(response["content"][0]["text"]) == {"ok": False, "error": "nope"}
    assert response["isError"] is True

    provider = _StubProvider(output="not json at all")
    response = _server(provider).handle(
        _frame("tools/call", params={"name": "entropicmem_search"})
    )["result"]
    assert response["isError"] is False  # unparseable output is not a tool failure
    assert response["content"][0]["text"] == "not json at all"


def test_tools_call_refusals_in_process() -> None:
    server = _server()
    for params, message in (
        ({"arguments": {}}, "tools/call needs a tool name"),
        ({"name": ""}, "tools/call needs a tool name"),
        ({"name": "entropicmem_search", "arguments": [1]}, "tools/call arguments must be an object"),
        ({"name": "entropicmem_nope", "arguments": {}}, "Unknown tool: entropicmem_nope"),
        ({"name": 42}, "tools/call needs a tool name"),
    ):
        with pytest.raises(mcp_server._ProtocolError) as caught:
            server.handle(_frame("tools/call", params=params))
        assert caught.value.code == mcp_server.INVALID_PARAMS, params
        assert caught.value.message == message, params


def test_a_failing_call_is_an_internal_error_and_the_server_survives() -> None:
    class _Boom(Exception):
        pass

    def _explode(name: str, arguments: Dict[str, Any]) -> Any:
        raise _Boom("x")

    provider = _StubProvider()
    provider.handle_tool_call = _explode  # type: ignore[assignment]
    server = _server(provider)
    response = server.handle(_frame("tools/call", params={"name": "entropicmem_search"}))
    assert response["error"]["code"] == mcp_server.INTERNAL_ERROR
    assert "_Boom" in response["error"]["message"]
    # One bad call must not kill the server: the next request still answers.
    assert server.handle(_frame("ping"))["result"] == {}


# -- the transport ----------------------------------------------------------


def test_serve_answers_each_line_until_eof_in_process() -> None:
    provider = _StubProvider(output='{"ok": false}')
    lines_in = [
        "",  # blank lines are skipped, not parsed
        "not-json",  # a parse error answers id null and the loop continues
        "[1, 2]",  # valid JSON that is not a request object
        json.dumps(_frame("initialize", params={})),
        json.dumps(_frame("tools/list")),
        json.dumps(_frame("tools/call", params={"name": "entropicmem_nope", "arguments": {}})),
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
    ]
    stdout = io.StringIO()
    mcp_server.McpServer(provider).serve(io.StringIO("\n".join(lines_in) + "\n"), stdout)
    out = [json.loads(line) for line in stdout.getvalue().splitlines()]

    assert [frame["error"]["code"] for frame in out[:2]] == [
        mcp_server.PARSE_ERROR,
        mcp_server.INVALID_REQUEST,
    ]
    assert out[0]["id"] is None
    assert out[2]["result"]["protocolVersion"] == mcp_server.LATEST_PROTOCOL_VERSION
    assert {tool["name"] for tool in out[3]["result"]["tools"]} == {
        "entropicmem_search",
        "entropicmem_remember",
    }
    assert out[4]["error"]["code"] == mcp_server.INVALID_PARAMS  # the _ProtocolError conversion
    assert out[4]["id"] == 1
    assert len(out) == 5  # the notification wrote nothing


def test_write_falls_back_to_ascii_when_the_stream_cannot_encode() -> None:
    class _AsciiOnly:
        def __init__(self) -> None:
            self.lines: List[str] = []

        def write(self, text: str) -> int:
            for index, char in enumerate(text):
                if ord(char) > 127:
                    raise UnicodeEncodeError("ascii", text, index, index + 1, "not ascii")
            self.lines.append(text)
            return len(text)

        def flush(self) -> None:
            pass

    stream = _AsciiOnly()
    payload = {"jsonrpc": "2.0", "id": 1, "result": {"note": "東京"}}
    mcp_server._write(stream, payload)
    assert len(stream.lines) == 1
    assert stream.lines[0].endswith("\n")
    assert "東京" not in stream.lines[0]
    assert json.loads(stream.lines[0])["result"]["note"] == "東京"


def test_utf8_stdio_reconfigures_real_streams_and_tolerates_stub_ones(monkeypatch, caplog) -> None:
    reconfigured: List[Tuple[Any, Dict[str, Any]]] = []

    class _Real:
        def reconfigure(self, **kwargs: Any) -> None:
            reconfigured.append((self, kwargs))

    class _Broken:
        def reconfigure(self, **kwargs: Any) -> None:
            raise ValueError("cannot change")

    real, broken = _Real(), _Broken()
    monkeypatch.setattr(sys, "stdin", real)
    monkeypatch.setattr(sys, "stdout", broken)
    with caplog.at_level(logging.DEBUG):
        mcp_server._use_utf8_stdio()
    assert reconfigured == [(real, {"encoding": "utf-8", "errors": "strict"})]
    # A stream that cannot change is left alone, quietly logged at debug.
    assert [rec.levelname for rec in caplog.records] == ["DEBUG"]
    assert "could not force UTF-8" in caplog.records[0].getMessage()

    # A plain StringIO has no reconfigure at all: skipped, no crash, nothing done.
    stub = io.StringIO()
    monkeypatch.setattr(sys, "stdin", stub)
    monkeypatch.setattr(sys, "stdout", stub)
    mcp_server._use_utf8_stdio()
    assert stub.getvalue() == ""


# -- the standalone host seam ------------------------------------------------


def test_standalone_host_reads_the_config_shapes(tmp_path: Path) -> None:
    host = mcp_server.StandaloneHost(tmp_path)

    assert host.hermes_home_from_kwargs({"irrelevant": True}) == host.home
    assert host.load_plugin_config(tmp_path) == {}  # no config file

    (tmp_path / "config.json").write_text("{not json", encoding="utf-8")
    assert host.load_plugin_config(tmp_path) == {}

    (tmp_path / "config.json").write_text('["a list"]', encoding="utf-8")
    assert host.load_plugin_config(tmp_path) == {}

    (tmp_path / "config.json").write_text('{"memory": {"entropicmem": {"a": 1}}}', encoding="utf-8")
    assert host.load_plugin_config(tmp_path) == {"a": 1}

    (tmp_path / "config.json").write_text('{"b": 2}', encoding="utf-8")
    assert host.load_plugin_config(tmp_path) == {"b": 2}


def test_standalone_host_resolves_paths_explicit_over_config_over_env(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path.resolve()
    explicit = tmp_path / "explicit"
    host = mcp_server.StandaloneHost(
        tmp_path, memory_db=explicit / "memory.db", vault_path=explicit / "vault", index_db=explicit / "index.db"
    )
    vault, index_db, memory_db = host.resolve_paths(tmp_path, {})
    assert (str(vault), str(index_db), str(memory_db)) == (
        str(explicit / "vault"),
        str(explicit / "index.db"),
        str(explicit / "memory.db"),
    )

    # Without the explicit values, a config key wins over the environment.
    host = mcp_server.StandaloneHost(tmp_path)
    config = {"memory_db": str(tmp_path / "from-config" / "memory.db")}
    monkeypatch.setenv("ENTROPICMEM_MEMORY_DB", str(tmp_path / "from-env" / "memory.db"))
    monkeypatch.setenv("ENTROPICMEM_INDEX_DB", str(tmp_path / "from-env" / "index.db"))
    vault, index_db, memory_db = host.resolve_paths(tmp_path, config)
    assert memory_db == tmp_path / "from-config" / "memory.db"
    assert index_db == tmp_path / "from-env" / "index.db"  # no config key: the env var wins
    assert vault == home / "vault"  # neither: the home default

    # With neither, every path falls back to the home.
    monkeypatch.delenv("ENTROPICMEM_MEMORY_DB")
    monkeypatch.delenv("ENTROPICMEM_INDEX_DB")
    vault, index_db, memory_db = host.resolve_paths(tmp_path, {})
    assert (str(vault), str(index_db), str(memory_db)) == (
        str(home / "vault"),
        str(home / "index.db"),
        str(home / "memory.db"),
    )


def test_standalone_host_seams_are_explicit_and_inert() -> None:
    host = mcp_server.StandaloneHost(Path("/tmp/nowhere"))

    assert host.resolve_scripts_dir(Path("/tmp/nowhere")) == Path(mcp_server.__file__).resolve().parent.parent

    marker = "em-mcp-w48-not-twice"
    sys.path.insert(0, marker)
    try:
        host.ensure_scripts_on_path(Path(marker))
        assert sys.path.count(marker) == 1  # idempotent: never inserted twice
    finally:
        sys.path.remove(marker)

    # A path that is not on sys.path yet is inserted once, at the front.
    host.ensure_scripts_on_path(Path("/tmp/nowhere"))
    try:
        assert sys.path[0] == "/tmp/nowhere"
        assert sys.path.count("/tmp/nowhere") == 1
    finally:
        sys.path.remove("/tmp/nowhere")

    status = host.recall_status("prefetch", 3)
    assert (status.label, status.count) == ("prefetch", 3)

    assert json.loads(host.tool_error("boom")) == {"ok": False, "error": "boom"}
    assert host.spawn_context_thread is None
    assert host.shadow_path() is None
    assert host.shadow_injected_ids("anything") == []
    assert host.run_shadow("db", profile="p", query="q", v2_ids=[]) is None


# -- the provider bootstrap and the entry point ------------------------------


def test_build_provider_bootstraps_a_new_home_as_v3_and_is_idempotent(tmp_path: Path) -> None:
    provider = mcp_server.build_provider(tmp_path)
    try:
        home = tmp_path.resolve()
        assert Path(provider._memory_db) == home / "memory.db"
        assert (home / "vault").is_dir()
        assert int(
            sqlite3.connect(str(home / "memory.db")).execute("PRAGMA user_version").fetchone()[0]
        ) >= 3
    finally:
        provider.shutdown()

    # A second build over the now-existing store must not re-bootstrap it.
    provider = mcp_server.build_provider(tmp_path)
    try:
        assert int(
            sqlite3.connect(str(tmp_path.resolve() / "memory.db"))
            .execute("PRAGMA user_version")
            .fetchone()[0]
        ) >= 3
    finally:
        provider.shutdown()


def test_build_provider_leaves_an_existing_v2_store_alone(tmp_path: Path) -> None:
    from memory_engine import MemoryEngine

    db = tmp_path / "memory.db"
    engine = MemoryEngine(db)
    engine.close()

    provider = mcp_server.build_provider(tmp_path)
    try:
        assert int(sqlite3.connect(str(db)).execute("PRAGMA user_version").fetchone()[0]) == 0
    finally:
        provider.shutdown()


def test_main_serves_a_stream_and_shuts_the_provider_down(
    tmp_path: Path, monkeypatch
) -> None:
    stdin = io.StringIO(json.dumps(_frame("ping")) + "\n")
    stdout = io.StringIO()
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", stdout)

    assert mcp_server.main(["--home", str(tmp_path)]) == 0
    served = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert served and served[0]["result"] == {}


def test_main_swallows_a_failing_shutdown(monkeypatch) -> None:
    class _Provider:
        def shutdown(self) -> None:
            raise RuntimeError("shutdown boom")

    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    monkeypatch.setattr(mcp_server, "build_provider", lambda *a, **k: _Provider())
    assert mcp_server.main(["--home", "/tmp/nowhere-w48"]) == 0


def test_main_returns_130_on_interrupt_and_1_on_a_broken_home(
    tmp_path: Path, monkeypatch
) -> None:
    def _interrupted(*args: Any, **kwargs: Any) -> None:
        raise KeyboardInterrupt()

    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    monkeypatch.setattr(mcp_server, "build_provider", _interrupted)
    assert mcp_server.main(["--home", str(tmp_path)]) == 130

    monkeypatch.undo()
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    broken = tmp_path / "not-a-directory"
    broken.write_text("x", encoding="utf-8")
    assert mcp_server.main(["--home", str(broken)]) == 1


def test_version_flag_prints_and_exits_cleanly(capsys) -> None:
    with pytest.raises(SystemExit) as caught:
        mcp_server.main(["--version"])
    assert caught.value.code == 0
    assert "entropicmem-mcp" in capsys.readouterr().out
