"""
test_graph_ux_v2_6.py - Structural tests for the v2.6 graph integration UI.

These assert the HTML template in graph_export.py ships the community legend
mode, cluster-island layout toggle, in-graph search UI, shortest-path UI, and
orphan highlight (Phases 2-5 of docs/GRAPH_INTEGRATION_PLAN.md). The graph
viewer is a self-contained D3 page, so its "API" is the generated markup/JS,
matching the v2.3 structural-test approach.
"""

import re
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parent.parent / "plugins" / "entropicmem" / "scripts" / "graph_export.py"


@pytest.fixture(scope="module")
def template():
    src = _SRC.read_text(encoding="utf-8")
    m = re.search(r'_HTML_TEMPLATE = r"""(.*?)"""\s*$', src, re.S)
    assert m, "could not locate _HTML_TEMPLATE in graph_export.py"
    return m.group(1)


# ─ Phase 2: cluster rendering ──────────────────────────────────────────────

def test_color_mode_switch_present(template):
    assert 'id="color-mode"' in template
    assert '<option value="domain"' in template
    assert '<option value="community"' in template


def test_node_color_consults_color_mode(template):
    m = re.search(r"function nodeColor\(d\) \{(.*?)\n\}", template, re.S)
    assert m, "nodeColor helper not found"
    body = m.group(1)
    assert 'colorMode === "community"' in body
    assert "d.community_color" in body
    assert "PALETTE[d.domain]" in body


def test_community_palette_lookup_built_from_export(template):
    assert "commPalette" in template
    assert "n.community_color" in template


def test_legend_community_mode(template):
    assert "Communities" in template
    assert "unclustered" in template
    assert "Community ${cid}" in template


def test_cluster_cfg_constants_and_call_sites(template):
    assert "legendMax: 10" in template, "cluster legend cap not in CFG"
    assert "islandStrength: 0.08" in template, "island strength not in CFG"
    assert "CFG.cluster.legendMax" in template, "legendMax not wired in buildLegend"
    assert "CFG.cluster.islandStrength" in template, "islandStrength not wired to the force"


def test_island_layout_toggle(template):
    assert 'id="island-toggle"' in template
    assert "function clusterForce(" in template
    assert "islandMode ? clusterForce(CFG.cluster.islandStrength) : null" in template
    assert "let islandMode = false" in template, "island layout must default off"


def test_color_mode_switch_rewires_render_and_legend(template):
    m = re.search(r'getElementById\("color-mode"\)\.addEventListener\("change",.*?\}\);', template, re.S)
    assert m, "color-mode change handler missing"
    handler = m.group(0)
    assert "buildLegend()" in handler
    assert "render()" in handler


def test_display_prefs_persisted(template):
    assert "entropicmem-graph-color-mode" in template
    assert "entropicmem-graph-island" in template
    assert "restoreDisplayPrefs" in template
    assert "saveDisplayPrefs" in template


# ─ Phase 3: in-graph search UI ─────────────────────────────────────────────

def test_vault_search_ui_present(template):
    assert 'id="vault-search"' in template
    assert 'id="search-results"' in template
    assert "function runVaultSearch(" in template
    assert "function renderSearchResults(" in template
    assert "function selectSearchResult(" in template


def test_vault_search_calls_server_endpoint(template):
    assert '"/api/search?q="' in template
    assert "encodeURIComponent(q)" in template


def test_vault_search_debounced_and_enter_wired(template):
    assert "searchTimer" in template
    assert "setTimeout(runVaultSearch" in template
    assert 'getElementById("vault-search")' in template


def test_search_results_handle_out_of_graph_notes(template):
    """Hits outside the 500-node export must open via the lazy modal fetch."""
    m = re.search(r"function selectSearchResult\(r\) \{(.*?)\n\}", template, re.S)
    assert m, "selectSearchResult not found"
    body = m.group(1)
    assert "jumpToNode(" in body
    assert "openModal(" in body
    assert "nodeG.data().some" in body


def test_vault_search_degrades_without_server(template):
    m = re.search(r"function runVaultSearch\(\) \{(.*?)\n\}", template, re.S)
    assert m, "runVaultSearch not found"
    body = m.group(1)
    assert 'location.protocol.startsWith("http")' in body
    assert "local graph server" in body


# ─ Phase 4: shortest-path tracing UI ───────────────────────────────────────

def test_path_ui_present(template):
    assert 'id="path-banner"' in template
    assert "function handlePathClick(" in template
    assert "function showPath(" in template
    assert "function clearPath(" in template
    assert "activePath" in template
    assert "pathStart" in template


def test_path_calls_server_endpoint(template):
    assert "/api/path?from=" in template
    assert "encodeURIComponent(fromId)" in template


def test_shift_click_triggers_path(template):
    m = re.search(r'\.on\("click", \(event, d\) => \{(.*?)\n    \}\)', template, re.S)
    assert m, "node click handler not found"
    body = m.group(1)
    assert "event.shiftKey" in body
    assert "handlePathClick(" in body
    assert "openModal(" in body


def test_path_dimming_compositor(template):
    """applyFocus/clearFocus must route through applyDimming so path, focus
    and (Phase 5) orphan dimming cannot fight each other."""
    assert "function applyDimming(" in template
    focus_body = re.search(r"function applyFocus\(id\) \{(.*?)\n\}", template, re.S)
    assert focus_body and "applyDimming()" in focus_body.group(1)
    clear_body = re.search(r"function clearFocus\(\) \{(.*?)\n\}", template, re.S)
    assert clear_body and "applyDimming()" in clear_body.group(1)
    assert 'classed("on-path"' in template
    assert ".node-group.on-path" in template


def test_escape_clears_path(template):
    m = re.search(r'if \(e\.key === "Escape"\) \{(.*?)\}', template, re.S)
    assert m, "Escape handler not found"
    assert "clearPath()" in m.group(1)


def test_render_focus_guard_checks_rendered_nodes(template):
    """render() must not re-apply focus for a node filtered out of the current
    view (the applyFocus dim-everything bug class)."""
    m = re.search(r"rootG\.attr\(\"transform\", currentTransform\);\n(.*?)\n  lastBadgeZoom", template, re.S)
    assert m, "render() focus re-apply block not found"
    block = m.group(1)
    assert "nodes.some(" in block
    assert "applyFocus(focusedId)" in block


# ─ Phase 5: orphan highlight ──────────────────────────────────────────────

def test_orphan_toggle_present(template):
    assert 'id="orphan-toggle"' in template
    assert "let orphanMode = false" in template


def test_orphan_dimming_branch_uses_degree(template):
    m = re.search(r"function applyDimming\(\) \{(.*?)\n\}", template, re.S)
    assert m, "applyDimming not found"
    body = m.group(1)
    assert "orphanMode" in body
    assert "(d.degree || 0) === 0" in body


def test_orphan_toggle_wired_to_orphan_mode(template):
    assert 'getElementById("orphan-toggle")' in template
    m = re.search(r'getElementById\("orphan-toggle"\)\.addEventListener\("change",.*?\}\);', template, re.S)
    assert m, "orphan-toggle change handler missing"
    assert "orphanMode = e.target.checked" in m.group(0)


def test_orphan_count_in_stats_pill(template):
    m = re.search(r"function updateStats\(\) \{(.*?)\n\}", template, re.S)
    assert m, "updateStats not found"
    body = m.group(1)
    assert "orphans" in body
    assert "degree" in body
