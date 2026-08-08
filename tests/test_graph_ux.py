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

    def _html(self, populated_index):
        _, index = populated_index
        out = Path(tempfile.mkdtemp()) / "graph.html"
        return export_html(index, out, max_nodes=50)

    def test_alpha_decay_set(self, populated_index):
        html = self._html(populated_index)
        assert "alphaDecay: 0.035" in html, "alphaDecay not in CFG"
        assert "alphaDecay(CFG.physics.alphaDecay)" in html, "alphaDecay not wired to CFG"

    def test_alpha_min_set(self, populated_index):
        html = self._html(populated_index)
        assert "alphaMin: 0.005" in html, "alphaMin not in CFG"
        assert "alphaMin(CFG.physics.alphaMin)" in html, "alphaMin not wired to CFG"

    def test_charge_strength_tuned(self, populated_index):
        html = self._html(populated_index)
        assert "charge: -180" in html, "charge strength not in CFG"
        assert "strength(CFG.physics.charge)" in html, "charge not wired to CFG"

    def test_link_distance_and_collision_radius(self, populated_index):
        """Link distance and collision padding tuning are preserved (review comment 3)."""
        html = self._html(populated_index)
        assert "linkDistance: 110" in html, "link distance not in CFG"
        assert "distance(CFG.physics.linkDistance)" in html, "link distance not wired to CFG"
        assert "collisionPad: 12" in html, "collision padding not in CFG"
        # Allow for minor whitespace/formatting differences around the expression
        collision_pattern = re.compile(
            r"forceCollide\(\)\.radius\(\s*d\s*=>\s*nodeRadius\(\s*d\s*\)\s*\+\s*CFG\.physics\.collisionPad\s*\)"
        )
        assert collision_pattern.search(html) is not None, \
            "collision force not wired to CFG.physics.collisionPad"

    def test_drag_alpha_target_reduced(self, populated_index):
        html = self._html(populated_index)
        assert "dragAlphaTarget: 0.15" in html, "drag alphaTarget not in CFG"
        assert "alphaTarget(CFG.physics.dragAlphaTarget)" in html, \
            "drag alphaTarget not wired to CFG"

    def test_auto_stop_on_end(self, populated_index):
        html = self._html(populated_index)
        assert 'simulation.on("end"' in html, "auto-stop on simulation end missing"

    def test_rounded_coordinates(self, populated_index):
        html = self._html(populated_index)
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
        assert "haloGradientRef" in html, "per-color halo gradient helper missing"
        assert "radialGradient" in html, "radial gradient creation missing"
        assert "halo-grad-" in html, "per-color halo gradient ids missing"

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

    def test_lod_thresholds_and_badges(self, populated_index):
        """LOD thresholds and tag badge behavior are encoded in the inline JS."""
        _, index = populated_index
        out = Path(tempfile.mkdtemp()) / "graph.html"
        html = export_html(index, out, max_nodes=50)
        # Threshold constants (centralized in CFG.lod)
        assert "hideBelow: 0.35" in html, "LOD hideBelow threshold missing"
        assert "fadeBelow: 0.6" in html, "LOD fadeBelow threshold missing"
        assert "badgesAbove: 2.5" in html, "LOD badgesAbove threshold missing"
        # Thresholds wired into updateLOD logic
        assert "CFG.lod.hideBelow" in html, "hideBelow not wired into updateLOD"
        assert "CFG.lod.fadeBelow" in html, "fadeBelow not wired into updateLOD"
        assert "CFG.lod.badgesAbove" in html, "badgesAbove not wired into updateLOD"
        # Badge behavior: class present and threshold-gated (no churn on every zoom)
        assert "node-badge" in html, "node-badge class missing from inline LOD JS"
        assert "lastBadgeZoom" in html, "badge churn guard (lastBadgeZoom) missing"


class TestZoomEnhancements:
    """Phase E: zoom extent and keyboard zoom."""

    def test_zoom_extent_widened(self, populated_index):
        _, index = populated_index
        out = Path(tempfile.mkdtemp()) / "graph.html"
        html = export_html(index, out, max_nodes=50)
        assert "min: 0.05" in html and "max: 8" in html, "zoom extent not in CFG"
        assert "scaleExtent([CFG.zoom.min, CFG.zoom.max])" in html, \
            "zoom extent not wired to CFG"

    def test_wheel_damping(self, populated_index):
        _, index = populated_index
        out = Path(tempfile.mkdtemp()) / "graph.html"
        html = export_html(index, out, max_nodes=50)
        assert "wheelDelta" in html, "wheel damping not configured"
        assert "wheelFactor: 0.04" in html, "wheel factor not in CFG"

    def test_keyboard_zoom(self, populated_index):
        _, index = populated_index
        out = Path(tempfile.mkdtemp()) / "graph.html"
        html = export_html(index, out, max_nodes=50)
        assert 'e.key === "+" || e.key === "="' in html, "keyboard zoom in missing"
        assert 'e.key === "-" || e.key === "_"' in html, "keyboard zoom out missing"

    def test_keyboard_zoom_ignores_form_inputs(self, populated_index):
        """Keyboard zoom must not trigger when focus is on input/textarea elements."""
        _, index = populated_index
        out = Path(tempfile.mkdtemp()) / "graph.html"
        html = export_html(index, out, max_nodes=50)
        assert "tagName" in html, "keyboard handler does not inspect focused element"
        assert "INPUT" in html, "keyboard handler does not guard against INPUT"
        assert "TEXTAREA" in html, "keyboard handler does not guard against TEXTAREA"

    def test_keyboard_zoom_respects_scale_extent_and_factor(self, populated_index):
        """Keyboard zoom honors the CFG scale extent clamp and zoom factor."""
        _, index = populated_index
        out = Path(tempfile.mkdtemp()) / "graph.html"
        html = export_html(index, out, max_nodes=50)
        assert "keyboardFactor: 1.3" in html, "keyboard zoom factor 1.3 not in CFG"
        assert "CFG.zoom.keyboardFactor" in html, "keyboard factor not wired to CFG"
        assert "Math.max(CFG.zoom.min, Math.min(CFG.zoom.max" in html, \
            "scale extent clamp not applied in keyboard zoom"


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

    def test_clipboard_feature_guarded(self, populated_index):
        """navigator.clipboard must be feature-checked before writeText (non-secure
        contexts or older browsers throw without it)."""
        _, index = populated_index
        out = Path(tempfile.mkdtemp()) / "graph.html"
        html = export_html(index, out, max_nodes=50)
        guard = "navigator.clipboard && navigator.clipboard.writeText"
        assert guard in html, "clipboard feature check missing in code copy"
        # Both code-copy and copyNoteLink must be guarded
        assert html.count(guard) >= 2, \
            f"clipboard guard appears {html.count(guard)}x, expected >= 2 (code copy + note link)"


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
