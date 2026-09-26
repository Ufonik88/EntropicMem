"""EM-211 foundation: the provider's engine contract cannot drift silently.

``em.facade.contract.PROVIDER_CALLS`` must equal what the provider source
actually calls, and every engine implementation must accept every recorded
call. When EM-211 lands, add the v3 facade to ``IMPLEMENTATIONS``.
"""

from __future__ import annotations

import ast
import inspect
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from em.facade import contract  # noqa: E402

PROVIDER = REPO / "plugins" / "entropicmem" / "__init__.py"


def _implementations():
    from memory_engine import MemoryEngine

    # EM-211: append the v3 facade class here, e.g. ("v3-facade", V3Engine).
    return [("v2", MemoryEngine)]


def _scan_provider() -> tuple[dict, set]:
    """(calls, attributes) on any name called ``engine`` in the provider."""
    tree = ast.parse(PROVIDER.read_text(encoding="utf-8"))
    calls: dict[str, tuple[set, set]] = {}
    called_nodes = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "engine"
        ):
            kw, npos = calls.setdefault(node.func.attr, (set(), set()))
            if any(k.arg is None for k in node.keywords):
                raise AssertionError(f"engine.{node.func.attr}(**kwargs) defeats the contract scan")
            kw.update(k.arg for k in node.keywords)
            npos.add(len(node.args))
            called_nodes.add(id(node.func))
    attrs = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "engine"
        and id(node) not in called_nodes
    }
    return calls, attrs


def test_contract_table_matches_the_provider_source():
    calls, _ = _scan_provider()
    found = {m: (frozenset(kw), frozenset(n)) for m, (kw, n) in calls.items()}
    assert found == contract.PROVIDER_CALLS, (
        "the provider's engine calls changed: update em/facade/contract.py "
        "PROVIDER_CALLS deliberately (and the v3 facade with it)"
    )


def test_non_call_attribute_access_is_recorded():
    _, attrs = _scan_provider()
    assert attrs == set(contract.PROVIDER_ATTRIBUTES), attrs


def test_every_behaviour_is_described():
    assert contract.BEHAVIOURS
    for key, text in contract.BEHAVIOURS.items():
        assert key == key.strip().lower() and " " not in key
        assert len(text) > 20


@pytest.mark.parametrize("name,impl", _implementations())
def test_implementation_accepts_every_recorded_call(name, impl):
    for method, (kwargs, positional_counts) in contract.PROVIDER_CALLS.items():
        fn = getattr(impl, method, None)
        assert callable(fn), f"{name} lacks {method}"
        sig = inspect.signature(fn)
        for npos in positional_counts:
            try:
                sig.bind(object(), *([None] * npos), **{k: None for k in kwargs})
            except TypeError as exc:
                raise AssertionError(f"{name}.{method} rejects the provider's call: {exc}") from exc
    for attr in ("__enter__", "__exit__"):
        assert callable(getattr(impl, attr, None)), f"{name} is not a context manager"


def test_v2_stored_fact_satisfies_fact_view():
    from memory_engine import StoredFact

    assert isinstance(StoredFact(id="x", content="y"), contract.FactView)
