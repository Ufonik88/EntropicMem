"""EM-212: ``_backend`` does not resolve engine modules through ``sys.modules``.

``resolve_paths`` did ``from vault import resolve_vault_path`` after putting the
plugin's ``scripts/`` at ``sys.path[0]``. The Hermes host runs many plugins in
one process. If any of them had already imported a module named ``vault``, the
import returned *that* module: EntropicMem then crashed on a missing function,
or silently resolved another plugin's vault path. The acceptance test is the
strict xfail ``test_f010_no_bare_module_imports_in_backend`` in
``tests/regressions/test_findings_v27.py``. This file pins the behaviour it
protects.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from plugins.entropicmem import _backend  # noqa: E402


def _decoy(monkeypatch, **attrs) -> types.ModuleType:
    mod = types.ModuleType("vault")
    mod.__dict__.update(attrs)
    monkeypatch.setitem(sys.modules, "vault", mod)
    return mod


def test_a_foreign_vault_module_is_not_used(tmp_path, monkeypatch):
    monkeypatch.delenv("ENTROPICMEM_VAULT_PATH", raising=False)
    decoy = _decoy(monkeypatch, resolve_vault_path=lambda *a, **k: Path("/somewhere/else"))
    vault, index_db, memory_db = _backend.resolve_paths(tmp_path, {})
    assert vault == (tmp_path / "entropicmem" / "vault").resolve()
    assert sys.modules["vault"] is decoy, "the other plugin's module must be left in place"


def test_a_foreign_vault_module_without_the_function_does_not_crash(tmp_path, monkeypatch):
    monkeypatch.delenv("ENTROPICMEM_VAULT_PATH", raising=False)
    _decoy(monkeypatch)  # a 'vault' module with no resolve_vault_path at all
    vault, _, _ = _backend.resolve_paths(tmp_path, {"vault_path": str(tmp_path / "v")})
    assert vault == (tmp_path / "v").resolve()


def test_precedence_is_unchanged(tmp_path, monkeypatch):
    monkeypatch.setenv("ENTROPICMEM_VAULT_PATH", str(tmp_path / "from-env"))
    assert _backend.resolve_paths(tmp_path, {})[0] == (tmp_path / "from-env").resolve()
    explicit = _backend.resolve_paths(tmp_path, {"vault_path": str(tmp_path / "cfg")})[0]
    assert explicit == (tmp_path / "cfg").resolve()
