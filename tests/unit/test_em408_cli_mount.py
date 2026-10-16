"""EM-408: the host-discovered ``hermes entropicmem …`` CLI mount.

The card's AC: *"``hermes entropicmem stats`` works when the provider is
active."* The host discovers the plugin CLI only while ``memory.provider:
entropicmem`` — ``plugins.memory.discover_plugin_cli_commands`` finds
``<plugin_dir>/cli.py``, imports it as ``_hermes_user_memory.entropicmem.cli``
with synthetic parents (the plugin ``__init__.py`` never executes), calls
``register_cli(<the parser for ``hermes entropicmem``>)`` and wires
``entropicmem_command`` as that parser's ``func``
(``hermes_cli/main.py``'s ``_attach_plugin_cli_command``).

These tests emulate exactly that loading path, so the mount is exercised on CI
where the host is absent; ``test_the_host_discovery_contract_is_pinned``
re-derives the contract statically from a reachable hermes-agent checkout
(skipped in CI, like ``test_provider_contract.py`` — read-only, no host
import). The one hazard the emulation must prove: the host parses with
``dest="command"`` and reads ``args.command`` after parsing, so the mounted
tree may not reuse that dest — it parses into ``entropicmem_command`` instead.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "plugins" / "entropicmem" / "scripts"
PLUGIN_DIR = ROOT / "plugins" / "entropicmem"
CLI_PY = PLUGIN_DIR / "cli.py"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

#: The module name the host gives a user-installed provider's cli.py.
HOST_CLI_MODULE = "_hermes_user_memory.entropicmem.cli"

#: Where the pinned hermes-agent checkout may live — the same candidate order
#: as ``test_provider_contract.py``, pointed at the memory plugin loader.
HOST_CANDIDATES = (
    Path(os.environ.get("ENTROPICMEM_HERMES_AGENT", "")) / "plugins" / "memory" / "__init__.py",
    Path(os.environ.get("ENTROPICMEM_HERMES_AGENT_DIR", "")) / "plugins" / "memory" / "__init__.py",
    Path.home() / ".hermes" / "hermes-agent" / "plugins" / "memory" / "__init__.py",
    Path(os.environ.get("HERMES_HOME", "")) / "hermes-agent" / "plugins" / "memory" / "__init__.py",
)


def _host_memory_init() -> "Path | None":
    """The pinned host's ``plugins/memory/__init__.py``, or None."""
    for candidate in HOST_CANDIDATES:
        if str(candidate) and candidate.is_file():
            return candidate
    return None


def _load_plugin_cli():
    """Load ``cli.py`` the way the host does: by path, namespaced, no ``__init__``."""
    spec = importlib.util.spec_from_file_location(HOST_CLI_MODULE, CLI_PY)
    assert spec and spec.loader, "cli.py must be importable by path"
    mod = importlib.util.module_from_spec(spec)
    sys.modules[HOST_CLI_MODULE] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.modules.pop(HOST_CLI_MODULE, None)
    return mod


def _host_shaped_parser(cli_mod):
    """The three host steps: add_parser("entropicmem"), register_cli, set func."""
    top = argparse.ArgumentParser(prog="hermes")
    subs = top.add_subparsers(dest="command")
    plugin_parser = subs.add_parser("entropicmem")
    cli_mod.register_cli(plugin_parser)
    plugin_parser.set_defaults(func=cli_mod.entropicmem_command)
    return top


def _hermetic(tmp_path, monkeypatch) -> None:
    """HOME/HERMES_HOME into tmp_path so no CLI read or write can touch ~/.hermes."""
    home = tmp_path / "home"
    (home / "entropicmem").mkdir(parents=True, exist_ok=True)
    for var in ("HOME", "USERPROFILE", "HERMES_HOME"):
        monkeypatch.setenv(var, str(home))
    for var in ("ENTROPICMEM_MEMORY_DB", "ENTROPICMEM_INDEX_DB", "ENTROPICMEM_VAULT_PATH"):
        monkeypatch.delenv(var, raising=False)


def test_the_plugin_exposes_the_host_discovery_contract():
    """cli.py sits where find_provider_dir looks and carries both entry points."""
    assert CLI_PY.is_file(), "the host discovers exactly <plugin_dir>/cli.py"
    cli = _load_plugin_cli()
    assert callable(getattr(cli, "register_cli", None))
    assert callable(getattr(cli, "entropicmem_command", None))


