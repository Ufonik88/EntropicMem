"""The ``hermes entropicmem …`` CLI surface (EM-408).

The host discovers this module only while ``memory.provider: entropicmem``
(``plugins.memory.discover_plugin_cli_commands``): it imports this file as
``_hermes_user_memory.entropicmem.cli`` with synthetic parent packages (the
plugin ``__init__.py`` is never executed), calls ``register_cli`` with the
parser it made for ``hermes entropicmem``, and wires ``entropicmem_command``
as that parser's ``func``.

Keep this module safe to import during argparse setup — the host builds the
top-level parser on every invocation: it imports no host and nothing heavy.
The command tree itself is shared with ``scripts/entropicmem.py`` through
``em/cli/parser.py``; only the root subparsers' ``dest`` differs, so the
top-level ``hermes`` parser's ``args.command`` is never clobbered.
"""

from __future__ import annotations

import sys
from pathlib import Path

# The host imports this file by path, so the path setup that
# ``scripts/entropicmem.py`` and the plugin's ``__init__.py`` perform cannot
# have run: put the plugin's ``scripts/`` dir (the ``em`` package and the
# standalone CLI module) on sys.path first.
_SCRIPTS_DIR = Path(__file__).resolve().parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

_DEST = "entropicmem_command"


def register_cli(subparser) -> None:
    """Mount the shared command tree onto the host's ``hermes entropicmem`` parser."""
    from em.cli.parser import add_commands

    add_commands(subparser, dest=_DEST)
    # dispatch() prints this parser's own help for a bare `hermes entropicmem`.
    subparser.set_defaults(_entropicmem_parser=subparser)


def entropicmem_command(args) -> int:
    """The host's ``func``: run the selected command, return its exit code."""
    from entropicmem import dispatch

    return dispatch(args, dest=_DEST, parser=getattr(args, "_entropicmem_parser", None))
