"""
test_graph_ux.py — Regression tests for the v2.2.0 visual graph UX overhaul.

Validates that graph_export.py produces structurally correct HTML with the
new physics, SVG glow defs, LOD, and modal enhancements, and that the
inline JavaScript still parses cleanly.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_SCRIPT_DIR = Path(__file__).resolve().parent.parent / "skills" / "entropicmem" / "scripts"
_CLI = str(_SCRIPT_DIR / "entropicmem.py")
sys.path.insert(0, str(_SCRIPT_DIR))

from vault import Vault
from index import VaultIndex
from graph_export import export_html, export_json


def _run(*args, **env):
    full_env = {**os.environ, **env}
    return subprocess.run(
        [sys.executable, _CLI, *args],
        capture_output=True, text=True, env=full_env,
    )


@pytest.fixture
def populated_index():
    """Create a vault with 20 notes across 4 domains and return (vault, index)."""
    with tempfile.TemporaryDirectory() as td:
        vp = Path(td) / "vault"
        ip = Path(td) / "index.db"
        _run("init", "--vault", str(vp), "--index-db", str(ip),
             ENTROPICMEM_VAULT_PATH=str(vp), ENTROPICMEM_INDEX_DB=str(ip))

        vault = Vault(vp)
        index = VaultIndex(ip)

        for i in range(5):
            for domain, tag in [("Infrastructure", "infra"), ("Ajax Systems", "ajax"),
                                ("Finance", "fin"), ("Knowledge", "know")]:
                body = f"Body {i}. See [[{domain} Note {i+1}]]" if i < 4 else f"Body {i}."
                path = vault.write_note(domain, f"{domain} Note {i}", body,
                                        tags=[tag, f"t{i}"], domain=domain)
                note = vault.read_note(path)
                index.upsert_note(note)
                index.upsert_edges_for_note(vault, note)

        yield vault, index
        index.close()


class TestPhysicsStability:
    """Phase D: physics tuning parameters present in the template."""

    def test_alpha_decay_set(self, populated_index):
        _, index = populated_index
        out = Path(tempfile.mkdtemp()) / "graph.html"
        html = export_html(index, out, max_nodes=50)
        assert "alphaDecay(0.035)" in html, "alphaDecay not tuned"

    def test_alpha_min_set(self, populated_index):
        _, index = populated_index
        out = Path(tempfile.mkdtemp()) / "graph.html"
        html = export_html(index, out, max_nodes=50)
        assert "alphaMin(0.005)" in html, "alphaMin not set"

    def test_charge_strength_tuned(self, populated_index):
        _, index = populated_index
        out = Path(tempfile.mkdtemp()) / "graph.html"
        html = export_html(index, out, max_nodes=50)
        assert "strength(-180)" in html, "charge strength not tuned"

    def test_drag_alpha_target_reduced(self, populated_index):
        _, index = populated_index
        out = Path(tempfile.mkdtemp()) / "graph.html"
        html = export_html(index, out, max_nodes=50)
        assert "alphaTarget(0.15)" in html, "drag alphaTarget not reduced from 0.3"

    def test_auto_stop_on_end(self, populated_index):
        _, index = populated_index
        out = Path(tempfile.mkdtemp()) / "graph.html"
        html = export_html(index, out, max_nodes=50)
        assert 'simulation.on("end"' in html, "auto-stop on simulation end missing"

    def test_rounded_coordinates(self, populated_index):
        _, index = populated_index
        out = Path(tempfile.mkdtemp()) / "graph.html"
        html = export_html(index, out, max_nodes=50)
        assert "Math.round(d.x)" in html, "sub-pixel rounding not applied"


class TestSVGGlowDefs:
    """Phase C: SVG glow filter defs and halo elements present."""

    def test_glow_filter_defined(self, populated_index):
        _, index = populated_index
        out = Path(tempfile.mkdtemp()) / "graph.html"
        html = export_html(index, out, max_nodes=50)
        assert 'id="node-glow"' in html, "node-glow filter not defined"
        assert "feGaussianBlur" in html, "Gaussian blur filter missing"

    def test_glow_filter_strong_defined(self, populated_index):
        _, index = populated_index
        out = Path(tempfile.mkdtemp()) / "graph.html"
        html = export_html(index, out, max_nodes=50)
        assert 'id="node-glow-strong"' in html, "node-glow-strong filter not defined"

    def test_halo_gradient_defined(self, populated_index):
        _, index = populated_index
        out = Path(tempfile.mkdtemp()) / "graph.html"
        html = export_html(index, out, max_nodes=50)
        assert 'id="halo-grad"' in html, "halo radial gradient not defined"

    def test_node_halo_class_in_template(self, populated_index):
        _, index = populated_index
        out = Path(tempfile.mkdtemp()) / "graph.html"
        html = export_html(index, out, max_nodes=50)
        assert '"node-halo"' in html, "node-halo class not in JS template"

    def test_update_node_halos_function(self, populated_index):
        _, index = populated_index
        out = Path(tempfile.mkdtemp()) / "graph.html"
        html = export_html(index, out, max_nodes=50)
        assert "function updateNodeHalos" in html, "updateNodeHalos function missing"

    def test_glow_filter_applied_to_shapes(self, populated_index):
        _, index = populated_index
        out = Path(tempfile.mkdtemp()) / "graph.html"
        html = export_html(index, out, max_nodes=50)
        assert 'url(#node-glow)' in html, "glow filter not applied to node shapes"


class TestLODSystem:
    """Phase E: level-of-detail label culling."""

    def test_update_lod_function(self, populated_index):
        _, index = populated_index
        out = Path(tempfile.mkdtemp()) / "graph.html"
        html = export_html(index, out, max_nodes=50)
        assert "function updateLOD" in html, "updateLOD function missing"

    def test_lod_called_on_zoom(self, populated_index):
        _, index = populated_index
        out = Path(tempfile.mkdtemp()) / "graph.html"
        html = export_html(index, out, max_nodes=50)
        assert "updateLOD()" in html, "updateLOD not called on zoom"


class TestZoomEnhancements:
    """Phase E: zoom extent and keyboard zoom."""

    def test_zoom_extent_widened(self, populated_index):
        _, index = populated_index
        out = Path(tempfile.mkdtemp()) / "graph.html"
        html = export_html(index, out, max_nodes=50)
        assert "scaleExtent([0.05, 8])" in html, "zoom extent not widened"

    def test_wheel_damping(self, populated_index):
        _, index = populated_index
        out = Path(tempfile.mkdtemp()) / "graph.html"
        html = export_html(index, out, max_nodes=50)
        assert "wheelDelta" in html, "wheel damping not configured"

    def test_keyboard_zoom(self, populated_index):
        _, index = populated_index
        out = Path(tempfile.mkdtemp()) / "graph.html"
        html = export_html(index, out, max_nodes=50)
        assert 'e.key === "+" || e.key === "="' in html, "keyboard zoom in missing"
        assert 'e.key === "-" || e.key === "_"' in html, "keyboard zoom out missing"


class TestMinimapNavigation:
    """Phase E3: minimap click-to-pan."""

    def test_minimap_click_handler(self, populated_index):
        _, index = populated_index
        out = Path(tempfile.mkdtemp()) / "graph.html"
        html = export_html(index, out, max_nodes=50)
        assert 'mmSvg.on("click"' in html, "minimap click handler missing"


class TestModalPolish:
    """Phase F: modal code copy buttons."""

    def test_code_copy_buttons(self, populated_index):
        _, index = populated_index
        out = Path(tempfile.mkdtemp()) / "graph.html"
        html = export_html(index, out, max_nodes=50)
        assert "code-copy-btn" in html or "Copy" in html, "code copy button missing"


class TestDesignTokens:
    """Phase B: design token consolidation."""

    def test_css_custom_properties(self, populated_index):
        _, index = populated_index
        out = Path(tempfile.mkdtemp()) / "graph.html"
        html = export_html(index, out, max_nodes=50)
        assert "--accent-glow" in html, "accent-glow token missing"
        assert "--radius" in html, "radius token missing"
        assert "--blur" in html, "blur token missing"
        assert "--transition" in html, "transition token missing"

    def test_glassmorphism_backdrop(self, populated_index):
        _, index = populated_index
        out = Path(tempfile.mkdtemp()) / "graph.html"
        html = export_html(index, out, max_nodes=50)
        assert "backdrop-filter: blur(var(--blur))" in html, \
            "glassmorphism blur not using token"

    def test_hover_glow_on_nodes(self, populated_index):
        _, index = populated_index
        out = Path(tempfile.mkdtemp()) / "graph.html"
        html = export_html(index, out, max_nodes=50)
        assert "node-group:hover .node-shape" in html, \
            "hover glow CSS rule missing"


class TestJSSyntaxValid:
    """Guard: inline JS still parses without SyntaxError."""

    def test_node_check_passes(self, populated_index):
        _, index = populated_index
        out = Path(tempfile.mkdtemp()) / "graph.html"
        html = export_html(index, out, max_nodes=50, vault_root=populated_index[0].root,
                           include_bodies=True)
        scripts = re.findall(r"<script>(.*?)</script>", html, re.DOTALL)
        assert scripts, "no inline <script> block"
        app_js = scripts[-1]

        node = shutil.which("node")
        if node:
            jsf = Path(tempfile.mkdtemp()) / "app.js"
            jsf.write_text(app_js)
            r = subprocess.run([node, "--check", str(jsf)], capture_output=True, text=True)
            assert r.returncode == 0, f"node --check failed:\n{r.stderr}"
        else:
            # If no node, at least check no obvious duplicate declarations
            for binding in ("let simulation", "const DATA"):
                assert app_js.count(binding) <= 2, f"too many '{binding}' declarations"


class TestExportSchemaStable:
    """Graph.json schema must remain backward compatible."""

    def test_json_schema_unchanged(self, populated_index):
        _, index = populated_index
        out = Path(tempfile.mkdtemp()) / "graph.json"
        data = export_json(index, out, max_nodes=50)
        assert "nodes" in data
        assert "edges" in data
        assert "meta" in data
        # Node fields present
        node = data["nodes"][0]
        for field in ("id", "title", "type", "domain", "importance", "tags", "color", "shape"):
            assert field in node, f"node field '{field}' missing"
        # Edge fields present
        if data["edges"]:
            edge = data["edges"][0]
            for field in ("source", "target", "weight", "kind"):
                assert field in edge, f"edge field '{field}' missing"
