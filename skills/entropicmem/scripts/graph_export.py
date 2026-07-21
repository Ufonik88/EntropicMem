"""
graph_export.py — Visual graph export for EntropicMem.

Exports vault data as JSON (primary), DOT (Graphviz), HTML (self-contained D3),
and Canvas format using data from VaultIndex.

Stdlib-only. D3 + marked loaded from CDN in HTML output (vendored copies are
used automatically when present next to the output file, for offline use).
"""

import json
from pathlib import Path
from typing import Optional

from index import VaultIndex

# ── per-domain color palette (from Ajax brand, colorblind-safe) ─────────────

DOMAIN_PALETTE = {
    "Infrastructure": "#1DCF8E",
    "Ajax Systems": "#5AE4AA",
    "X-Growth": "#00AD74",
    "Finance": "#FFB800",
    "Workflows": "#7C4DFF",
    "People": "#FF6B6B",
    "Knowledge": "#4FC3F7",
    "Products-Research": "#FF9800",
    "Projects": "#9CCC65",
}

DEFAULT_COLOR = "#888888"

# ── node type → shape mapping ──────────────────────────────────────────────

TYPE_SHAPES = {
    "permanent": "circle",
    "literature": "square",
    "moc": "diamond",
    "index": "triangle",
    "log": "triangle",
}


def get_color(domain: str) -> str:
    return DOMAIN_PALETTE.get(domain, DEFAULT_COLOR)


def get_shape(note_type: str) -> str:
    return TYPE_SHAPES.get(note_type, "circle")


# ── JSON export ─────────────────────────────────────────────────────────────

def export_json(
    index: VaultIndex,
    output_path: Path,
    domain: Optional[str] = None,
    min_importance: float = 0.0,
    max_nodes: int = 500,
) -> dict:
    """
    Export nodes + edges as JSON. Primary format consumed by graph.html.

    Returns the dict that was written (for testing).
    """
    nodes = index.get_graph_nodes(
        domain=domain, min_importance=min_importance, max_nodes=max_nodes
    )

    # Build node list with visual properties
    node_list = []
    for n in nodes:
        tags = n.get("tags", "")
        if isinstance(tags, str) and tags:
            tags = [t.strip() for t in tags.split(",")]
        elif not isinstance(tags, list):
            tags = []

        node_list.append({
            "id": n["note_id"],
            "title": n.get("title", n["note_id"]),
            "type": n.get("note_type", "permanent"),
            "domain": n.get("domain", ""),
            "importance": n.get("importance", 0.3),
            "tags": tags,
            "color": get_color(n.get("domain", "")),
            "shape": get_shape(n.get("note_type", "permanent")),
        })

    # Build edge list (only edges where both nodes exist in the export set)
    node_ids = {n["id"] for n in node_list}
    all_edges = index.get_graph_edges(domain=domain, min_weight=1)
    edge_list = []
    for e in all_edges:
        if e.source_id in node_ids and e.target_id in node_ids:
            edge_list.append({
                "source": e.source_id,
                "target": e.target_id,
                "weight": e.weight,
                "kind": e.kind,
            })

    payload = {
        "nodes": node_list,
        "edges": edge_list,
        "meta": {
            "generated": "",
            "node_count": len(node_list),
            "edge_count": len(edge_list),
            "domains": list(set(n.get("domain", "") for n in node_list)),
            "max_importance": max((n.get("importance", 0) for n in node_list), default=0),
            "filters": {
                "domain": domain,
                "min_importance": min_importance,
                "max_nodes": max_nodes,
            },
        },
    }

    from datetime import datetime, timezone
    payload["meta"]["generated"] = datetime.now(timezone.utc).isoformat()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


# ── DOT export ──────────────────────────────────────────────────────────────

def export_dot(
    index: VaultIndex,
    output_path: Path,
    domain: Optional[str] = None,
    min_importance: float = 0.0,
    max_nodes: int = 200,
) -> str:
    """Export as Graphviz DOT for static renders."""
    nodes = index.get_graph_nodes(
        domain=domain, min_importance=min_importance, max_nodes=max_nodes
    )
    node_ids = {n["note_id"] for n in nodes}
    all_edges = index.get_graph_edges(domain=domain, min_weight=1)

    lines = ["digraph vault {", "  rankdir=LR;", '  bgcolor="#0a0a0f";',
             '  node [fontname="sans-serif"];', '  edge [color="#444444"];', ""]

    for n in nodes:
        color = get_color(n.get("domain", ""))
        label = n.get("title", n["note_id"]).replace('"', r'\"')
        lines.append(f'  "{n["note_id"]}" [label="{label}", color="{color}", fontcolor="{color}"];')

    for e in all_edges:
        if e.source_id in node_ids and e.target_id in node_ids:
            lines.append(f'  "{e.source_id}" -> "{e.target_id}" [penwidth={0.5 + e.weight * 0.5}];')

    lines.append("}")
    content = "\n".join(lines)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    return content


# ── Canvas export ───────────────────────────────────────────────────────────

