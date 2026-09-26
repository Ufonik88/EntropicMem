"""The CLI honours HERMES_HOME for the shared publish store too.

The CLI resolved its database paths from HERMES_HOME, but built every
``MemoryEngine`` without ``hermes_home``, and ``shared init`` called
``shared_path()`` with none. The shared store then defaulted to
``~/.hermes/entropicmem-shared/`` even under a custom HERMES_HOME, while the
provider (which passes its home) used ``$HERMES_HOME/entropicmem-shared/``.
The CLI and the running agent disagreed on where the shared log lives.
Reported in the Hermes catalog review of 2.8.0.

Both ``HOME`` and ``HERMES_HOME`` point into ``tmp_path``, so no test here can
touch a real ``~/.hermes``.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "plugins" / "entropicmem" / "scripts"


def _env(tmp_path: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("ENTROPICMEM_")}
    env.update(
        HOME=str(tmp_path / "home"),
        USERPROFILE=str(tmp_path / "home"),  # Windows' Path.home()
        HERMES_HOME=str(tmp_path / "custom-home"),
        PYTHONPATH=str(SCRIPTS),
    )
    (tmp_path / "home").mkdir(exist_ok=True)
    return env


def _cli(tmp_path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "entropicmem.py"), *args],
        env=_env(tmp_path),
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_shared_init_lands_under_hermes_home(tmp_path):
    out = _cli(tmp_path, "shared-init")
    assert out.returncode == 0, out.stderr
    assert (tmp_path / "custom-home" / "entropicmem-shared" / "memory.db").is_file()
    assert not (tmp_path / "home" / ".hermes").exists(), "wrote under ~/.hermes despite HERMES_HOME"


def test_cli_engines_carry_hermes_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "custom-home"))
    monkeypatch.delenv("ENTROPICMEM_MEMORY_DB", raising=False)
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    import entropicmem

    engine = entropicmem._engine()
    try:
        assert engine._hermes_home == (tmp_path / "custom-home").resolve()
        shared = engine.shared_path(engine._hermes_home)
        assert shared == (tmp_path / "custom-home" / "entropicmem-shared" / "memory.db").resolve()
    finally:
        engine.close()


def test_the_cli_builds_engines_only_through_the_helper():
    """Drift guard: a bare MemoryEngine(...) in the CLI would drop hermes_home again."""
    tree = ast.parse((SCRIPTS / "entropicmem.py").read_text(encoding="utf-8"))
    inside_helper = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_engine":
            inside_helper = {id(n) for n in ast.walk(node)}
    assert inside_helper, "the _engine() helper is missing"
    bare = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "MemoryEngine"
        and id(node) not in inside_helper
    ]
    assert not bare, f"MemoryEngine(...) built outside _engine() at lines {bare}"
