"""EM-806 (S8 packaging): the wheel ships the engine, and a pip install loads the provider.

Chunk 43 found the first half of this card by accident — a wheel built from this repo
carried `em.*` and `em_internal.*` and **no flat engine module**, so `import em.graph`
died inside `em_internal.index` (`from memory_engine import …`) outside the source
tree. It recorded the gap as "belongs to EM-806" rather than fixing it there. The
second half is the card's own AC: `pip install entropicmem` must give a Hermes host a
provider to load, which needs (a) a `hermes_agent.memory_providers` entry point,
(b) the plugin shell shipped under an importable name, and (c) the shell's
`config_schema.py`/`cli.py` shipped **beside** it, because the host reads those from
the entry point's package directory rather than importing them.

These are structural guards on `pyproject.toml` and `plugin.yaml`, not a wheel build:
the suite's venv has no setuptools, and a build test would be slower *and* weaker than
deriving the module set from the imports that need it. The build itself is checked by
the `plugin-validate` job's pip-install smoke step (which installs the wheel and loads
the provider through the host's own loader) and by hand outside CI. Nothing here
asserts product behaviour: EM-806 moves no tool, hook, schema, config key or store row.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
PLUGIN = REPO / "plugins" / "entropicmem"
PYPROJECT = REPO / "pyproject.toml"

ENTRY_POINT_GROUP = "hermes_agent.memory_providers"
ENTRY_POINT_VALUE = "entropicmem_plugin:register"

#: The manifest floor the card asks for: the first host release carrying both
#: `spawn_context_thread` and `RecallStatus`. Measured against the host's own
#: history — `spawn_context_thread` first appears in tag `v2026.9.14`, whose
#: `pyproject.toml` reads `version = "0.21.3"`; `v2026.9.11` has neither it nor
#: the same file's later shape. Do not raise it without the same evidence.
REQUIRES_HERMES = ">=0.21.3"

#: Flat modules that are CLI/ops entry points, never imported by the engine. They
#: are excluded from the wheel deliberately (the CLI is reachable as
#: `hermes entropicmem` through the shipped `cli.py`; a top-level module named
#: `entropicmem` beside the distribution of the same name is a collision this card
#: does not need). If one starts being imported by `em`/`em_internal`, the
#: derivation below pulls it in and this tuple has to move with it.
_NOT_ENGINE_MODULES = ("entropicmem", "graph_static", "parity_audit")


# ── the derivation: what the engine actually imports ──────────────────────────


def _flat_modules() -> set[str]:
    """The top-level modules sitting beside the `em`/`em_internal` packages."""
    return {p.stem for p in SCRIPTS.glob("*.py") if p.name != "__init__.py"}


def _imports(path: Path) -> set[str]:
    """Top-level module names a file imports, including lazy (in-function) imports.

    `ast.walk` is what makes this complete: `memory_engine`'s `temporal` import and
    `em/graph/export.py`'s `em_internal.vault` imports live inside functions, and a
    top-of-file scan would ship a wheel missing exactly those.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def required_flat_modules() -> set[str]:
    """The import closure of flat modules the engine needs, derived from the source.

    Start from every flat module imported anywhere under `em/` or `em_internal/`,
    then close over the flat modules *those* import — `memory_engine` imports
    `graph_query`, `pii`, `stopwords` and `temporal`; `session_digest` imports
    `textutil`. Deriving it is the point: a new dependency fails on its first
    commit instead of on a user's `pip install`.
    """
    flat = _flat_modules()
    needed: set[str] = set()
    for package in ("em", "em_internal"):
        for path in (SCRIPTS / package).rglob("*.py"):
            needed |= _imports(path) & flat
    frontier = list(needed)
    while frontier:
        for dependency in _imports(SCRIPTS / f"{frontier.pop()}.py") & flat:
            if dependency not in needed:
                needed.add(dependency)
                frontier.append(dependency)
    return needed


def _pyproject() -> str:
    return PYPROJECT.read_text(encoding="utf-8")


def declared_py_modules() -> list[str]:
    match = re.search(r"^py-modules\s*=\s*\[(.*?)\]", _pyproject(), re.M | re.S)
    assert match, "pyproject.toml declares no py-modules (the wheel then ships no flat module)"
    return sorted(re.findall(r'"([^"]+)"', match.group(1)))


