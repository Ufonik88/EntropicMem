"""EM-404 slice 2: the tool handlers live in ``em/provider/tools.py``, moved.

Slice 1 moved the seven schema constants; slice 2 moves ``get_tool_schemas``,
``handle_tool_call`` and the seven handler bodies onto ``ToolHandlers`` in the
same file, composed into the provider as a base class (the same shape EM-401
used for the plugin shell, one level in). The move is behaviour-free, so this
file pins the *layout* and the two runtime properties the split could quietly
break: the screen function stays one implementation, and the dispatch's
``fail_soft`` belt moved with it.

The behaviour-honesty side is carried by the existing source-scanning guards,
each repointed at both implementation files: the facade contract table
(``test_em_facade_contract``), the deferred-import scan
(``test_plugin_imports``), the injection-marker text
(``test_em_retrieval_packer``), the no-host rule (``test_provider_contract``),
and the raw-``MemoryEngine``/threading drift guards
(``test_em_engine_select``/``test_findings_v27``).

Rules: invented data only.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
PROVIDER = SCRIPTS / "em" / "provider" / "provider.py"
TOOLS = SCRIPTS / "em" / "provider" / "tools.py"

#: Every method the tool surface owns, and the module-level names that went
#: with them. EM-404's validation slice replaced the seven-tool surface with
#: Appendix B's nine, so the pins list the nine handlers.
TOOL_METHODS = {
    "get_tool_schemas",
    "handle_tool_call",
    "_remember",
    "_search",
    "_update",
    "_forget",
    "_timeline",
    "_entity",
    "_profile",
    "_review",
    "_stats",
}
MODULE_NAMES = {"_tool_call_failed", "_screen_for_injection"}


def _class(tree: ast.Module, name: str) -> ast.ClassDef:
    return next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name == name
    )


def _methods(cls: ast.ClassDef) -> set:
    return {
        node.name for node in cls.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def test_the_provider_composes_the_tool_handlers_mixin():
    """The moved methods are gone from the provider's class body, and it
    composes them back in through the mixin — a half-move fails here."""
    cls = _class(ast.parse(PROVIDER.read_text(encoding="utf-8")), "EntropicMemProvider")
    bases = {b.id for b in cls.bases if isinstance(b, ast.Name)}
    assert "ToolHandlers" in bases, (
        "EntropicMemProvider must compose em.provider.tools.ToolHandlers "
        "(EM-404 slice 2)"
    )
    leftover = TOOL_METHODS & _methods(cls)
    assert not leftover, (
        f"tool methods defined in the provider class body: {sorted(leftover)} — "
        "they belong in em/provider/tools.py (EM-404 slice 2)"
    )


def test_tools_defines_the_whole_tool_surface():
    tree = ast.parse(TOOLS.read_text(encoding="utf-8"))
    cls = _class(tree, "ToolHandlers")
    defined = _methods(cls)
    missing = TOOL_METHODS - defined
    assert not missing, f"ToolHandlers is missing {sorted(missing)}"
    module_defs = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert MODULE_NAMES <= module_defs, (
        f"module-level helpers moved with the handlers: missing "
        f"{sorted(MODULE_NAMES - module_defs)}"
    )
    assigned = {
        target.id
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    assert {
        "ENTITY_SCHEMA",
        "FORGET_SCHEMA",
        "INJECTION_WARNING",
        "PROFILE_SCHEMA",
        "REMEMBER_SCHEMA",
        "REVIEW_SCHEMA",
        "SEARCH_SCHEMA",
        "STATS_SCHEMA",
        "TIMELINE_SCHEMA",
        "UPDATE_SCHEMA",
    } <= assigned


def test_the_screen_function_has_one_implementation():
    """The provider screens non-tool render paths with the same function the
    recall/get handlers use — an import, not a copy that can drift — and the
    host shell re-exports the marker from its new home."""
    from plugins.entropicmem import INJECTION_WARNING as shell_warning

    from em.provider import provider as provider_mod
    from em.provider import tools as tools_mod

    assert provider_mod._screen_for_injection is tools_mod._screen_for_injection
    assert provider_mod.ToolHandlers is tools_mod.ToolHandlers
    assert shell_warning is tools_mod.INJECTION_WARNING


def test_handle_tool_call_fails_soft_like_the_hook_contract(monkeypatch):
    """§4.4: the dispatch returns a JSON string **always** — a handler that
    raises comes back as the bounded error body naming the tool, never as an
    exception. Slice 2 moved this ``fail_soft`` belt; deleting the decorator in
    ``tools.py`` makes this red (the junk-args fuzz below cannot see that:
    an uninitialized provider returns 'not initialized' before any handler
    touches its args, so nothing raises there with or without the belt)."""
    from plugins.entropicmem import EntropicMemMemoryProvider

    provider = EntropicMemMemoryProvider(config={})

    def boom(args):
        raise RuntimeError("test-only failure")

    monkeypatch.setattr(provider, "_stats", boom)
    out = provider.handle_tool_call("entropicmem_stats", {})
    assert isinstance(out, str)
    assert "entropicmem_stats" in out


def test_handle_tool_call_never_raises_on_junk_args():
    """The card's fuzz AC, first half: junk reaches the dispatch and every
    outcome is a string — unknown names, wrong-typed values, even non-dict
    args. (Validation-quality errors are a later EM-404 slice; this pins the
    dispatch surface that returned from the move.)"""
    import random

    from plugins.entropicmem import EntropicMemMemoryProvider

    provider = EntropicMemMemoryProvider(config={})
    rng = random.Random(404)
    tool_names = [
        "entropicmem_remember", "entropicmem_search", "entropicmem_update",
        "entropicmem_forget", "entropicmem_timeline", "entropicmem_entity",
        "entropicmem_profile", "entropicmem_review", "entropicmem_stats",
        "entropicmem_recall", "entropicmem_get", "entropicmem_query",
        "entropicmem_patch_core", "entropicmem_consolidate", "not_a_tool", "",
    ]
    junk = ["", None, 7, 3.14, True, ["x"], {"k": "v"}, "   ", "a" * 5000]
    keys = ["content", "query", "importance", "id", "dry_run", "junk"]
    for _ in range(120):
        name = rng.choice(tool_names)
        args = {rng.choice(keys): rng.choice(junk)}
        if rng.random() < 0.2:
            args = rng.choice(junk)  # non-dict args must not raise either
        out = provider.handle_tool_call(name, args)
        assert isinstance(out, str), (name, args, out)
