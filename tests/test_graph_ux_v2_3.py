"""
test_graph_ux_v2_3.py — Structural tests for the v2.3.0 graph UI/UX overhaul.

These assert the HTML template in graph_export.py actually ships the UX
fixes (wheel deltaMode normalization, collapsible overlays, zoom controls,
HiDPI PNG export, tooltip edge-flipping, focus trap, loading/empty states).
They intentionally inspect the template source: the graph viewer is a
self-contained D3 page, so its "API" is the generated markup/JS.
"""

import re
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parent.parent / "plugins" / "entropicmem" / "scripts" / "graph_export.py"


@pytest.fixture(scope="module")
def template():
    src = _SRC.read_text(encoding="utf-8")
    m = re.search(r'_HTML_TEMPLATE = r"""(.*)"""\s*$', src, re.S)
    assert m, "could not locate _HTML_TEMPLATE in graph_export.py"
    return m.group(1)


# ── Phase 1: scroll sensitivity calibration ─────────────────────────────────

def test_wheel_delta_normalizes_delta_mode(template):
    """wheelDelta must branch on event.deltaMode (0=pixel, 1=line, 2=page)."""
    assert "wheelDelta(event =>" in template
    assert "deltaMode" in template
    assert "mode === 1" in template and "mode === 2" in template


def test_zoom_controls_present(template):
    for btn in ("btn-zoom-in", "btn-zoom-out", "btn-zoom-fit", "btn-zoom-100"):
        assert f'id="{btn}"' in template


def test_zoom_helpers_present(template):
    assert "function zoomBy(" in template
    assert "function zoomFit(" in template
    assert "function zoomTo(" in template


def test_dblclick_zoom(template):
    assert 'svg.on("dblclick"' in template


# ── Phase 2: collapsible overlays ───────────────────────────────────────────

def test_toggle_overlay_helper(template):
    assert "function toggleOverlay(" in template
    assert "function setOverlayCollapsed(" in template


def test_collapse_state_persisted(template):
    assert "entropicmem-graph-" in template
    assert "localStorage" in template


def test_collapse_buttons_wired(template):
    for btn in ("collapse-panel", "collapse-legend", "collapse-minimap", "collapse-stats"):
        assert f'id="{btn}"' in template


def test_overlay_keyboard_shortcuts(template):
    # H/L/M/S toggles
    for shortcut in ('toggleOverlay("panel")', 'toggleOverlay("legend")',
                     'toggleOverlay("minimap-wrap")', 'toggleOverlay("stats-wrap")'):
        assert shortcut in template


# ── Phase 3: rendering fidelity ─────────────────────────────────────────────

def test_png_export_hidpi(template):
    assert "devicePixelRatio" in template
    assert "W * dpr" in template


def test_compositing_hint_on_root(template):
    assert 'style("will-change", "transform")' in template


# ── Phase 4: general UX ─────────────────────────────────────────────────────

def test_tooltip_edge_flip(template):
    assert "offsetWidth" in template
    assert "flipX" in template and "flipY" in template


def test_escape_releases_focus_when_no_modal(template):
    # Escape handler must call clearFocus() in the non-modal branch
    m = re.search(r'if \(e\.key === "Escape"\) \{(.*?)\}', template, re.S)
    assert m, "Escape handler not found"
    assert "clearFocus()" in m.group(1)


def test_loading_and_empty_states(template):
    assert 'id="loading"' in template
    assert "Building graph" in template
    assert 'id="empty-state"' in template
    assert "No notes match these filters" in template


def test_modal_focus_trap(template):
    assert "function trapModalFocus(" in template
    assert 'e.key !== "Tab"' in template


def test_stats_use_span(template):
    # stats text lives in #stats-text so the collapse button isn't clobbered
    assert 'id="stats-text"' in template
    assert "function updateStats(" in template


def test_legend_svg_icons(template):
    # Unicode glyphs replaced by inline SVG icon set
    assert "SHAPE_SVGS" in template
    assert "legend-content" in template


def test_keyboard_shortcuts_documented_in_panel(template):
    assert 'class="shortcuts"' in template
    assert "<kbd>H</kbd>" in template


# ── Wikilink lazy resolution (red dead-link fix) ────────────────────────────

def test_pending_wikilinks_resolve_by_title(template):
    """Unresolved [[wikilinks]] must be clickable 'pending' links that fetch
    /api/note/by-title/ — not permanently dead red .broken spans."""
    assert "wikilink.pending" in template
    assert '"/api/note/by-title/"' in template
    assert "Resolving link…" in template
    assert "failBroken" in template
    assert ".broken" in template


def test_open_modal_guards_out_of_graph_nodes(template):
    """openModal must not dim the whole graph when the note is not rendered."""
    assert "nodeG.data().some" in template
    assert "applyFocus(node.id)" in template