def declared_packages() -> list[str]:
    match = re.search(r"^packages\s*=\s*\[(.*?)\]", _pyproject(), re.M | re.S)
    assert match, "pyproject.toml declares no packages"
    return sorted(re.findall(r'"([^"]+)"', match.group(1)))


def package_dir() -> dict[str, str]:
    match = re.search(r"^package-dir\s*=\s*\{([^}]*)\}", _pyproject(), re.M)
    assert match, "pyproject.toml declares no package-dir mapping"
    return dict(re.findall(r'"([^"]*)"\s*=\s*"([^"]+)"', match.group(1)))


def entry_points() -> dict[str, str]:
    text = _pyproject()
    header = f'[project.entry-points."{ENTRY_POINT_GROUP}"]'
    assert header in text, f"pyproject.toml declares no {ENTRY_POINT_GROUP} entry point"
    block = text.split(header, 1)[1].split("\n[", 1)[0]
    return dict(re.findall(r'^\s*([A-Za-z0-9_.-]+)\s*=\s*"([^"]+)"', block, re.M))


def optional_extras() -> list[str]:
    match = re.search(r"^\[project\.optional-dependencies\]\s*\n(.*?)(?=^\[|\Z)", _pyproject(), re.M | re.S)
    assert match, "pyproject.toml declares no optional-dependencies"
    return sorted(re.findall(r"^([A-Za-z0-9_-]+)\s*=", match.group(1), re.M))


def _plugin_yaml() -> str:
    return (PLUGIN / "plugin.yaml").read_text(encoding="utf-8")


# ── the wheel ships the engine ───────────────────────────────────────────────


def test_the_derivation_finds_the_modules_the_engine_really_imports():
    """A broken parser must not make the guards below vacuous.

    The three names here are the card's own evidence: `em_internal.index` imports
    `memory_engine`, the store screens through `injection_screen`, and redaction
    goes through `pii`. If the AST scan ever returned `set()`, the equality guard
    would compare two empty sets and pass while the wheel shipped nothing.
    """
    required = required_flat_modules()
    assert {"memory_engine", "injection_screen", "pii"} <= required, sorted(required)
    assert required <= _flat_modules(), sorted(required - _flat_modules())
    # the closure is real, not just the first layer: these come from flat modules
    assert {"graph_query", "temporal", "textutil", "stopwords"} <= required, sorted(required)


def test_the_wheel_declares_every_flat_module_the_engine_imports():
    """The chunk-43 failure: a wheel with `em.*` but no `memory_engine`.

    `em_internal/index.py` imports it at module level, so an installed copy raised
    `ModuleNotFoundError: memory_engine` on `import em.graph` — the graph export, and
    anything else touching `em_internal.index`, was source-tree-only.
    """
    required = required_flat_modules()
    declared = set(declared_py_modules())
    missing = sorted(required - declared)
    assert not missing, (
        f"py-modules is missing {missing}; an installed wheel would fail to import the "
        "engine outside the source tree"
    )


def test_the_declared_flat_modules_are_exactly_the_engine_closure():
    """The other direction: a stale entry ships code nothing imports.

    Exact equality is what keeps the list honest over time — adding a flat-module
    dependency changes `required` and fails here until `py-modules` grows with it,
    and deleting a module from the tree fails here until its entry goes too.
    """
    required = required_flat_modules()
    declared = set(declared_py_modules())
    unexpected = sorted(declared - required)
    assert not unexpected, (
        f"py-modules declares {unexpected}, which no em/ or em_internal/ module imports; "
        "either the dependency moved or the entry is stale"
    )
    for name in _NOT_ENGINE_MODULES:
        assert name not in declared, (
            f"{name} is a CLI/ops entry point and is deliberately not shipped as a module"
        )


# ── the provider is discoverable after `pip install` ─────────────────────────


