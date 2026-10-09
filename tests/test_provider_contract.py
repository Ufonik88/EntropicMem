"""EM-401's second acceptance criterion: the pinned host contract.

*"Contract test enumerates ``MemoryProvider`` methods from the pinned
hermes-agent and asserts each optional one is implemented or explicitly listed
as intentionally unimplemented."*

The host is not on ``sys.path`` in CI — and must not be, since a test that
depends on the host being importable would be skipped there. So the enumeration
is **pinned**: ``tests/harness/pinned_memory_provider.json`` is a dated copy of
the base class this plugin is developed against. On a box where the host is
reachable the pin is re-derived and compared, so a host upgrade that adds or
changes a method fails loudly instead of silently widening what the host may
call. On CI the pin is the contract, and every check below still runs.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import os
import sys
import types
from pathlib import Path
from typing import Dict, List, Optional

import pytest

REPO = Path(__file__).resolve().parent.parent
PIN_PATH = REPO / "tests" / "harness" / "pinned_memory_provider.json"
MANIFEST_PATH = REPO / "plugins" / "entropicmem" / "plugin.yaml"
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from em.provider import provider as surface  # noqa: E402

#: Where the pinned hermes-agent checkout may live, in order. The first env var
#: lets a CI job or a developer point at another checkout deliberately.
HOST_CANDIDATES = (
    Path(os.environ.get("ENTROPICMEM_HERMES_AGENT", "")) / "agent" / "memory_provider.py",
    Path(os.environ.get("ENTROPICMEM_HERMES_AGENT_DIR", "")) / "agent" / "memory_provider.py",
    Path.home() / ".hermes" / "hermes-agent" / "agent" / "memory_provider.py",
    Path(os.environ.get("HERMES_HOME", "")) / "hermes-agent" / "agent" / "memory_provider.py",
)

_PIN: Dict[str, object] = json.loads(PIN_PATH.read_text(encoding="utf-8"))
_HOST_MODULE_NAME = "_contract_host_memory_provider"


# ── the host, when it is reachable ────────────────────────────────────────────


def _host_file() -> Optional[Path]:
    """The pinned host's ``agent/memory_provider.py``, or None."""
    for candidate in HOST_CANDIDATES:
        if str(candidate) and candidate.is_file():
            return candidate
    return None


