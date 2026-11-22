"""MCP stdio smoke tests for the OpenBot bridge.

The server is exercised as a real subprocess over stdin/stdout, which is the
transport OpenBot uses. The checks are deliberately small: initialize,
tools/list, one remember/search round trip, and the JSON-RPC error paths.
The store is a temporary home; no test reads or writes a live store.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

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
