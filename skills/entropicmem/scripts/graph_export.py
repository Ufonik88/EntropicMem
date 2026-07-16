"""
graph_export.py — Visual graph export for EntropicMem.

Exports vault data as JSON (primary), DOT (Graphviz), HTML (self-contained D3),
and Canvas format using data from VaultIndex.

Stdlib-only. D3 loaded from CDN in HTML output.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

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

    stats = index.get_stats()
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
) -> str:
    """
    Export as a single self-contained HTML file with embedded graph data.
    Works via file:// or HTTP server. D3 v7 loaded from CDN.
    """
    data = export_json(
        index, output_path.parent / "graph.json",
        domain=domain, min_importance=min_importance, max_nodes=max_nodes
    )
    graph_json = json.dumps(data)

    html = _HTML_TEMPLATE.replace("{{GRAPH_DATA}}", graph_json)
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
<script src="https://d3js.org/d3.v7.min.js"></script>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { background: #0a0a0f; color: #ccc; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; overflow: hidden; }
#graph { width: 100vw; height: 100vh; }
#panel { position: absolute; top: 12px; left: 12px; background: rgba(15,15,25,0.92); border: 1px solid #2a2a3a; border-radius: 8px; padding: 14px; max-width: 280px; font-size: 13px; z-index: 10; }
#panel h2 { font-size: 15px; margin: 0 0 8px; color: #5AE4AA; }
#panel label { display: block; margin: 6px 0 2px; color: #888; font-size: 11px; text-transform: uppercase; }
#panel select, #panel input { width: 100%; padding: 5px 8px; background: #1a1a2e; border: 1px solid #333; border-radius: 4px; color: #ccc; font-size: 12px; }
#panel input[type=range] { padding: 0; }
.domain-check { display: flex; align-items: center; gap: 6px; margin: 2px 0; font-size: 12px; }
.domain-check input { width: auto; }
#legend { position: absolute; bottom: 12px; right: 12px; background: rgba(15,15,25,0.92); border: 1px solid #2a2a3a; border-radius: 8px; padding: 10px 14px; font-size: 12px; z-index: 10; }
#legend .row { display: flex; align-items: center; gap: 8px; margin: 3px 0; }
#legend .swatch { width: 12px; height: 12px; border-radius: 50%; display: inline-block; }
#tooltip { position: absolute; background: rgba(10,10,20,0.94); border: 1px solid #444; border-radius: 6px; padding: 10px 14px; pointer-events: none; font-size: 12px; z-index: 20; display: none; max-width: 300px; }
#tooltip .tt-title { font-weight: 600; margin-bottom: 4px; }
#tooltip .tt-meta { color: #888; }
#stats { position: absolute; bottom: 12px; left: 12px; color: #555; font-size: 11px; z-index: 10; }
svg text { fill: #ccc; font-size: 10px; pointer-events: none; }
</style>
</head>
<body>
<div id="graph"></div>
<div id="panel">
  <h2>EntropicMem Graph</h2>
  <label>Domain filter</label>
  <div id="domain-checks"></div>
  <label>Min importance</label>
  <input type="range" id="imp-slider" min="0" max="1" step="0.05" value="0">
  <span id="imp-val">0.0</span>
  <label>Search tags</label>
  <input type="text" id="tag-search" placeholder="e.g. infrastructure, hermes">
  <br><br>
  <button onclick="resetFilters()" style="width:100%;padding:4px;background:#2a2a3a;border:1px solid #444;color:#ccc;border-radius:4px;cursor:pointer;">Reset</button>
</div>
<div id="legend"></div>
<div id="stats"></div>
<div id="tooltip"></div>
<script>
const DATA = {{GRAPH_DATA}};
const PALETTE = {};

// Build domain palette from data
DATA.nodes.forEach(n => { if (n.domain && !PALETTE[n.domain]) PALETTE[n.domain] = n.color; });

const SHAPES = { circle: "circle", square: "rect", diamond: "diamond", triangle: "triangle" };

let simulation, svg, linkG, nodeG, currentDomain = "", currentMinImp = 0, currentTag = "";

function nodeRadius(d) { return Math.max(4, Math.min(24, Math.log((d.importance || 0.3) * 100) * 6)); }
function edgeWidth(d) { return 0.5 + (d.weight || 1) * 1.2; }
function nodeColor(d) { return d.color || PALETTE[d.domain] || "#888"; }

function buildLegend() {
  const legend = document.getElementById("legend");
  let html = '<div style="font-weight:600;margin-bottom:4px;">Domains</div>';
  for (const [domain, color] of Object.entries(PALETTE)) {
    html += `<div class="row"><span class="swatch" style="background:${color};box-shadow:0 0 6px ${color};"></span>${domain}</div>`;
  }
  html += '<div style="margin-top:6px;font-weight:600;">Shapes</div>';
  html += '<div class="row"><span style="width:12px;text-align:center;">●</span> permanent</div>';
  html += '<div class="row"><span style="width:12px;text-align:center;">■</span> literature</div>';
  html += '<div class="row"><span style="width:12px;text-align:center;">◆</span> moc/index</div>';
  legend.innerHTML = html;
}

function buildDomainChecks() {
  const container = document.getElementById("domain-checks");
  container.innerHTML = "";
  for (const domain of Object.keys(PALETTE).sort()) {
    const label = document.createElement("label");
    label.className = "domain-check";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.value = domain;
    cb.checked = true;
    cb.onchange = updateFilters;
    label.appendChild(cb);
    label.appendChild(document.createTextNode(domain));
    container.appendChild(label);
  }
}

function getFilteredData() {
  let nodes = DATA.nodes;
  if (currentDomain) nodes = nodes.filter(n => n.domain === currentDomain);
  if (currentMinImp > 0) nodes = nodes.filter(n => (n.importance || 0) >= currentMinImp);
  if (currentTag) {
    const tags = currentTag.toLowerCase().split(/[\s,]+/).filter(Boolean);
    nodes = nodes.filter(n => {
      const nt = (n.tags || []).map(t => t.toLowerCase()).join(" ");
      return tags.every(t => nt.includes(t));
    });
  }
  const nodeIds = new Set(nodes.map(n => n.id));
  const edges = DATA.edges.filter(e => nodeIds.has(e.source) && nodeIds.has(e.target));
  return { nodes, edges };
}

function updateFilters() {
  const checks = document.querySelectorAll(".domain-check input");
  const active = Array.from(checks).filter(c => c.checked).map(c => c.value);
  currentDomain = active.length === Object.keys(PALETTE).length ? "" : "";
  if (active.length === 1) currentDomain = active[0];
  currentMinImp = parseFloat(document.getElementById("imp-slider").value);
  currentTag = document.getElementById("tag-search").value.trim();
  document.getElementById("imp-val").textContent = currentMinImp.toFixed(1);
  render();
}

function resetFilters() {
  document.querySelectorAll(".domain-check input").forEach(c => c.checked = true);
  document.getElementById("imp-slider").value = 0;
  document.getElementById("tag-search").value = "";
  currentDomain = ""; currentMinImp = 0; currentTag = "";
  document.getElementById("imp-val").textContent = "0.0";
  render();
}

function render() {
  const { nodes, edges } = getFilteredData();
  document.getElementById("stats").textContent =
    `${nodes.length} nodes / ${edges.length} edges | ${DATA.meta.domains.length} domains`;

  const W = window.innerWidth, H = window.innerHeight;
  svg.selectAll("*").remove();

  // Glow filter
  const defs = svg.append("defs");
  const filter = defs.append("filter").attr("id", "glow");
  filter.append("feGaussianBlur").attr("stdDeviation", "2.5").attr("result", "blur");
  const merge = filter.append("feMerge");
  merge.append("feMergeNode").attr("in", "blur");
  merge.append("feMergeNode").attr("in", "SourceGraphic");

  // Edges
  linkG = svg.append("g").selectAll("line").data(edges).join("line")
    .attr("stroke", "#333").attr("stroke-width", edgeWidth).attr("stroke-opacity", 0.5);

  // Nodes
  nodeG = svg.append("g").selectAll("g").data(nodes).join("g")
    .attr("cursor", "pointer")
    .call(d3.drag()
      .on("start", (event, d) => { if (!event.active) simulation.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
      .on("drag", (event, d) => { d.fx = event.x; d.fy = event.y; })
      .on("end", (event, d) => { if (!event.active) simulation.alphaTarget(0); d.fx = null; d.fy = null; })
    );

  nodeG.append("circle")
    .attr("r", nodeRadius)
    .attr("fill", nodeColor)
    .attr("filter", "url(#glow)")
    .attr("stroke", "#fff").attr("stroke-width", 0.5).attr("stroke-opacity", 0.2);

  nodeG.append("text")
    .text(d => d.title ? d.title.substring(0, 30) : d.id)
    .attr("dy", d => nodeRadius(d) + 12)
    .attr("text-anchor", "middle")
    .attr("fill", "#aaa")
    .style("font-size", "9px");

  // Tooltip
  nodeG.on("mouseover", (event, d) => {
    const tip = document.getElementById("tooltip");
    tip.style.display = "block";
    tip.innerHTML = `<div class="tt-title" style="color:${nodeColor(d)}">${d.title || d.id}</div>
      <div class="tt-meta">${d.type} | ${d.domain || "uncategorized"} | imp: ${(d.importance || 0).toFixed(2)}</div>
      <div class="tt-meta">tags: ${(d.tags || []).join(", ") || "—"}<br>Click to open in vault</div>`;
  });
  nodeG.on("mousemove", (event) => {
    const tip = document.getElementById("tooltip");
    tip.style.left = (event.pageX + 14) + "px";
    tip.style.top = (event.pageY - 10) + "px";
  });
  nodeG.on("mouseout", () => { document.getElementById("tooltip").style.display = "none"; });

  // Click → open via protocol
  nodeG.on("click", (event, d) => {
    const url = "entropicmem://open/" + encodeURIComponent(d.id);
    try { navigator.sendBeacon(url); } catch(e) {}
    window.open(url, "_blank");
  });

  // Simulation
  simulation = d3.forceSimulation(nodes)
    .force("link", d3.forceLink(edges).id(d => d.id).distance(80))
    .force("charge", d3.forceManyBody().strength(-120))
    .force("center", d3.forceCenter(W / 2, H / 2))
    .force("collision", d3.forceCollide().radius(d => nodeRadius(d) + 8));

  simulation.on("tick", () => {
    linkG.attr("x1", d => d.source.x).attr("y1", d => d.source.y)
         .attr("x2", d => d.target.x).attr("y2", d => d.target.y);
    nodeG.attr("transform", d => `translate(${d.x},${d.y})`);
  });
}

// Init
document.addEventListener("DOMContentLoaded", () => {
  svg = d3.select("#graph").append("svg").attr("width", "100%").attr("height", "100%");
  buildLegend();
  buildDomainChecks();
  document.getElementById("imp-slider").oninput = updateFilters;
  document.getElementById("tag-search").oninput = updateFilters;
  render();
  window.addEventListener("resize", render);
});
</script>
</body>
</html>"""
