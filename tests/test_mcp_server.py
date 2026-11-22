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
