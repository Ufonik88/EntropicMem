"""The docs' command counts are pinned to argparse, not to memory.

`docs/CLI_REFERENCE.md` and `README.md` both state how many top-level commands
the CLI has, and that number has already drifted once: the EM-209 commit that
added `worker run` had to hand-fix `34` to `35` in both files. Here the count
and the names come from the CLI's own `--help` output, so the next command
cannot land without its documentation. `--help` stays dependency-free by
contract: it runs on the standard library alone.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CLI = REPO / "plugins" / "entropicmem" / "scripts" / "entropicmem.py"
REFERENCE = REPO / "docs" / "CLI_REFERENCE.md"
README = REPO / "README.md"

# Fewer than this means the usage line was parsed wrongly, not that the CLI shrank.
_SANITY_FLOOR = 20


def _cli_env() -> dict:
    """A live-store path in the environment must never reach the CLI."""
    return {key: value for key, value in os.environ.items() if not key.startswith("ENTROPICMEM_")}


@lru_cache(maxsize=1)
def top_level_commands() -> tuple:
    """The subcommand list, read from the CLI's own usage line."""
    result = subprocess.run(
        [sys.executable, str(CLI), "--help"],
        env=_cli_env(),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"--help failed: {result.stderr}"
    match = re.search(r"\{([^}]+)\}", result.stdout)
    assert match, f"no subcommand list in --help output:\n{result.stdout}"
    commands = tuple(name.strip() for name in match.group(1).split(",") if name.strip())
    assert len(commands) > _SANITY_FLOOR, f"suspiciously short command list: {commands}"
    return commands


def _declared_count(path: Path) -> int:
    match = re.search(r"(\d+) top-level commands", path.read_text(encoding="utf-8"))
    assert match, f"{path.name} no longer states a top-level command count"
    return int(match.group(1))


def test_reference_declares_the_real_command_count() -> None:
    assert _declared_count(REFERENCE) == len(top_level_commands())


def test_readme_declares_the_real_command_count() -> None:
    assert _declared_count(README) == len(top_level_commands())


def test_every_top_level_command_has_a_reference_entry() -> None:
    """Each name must be a whole backticked token, not a prefix of another.

    A plain substring check passes on `` `worker-run` `` for the command
    ``worker``: the word has to END there too (backtick, space, or any other
    non-word, non-dash character).
    """
    reference = REFERENCE.read_text(encoding="utf-8")
    missing = [
        name
        for name in top_level_commands()
        if not re.search(rf"`{re.escape(name)}(?:`|[^\w-])", reference)
    ]
    assert not missing, f"no entry in docs/CLI_REFERENCE.md for: {missing}"