def _load_host_class():
    """Load the host base class by FILE PATH.

    ``tests/conftest.py`` installs a ``MagicMock`` for ``agent.memory_provider``
    so the plugin can be imported without the host; loading the real file under
    a private module name reads it without disturbing that mock (the module
    imports only stdlib).
    """
    path = _host_file()
    if path is None:
        pytest.skip("pinned hermes-agent not reachable on this box")
    spec = importlib.util.spec_from_file_location(_HOST_MODULE_NAME, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[_HOST_MODULE_NAME] = module
    try:
        spec.loader.exec_module(module)
        return module.MemoryProvider, module
    finally:
        sys.modules.pop(_HOST_MODULE_NAME, None)


def _enumerate(cls, module=None) -> Dict[str, object]:
    """The pin's shape, derived from a live class."""
    kinds = {
        inspect.Parameter.POSITIONAL_ONLY: "positional_only",
        inspect.Parameter.POSITIONAL_OR_KEYWORD: "positional_or_keyword",
        inspect.Parameter.KEYWORD_ONLY: "keyword_only",
        inspect.Parameter.VAR_POSITIONAL: "var_positional",
        inspect.Parameter.VAR_KEYWORD: "var_keyword",
    }
    methods: Dict[str, Dict[str, object]] = {}
    abstract: List[str] = []
    for name, value in sorted(vars(cls).items()):
        if name.startswith("__") or name == "_abc_impl":
            continue
        is_property = isinstance(value, property)
        fn = value.fget if is_property else value
        if not isinstance(fn, types.FunctionType):
            continue
        methods[name] = {
            "property": is_property,
            "params": [
                {
                    "name": p.name,
                    "kind": kinds[p.kind],
                    "has_default": p.default is not inspect.Parameter.empty,
                }
            for p in inspect.signature(fn).parameters.values()
            ],
        }
        if getattr(fn, "__isabstractmethod__", False):
            abstract.append(name)
    return {
        "abstract_methods": sorted(set(abstract)),
        "methods": methods,
        "class_constant": {
            "pre_compress_checkpoint_api_version": cls.pre_compress_checkpoint_api_version
        },
        "module_constant": {
            "PRE_COMPRESS_CHECKPOINT_API_VERSION": (
                module.PRE_COMPRESS_CHECKPOINT_API_VERSION if module is not None else None
            )
        },
    }


def _pin_shape() -> Dict[str, object]:
    """The pin reduced to what ``_enumerate`` produces (its prose fields drop)."""
    return {
        "abstract_methods": _PIN["abstract_methods"],
        "methods": _PIN["methods"],
        "class_constant": _PIN["class_constant"],
        "module_constant": _PIN["module_constant"],
    }


def _provider():
    """A fresh, uninitialized provider: the contract is about the class."""
    from plugins.entropicmem import EntropicMemMemoryProvider

    return EntropicMemMemoryProvider()


def _manifest() -> Dict[str, object]:
    text = MANIFEST_PATH.read_text(encoding="utf-8")
    try:
        import yaml

        return yaml.safe_load(text)
    except ImportError:
        pass
    data: Dict[str, object] = {}
    current = None
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[0] not in " \t":
            key, _, val = line.partition(":")
            current = key.strip()
            data[current] = [] if not val.strip() else val.strip().strip('"')
        elif line.strip().startswith("- ") and isinstance(data.get(current), list):
            data[current].append(line.strip()[2:].strip())
    return data


def _binds(fn, params: List[Dict[str, object]]) -> Optional[str]:
    """None when *fn* accepts a call shaped like the base's *params*, else why not."""
    args, kwargs = [], {}
    for index, param in enumerate(params):
        name = str(param["name"])
        if name == "self":
            continue
        if param["kind"] in ("positional_only", "positional_or_keyword"):
            args.append(f"<{name}>")
        elif param["kind"] == "keyword_only":
            kwargs[name] = f"<{name}>"
        # var_positional / var_keyword: the base accepts anything extra.
    try:
        inspect.signature(fn).bind(*args, **kwargs)
    except TypeError as exc:
        return str(exc)
    return None


# ── the pin itself ────────────────────────────────────────────────────────────


def test_the_pin_records_a_host_source_and_date():
    assert _PIN["source"] == "agent/memory_provider.py"
    assert "hermes-agent" in str(_PIN["pinned_from"])
    assert "2026-" in str(_PIN["pinned_from"]), "the pin must say when it was taken"


def test_the_pin_matches_the_host_when_the_host_is_reachable():
    """A host upgrade must move the pin deliberately.

    Skips when the host is not on this machine (CI); the pin is then the
    contract and the checks below still run against it.
    """
    cls, module = _load_host_class()
    live = _enumerate(cls, module)
    assert live == _pin_shape(), (
        "the pinned hermes-agent differs from tests/harness/pinned_memory_provider.json — "
        "re-derive the pin deliberately (the host's hook surface is what the catalog "
        "review verifies the plugin against) and note the new date"
    )


def test_the_pin_carries_the_checkpoint_api_version():
    # The base class defaults to the best-effort v1 contract; a provider that
    # durably checkpoints opts in to 2 (host: PRE_COMPRESS_CHECKPOINT_API_VERSION).
    assert _PIN["class_constant"]["pre_compress_checkpoint_api_version"] == 1
    assert _PIN["module_constant"]["PRE_COMPRESS_CHECKPOINT_API_VERSION"] == 2


# ── the provider against the pinned contract ──────────────────────────────────


def test_the_provider_implements_or_defers_every_pinned_method():
    provider = _provider()
    unaccounted = []
    for name, entry in _PIN["methods"].items():
        if entry["property"]:
            # The host reads it as an attribute (``name``); it is "implemented"
            # when the provider's class exposes it as a property returning a str.
            if isinstance(getattr(type(provider), name, None), property):
                continue
        elif callable(getattr(provider, name, None)):
            continue
        if name in surface.deferred():
            continue
        unaccounted.append(name)
    assert not unaccounted, (
        f"pinned MemoryProvider methods neither implemented nor deferred: "
        f"{sorted(unaccounted)} — implement them or add a row to "
        "em.provider.provider.HOOK_SURFACE naming the card that lands them"
    )


def test_the_surface_table_and_the_provider_agree():
    """Both directions: no implemented row missing, no deferred row shipped."""
    provider = _provider()
    problems = surface.audit(provider)
    assert not problems, "\n".join(problems)


def test_audit_reports_a_real_problem():
    """The audit must be able to fail — an always-empty one proves nothing.

    Fed a stand-in class with a row missing and one shipped early, the way a
    provider that forgets a hook (or lands a deferred one) would look. Without
    this, ``assert not audit(provider)`` passes against a broken auditor.
    """
    class MissingAHook:
        def name(self):
            return "stub"

    problems = surface.audit(MissingAHook())
    assert problems, "an audit of a class missing rows must report them"
    assert any("initialize" in p for p in problems)

    class EarlyHook:
        def name(self):
            return "stub"

        def identity_signature(self):  # deferred to EM-402
            return {}

    problems = surface.audit(EarlyHook())
    assert any("identity_signature" in p for p in problems)


def test_the_deferred_set_is_exactly_the_unimplemented_pinned_methods():
    """Both ways: an unimplemented pinned method must be deferred, and a
    deferred row must still be one the host may call (renaming it away must not
    silently widen the gap the contract covers)."""
    provider = _provider()
    gaps = set()
    for name, entry in _PIN["methods"].items():
        if entry["property"]:
            if not isinstance(getattr(type(provider), name, None), property):
                gaps.add(name)
        elif not callable(getattr(provider, name, None)):
            gaps.add(name)
    assert set(surface.deferred()) == gaps


def test_every_deferred_hook_names_its_card_and_a_reason():
    for name, spec in surface.deferred().items():
        assert spec.deferred_to.startswith("EM-"), f"{name}: deferred to {spec.deferred_to!r}"
        assert len(spec.defer_reason) > 20, f"{name}: the reason must say why"


def test_the_provider_signature_accepts_the_pinned_call():
    provider = _provider()
    for name, entry in _PIN["methods"].items():
        if entry["property"]:
            continue  # an attribute read, not a call — checked above
        fn = getattr(provider, name, None)
        if not callable(fn):
            continue
        problem = _binds(fn, entry["params"])
        assert problem is None, f"{name} cannot be called the way the host calls it: {problem}"


def test_the_checkpoint_api_version_is_the_hosts():
    from plugins.entropicmem import EntropicMemMemoryProvider

    # The base class defaults to the best-effort v1; our provider opts in to the
    # current API version, which is the module constant in the pin.
    assert EntropicMemMemoryProvider.pre_compress_checkpoint_api_version == 2
    assert (
        EntropicMemMemoryProvider.pre_compress_checkpoint_api_version
        == _PIN["module_constant"]["PRE_COMPRESS_CHECKPOINT_API_VERSION"]
    )


def test_the_provider_is_the_class_the_host_registered():
    from plugins.entropicmem import EntropicMemMemoryProvider, MemoryProvider

    assert issubclass(EntropicMemMemoryProvider, MemoryProvider)
    assert _provider().name == "entropicmem"


def test_the_manifest_declares_exactly_the_hooks_that_exist():
    """``provides_hooks`` is what the catalog review verifies against.

    Adding an ``on_*`` hook to the provider without a manifest change — or the
    reverse — fails here, because the two lists must be the same set (and
    changing either is release-gated: see AGENTS.md's provider-tool rule).
    """
    declared = set(_manifest().get("provides_hooks") or [])
    on_hooks = {
        name
        for name in dir(type(_provider()))
        if name.startswith("on_") and callable(getattr(type(_provider()), name))
    }
    assert declared == on_hooks == set(surface.manifest_hooks())


def test_the_surface_covers_the_pins_optional_hooks():
    """Every optional hook in the pin appears in the §4.1 surface table."""
    pinned = set(_PIN["methods"])
    assert pinned <= {spec.name for spec in surface.specs()}, (
        "pinned methods missing from em.provider.provider.HOOK_SURFACE: "
        f"{sorted(pinned - {s.name for s in surface.specs()})}"
    )
