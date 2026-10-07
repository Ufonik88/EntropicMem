"""
Regression guard for the plugin's deferred imports (v2.3.2).

The plugin defers `from <module> import <name>` inside tool handlers so the
Hermes process can load without the scripts dir on sys.path. On 2026-08-14
`entropicmem_query` broke at call time because it imported `retrieve`, a
name `retrieval.py` never exported. Nothing caught it: the plugin imports
fine, and the ImportError only fires when the tool runs.

These tests:
  1. AST-scan every deferred `from <scripts-module> import <name>` in the
     plugin and assert the name actually exists in the module.
  2. Exercise `_query` end-to-end against a real temp vault + index.
"""
import ast
import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
PLUGIN = REPO / "plugins" / "entropicmem" / "__init__.py"

sys.path.insert(0, str(SCRIPTS))

# Modules that live in the scripts dir (plugin imports them by bare name).
# EM-212 moved six of them under the ``em_internal`` package, so the scan must
# follow them there — otherwise the 2026-08-14 bug class (a deferred import of a
# name the module never exported) stops being checked for those six.
SCRIPT_MODULES = {
    p.stem for p in SCRIPTS.glob("*.py") if p.stem != "__init__"
}
SCRIPT_MODULES |= {
    f"em_internal.{p.stem}"
    for p in (SCRIPTS / "em_internal").glob("*.py")
    if p.stem != "__init__"
}


def _load_plugin_module():
    # Mirror conftest.py: mock the agent.memory_provider base before import.
    if "agent.memory_provider" not in sys.modules:
        mock_mp = MagicMock()
        sys.modules.setdefault("agent", MagicMock())
        sys.modules["agent.memory_provider"] = mock_mp
        mock_mp.MemoryProvider = type("MemoryProvider", (), {})
    spec = importlib.util.spec_from_file_location(
        "entropicmem_plugin_imports",
        PLUGIN,
        submodule_search_locations=[str(PLUGIN.parent)],
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["entropicmem_plugin_imports._backend"] = MagicMock()
    # Register the module itself, as a real import would. Without this a relative
    # submodule import (`from . import _shadow`) cannot resolve its parent package and
    # raises ModuleNotFoundError for a module that is right there — a harness artefact,
    # not a plugin defect, and one that would hide a genuine relative-import break.
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _deferred_imports():
    """Yield (module, name, lineno) for deferred script-module imports."""
    tree = ast.parse(PLUGIN.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in SCRIPT_MODULES:
            for alias in node.names:
                yield node.module, alias.name, node.lineno


def test_deferred_imports_resolve():
    """Every deferred `from X import Y` in the plugin must exist in X."""
    failures = []
    checked = 0
    for module, name, lineno in _deferred_imports():
        checked += 1
        target = importlib.import_module(module)
        if not hasattr(target, name):
            failures.append(f"{module}.{name} (plugin line {lineno})")
    assert checked > 0, "no deferred imports found — scan is broken"
    assert not failures, "plugin imports names that do not exist: " + ", ".join(failures)


def test_deferred_import_scan_covers_retrieval():
    """Sanity: the scan sees the retrieval import (the 2026-08-14 bug class).

    ``retrieval`` now lives under ``em_internal`` (EM-212), so the match is on
    the qualified module name.
    """
    seen = {(m, n) for m, n, _ in _deferred_imports() if m.endswith("retrieval")}
    assert seen, "retrieval import not found in plugin"
    assert all(name.startswith("retrieve") for name in {n for _, n in seen})


def test_query_tool_end_to_end(tmp_path):
    """`_query` returns cited results against a real vault + index."""
    plugin_mod = _load_plugin_module()

    vault_path = tmp_path / "vault"
    index_path = tmp_path / "index.db"

    from em_internal.index import VaultIndex
    from em_internal.vault import Vault

    vault = Vault(vault_path)
    vault.root.mkdir(parents=True, exist_ok=True)
    vault.write_note(
        folder="Knowledge",
        title="Orbital Mechanics Primer",
        body="Delta-v budgets dominate mission design. [[Launch Windows]]",
    )
    vault.write_note(
        folder="Knowledge",
        title="Launch Windows",
        body="Hohmann transfers define the cheapest launch windows.",
    )
    index = VaultIndex(index_path)
    index.rebuild(vault)
    index.close()

    provider = plugin_mod.EntropicMemMemoryProvider(config={})
    provider._vault_path = vault_path
    provider._index_db = index_path
    provider._scripts_dir = SCRIPTS

    out = provider._query({"query": "launch windows", "top_k": 5})
    payload = json.loads(out)
    assert "error" not in payload, f"_query returned error: {payload}"
    titles = [r["title"] for r in payload["results"]]
    assert any("Launch Windows" in t for t in titles), titles
    # contract: hits carry citation fields
    first = payload["results"][0]
    for key in ("note_id", "title", "path", "domain", "snippet"):
        assert key in first, f"missing citation field: {key}"


def test_query_tool_empty_query_errors():
    plugin_mod = _load_plugin_module()
    provider = plugin_mod.EntropicMemMemoryProvider(config={})
    out = provider._query({"query": "   "})
    assert "error" in json.loads(out)
