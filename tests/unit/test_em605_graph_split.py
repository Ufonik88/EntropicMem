"""EM-605 slice 1 — the graph monolith is split into model, renderers and assets.

``graph_export.py`` was a 2,122-line module holding three unrelated things: the
graph *model* (nodes, edges, palettes, community detection), the four
*renderers* (json, dot, canvas, the self-contained HTML), and the viewer itself
as one `_HTML_TEMPLATE` raw string. EM-605 slice 1 splits it into
``em/graph/model.py``, ``em/graph/export.py`` and ``em/graph/assets/`` —
``graph.html`` (the shell), ``graph.css`` and ``graph.js`` — read through
:mod:`importlib.resources` and inlined at export so a written ``graph.html``
stays one self-contained file.

This slice changes no behaviour, so the existing graph suites (template
integrity, UX v2.3/v2.6, XSS, community, path safety, server security) are the
real safety net — they all pass unchanged. What is pinned *here* is the shape of
the split, which nothing else checks:

* the exporter inlines all three assets and leaves no placeholder behind;
* ``graph_export`` is really gone, and the model/renderers live where the card
  says (no half-migrated module left behind);
* the wheel declares ``em.graph`` and its assets, because ``pyproject.toml``'s
  ``packages=`` list is explicit — without both, an installed copy loses the
  viewer while a directory-copied plugin keeps it, a drift no test would see;
* the split is faithful: the assets reassemble to exactly the template the
  exporter substitutes into (the one property that makes this refactor safe).

Rules: invented data only.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import graph_assets
import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "plugins" / "entropicmem" / "scripts"
ROOT = Path(__file__).resolve().parents[2]

from em.graph.export import export_html, export_json  # noqa: E402
from em.graph.model import build_graph_payload  # noqa: E402
from em_internal.index import VaultIndex  # noqa: E402
from em_internal.vault import Vault  # noqa: E402


def _build_vault(tmp_path: Path):
    root = tmp_path / "vault"
    root.mkdir(parents=True, exist_ok=True)
    vault = Vault(root)
    for title in ("Alpha", "Beta", "Gamma"):
        others = [t for t in ("Alpha", "Beta", "Gamma") if t != title]
        body = "Links: " + " ".join(f"[[{t}]]" for t in others)
        vault.write_note("Knowledge", title, body, tags=["t"], domain="Knowledge")
    return vault


@pytest.fixture
def populated(tmp_path):
    vault = _build_vault(tmp_path)
    index = VaultIndex(tmp_path / "index.db")
    for rel in vault.list_notes():
        index.upsert_note(vault.read_note(rel))
    index._rebuild_edges(vault)
    yield vault, index, tmp_path
    index.close()


# ── the assets reassemble to exactly what the exporter inlines ───────────────

def test_the_assets_reassemble_to_the_substituted_template():
    """The test helper's reassembly is the exporter's: the shell plus the CSS
    and JS inlined, with only the data/favicon placeholders left for export.

    This is the property the whole slice rests on — if the shell and the two
    other assets are not what the exporter composes, every structural test
    below is checking a fiction.
    """
    composed = graph_assets.template()
    assert composed.count("__ENTROPICMEM_CSS__") == 0
    assert composed.count("__ENTROPICMEM_JS__") == 0
    # exactly the two export-time placeholders survive
    assert composed.count("__ENTROPICMEM_GRAPH_DATA__") == 1
    assert composed.count("__ENTROPICMEM_FAVICON__") == 1
    # the three asset bodies really are in there, in order
    css = graph_assets.asset("graph.css")
    js = graph_assets.asset("graph.js")
    assert css and css in composed
    assert js and js in composed
    assert composed.index(css) < composed.index(js)


def test_exported_html_inlines_every_asset_and_leaves_no_placeholder(populated):
    vault, index, tmp_path = populated
    html = export_html(index, tmp_path / "graph.html", max_nodes=50)

    assert "__ENTROPICMEM_" not in html, "an export-time placeholder survived"
    # the CSS body is inlined verbatim (it carries no placeholder)…
    assert graph_assets.asset("graph.css") in html
    # …and so is the JS, split around the one line the exporter substitutes
    js = graph_assets.asset("graph.js")
    head, sep, tail = js.partition("const DATA = __ENTROPICMEM_GRAPH_DATA__;")
    assert sep, "graph.js no longer carries the data placeholder"
    assert head and tail
    assert head in html and tail in html, "the JS body was not inlined"
    assert html.index(head) < html.index(tail)
    # the data really was substituted: the payload rides that line
    assert re.search(r"const DATA = \{.*\"nodes\"", html, re.DOTALL), "graph data not embedded"
    assert "data:image/png;base64," in html, "favicon not substituted"


# ── export_json is a thin write over the model ──────────────────────────────

def test_export_json_writes_what_the_model_builds(populated):
    """The split must not fork the payload: export_json writes exactly the
    model's payload (bar the wall-clock `generated` stamp), so the JSON and
    HTML renderers can never disagree about the graph."""
    vault, index, tmp_path = populated
    written = export_json(index, tmp_path / "graph.json", max_nodes=50)
    built = build_graph_payload(index, max_nodes=50)

    def _stable(payload):
        meta = dict(payload["meta"])
        meta.pop("generated", None)
        return {**payload, "meta": meta}

    assert _stable(written) == _stable(built)


# ── the body gate's one visible string survives the split ──────────────────

def test_the_body_gate_still_names_the_export_path(populated, monkeypatch):
    """The split's one observable difference, closed: the body gate's context.

    `export_json` used to report `export_json(<path>)` in the gate's
    RuntimeError, so the message pointed at the file that came back empty. The
    payload builder now owns the gate, and it takes the caller's name so the
    message is still the export path — not a renamed, less useful one.
    """
    vault, index, tmp_path = populated
    import em.graph.model as model_mod

    real = model_mod.assert_bodies_present
    seen: dict = {}

    def spy(payload, *, context="graph export"):
        seen["context"] = context
        return real(payload, context=context)

    monkeypatch.setattr(model_mod, "assert_bodies_present", spy)
    out = tmp_path / "graph.json"
    try:
        export_json(index, out, max_nodes=50, include_bodies=True)
    except RuntimeError:
        pass  # the gate fired, which is fine: the context is the claim
    assert seen.get("context") == f"export_json({out})"


# ── the split is complete: no monolith left behind ─────────────────────────

def test_the_monolith_is_gone_and_the_package_holds_the_split():
    assert importlib.util.find_spec("graph_export") is None, "graph_export.py came back"
    assert (SCRIPTS / "graph_export.py").exists() is False

    import em.graph.export as export_mod
    import em.graph.model as model_mod

    # the model owns the graph's structure…
    for name in (
        "DEFAULT_COLOR",
        "DOMAIN_PALETTE",
        "TYPE_SHAPES",
        "assert_bodies_present",
        "body_coverage",
        "build_graph_payload",
        "detect_communities",
        "get_color",
        "get_community_color",
        "get_shape",
        "resolve_note_path",
    ):
        assert hasattr(model_mod, name), f"em.graph.model lost {name}"

    # …and the renderers own the output formats
    for name in ("export_canvas", "export_dot", "export_html", "export_json"):
        assert hasattr(export_mod, name), f"em.graph.export lost {name}"


def test_the_model_does_not_import_the_renderers():
    """One direction only: the model is the base layer. A model that imported a
    renderer would cycle the moment a second renderer wants the payload."""
    import ast

    tree = ast.parse((SCRIPTS / "em" / "graph" / "model.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")

    assert not any(name.startswith("em.graph.export") for name in imported), imported
    # the model is markup-free and write-free: it never serialises a document
    assert "json" not in imported, imported
    assert "html" not in imported, imported


# ── packaging: the wheel ships the viewer ──────────────────────────────────

def test_the_wheel_declares_em_graph_and_its_assets():
    """``packages=`` is an explicit list and the viewer is data, not Python: a
    released wheel without either entry serves an empty page, and the catalog's
    directory-copy install would hide it."""
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    packages = re.search(r"^packages = \[(.*)\]$", pyproject, re.MULTILINE)
    assert packages, "packages= list not found"
    assert '"em.graph"' in packages.group(1)

    assert "[tool.setuptools.package-data]" in pyproject
    data_block = re.search(
        r"^\[tool\.setuptools\.package-data\]\s*\n(.*?)(?=^\[|\Z)",
        pyproject,
        re.MULTILINE | re.DOTALL,
    )
    assert data_block, "package-data block not found"
    assert '"em.graph"' in data_block.group(1)
    for glob in ("assets/*.html", "assets/*.css", "assets/*.js"):
        assert glob in data_block.group(1), f"package-data lost {glob}"

    for name in ("graph.html", "graph.css", "graph.js"):
        assert (SCRIPTS / "em" / "graph" / "assets" / name).is_file()