def test_the_card_ac_runs_stats_through_the_mount(tmp_path, monkeypatch, capsys):
    """`hermes entropicmem stats` works — and the flags mount with it."""
    _hermetic(tmp_path, monkeypatch)
    top = _host_shaped_parser(_load_plugin_cli())

    args = top.parse_args(["entropicmem", "stats"])
    assert args.func(args) == 0
    assert "Facts: 0" in capsys.readouterr().out

    args = top.parse_args(["entropicmem", "--version"])
    assert args.func(args) == 0
    import em

    assert f"v{em.__version__}" in capsys.readouterr().out


def test_the_mount_never_clobbers_the_hosts_command_dest():
    """dest="entropicmem_command" leaves the host's args.command intact."""
    top = _host_shaped_parser(_load_plugin_cli())

    args = top.parse_args(["entropicmem", "stats"])
    assert args.command == "entropicmem"
    assert args.entropicmem_command == "stats"

    args = top.parse_args(["entropicmem", "worker", "run"])
    assert args.command == "entropicmem"
    assert args.entropicmem_command == "worker"
    assert args.worker_command == "run"


def test_the_mounted_tree_is_the_standalone_tree():
    """One builder: the standalone parser and a bare mount offer the same commands."""
    from em.cli.parser import add_commands, build_parser

    def commands(parser: argparse.ArgumentParser) -> set:
        action = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
        return set(action.choices)

    standalone = build_parser()
    mounted = argparse.ArgumentParser(prog="hermes entropicmem")
    add_commands(mounted, dest="entropicmem_command")
    assert commands(standalone) == commands(mounted)
    assert "stats" in commands(standalone)
    assert len(commands(standalone)) >= 30  # sanity floor: a broken parse would shrink the set


def test_the_standalone_cli_still_dispatches_stats(tmp_path):
    """main() = build_parser + dispatch: the script path is unchanged by the split."""
    home = tmp_path / "home"
    (home / "entropicmem").mkdir(parents=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith("ENTROPICMEM_")}
    env.update(
        HOME=str(home),
        USERPROFILE=str(home),
        HERMES_HOME=str(home),
        PYTHONPATH=str(SCRIPTS),
    )
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / "entropicmem.py"), "stats"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "Facts: 0" in proc.stdout


def test_dispatch_returns_the_unknown_command_exit_code(capsys):
    """The handler's return IS the exit code (the mount's func contract)."""
    import entropicmem

    rc = entropicmem.dispatch(
        argparse.Namespace(entropicmem_command="no-such-command"),
        dest="entropicmem_command",
    )
    assert rc == 1
    assert "no-such-command" in capsys.readouterr().err


def test_the_host_discovery_contract_is_pinned():
    """The host-side contract this mount relies on, re-derived when reachable."""
    host_init = _host_memory_init()
    if host_init is None:
        pytest.skip("hermes-agent checkout not reachable (CI: the host is absent)")
    source = host_init.read_text(encoding="utf-8")
    for needle in (
        'if not plugin_dir or not (plugin_dir / "cli.py").exists():',
        'module_name = _module_name(plugin_dir, active_provider) + ".cli"',
        '_register_synthetic_package(_module_name(plugin_dir, active_provider), [str(plugin_dir)])',
        'register_cli = getattr(cli_mod, "register_cli", None)',
        '"handler_fn": getattr(cli_mod, f"{active_provider}_command", None),',
        'return cfg_get(config, "memory", "provider") or None',
    ):
        assert needle in source, f"host discovery changed: {needle!r}"

    host_root = host_init.parents[2]
    main_py = (host_root / "hermes_cli" / "main.py").read_text(encoding="utf-8")
    for needle in (
        'cmd_info["setup_fn"](plugin_parser)',
        'plugin_parser.set_defaults(func=cmd_info["handler_fn"])',
    ):
        assert needle in main_py, f"host mount changed: {needle!r}"
    parser_py = (host_root / "hermes_cli" / "_parser.py").read_text(encoding="utf-8")
    assert (
        'subparsers = parser.add_subparsers(dest="command", help="Command to run", metavar="<command>")'
        in parser_py
    ), "the host's top-level dest changed — revisit the mount's dest choice"