def test_the_provider_entry_point_names_the_packaged_shell():
    """The host's own group, name and target — verified against `plugins/memory`."""
    assert entry_points() == {"entropicmem": ENTRY_POINT_VALUE}
    module = ENTRY_POINT_VALUE.split(":", 1)[0]
    assert (PLUGIN / "__init__.py").is_file()
    assert (PLUGIN / "__init__.py").read_text(encoding="utf-8").count("def register(ctx)") == 1, (
        f"{module}:register must be a real `register(ctx)` in the shell the wheel ships"
    )


def test_the_entry_point_target_is_shipped_as_a_package_with_its_siblings():
    """A package, not a module, and for a measured reason.

    `plugins/memory/__init__.py`'s `_entry_point_package_dir` returns a directory
    **only** when the entry point resolves to a package's `__init__.py`, and
    `find_provider_dir` then reads `config_schema.py` (the dashboard panel) and
    `cli.py` (the `hermes entropicmem` command tree, EM-408) from disk. A one-file
    `entropicmem_plugin.py` would install a provider with neither.
    """
    assert "entropicmem_plugin" in declared_packages(), sorted(declared_packages())
    directories = package_dir()
    assert directories.get("entropicmem_plugin") == "plugins/entropicmem", directories
    for sibling in ("__init__.py", "config_schema.py", "cli.py"):
        assert (PLUGIN / sibling).is_file(), f"the packaged shell is missing {sibling}"


# ── the manifest says what a pip install is judged on ────────────────────────


def test_the_manifest_declares_the_host_floor_the_provider_needs():
    text = _plugin_yaml()
    match = re.search(r"^requires_hermes:\s*[\"']?([^\"'\s#]+)", text, re.M)
    assert match, "plugin.yaml declares no requires_hermes (the host reads it at load time)"
    spec = match.group(1)
    assert spec == REQUIRES_HERMES, spec
    comparator = re.match(r"^(>=|<=|==|!=|>|<)\s*(\d+(?:\.\d+){0,2})$", spec)
    assert comparator, f"{spec!r} is not the comparator form the host's validator accepts"


def test_the_manifest_declares_no_pip_dependencies():
    """The engine is stdlib-only; the optional extras are opt-in, not requirements.

    A catalog install is a directory copy with no `pyproject.toml`, so this field is
    the only place its dependency story exists. Declaring it empty is a claim, and the
    distribution's own `dependencies = []` must agree with it.
    """
    text = _plugin_yaml()
    assert re.search(r"^pip_dependencies:\s*\[\]\s*$", text, re.M), (
        "plugin.yaml must declare `pip_dependencies: []` explicitly"
    )
    assert re.search(r"^dependencies\s*=\s*\[\s*\]", _pyproject(), re.M), (
        "pyproject's project.dependencies is no longer empty; the manifest claim is now false"
    )


def test_the_packaged_shell_does_not_re_include_the_engine_as_data():
    """A measured artifact property: `entropicmem_plugin` is built from a directory
    that also holds the whole engine under `scripts/`.

    Without an exclusion, setuptools treats every file under `scripts/` as *data* of
    the package — the first build of this card shipped the engine twice (once
    top-level as `em.*`/`py-modules`, once inside `entropicmem_plugin/scripts/`)
    plus whatever `*.egg-info` the build had just written. The exclusion is the fix,
    and it is asserted here rather than only measured because a future package-dir
    change would silently reintroduce the copy.
    """
    match = re.search(
        r"^\[tool\.setuptools\.exclude-package-data\]\s*\n(.*?)(?=^\[|\Z)",
        _pyproject(),
        re.M | re.S,
    )
    assert match, "pyproject.toml has no [tool.setuptools.exclude-package-data] block"
    globs = re.findall(r'"([^"]+)"', match.group(1))
    assert any(g.startswith("scripts") for g in globs), (
        "the packaged shell does not exclude scripts/ from its data files, so the wheel "
        f"would carry a second copy of the engine: {globs}"
    )


def test_every_optional_extra_is_documented_where_a_pip_install_is():
    """The card's "optional extras documented" clause, pinned to the extras themselves."""
    extras = optional_extras()
    assert extras, "pyproject declares no optional dependencies"
    for doc in (PLUGIN / "README.md", REPO / "README.md"):
        text = doc.read_text(encoding="utf-8")
        missing = [name for name in extras if f"[{name}]" not in text]
        assert not missing, f"{doc.name} does not document the extras {missing}"