def export_canvas(
    index: VaultIndex,
    output_path: Path,
    domain: Optional[str] = None,
    min_importance: float = 0.0,
    max_nodes: int = 100,
) -> dict:
    """Export as JSON Canvas format."""
    nodes = index.get_graph_nodes(
        domain=domain, min_importance=min_importance, max_nodes=max_nodes
    )
    node_map = {}
    canvas_nodes = []
    spacing = 400
    cols = 5

    for i, n in enumerate(nodes):
        node_map[n["note_id"]] = n
        row = i // cols
        col = i % cols
        canvas_nodes.append({
            "id": n["note_id"],
            "type": "text",
            "text": f"**{n.get('title', n['note_id'])}**\n\n*{n.get('note_type', '')} | {n.get('domain', '')}*",
            "x": col * spacing,
            "y": row * spacing,
            "width": 350,
            "height": 150,
            "color": "1",
        })

    all_edges = index.get_graph_edges(domain=domain, min_weight=1)
    canvas_edges = []
    for e in all_edges:
        if e.source_id in node_map and e.target_id in node_map:
            canvas_edges.append({
                "id": f"{e.source_id}__{e.target_id}",
                "fromNode": e.source_id,
                "toNode": e.target_id,
                "fromSide": "right",
                "toSide": "left",
            })

    payload = {"nodes": canvas_nodes, "edges": canvas_edges}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


# ── HTML export (embedded JSON for file:// compatibility) ───────────────────

