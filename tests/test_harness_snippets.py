"""The harness-compatibility pack: fragments parse, the map names them, and
the tool table matches the server that ships.

``docs/HARNESSES.md`` is the compatibility map a reader follows to wire an
agent harness to ``entropicmem-mcp``; ``integrations/harnesses/`` holds the
config fragments it points at. A fragment that stops parsing, a fragment the
map forgot to mention (or a link to one that no longer exists), or a tool
table that drifted from the server's real surface would each send a reader
to a config that cannot work. CI checks out tracked files only, so an
untracked fragment is the same as a missing one — the same trap
``tests/test_docs_links.py`` guards for the docs.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
HARNESSES_DIR = REPO / "integrations" / "harnesses"
DOC = REPO / "docs" / "HARNESSES.md"
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"

#: The fragment set the map documents. A new harness means a new fragment, a
#: new section in docs/HARNESSES.md, and a name here — in one change, or
#: this file goes red.
EXPECTED_FRAGMENTS = {
    "claude-code.mcp.json",
    "generic.mcp.json",
    "opencode.json",
    "openclaw.config.json",
    "codex.config.toml",
    "grok.config.toml",
}

#: The matrix rows docs/HARNESSES.md must carry. A harness dropped from the
#: map goes red here.
EXPECTED_HARNESSES = (
    "Hermes Agent",
    "OpenBot",
    "Claude Code",
    "Codex (CLI",
    "OpenCode",
    "Gemini CLI",
    "Cursor",
    "VS Code (Copilot",
    "grok CLI",
    "OpenClaw",
    "MausBot and OpenMausBot",
    "OpenAI dots",
)

_TOOL_ROW = re.compile(r"^\| `(entropicmem_[a-z_]+)` \|", re.MULTILINE)
_SNIPPET_LINK = re.compile(r"\]\(\.\./integrations/harnesses/([A-Za-z0-9._-]+)\)")


def test_the_fragment_set_is_exactly_the_documented_one() -> None:
    on_disk = {path.name for path in HARNESSES_DIR.iterdir() if path.is_file()}
    assert on_disk == EXPECTED_FRAGMENTS, (
        "integrations/harnesses/ drifted from the map: change the fragment "
        "set and docs/HARNESSES.md together, and update EXPECTED_FRAGMENTS"
    )


@pytest.mark.parametrize(
    "name",
    sorted(fragment for fragment in EXPECTED_FRAGMENTS if fragment.endswith(".json")),
)
def test_json_fragments_parse_and_name_the_real_entry_point(name: str) -> None:
    payload = json.loads((HARNESSES_DIR / name).read_text(encoding="utf-8"))
    servers = payload.get("mcpServers") or payload["mcp"]["servers"]
    assert list(servers) == ["entropicmem"], (
        f"{name}: exactly one server entry, named entropicmem"
    )
    entry = servers["entropicmem"]
    command = entry["command"]
    if isinstance(command, list):  # OpenCode's array form
        assert command == ["entropicmem-mcp"], f"{name}: the launch command moved"
    else:
        assert command == "entropicmem-mcp", f"{name}: the launch command moved"
        assert entry["args"] == [], f"{name}: args must stay empty by default"


@pytest.mark.parametrize("name", ["codex.config.toml", "grok.config.toml"])
def test_toml_fragments_pin_the_real_entry_point(name: str) -> None:
    text = (HARNESSES_DIR / name).read_text(encoding="utf-8")
    assert "[mcp_servers.entropicmem]" in text, f"{name}: the server table moved"
    assert 'command = "entropicmem-mcp"' in text, f"{name}: the launch command moved"


def test_the_map_links_every_fragment() -> None:
    text = DOC.read_text(encoding="utf-8")
    linked = set(_SNIPPET_LINK.findall(text))
    assert linked == EXPECTED_FRAGMENTS, (
        "docs/HARNESSES.md must link each fragment via "
        "../integrations/harnesses/<name>; missing or extra: "
        f"{linked ^ EXPECTED_FRAGMENTS}"
    )


def test_the_matrix_rows_every_expected_harness() -> None:
    text = DOC.read_text(encoding="utf-8")
    missing = [label for label in EXPECTED_HARNESSES if f"| {label}" not in text]
    assert not missing, f"docs/HARNESSES.md lost matrix rows: {missing}"


def test_the_tool_table_matches_the_server_that_ships(tmp_path: Path) -> None:
    documented = set(_TOOL_ROW.findall(DOC.read_text(encoding="utf-8")))
    served = _tools_list_names(tmp_path)
    assert documented == served, (
        "docs/HARNESSES.md's tool table drifted from em/mcp_server.py's "
        f"real surface: doc-only={documented - served}, "
        f"server-only={served - documented}"
    )


def test_fragments_carry_no_absolute_user_paths_or_credentials() -> None:
    """The repo is public: fragments must stay placeholder-only."""
    banned = ("/home/", "/Users/", "AKIA", "ASIA", "password", "token", "secret")
    for path in sorted(HARNESSES_DIR.iterdir()):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8").lower()
        for needle in banned:
            assert needle not in text, f"{path.name} mentions {needle!r}"


def _tools_list_names(tmp_path: Path) -> set[str]:
    """Boot the real server over stdio and read tools/list — the same drive
    tests/test_mcp_server.py uses, reduced to the one call this guard needs."""
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    payload = "\n".join(json.dumps(request) for request in requests) + "\n"
    env = {k: v for k, v in os.environ.items() if not k.startswith("ENTROPICMEM_")}
    env["PYTHONPATH"] = str(SCRIPTS)
    proc = subprocess.run(
        [sys.executable, "-m", "em.mcp_server", "--home", str(tmp_path / "home")],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    names: set[str] = set()
    for line in proc.stdout.splitlines():
        try:
            frame = json.loads(line)
        except json.JSONDecodeError:
            continue
        for tool in (frame.get("result") or {}).get("tools", []):
            if tool.get("name"):
                names.add(str(tool["name"]))
    assert names, (
        "the server did not answer tools/list: "
        f"rc={proc.returncode}, stderr tail: {proc.stderr[-300:]}"
    )
    return names