def export_html(
    index: VaultIndex,
    output_path: Path,
    domain: Optional[str] = None,
    min_importance: float = 0.0,
    max_nodes: int = 500,
    vault_root: Optional[Path] = None,
) -> str:
    """
    Export as a single self-contained HTML file with embedded graph data.
    Works via file:// or HTTP server. D3 v7 + marked loaded from CDN, with
    automatic fallback to vendored copies placed next to the output file.
    Includes full note bodies for modal display.

    vault_root: path to the vault. When omitted it is resolved from the
    environment (ENTROPICMEM_VAULT_PATH / OBSIDIAN_VAULT_PATH) so the modal
    can show full note bodies. Pass it explicitly from the CLI for reliability.
    """
    data = export_json(
        index, output_path.parent / "graph.json",
        domain=domain, min_importance=min_importance, max_nodes=max_nodes
    )

    # Resolve the vault once (not per-node) and attach full bodies.
    vault = None
    if vault_root is None:
        try:
            from vault import resolve_vault_path
            vault_root = resolve_vault_path()
        except Exception:
            vault_root = None
    if vault_root is not None:
        try:
            from vault import Vault
            vault = Vault(Path(vault_root))
        except Exception:
            vault = None

    if vault is not None:
        for node in data["nodes"]:
            meta = index.get_note(node["id"])
            if not meta:
                continue
            node["full_body"] = meta.get("body_preview", "")
            try:
                note = vault.read_note(Path(meta["path"]))
                node["full_body"] = note.body
            except Exception:
                pass

    # Serialize and make it safe to embed inside a <script> tag: the only
    # sequence that can prematurely close the tag is "</", so escape it.
    graph_json = json.dumps(data).replace("</", "<\\/")
    html = _HTML_TEMPLATE.replace("__ENTROPICMEM_GRAPH_DATA__", graph_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    return html


# ── HTML template (D3 v7, galaxy theme) ─────────────────────────────────────

_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>EntropicMem — Vault Graph</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&display=swap" rel="stylesheet">
<script src="https://d3js.org/d3.v7.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<style>
:root {
  --bg: #0a0a0f;
  --panel: rgba(15,15,25,0.92);
  --border: #2a2a3a;
  --accent: #5AE4AA;
  --accent-dim: #1DCF8E;
  --text: #ccc;
  --text-dim: #888;
  --display: 'Space Grotesk', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  --body: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
html, body { height: 100%; }
body { background: var(--bg); color: var(--text); font-family: var(--body); overflow: hidden; }
#graph { position: absolute; inset: 0; width: 100vw; height: 100vh; }
#graph svg { display: block; }

/* ── Control panel ── */
#panel { position: absolute; top: 12px; left: 12px; background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 14px; width: 260px; font-size: 13px; z-index: 10; backdrop-filter: blur(6px); max-height: calc(100vh - 24px); overflow-y: auto; }
#panel h2 { font-family: var(--display); font-size: 16px; font-weight: 700; margin: 0 0 10px; color: var(--accent); letter-spacing: 0.3px; }
#panel label { display: block; margin: 10px 0 3px; color: var(--text-dim); font-size: 10px; text-transform: uppercase; letter-spacing: 0.8px; font-weight: 600; }
#panel select, #panel input[type=text] { width: 100%; padding: 6px 9px; background: #1a1a2e; border: 1px solid #333; border-radius: 5px; color: var(--text); font-size: 12px; font-family: var(--body); }
#panel input[type=text]:focus, #panel select:focus { outline: none; border-color: var(--accent); }
#panel input[type=range] { width: 100%; accent-color: var(--accent); }
.domain-check { display: flex; align-items: center; gap: 7px; margin: 3px 0; font-size: 12px; cursor: pointer; }
.domain-check input { width: auto; accent-color: var(--accent); }
.domain-check .swatch { width: 10px; height: 10px; border-radius: 50%; flex: none; }
.btn-row { display: flex; gap: 6px; margin-top: 12px; }
.btn { flex: 1; padding: 6px; background: #2a2a3a; border: 1px solid #444; color: var(--text); border-radius: 5px; cursor: pointer; font-size: 11px; font-family: var(--body); transition: all 0.15s; }
.btn:hover { background: #353548; border-color: var(--accent); color: var(--accent); }
#imp-val { color: var(--accent); font-weight: 600; }

/* ── Legend ── */
#legend { position: absolute; bottom: 12px; right: 12px; background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 10px 14px; font-size: 12px; z-index: 10; backdrop-filter: blur(6px); max-width: 220px; }
#legend .lg-title { font-family: var(--display); font-weight: 600; margin-bottom: 5px; color: var(--text); font-size: 11px; text-transform: uppercase; letter-spacing: 0.6px; }
#legend .row { display: flex; align-items: center; gap: 8px; margin: 3px 0; color: var(--text-dim); }
#legend .swatch { width: 11px; height: 11px; border-radius: 50%; flex: none; }
#legend .shape-glyph { width: 14px; text-align: center; flex: none; color: var(--text); }

/* ── Minimap ── */
#minimap { position: absolute; bottom: 12px; right: 244px; width: 180px; height: 130px; background: var(--panel); border: 1px solid var(--border); border-radius: 10px; z-index: 10; overflow: hidden; backdrop-filter: blur(6px); }
#minimap .viewport-rect { fill: rgba(90,228,170,0.12); stroke: var(--accent); stroke-width: 1; }

/* ── Tooltip ── */
#tooltip { position: absolute; background: rgba(10,10,20,0.96); border: 1px solid #444; border-radius: 7px; padding: 10px 13px; pointer-events: none; font-size: 12px; z-index: 20; display: none; max-width: 300px; box-shadow: 0 6px 24px rgba(0,0,0,0.5); }
#tooltip .tt-title { font-family: var(--display); font-weight: 600; margin-bottom: 4px; }
#tooltip .tt-meta { color: var(--text-dim); line-height: 1.5; }

/* ── Stats / status ── */
#stats { position: absolute; bottom: 12px; left: 12px; color: #555; font-size: 11px; z-index: 10; }
#focus-banner { position: absolute; top: 12px; left: 50%; transform: translateX(-50%); background: var(--panel); border: 1px solid var(--accent); color: var(--accent); border-radius: 20px; padding: 6px 16px; font-size: 12px; z-index: 10; display: none; backdrop-filter: blur(6px); }
#focus-banner b { font-family: var(--display); }

svg text { fill: #aaa; font-size: 9px; pointer-events: none; font-family: var(--body); }
.node-shape { cursor: pointer; transition: opacity 0.2s; }
.node-group:focus { outline: none; }
.node-group:focus .node-shape { stroke: #fff; stroke-width: 2; }

/* ── Modal ── */
#modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.85); z-index: 100; display: none; backdrop-filter: blur(4px); }
#modal { position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%); width: 78vw; max-width: 1000px; height: 80vh; max-height: 92vh; background: #111218; border: 1px solid var(--border); border-radius: 14px; z-index: 101; display: none; flex-direction: column; overflow: hidden; box-shadow: 0 20px 60px rgba(0,0,0,0.6), 0 0 0 1px rgba(90,228,170,0.12); }
#modal-header { display: flex; align-items: center; justify-content: space-between; padding: 16px 20px; border-bottom: 1px solid var(--border); background: #0d0d14; }
#modal-title { font-family: var(--display); font-size: 17px; font-weight: 700; color: var(--accent); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 70%; }
#modal-actions { display: flex; gap: 8px; align-items: center; }
#modal-actions .btn { flex: none; padding: 5px 10px; }
#modal-close { background: none; border: none; color: var(--text-dim); font-size: 26px; cursor: pointer; padding: 2px 8px; line-height: 1; transition: color 0.15s; }
#modal-close:hover { color: var(--accent); }
#modal-body { flex: 1; overflow: auto; padding: 22px 26px; }
#modal-body h1, #modal-body h2, #modal-body h3, #modal-body h4 { font-family: var(--display); color: var(--accent); margin: 1.2em 0 0.5em; font-weight: 600; line-height: 1.3; }
#modal-body h1 { font-size: 1.7em; border-bottom: 1px solid var(--border); padding-bottom: 0.3em; }
#modal-body h2 { font-size: 1.4em; }
#modal-body h3 { font-size: 1.2em; }
#modal-body p { margin: 0.8em 0; line-height: 1.65; color: #ddd; }
#modal-body a { color: var(--accent); text-decoration: none; }
#modal-body a:hover { text-decoration: underline; }
#modal-body code { background: #1a1a2e; padding: 0.15em 0.4em; border-radius: 4px; font-family: 'SF Mono', 'Fira Code', monospace; font-size: 0.9em; color: var(--accent); }
#modal-body pre { background: #0d0d14; border: 1px solid var(--border); border-radius: 8px; padding: 16px; overflow-x: auto; margin: 1em 0; }
#modal-body pre code { background: none; padding: 0; color: var(--text); font-size: 0.85em; }
#modal-body blockquote { border-left: 3px solid var(--accent); padding-left: 16px; margin: 1em 0; color: var(--text-dim); font-style: italic; }
#modal-body ul, #modal-body ol { margin: 1em 0; padding-left: 24px; }
#modal-body li { margin: 0.4em 0; line-height: 1.55; }
#modal-body table { border-collapse: collapse; width: 100%; margin: 1em 0; font-size: 0.9em; }
#modal-body th, #modal-body td { border: 1px solid var(--border); padding: 8px 12px; text-align: left; }
#modal-body th { background: #1a1a2e; color: var(--accent); font-weight: 600; }
#modal-body tr:nth-child(even) { background: #151520; }
#modal-body hr { border: none; border-top: 1px solid var(--border); margin: 2em 0; }
#modal-body .wikilink { color: var(--accent); text-decoration: none; border-bottom: 1px dotted var(--accent); cursor: pointer; }
#modal-body .wikilink:hover { border-bottom: 1px solid var(--accent); background: rgba(90,228,170,0.1); }
#modal-body .wikilink.broken { color: #FF6B6B; border-bottom-color: #FF6B6B; cursor: not-allowed; }
#modal-body .frontmatter { background: #151520; border: 1px solid var(--border); border-radius: 8px; padding: 14px 16px; margin-bottom: 20px; font-size: 0.85em; color: #aaa; }
#modal-body .frontmatter .fm-key { color: var(--accent); font-weight: 600; }
#modal-body .frontmatter .fm-value { color: var(--text); }
#modal-body .fm-tag { display: inline-block; background: #1a1a2e; border: 1px solid #333; border-radius: 12px; padding: 1px 9px; margin: 2px 3px 2px 0; font-size: 0.85em; color: var(--accent); cursor: pointer; }
#modal-body .fm-tag:hover { border-color: var(--accent); }
.empty-note { color: var(--text-dim); font-style: italic; }
</style>
</head>
<body>
<div id="graph" role="application" aria-label="Knowledge graph of vault notes"></div>

<div id="panel">
  <h2>EntropicMem Graph</h2>
  <label for="node-search">Find a note</label>
  <input type="text" id="node-search" placeholder="Search titles… (Enter to jump)" autocomplete="off" aria-label="Search notes by title">
  <label for="tag-search">Filter by tag</label>
  <input type="text" id="tag-search" list="tag-suggestions" placeholder="e.g. infrastructure, hermes" aria-label="Filter nodes by tag">
  <datalist id="tag-suggestions"></datalist>
  <label>Domains</label>
  <div id="domain-checks"></div>
  <label for="imp-slider">Min importance: <span id="imp-val">0.0</span></label>
  <input type="range" id="imp-slider" min="0" max="1" step="0.05" value="0" aria-label="Minimum importance filter">
  <div class="btn-row">
    <button class="btn" id="btn-reset" type="button">Reset</button>
    <button class="btn" id="btn-export" type="button">Export PNG</button>
  </div>
</div>

<div id="focus-banner">Focused: <b id="focus-name"></b> — click empty space to release</div>
<div id="legend"></div>
<div id="minimap" aria-hidden="true"></div>
<div id="stats"></div>
<div id="tooltip" role="tooltip"></div>

<div id="modal-overlay"></div>
<div id="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title">
  <div id="modal-header">
    <span id="modal-title">Note</span>
    <div id="modal-actions">
      <button class="btn" id="btn-copy-link" type="button">Copy link</button>
      <button id="modal-close" aria-label="Close note">&times;</button>
    </div>
  </div>
  <div id="modal-body" tabindex="0"></div>
</div>

<script>
"use strict";
const DATA = __ENTROPICMEM_GRAPH_DATA__;

/* ── Derived lookups ── */
const PALETTE = {};
DATA.nodes.forEach(n => { if (n.domain && !PALETTE[n.domain]) PALETTE[n.domain] = n.color; });
const nodeById = new Map(DATA.nodes.map(n => [n.id, n]));
const nodeByTitle = new Map();
DATA.nodes.forEach(n => { nodeByTitle.set((n.title || n.id).toLowerCase(), n); });

// Adjacency for focus mode (undirected neighborhood)
const adjacency = new Map(DATA.nodes.map(n => [n.id, new Set()]));
DATA.edges.forEach(e => {
  const s = typeof e.source === "object" ? e.source.id : e.source;
  const t = typeof e.target === "object" ? e.target.id : e.target;
  if (adjacency.has(s)) adjacency.get(s).add(t);
  if (adjacency.has(t)) adjacency.get(t).add(s);
});

/* ── Visual encodings ── */
function nodeRadius(d) { return Math.max(5, Math.min(26, Math.log((d.importance || 0.3) * 100 + 1) * 6)); }
function edgeWidth(d) { return 0.6 + (d.weight || 1) * 1.1; }
function nodeColor(d) { return d.color || PALETTE[d.domain] || "#888"; }
function edgeDash(d) { return d.kind === "tag" ? "4,3" : null; }

/* ── State ── */
let simulation, svg, rootG, linkG, nodeG, labelG;
let mmSvg, mmNodeG, mmViewport;
let currentDomain = "", currentMinImp = 0, currentTag = "";
let focusedId = null;
let currentTransform = d3.zoomIdentity;
let lastTrigger = null;   // element that opened the modal, for focus return
let W = window.innerWidth, H = window.innerHeight;

const zoom = d3.zoom().scaleExtent([0.1, 5]).on("zoom", (event) => {
  currentTransform = event.transform;
  if (rootG) rootG.attr("transform", event.transform);
  updateMinimapViewport();
});

/* ── Shape path generator (centered on 0,0 for given radius) ── */
function shapePath(shape, r) {
  if (shape === "square") {
    const s = r * 1.7;
    return `M${-s/2},${-s/2} L${s/2},${-s/2} L${s/2},${s/2} L${-s/2},${s/2} Z`;
  }
  if (shape === "diamond") {
    const s = r * 1.5;
    return `M0,${-s} L${s},0 L0,${s} L${-s},0 Z`;
  }
  if (shape === "triangle") {
    const s = r * 1.6;
    return `M0,${-s} L${s * 0.87},${s * 0.5} L${-s * 0.87},${s * 0.5} Z`;
  }
  return null; // circle handled separately
}

/* ── Legend ── */
function buildLegend() {
  const legend = document.getElementById("legend");
  let html = '<div class="lg-title">Domains</div>';
  for (const [domain, color] of Object.entries(PALETTE)) {
    html += `<div class="row"><span class="swatch" style="background:${color};box-shadow:0 0 6px ${color};"></span>${domain}</div>`;
  }
  html += '<div class="lg-title" style="margin-top:8px;">Shapes</div>';
  html += '<div class="row"><span class="shape-glyph">●</span> permanent</div>';
  html += '<div class="row"><span class="shape-glyph">■</span> literature</div>';
  html += '<div class="row"><span class="shape-glyph">◆</span> moc</div>';
  html += '<div class="row"><span class="shape-glyph">▲</span> index / log</div>';
  html += '<div class="lg-title" style="margin-top:8px;">Edges</div>';
  html += '<div class="row"><span class="shape-glyph">—</span> wikilink</div>';
  html += '<div class="row"><span class="shape-glyph">┄</span> tag link</div>';
  legend.innerHTML = html;
}

/* ── Domain checkboxes ── */
function buildDomainChecks() {
  const container = document.getElementById("domain-checks");
  container.innerHTML = "";
  for (const domain of Object.keys(PALETTE).sort()) {
    const label = document.createElement("label");
    label.className = "domain-check";
    const cb = document.createElement("input");
    cb.type = "checkbox"; cb.value = domain; cb.checked = true;
    cb.addEventListener("change", updateFilters);
    const sw = document.createElement("span");
    sw.className = "swatch"; sw.style.background = PALETTE[domain];
    label.appendChild(cb); label.appendChild(sw);
    label.appendChild(document.createTextNode(domain));
    container.appendChild(label);
  }
}

/* ── Tag suggestions ── */
function buildTagSuggestions() {
  const tags = new Set();
  DATA.nodes.forEach(n => (n.tags || []).forEach(t => tags.add(t)));
  const dl = document.getElementById("tag-suggestions");
  dl.innerHTML = Array.from(tags).sort().map(t => `<option value="${t}">`).join("");
}

/* ── Filtering ── */
function getFilteredData() {
  let nodes = DATA.nodes;
  if (currentDomain) nodes = nodes.filter(n => n.domain === currentDomain);
  if (currentMinImp > 0) nodes = nodes.filter(n => (n.importance || 0) >= currentMinImp);
  if (currentTag) {
    const want = currentTag.toLowerCase().split(/[\s,]+/).filter(Boolean);
    nodes = nodes.filter(n => {
      const nt = (n.tags || []).map(t => t.toLowerCase()).join(" ");
      return want.every(t => nt.includes(t));
    });
  }
  const ids = new Set(nodes.map(n => n.id));
  const edges = DATA.edges.filter(e => {
    const s = typeof e.source === "object" ? e.source.id : e.source;
    const t = typeof e.target === "object" ? e.target.id : e.target;
    return ids.has(s) && ids.has(t);
  });
  return { nodes, edges };
}

function updateFilters() {
  const checks = document.querySelectorAll(".domain-check input");
  const active = Array.from(checks).filter(c => c.checked).map(c => c.value);
  currentDomain = active.length === 1 ? active[0] : "";
  currentMinImp = parseFloat(document.getElementById("imp-slider").value);
  currentTag = document.getElementById("tag-search").value.trim();
  document.getElementById("imp-val").textContent = currentMinImp.toFixed(1);
  render();
}

function resetFilters() {
  document.querySelectorAll(".domain-check input").forEach(c => c.checked = true);
  document.getElementById("imp-slider").value = 0;
  document.getElementById("tag-search").value = "";
  document.getElementById("node-search").value = "";
  currentDomain = ""; currentMinImp = 0; currentTag = "";
  document.getElementById("imp-val").textContent = "0.0";
  clearFocus();
  render();
}

/* ── Focus mode ── */
function applyFocus(id) {
  focusedId = id;
  const neighbors = adjacency.get(id) || new Set();
  nodeG.style("opacity", d => (d.id === id || neighbors.has(d.id)) ? 1 : 0.12);
  labelG.style("opacity", d => (d.id === id || neighbors.has(d.id)) ? 1 : 0.08);
  linkG.style("opacity", e => {
    const s = typeof e.source === "object" ? e.source.id : e.source;
    const t = typeof e.target === "object" ? e.target.id : e.target;
    return (s === id || t === id) ? 0.85 : 0.04;
  });
  const node = nodeById.get(id);
  document.getElementById("focus-name").textContent = node ? (node.title || node.id) : id;
  document.getElementById("focus-banner").style.display = "block";
}

function clearFocus() {
  focusedId = null;
  if (nodeG) nodeG.style("opacity", 1);
  if (labelG) labelG.style("opacity", 1);
  if (linkG) linkG.style("opacity", 0.5);
  document.getElementById("focus-banner").style.display = "none";
}

/* ── Search / zoom-to-node ── */
function jumpToNode(node) {
  if (!node) return;
  const scale = 1.8;
  const t = d3.zoomIdentity.translate(W / 2 - node.x * scale, H / 2 - node.y * scale).scale(scale);
  svg.transition().duration(650).call(zoom.transform, t);
  applyFocus(node.id);
}

function handleSearch() {
  const q = document.getElementById("node-search").value.trim().toLowerCase();
  if (!q) return;
  const { nodes } = getFilteredData();
  let best = nodes.find(n => (n.title || n.id).toLowerCase() === q);
  if (!best) best = nodes.find(n => (n.title || n.id).toLowerCase().includes(q));
  if (best) jumpToNode(best);
}

/* ── Render ── */
function render() {
  const { nodes, edges } = getFilteredData();
  const dropped = DATA.edges.length - edges.length;
  document.getElementById("stats").textContent =
    `${nodes.length} nodes / ${edges.length} edges` +
    (dropped > 0 ? ` (${dropped} hidden by filters)` : "") +
    ` | ${DATA.meta.domains.length} domains`;

  // Preserve positions of nodes that persist across re-renders
  const oldPos = new Map();
  if (nodeG) nodeG.each(function(d) { oldPos.set(d.id, { x: d.x, y: d.y, vx: d.vx, vy: d.vy }); });

  svg.selectAll(".layer").remove();
  rootG = svg.append("g").attr("class", "layer");
  linkG = rootG.append("g").attr("class", "links").selectAll("line").data(edges).join("line")
    .attr("stroke", "#3a3a4a").attr("stroke-width", edgeWidth)
    .attr("stroke-opacity", 0.5).attr("stroke-dasharray", edgeDash);

  nodeG = rootG.append("g").attr("class", "nodes").selectAll("g").data(nodes, d => d.id).join("g")
    .attr("class", "node-group").attr("tabindex", 0)
    .attr("role", "button").attr("aria-label", d => `${d.title || d.id}, ${d.domain || "uncategorized"}`)
    .call(d3.drag()
      .on("start", (event, d) => { if (!event.active) simulation.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
      .on("drag", (event, d) => { d.fx = event.x; d.fy = event.y; })
      .on("end", (event, d) => { if (!event.active) simulation.alphaTarget(0); d.fx = null; d.fy = null; }))
    .on("click", (event, d) => { event.stopPropagation(); openModal(d, event.currentTarget); })
    .on("keydown", (event, d) => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); openModal(d, event.currentTarget); }
    })
    .on("mouseover", (event, d) => showTooltip(event, d))
    .on("mousemove", moveTooltip)
    .on("mouseout", hideTooltip);

  // Restore positions for a smooth transition instead of a full re-scatter
  nodeG.each(function(d) {
    const p = oldPos.get(d.id);
    if (p) { d.x = p.x; d.y = p.y; d.vx = p.vx; d.vy = p.vy; }
  });

  // Shape per node type (circle vs path)
  nodeG.each(function(d) {
    const g = d3.select(this);
    const path = shapePath(d.shape, nodeRadius(d));
    if (path) {
      g.append("path").attr("class", "node-shape").attr("d", path)
        .attr("fill", nodeColor(d)).attr("stroke", "#fff")
        .attr("stroke-width", 0.6).attr("stroke-opacity", 0.25);
    } else {
      g.append("circle").attr("class", "node-shape").attr("r", nodeRadius(d))
        .attr("fill", nodeColor(d)).attr("stroke", "#fff")
        .attr("stroke-width", 0.6).attr("stroke-opacity", 0.25);
    }
  });

  labelG = rootG.append("g").attr("class", "labels").selectAll("text").data(nodes, d => d.id).join("text")
    .text(d => (d.title ? d.title.substring(0, 28) : d.id))
    .attr("dy", d => nodeRadius(d) + 12).attr("text-anchor", "middle");

  simulation = d3.forceSimulation(nodes)
    .force("link", d3.forceLink(edges).id(d => d.id).distance(85))
    .force("charge", d3.forceManyBody().strength(-140))
    .force("center", d3.forceCenter(W / 2, H / 2))
    .force("collision", d3.forceCollide().radius(d => nodeRadius(d) + 9));

  simulation.on("tick", () => {
    linkG.attr("x1", d => d.source.x).attr("y1", d => d.source.y)
         .attr("x2", d => d.target.x).attr("y2", d => d.target.y);
    nodeG.attr("transform", d => `translate(${d.x},${d.y})`);
    labelG.attr("x", d => d.x).attr("y", d => d.y);
    updateMinimap();
  });

  rootG.attr("transform", currentTransform);
  if (focusedId && nodeById.has(focusedId)) applyFocus(focusedId);
  else clearFocus();
}

/* ── Tooltip ── */
function showTooltip(event, d) {
  const tip = document.getElementById("tooltip");
  tip.style.display = "block";
  tip.innerHTML = `<div class="tt-title" style="color:${nodeColor(d)}">${escapeHtml(d.title || d.id)}</div>
    <div class="tt-meta">${d.type} · ${d.domain || "uncategorized"} · importance ${(d.importance || 0).toFixed(2)}</div>
    <div class="tt-meta">tags: ${(d.tags || []).join(", ") || "—"}</div>
    <div class="tt-meta" style="margin-top:3px;color:#5AE4AA;">click to open · drag to move</div>`;
  moveTooltip(event);
}
function moveTooltip(event) {
  const tip = document.getElementById("tooltip");
  tip.style.left = (event.pageX + 14) + "px";
  tip.style.top = (event.pageY - 10) + "px";
}
function hideTooltip() { document.getElementById("tooltip").style.display = "none"; }

/* ── Minimap ── */
function initMinimap() {
  mmSvg = d3.select("#minimap").append("svg").attr("width", 180).attr("height", 130);
  mmNodeG = mmSvg.append("g");
  mmViewport = mmSvg.append("rect").attr("class", "viewport-rect");
}
function updateMinimap() {
  if (!mmSvg || !nodeG) return;
  const nodes = nodeG.data();
  if (!nodes.length) return;
  const xs = nodes.map(n => n.x), ys = nodes.map(n => n.y);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const pad = 40;
  const bw = (maxX - minX) || 1, bh = (maxY - minY) || 1;
  const scale = Math.min(170 / (bw + pad * 2), 120 / (bh + pad * 2));
  const ox = 5 - (minX - pad) * scale, oy = 5 - (minY - pad) * scale;
  mmSvg._mm = { scale, ox, oy };
  mmNodeG.selectAll("circle").data(nodes, d => d.id).join("circle")
    .attr("cx", d => d.x * scale + ox).attr("cy", d => d.y * scale + oy)
    .attr("r", 1.6).attr("fill", nodeColor);
  updateMinimapViewport();
}
function updateMinimapViewport() {
  if (!mmSvg || !mmSvg._mm) return;
  const { scale, ox, oy } = mmSvg._mm;
  const t = currentTransform;
  // Visible world-space rect -> minimap coords
  const wx0 = (-t.x) / t.k, wy0 = (-t.y) / t.k;
  const wx1 = (W - t.x) / t.k, wy1 = (H - t.y) / t.k;
  mmViewport
    .attr("x", wx0 * scale + ox).attr("y", wy0 * scale + oy)
    .attr("width", (wx1 - wx0) * scale).attr("height", (wy1 - wy0) * scale);
}

/* ── Modal ── */
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function linkifyWikilinks(container) {
  // Convert [[Target]] text into clickable spans that open the target note.
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT, null);
  const targets = [];
  let n;
  while ((n = walker.nextNode())) {
    if (n.nodeValue && n.nodeValue.includes("[[")) targets.push(n);
  }
  targets.forEach(textNode => {
    const frag = document.createDocumentFragment();
    const parts = textNode.nodeValue.split(/(\[\[.+?\]\])/g);
    parts.forEach(part => {
      const m = part.match(/^\[\[(.+?)\]\]$/);
      if (m) {
        const raw = m[1];
        const target = raw.includes("|") ? raw.split("|")[0].trim() : raw.trim();
        const label = raw.includes("|") ? raw.split("|").slice(1).join("|").trim() : raw.trim();
        const dest = nodeByTitle.get(target.toLowerCase());
        const span = document.createElement("span");
        span.className = "wikilink" + (dest ? "" : " broken");
        span.textContent = label;
        span.setAttribute("role", "link");
        span.tabIndex = 0;
        if (dest) {
          const open = () => openModal(dest, span);
          span.addEventListener("click", open);
          span.addEventListener("keydown", (e) => { if (e.key === "Enter") open(); });
        } else {
          span.title = "Linked note not in this export";
        }
        frag.appendChild(span);
      } else if (part) {
        frag.appendChild(document.createTextNode(part));
      }
    });
    textNode.parentNode.replaceChild(frag, textNode);
  });
}

function openModal(node, trigger) {
  lastTrigger = trigger || document.activeElement;
  const modal = document.getElementById("modal");
  const overlay = document.getElementById("modal-overlay");
  const bodyEl = document.getElementById("modal-body");
  document.getElementById("modal-title").textContent = node.title || node.id;

  let content = '<div class="frontmatter">';
  if (node.domain) content += `<div><span class="fm-key">domain:</span> <span class="fm-value">${escapeHtml(node.domain)}</span></div>`;
  if (node.type) content += `<div><span class="fm-key">type:</span> <span class="fm-value">${escapeHtml(node.type)}</span></div>`;
  if (node.importance != null) content += `<div><span class="fm-key">importance:</span> <span class="fm-value">${node.importance.toFixed(2)}</span></div>`;
  if (node.tags && node.tags.length) {
    content += `<div><span class="fm-key">tags:</span> <span class="fm-value">` +
      node.tags.map(t => `<span class="fm-tag" data-tag="${escapeHtml(t)}">${escapeHtml(t)}</span>`).join("") +
      `</span></div>`;
  }
  content += '</div>';

  const noteBody = node.full_body || node.body_preview || "";
  if (noteBody) {
    content += marked.parse(noteBody);
  } else {
    content += '<p class="empty-note">No content available for this note.</p>';
  }

  bodyEl.innerHTML = content;
  linkifyWikilinks(bodyEl);

  // Tag chips filter the graph and close the modal
  bodyEl.querySelectorAll(".fm-tag").forEach(chip => {
    chip.addEventListener("click", () => {
      document.getElementById("tag-search").value = chip.dataset.tag;
      closeModal();
      updateFilters();
    });
  });

  modal.style.display = "flex";
  overlay.style.display = "block";
  document.body.style.overflow = "hidden";
  document.getElementById("modal-close").focus();
  applyFocus(node.id);
}

function closeModal() {
  document.getElementById("modal").style.display = "none";
  document.getElementById("modal-overlay").style.display = "none";
  document.body.style.overflow = "";
  if (lastTrigger && typeof lastTrigger.focus === "function") lastTrigger.focus();
}

/* ── Copy link to note ── */
function copyNoteLink() {
  const title = document.getElementById("modal-title").textContent;
  const url = `${location.origin}${location.pathname}#note=${encodeURIComponent(title)}`;
  navigator.clipboard.writeText(url).then(() => {
    const btn = document.getElementById("btn-copy-link");
    const orig = btn.textContent;
    btn.textContent = "Copied!";
    setTimeout(() => { btn.textContent = orig; }, 1200);
  }).catch(() => {});
}

/* ── Export PNG ── */
function exportPNG() {
  const svgEl = svg.node();
  const clone = svgEl.cloneNode(true);
  clone.setAttribute("width", W); clone.setAttribute("height", H);
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  const bg = document.createElementNS("http://www.w3.org/2000/svg", "rect");
  bg.setAttribute("width", W); bg.setAttribute("height", H); bg.setAttribute("fill", "#0a0a0f");
  clone.insertBefore(bg, clone.firstChild);
  const xml = new XMLSerializer().serializeToString(clone);
  const img = new Image();
  const svg64 = "data:image/svg+xml;base64," + btoa(unescape(encodeURIComponent(xml)));
  img.onload = () => {
    const canvas = document.createElement("canvas");
    canvas.width = W; canvas.height = H;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(img, 0, 0);
    const a = document.createElement("a");
    a.download = "entropicmem-graph.png";
    a.href = canvas.toDataURL("image/png");
    a.click();
  };
  img.src = svg64;
}

/* ── Wiring ── */
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeModal();
});

document.addEventListener("DOMContentLoaded", () => {
  svg = d3.select("#graph").append("svg").attr("width", "100%").attr("height", "100%");
  svg.call(zoom).on("click", () => clearFocus());
  initMinimap();
  buildLegend();
  buildDomainChecks();
  buildTagSuggestions();

  document.getElementById("imp-slider").addEventListener("input", updateFilters);
  document.getElementById("tag-search").addEventListener("input", updateFilters);
  document.getElementById("node-search").addEventListener("keydown", (e) => { if (e.key === "Enter") handleSearch(); });
  document.getElementById("btn-reset").addEventListener("click", resetFilters);
  document.getElementById("btn-export").addEventListener("click", exportPNG);
  document.getElementById("modal-close").addEventListener("click", closeModal);
  document.getElementById("modal-overlay").addEventListener("click", closeModal);
  document.getElementById("btn-copy-link").addEventListener("click", copyNoteLink);

  render();
  window.addEventListener("resize", () => { W = window.innerWidth; H = window.innerHeight; render(); });

  // Deep-link: open a note from #note=Title
  const m = location.hash.match(/#note=(.+)/);
  if (m) {
    const node = nodeByTitle.get(decodeURIComponent(m[1]).toLowerCase());
    if (node) setTimeout(() => { jumpToNode(node); openModal(node, null); }, 700);
  }
});
</script>
</body>
</html>"""
