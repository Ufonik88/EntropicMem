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

# ── per-domain color palette (brand-inspired, colorblind-safe) ─────────────

DOMAIN_PALETTE = {
    "Infrastructure": "#1DCF8E",
    "Acme Corp": "#5AE4AA",
    "Content-Growth": "#00AD74",
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


# ─ community palette + detection (structure layer, stdlib) ───────────────
# Okabe-Ito colorblind-safe core set plus accessible extras that read on the
# dark galaxy theme. Deterministic per community id (indexed, cycles when the
# number of communities exceeds the palette).

COMMUNITY_PALETTE = [
    "#E69F00",  # orange
    "#56B4E9",  # sky blue
    "#009E73",  # bluish green
    "#F0E442",  # yellow
    "#0072B2",  # blue
    "#D55E00",  # vermillion
    "#CC79A7",  # reddish purple
    "#5AE4AA",  # accent green
    "#FF6B6B",  # soft red
    "#9CCC65",  # light green
    "#7C4DFF",  # violet
]


def get_community_color(community_id: int) -> str:
    return COMMUNITY_PALETTE[community_id % len(COMMUNITY_PALETTE)]


def detect_communities(edges, max_iter: int = 30) -> dict:
    """Label propagation over an undirected edge set. Stdlib-only.

    Deterministic by construction: nodes are processed in sorted order, ties
    between candidate labels resolve to the smallest label, and final ids are
    renumbered by (size desc, smallest member). Identical graph state always
    produces identical ids, so community colors cannot flicker between
    rebuilds.

    Args:
        edges: iterable of (source_id, target_id) pairs.
        max_iter: sweep cap; label propagation converges well before this on
            vault-scale graphs.

    Returns:
        {node_id: community_id} for nodes participating in at least one edge.
        Isolated nodes are absent (and export as community=null).
    """
    adjacency: dict = {}
    for source, target in edges:
        if source == target:
            continue
        adjacency.setdefault(source, set()).add(target)
        adjacency.setdefault(target, set()).add(source)
    if not adjacency:
        return {}

    labels = {node: node for node in adjacency}
    for _ in range(max_iter):
        changed = False
        for node in sorted(adjacency):
            neighbors = adjacency[node]
            if not neighbors:
                continue
            counts: dict = {}
            for neighbor in neighbors:
                label = labels[neighbor]
                counts[label] = counts.get(label, 0) + 1
            best = min(counts, key=lambda label: (-counts[label], label))
            if labels[node] != best:
                labels[node] = best
                changed = True
        if not changed:
            break

    groups: dict = {}
    for node, label in labels.items():
        groups.setdefault(label, []).append(node)
    ordered = sorted(groups.values(), key=lambda members: (-len(members), min(members)))
    community_of: dict = {}
    for community_id, members in enumerate(ordered):
        for node in members:
            community_of[node] = community_id
    return community_of


def body_coverage(nodes: list) -> dict:
    """Return body coverage stats for a graph node list.

    Used by the graph server, refresh wrapper, and health check so empty
    modals can never go silent again.
    """
    total = len(nodes or [])
    with_body = 0
    for n in nodes or []:
        if (n.get("full_body") or n.get("body_preview") or "").strip():
            with_body += 1
    empty = total - with_body
    pct = (100.0 * with_body / total) if total else 100.0
    return {
        "total": total,
        "with_body": with_body,
        "empty": empty,
        "coverage_pct": round(pct, 1),
        "ok": total == 0 or empty == 0,
    }


def assert_bodies_present(payload: dict, *, context: str = "graph export") -> dict:
    """Raise RuntimeError if bodies were requested but the export is body-less.

    The failure mode we hit twice: include_bodies claimed True (or the local
    viewer expects bodies) but every node lacks full_body/body_preview, so
    every modal shows \"No content available\". A few genuinely empty notes
    are fine; a near-total miss is not.
    """
    nodes = payload.get("nodes") or []
    stats = body_coverage(nodes)
    meta = payload.get("meta") or {}
    if meta.get("include_bodies") is False:
        return stats  # lean export is intentional
    total = stats["total"]
    if total == 0:
        return stats
    # Hard fail: zero bodies when nodes exist
    if stats["with_body"] == 0:
        raise RuntimeError(
            f"{context}: 0/{total} nodes have body content "
            f"(coverage {stats['coverage_pct']}%). "
            "Refusing a body-less graph export — this is the empty-modal bug."
        )
    # Soft fail: large export with most bodies missing (index/FTS broken)
    if total >= 10 and stats["coverage_pct"] < 90.0:
        raise RuntimeError(
            f"{context}: only {stats['with_body']}/{total} nodes have bodies "
            f"({stats['coverage_pct']}% < 90%). "
            "Index/FTS likely stale — rebuild before accepting the export."
        )
    return stats


# ── JSON export ─────────────────────────────────────────────────────────────

def export_json(
    index: VaultIndex,
    output_path: Path,
    domain: Optional[str] = None,
    min_importance: float = 0.0,
    max_nodes: int = 500,
    include_bodies: bool = False,
) -> dict:
    """
    Export nodes + edges as JSON. Primary format consumed by graph.html.

    Note bodies (body_preview/full_body) are only embedded when
    include_bodies=True. Default is off so a shared/exported graph.json
    never leaks vault content. Pass include_bodies=True only for offline
    modal reading on a trusted machine.

    Returns the dict that was written (for testing).
    """
    # Full in-scope edge set. Single fetch (previously fetched twice with the
    # same args): drives degree, community detection, and the cap re-rank.
    all_edges = index.get_graph_edges(domain=domain, min_weight=1)
    degree_of: dict = {}
    for e in all_edges:
        degree_of[e.source_id] = degree_of.get(e.source_id, 0) + 1
        degree_of[e.target_id] = degree_of.get(e.target_id, 0) + 1
    community_of = detect_communities((e.source_id, e.target_id) for e in all_edges)

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

        community_id = community_of.get(n["note_id"])
        node_list.append({
            "id": n["note_id"],
            "title": n.get("title", n["note_id"]),
            "type": n.get("note_type", "permanent"),
            "domain": n.get("domain", ""),
            "importance": n.get("importance", 0.3),
            "tags": tags,
            "color": get_color(n.get("domain", "")),
            "shape": get_shape(n.get("note_type", "permanent")),
            "community": community_id,
            "community_color": (
                get_community_color(community_id)
                if community_id is not None else DEFAULT_COLOR
            ),
            "degree": degree_of.get(n["note_id"], 0),
        })
        # Bodies only embedded when explicitly requested (security default: off)
        if include_bodies:
            node_list[-1]["body_preview"] = n.get("body_preview", "")
            node_list[-1]["full_body"] = n.get("full_body", n.get("body_preview", ""))
            # path helps the modal frontmatter; only with bodies (same trust plane)
            if n.get("path"):
                node_list[-1]["path"] = n["path"]

    # Build edge list (only edges where both nodes exist in the export set)
    node_ids = {n["id"] for n in node_list}

    # If we hit the max_nodes cap, re-rank to prefer triple-heavy / high-degree
    # nodes so the visible graph looks like a connected web, not an isolated
    # importance-sorted dot field. Edges whose endpoints are both kept stay;
    # nodes that got truncated drop their incident edges.
    if max_nodes and len(node_list) >= max_nodes:
        node_list.sort(key=lambda n: (n.get("degree", 0), n.get("importance", 0.3)), reverse=True)
        node_list = node_list[:max_nodes]
        node_ids = {n["id"] for n in node_list}
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
            "include_bodies": include_bodies,
            "domains": list(set(n.get("domain", "") for n in node_list)),
            "community_count": len(set(community_of.values())),
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
    payload["meta"]["body_coverage"] = body_coverage(node_list)

    # Hard gate: never write a "bodies included" export that is actually empty.
    # This is the permanent fix for empty graph modals (hit twice before).
    if include_bodies:
        assert_bodies_present(payload, context=f"export_json({output_path})")

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
    include_bodies: bool = False,
) -> str:
    """
    Export as a single self-contained HTML file with embedded graph data.
    Works via file:// or HTTP server. D3 v7 + marked loaded from CDN, with
    automatic fallback to vendored copies placed next to the output file.

    By default note bodies are NOT embedded (security: avoids leaking vault
    content via local HTTP/graph share). Pass include_bodies=True for offline
    modal reading on a trusted machine only.

    vault_root: path to the vault when include_bodies=True. When omitted and
    bodies are requested, resolved from ENTROPICMEM_VAULT_PATH only (not Obsidian).
    """
    data = export_json(
        index, output_path.parent / "graph.json",
        domain=domain, min_importance=min_importance, max_nodes=max_nodes,
        include_bodies=include_bodies,
    )

    # Attach full bodies only when explicitly requested.
    if include_bodies:
        vault = None
        if vault_root is None:
            try:
                import os

                from vault import resolve_vault_path
                env = os.environ.get("ENTROPICMEM_VAULT_PATH")
                vault_root = Path(env).expanduser() if env else resolve_vault_path()
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
                # Skip nodes that already have full_body from the data source
                # (e.g. FTS index enrichment in get_graph_nodes)
                if node.get("full_body", ""):
                    continue
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
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<script src="https://d3js.org/d3.v7.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<style>
:root {
  --bg: #0a0a0f;
  --bg-grad: radial-gradient(ellipse at 50% 0%, #12121c 0%, #0a0a0f 60%);
  --panel: rgba(15,15,25,0.88);
  --border: #2a2a3a;
  --border-subtle: rgba(90,228,170,0.08);
  --accent: #5AE4AA;
  --accent-dim: #1DCF8E;
  --accent-glow: rgba(90,228,170,0.15);
  --text: #d6d6de;
  --text-dim: #9a9aa8;
  --text-bright: #f2f2f7;
  --display: 'Space Grotesk', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  --body: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  --blur: 12px;
  --radius: 12px;
  --radius-sm: 6px;
  --transition: 0.18s cubic-bezier(0.4, 0, 0.2, 1);
}
* { margin: 0; padding: 0; box-sizing: border-box; }
html, body { height: 100%; }
body { background: var(--bg-grad); color: var(--text); font-family: var(--body); overflow: hidden; }
#graph { position: absolute; inset: 0; width: 100vw; height: 100vh; }
#graph svg { display: block; }

/* ── Shared icon button / collapse affordances ── */
.icon { width: 14px; height: 14px; stroke: currentColor; fill: none; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; flex: none; }
.collapse-btn { position: absolute; top: 10px; right: 10px; background: none; border: none; color: var(--text-dim); cursor: pointer; padding: 4px; border-radius: 6px; line-height: 0; transition: color var(--transition), background var(--transition); }
.collapse-btn:hover { color: var(--accent); background: rgba(90,228,170,0.08); }
.collapse-btn .icon-chev { transition: transform 0.25s ease; }
.collapsed .collapse-btn .icon-chev { transform: rotate(180deg); }

/* ── Control panel ── */
#panel { position: absolute; top: 12px; left: 12px; background: var(--panel); border: 1px solid var(--border); border-radius: var(--radius); padding: 16px; width: 264px; font-size: 13px; z-index: 10; backdrop-filter: blur(var(--blur)); -webkit-backdrop-filter: blur(var(--blur)); max-height: calc(100vh - 24px); overflow-y: auto; box-shadow: 0 8px 32px rgba(0,0,0,0.4); transition: transform 0.25s ease; }
#panel.collapsed { transform: translateX(calc(-100% + 44px)); overflow: hidden; }
#panel.collapsed:hover { transform: translateX(calc(-100% + 52px)); }
#panel h2 { font-family: var(--display); font-size: 16px; font-weight: 700; margin: 0 0 12px; color: var(--accent); letter-spacing: 0.3px; text-shadow: 0 0 12px var(--accent-glow); padding-right: 24px; }
#panel label { display: block; margin: 12px 0 4px; color: var(--text-dim); font-size: 10px; text-transform: uppercase; letter-spacing: 0.8px; font-weight: 600; }
#panel select, #panel input[type=text] { width: 100%; padding: 7px 10px; background: #1a1a2e; border: 1px solid #333; border-radius: var(--radius-sm); color: var(--text); font-size: 12px; font-family: var(--body); transition: border-color var(--transition); }
#panel input[type=text]:focus, #panel select:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 2px var(--accent-glow); }
#panel input[type=range] { width: 100%; accent-color: var(--accent); }
#panel .shortcuts { margin-top: 14px; padding-top: 10px; border-top: 1px solid var(--border); color: var(--text-dim); font-size: 10px; line-height: 1.8; }
#panel .shortcuts kbd { background: #1a1a2e; border: 1px solid #333; border-radius: 4px; padding: 0 5px; font-family: inherit; font-size: 10px; color: var(--text); }
.domain-check { display: flex; align-items: center; gap: 7px; margin: 3px 0; font-size: 12px; cursor: pointer; }
.domain-check input { width: auto; accent-color: var(--accent); }
.domain-check .swatch { width: 10px; height: 10px; border-radius: 50%; flex: none; }
.btn-row { display: flex; gap: 6px; margin-top: 14px; }
.btn { flex: 1; padding: 7px; background: #2a2a3a; border: 1px solid #444; color: var(--text); border-radius: var(--radius-sm); cursor: pointer; font-size: 11px; font-family: var(--body); transition: all var(--transition); }
.btn:hover { background: #353548; border-color: var(--accent); color: var(--accent); box-shadow: 0 0 12px var(--accent-glow); }
.btn:active { transform: scale(0.97); }
.zoom-row { display: flex; gap: 6px; margin-top: 12px; }
.zoom-btn { flex: 1; display: flex; align-items: center; justify-content: center; padding: 6px; background: #1a1a2e; border: 1px solid #333; color: var(--text-dim); border-radius: var(--radius-sm); cursor: pointer; transition: all var(--transition); line-height: 0; }
.zoom-btn:hover { border-color: var(--accent); color: var(--accent); box-shadow: 0 0 10px var(--accent-glow); }
.zoom-btn:active { transform: scale(0.94); }
#imp-val { color: var(--accent); font-weight: 600; }
#search-results { margin-top: 6px; max-height: 220px; overflow-y: auto; border: 1px solid #333; border-radius: var(--radius-sm); background: #14141f; }
#search-results[hidden] { display: none; }
.search-hit { display: block; width: 100%; text-align: left; background: none; border: none; border-bottom: 1px solid #222232; padding: 7px 9px; color: var(--text); cursor: pointer; font-family: var(--body); }
.search-hit:last-child { border-bottom: none; }
.search-hit:hover { background: rgba(90,228,170,0.08); }
.search-hit .sh-title { display: block; font-size: 12px; }
.search-hit .sh-meta { display: block; font-size: 10px; color: var(--text-dim); margin-top: 1px; }
.search-hit.off-graph .sh-title { color: var(--text-dim); }
.search-empty { padding: 8px 9px; color: var(--text-dim); font-size: 11px; }

/* ── Bottom-right dock (legend + minimap move as one unit) ── */
#dock { position: absolute; bottom: 12px; right: 12px; display: flex; flex-direction: column; align-items: flex-end; gap: 10px; z-index: 10; }
#legend { position: relative; background: var(--panel); border: 1px solid var(--border); border-radius: var(--radius); padding: 12px 16px; font-size: 12px; backdrop-filter: blur(var(--blur)); -webkit-backdrop-filter: blur(var(--blur)); width: 220px; box-shadow: 0 8px 32px rgba(0,0,0,0.4); transition: opacity 0.2s ease, transform 0.25s ease; }
#legend.collapsed { opacity: 0; pointer-events: none; transform: translateX(16px) scale(0.96); }
#legend .lg-title { font-family: var(--display); font-weight: 600; margin-bottom: 6px; color: var(--text-bright); font-size: 11px; text-transform: uppercase; letter-spacing: 0.6px; padding-right: 20px; }
#legend .row { display: flex; align-items: center; gap: 8px; margin: 3px 0; color: var(--text-dim); }
#legend .swatch { width: 11px; height: 11px; border-radius: 50%; flex: none; }
#legend .shape-glyph { width: 14px; text-align: center; flex: none; color: var(--text); display: inline-flex; justify-content: center; }
#legend .shape-glyph svg { display: block; }

/* ── Minimap ── */
#minimap-wrap { position: relative; transition: opacity 0.2s ease, transform 0.25s ease; }
#minimap-wrap.collapsed { opacity: 0; pointer-events: none; transform: translateX(16px) scale(0.96); }
#minimap { width: 180px; height: 130px; background: var(--panel); border: 1px solid var(--border); border-radius: var(--radius); overflow: hidden; backdrop-filter: blur(var(--blur)); -webkit-backdrop-filter: blur(var(--blur)); cursor: pointer; box-shadow: 0 8px 32px rgba(0,0,0,0.4); }
#minimap .viewport-rect { fill: rgba(90,228,170,0.12); stroke: var(--accent); stroke-width: 1; }

/* ── Tooltip ── */
#tooltip { position: absolute; background: rgba(10,10,20,0.96); border: 1px solid #444; border-radius: 8px; padding: 10px 13px; pointer-events: none; font-size: 12px; z-index: 20; display: none; max-width: 300px; box-shadow: 0 6px 24px rgba(0,0,0,0.5); }
#tooltip .tt-title { font-family: var(--display); font-weight: 600; margin-bottom: 4px; }
#tooltip .tt-meta { color: var(--text-dim); line-height: 1.5; }

/* ── Stats / status ── */
#stats-wrap { position: absolute; bottom: 12px; left: 12px; z-index: 10; transition: opacity 0.2s ease, transform 0.25s ease; }
#stats-wrap.collapsed { opacity: 0; pointer-events: none; transform: translateY(8px); }
#stats { background: var(--panel); border: 1px solid var(--border); border-radius: 20px; padding: 6px 34px 6px 14px; color: var(--text-dim); font-size: 11px; backdrop-filter: blur(var(--blur)); -webkit-backdrop-filter: blur(var(--blur)); position: relative; }
#stats .collapse-btn { top: 50%; right: 8px; transform: translateY(-50%); padding: 2px; }
#focus-banner { position: absolute; top: 12px; left: 50%; transform: translateX(-50%); background: var(--panel); border: 1px solid var(--accent); color: var(--accent); border-radius: 20px; padding: 6px 16px; font-size: 12px; z-index: 10; display: none; backdrop-filter: blur(var(--blur)); -webkit-backdrop-filter: blur(var(--blur)); box-shadow: 0 0 24px var(--accent-glow); }
#focus-banner b { font-family: var(--display); }
#path-banner { position: absolute; top: 12px; left: 50%; transform: translateX(-50%); background: var(--panel); border: 1px solid var(--accent); color: var(--accent); border-radius: 20px; padding: 6px 16px; font-size: 12px; z-index: 11; display: none; backdrop-filter: blur(var(--blur)); -webkit-backdrop-filter: blur(var(--blur)); box-shadow: 0 0 24px var(--accent-glow); max-width: 82vw; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

/* ── Loading / empty states ── */
#loading { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 14px; z-index: 50; background: var(--bg-grad); color: var(--text-dim); font-size: 13px; letter-spacing: 0.4px; transition: opacity 0.4s ease; }
#loading.done { opacity: 0; pointer-events: none; }
#loading .spinner { width: 34px; height: 34px; border-radius: 50%; border: 2px solid var(--border); border-top-color: var(--accent); animation: spin 0.9s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
#empty-state { position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); text-align: center; color: var(--text-dim); font-size: 13px; z-index: 5; display: none; pointer-events: none; }
#empty-state .empty-title { font-family: var(--display); font-size: 15px; color: var(--text); margin-bottom: 6px; }

svg text { fill: #b9b9c6; font-size: 9px; pointer-events: none; font-family: var(--body); shape-rendering: geometricPrecision; }
.node-shape { cursor: pointer; transition: opacity var(--transition); }
.node-halo { transition: opacity 0.3s ease-out, r 0.3s ease-out; }
.node-group { transition: filter var(--transition), opacity var(--transition); }
.node-group:hover .node-shape { filter: url(#node-glow-strong) !important; }
.node-group:focus { outline: none; }
.node-group:focus .node-shape { stroke: #fff; stroke-width: 2; }
.node-group.selected .node-shape { stroke: var(--accent); stroke-width: 2.2; stroke-opacity: 0.9; filter: url(#node-glow-strong); }
.node-group.on-path .node-shape { stroke: var(--accent); stroke-width: 2.2; stroke-opacity: 0.95; filter: url(#node-glow-strong); }

/* ── Modal ── */
#modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.85); z-index: 100; display: none; backdrop-filter: blur(4px); }
#modal { position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%); width: 78vw; max-width: 1000px; height: 80vh; max-height: 92vh; background: #111218; border: 1px solid var(--border); border-radius: 16px; z-index: 101; display: none; flex-direction: column; overflow: hidden; box-shadow: 0 24px 72px rgba(0,0,0,0.7), 0 0 0 1px rgba(90,228,170,0.12); }
#modal-header { display: flex; align-items: center; justify-content: space-between; padding: 16px 20px; border-bottom: 1px solid var(--border); background: #0d0d14; }
#modal-title { font-family: var(--display); font-size: 17px; font-weight: 700; color: var(--accent); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 70%; }
#modal-actions { display: flex; gap: 8px; align-items: center; }
#modal-actions .btn { flex: none; padding: 5px 10px; display: inline-flex; align-items: center; gap: 5px; }
#modal-close { background: none; border: none; color: var(--text-dim); cursor: pointer; padding: 4px 6px; line-height: 0; border-radius: 6px; transition: color 0.15s, background 0.15s; }
#modal-close:hover { color: var(--accent); background: rgba(90,228,170,0.08); }
#modal-close .icon { width: 18px; height: 18px; }
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
#modal-body .wikilink.pending { color: var(--accent-dim); border-bottom: 1px dashed var(--accent-dim); cursor: pointer; }
#modal-body .wikilink.pending:hover { color: var(--accent); border-bottom-color: var(--accent); background: rgba(90,228,170,0.1); }
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

<svg width="0" height="0" style="position:absolute" aria-hidden="true">
  <defs>
    <filter id="node-glow" x="-50%" y="-50%" width="200%" height="200%">
      <feGaussianBlur stdDeviation="2.5" result="blur"/>
      <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <filter id="node-glow-strong" x="-100%" y="-100%" width="300%" height="300%">
      <feGaussianBlur stdDeviation="4.5" result="blur"/>
      <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
  </defs>
</svg>

<div id="panel">
  <button class="collapse-btn" id="collapse-panel" aria-label="Toggle control panel" aria-expanded="true" title="Toggle panel (H)"><svg class="icon icon-chev" viewBox="0 0 24 24"><polyline points="15 18 9 12 15 6"/></svg></button>
  <h2>EntropicMem Graph</h2>
  <label for="node-search">Find a note</label>
  <input type="text" id="node-search" placeholder="Search titles… (Enter to jump)" autocomplete="off" aria-label="Search notes by title">
  <label for="vault-search">Search the vault</label>
  <input type="text" id="vault-search" placeholder="Full-text search… (Enter)" autocomplete="off" aria-label="Full-text vault search">
  <div id="search-results" hidden></div>
  <label for="tag-search">Filter by tag</label>
  <input type="text" id="tag-search" list="tag-suggestions" placeholder="e.g. infrastructure, hermes" aria-label="Filter nodes by tag">
  <datalist id="tag-suggestions"></datalist>
  <label>Domains</label>
  <div id="domain-checks"></div>
  <label for="color-mode">Color by</label>
  <select id="color-mode" aria-label="Node color mode">
    <option value="domain" selected>Domain</option>
    <option value="community">Community</option>
  </select>
  <label class="domain-check" style="margin-top:10px;"><input type="checkbox" id="island-toggle" aria-label="Cluster islands layout"> Cluster islands</label>
  <label class="domain-check"><input type="checkbox" id="orphan-toggle" aria-label="Highlight orphan notes"> Highlight orphans</label>
  <label for="imp-slider">Min importance: <span id="imp-val">0.0</span></label>
  <input type="range" id="imp-slider" min="0" max="1" step="0.05" value="0" aria-label="Minimum importance filter">
  <div class="zoom-row" role="group" aria-label="Zoom controls">
    <button class="zoom-btn" id="btn-zoom-in" type="button" aria-label="Zoom in (+)" title="Zoom in (+)"><svg class="icon" viewBox="0 0 24 24"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/><line x1="11" y1="8" x2="11" y2="14"/><line x1="8" y1="11" x2="14" y2="11"/></svg></button>
    <button class="zoom-btn" id="btn-zoom-out" type="button" aria-label="Zoom out (-)" title="Zoom out (-)"><svg class="icon" viewBox="0 0 24 24"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/><line x1="8" y1="11" x2="14" y2="11"/></svg></button>
    <button class="zoom-btn" id="btn-zoom-fit" type="button" aria-label="Fit graph to view (0)" title="Fit to view (0)"><svg class="icon" viewBox="0 0 24 24"><path d="M8 3H5a2 2 0 0 0-2 2v3"/><path d="M16 3h3a2 2 0 0 1 2 2v3"/><path d="M8 21H5a2 2 0 0 1-2-2v-3"/><path d="M16 21h3a2 2 0 0 0 2-2v-3"/></svg></button>
    <button class="zoom-btn" id="btn-zoom-100" type="button" aria-label="Reset zoom to 100%" title="Actual size (1:1)"><svg class="icon" viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><circle cx="12" cy="12" r="9" stroke-dasharray="3 3"/></svg></button>
  </div>
  <div class="btn-row">
    <button class="btn" id="btn-reset" type="button">Reset</button>
    <button class="btn" id="btn-export" type="button">Export PNG</button>
  </div>
  <div class="shortcuts">
    <kbd>+</kbd>/<kbd>-</kbd> zoom &nbsp; <kbd>0</kbd> fit &nbsp; <kbd>Esc</kbd> clear path / release focus<br>
    <kbd>H</kbd> panel &nbsp; <kbd>L</kbd> legend &nbsp; <kbd>M</kbd> minimap &nbsp; <kbd>S</kbd> stats
  </div>
</div>

<div id="focus-banner">Focused: <b id="focus-name"></b> — click empty space or press Esc to release</div>
<div id="path-banner"></div>
<div id="dock">
  <div id="legend">
    <button class="collapse-btn" id="collapse-legend" aria-label="Toggle legend" aria-expanded="true" title="Toggle legend (L)"><svg class="icon icon-chev" viewBox="0 0 24 24"><polyline points="9 18 15 12 9 6"/></svg></button>
    <div id="legend-content"></div>
  </div>
  <div id="minimap-wrap">
    <button class="collapse-btn" id="collapse-minimap" aria-label="Toggle minimap" aria-expanded="true" title="Toggle minimap (M)" style="z-index:2;"><svg class="icon icon-chev" viewBox="0 0 24 24"><polyline points="9 18 15 12 9 6"/></svg></button>
    <div id="minimap" aria-hidden="true"></div>
  </div>
</div>
<div id="stats-wrap">
  <div id="stats"><span id="stats-text"></span><button class="collapse-btn" id="collapse-stats" aria-label="Toggle stats" aria-expanded="true" title="Toggle stats (S)"><svg class="icon" viewBox="0 0 24 24" style="width:11px;height:11px;"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button></div>
</div>
<div id="tooltip" role="tooltip"></div>
<div id="loading"><div class="spinner"></div><div>Building graph…</div></div>
<div id="empty-state"><div class="empty-title">No notes match these filters</div><div>Loosen the importance slider, tag, or domain filters.</div></div>

<div id="modal-overlay"></div>
<div id="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title">
  <div id="modal-header">
    <span id="modal-title">Note</span>
    <div id="modal-actions">
      <button class="btn" id="btn-copy-link" type="button"><svg class="icon" viewBox="0 0 24 24"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>Copy link</button>
      <button id="modal-close" aria-label="Close note"><svg class="icon" viewBox="0 0 24 24"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>
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
const commPalette = new Map();
DATA.nodes.forEach(n => { if (n.community != null && !commPalette.has(n.community)) commPalette.set(n.community, n.community_color || "#888"); });
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
function nodeColor(d) {
  if (colorMode === "community" && d.community != null) return d.community_color || commPalette.get(d.community) || "#888";
  return d.color || PALETTE[d.domain] || "#888";
}
function edgeWidth(d) {
  const kind = d.kind || "";
  if (kind === "wikilink") return 0.8;
  if (kind.startsWith("triple")) return 1.8;
  if (kind === "tag") return 1.0;
  return 1.0;
}
function edgeColor(d) { return "#6b6b7d"; }
function edgeDash(d) {
  if (d.kind === "tag" || d.kind === "wikilink") return null;
  if (d.kind.startsWith("triple")) return "2,3";
  return null;
}

/* ── Tunable configuration (physics, zoom/LOD, halo, clipboard) ── */
const CFG = {
  physics: { linkDistance: 110, charge: -180, collisionPad: 12, alphaDecay: 0.035, alphaMin: 0.005, dragAlphaTarget: 0.15 },
  // wheelFactor is applied AFTER deltaMode normalization (pixel units), so one
  // mouse-wheel notch (~100px) zooms ~1.18x and trackpads feel identical.
  zoom: { min: 0.05, max: 8, wheelFactor: 0.0016, keyboardFactor: 1.3, focusScale: 1.8 },
  lod: { hideBelow: 0.35, fadeBelow: 0.6, badgesAbove: 2.5 },
  halo: { baseScale: 2.2, speedDivisor: 3, maxIntensity: 0.6, minOpacity: 0.08, restScale: 2.0, velScale: 0.5 },
  // community rendering: legendMax caps legend rows; islandStrength drives the
  // optional cluster-centroid force (2D reading of the reference tool's
  // multi-galaxy; default off, toggle in the panel).
  cluster: { legendMax: 10, islandStrength: 0.08 },
};

/* ── Per-color cached halo gradients (tinted radial fade) ── */
const haloGradCache = new Map();
function haloGradientRef(color) {
  if (!haloGradCache.has(color)) {
    const id = `halo-grad-${haloGradCache.size}`;
    const grad = svg.select("defs").append("radialGradient")
      .attr("id", id).attr("cx", "50%").attr("cy", "50%").attr("r", "50%");
    grad.append("stop").attr("offset", "0%").attr("stop-color", color).attr("stop-opacity", 0.35);
    grad.append("stop").attr("offset", "60%").attr("stop-color", color).attr("stop-opacity", 0.12);
    grad.append("stop").attr("offset", "100%").attr("stop-color", color).attr("stop-opacity", 0);
    haloGradCache.set(color, id);
  }
  return `url(#${haloGradCache.get(color)})`;
}

/* ── State ── */
let simulation, svg, rootG, linkG, nodeG, labelG;
let mmSvg, mmNodeG, mmViewport;
let currentDomain = "", currentMinImp = 0, currentTag = "";
let focusedId = null;
let pathStart = null;       // first endpoint of a shift-click path query
let activePath = null;      // rendered shortest path (array of node ids)
let colorMode = "domain";   // legend + node color mode: "domain" | "community"
let islandMode = false;     // optional cluster-centroid layout (default off)
let orphanMode = false;     // highlight degree-0 notes (hygiene signal, no deletion)
let searchTimer = null;     // debounce timer for the vault search input
let currentTransform = d3.zoomIdentity;
let lastTrigger = null;   // element that opened the modal, for focus return
let W = window.innerWidth, H = window.innerHeight;

const zoom = d3.zoom().scaleExtent([CFG.zoom.min, CFG.zoom.max])
  // deltaMode-normalized: 0=pixel (trackpads), 1=line (mouse wheels), 2=page.
  // Convert line/page deltas to pixels first so every device zooms at the same rate.
  .wheelDelta(event => {
    const mode = event.deltaMode;
    const raw = mode === 1 ? event.deltaY * 33 : mode === 2 ? event.deltaY * 1000 : event.deltaY;
    return -raw * CFG.zoom.wheelFactor;
  })
  .on("zoom", (event) => {
    currentTransform = event.transform;
    if (rootG) rootG.attr("transform", event.transform);
    updateMinimapViewport();
    updateLOD();
  });

/* ── Zoom helpers (shared by buttons, keys, dblclick) ── */
function zoomBy(factor, cx, cy) {
  if (!svg) return;
  cx = cx == null ? W / 2 : cx;
  cy = cy == null ? H / 2 : cy;
  const newK = Math.max(CFG.zoom.min, Math.min(CFG.zoom.max, currentTransform.k * factor));
  const t = currentTransform;
  // Keep the anchor point (cx, cy) fixed while scaling.
  const wx = (cx - t.x) / t.k, wy = (cy - t.y) / t.k;
  const next = d3.zoomIdentity.translate(cx - wx * newK, cy - wy * newK).scale(newK);
  svg.transition().duration(200).call(zoom.transform, next);
}

function zoomTo(k) {
  if (!svg) return;
  const newK = Math.max(CFG.zoom.min, Math.min(CFG.zoom.max, k));
  const t = currentTransform;
  const cx = W / 2, cy = H / 2;
  const wx = (cx - t.x) / t.k, wy = (cy - t.y) / t.k;
  const next = d3.zoomIdentity.translate(cx - wx * newK, cy - wy * newK).scale(newK);
  svg.transition().duration(350).call(zoom.transform, next);
}

function zoomFit() {
  if (!svg || !nodeG) return;
  const nodes = nodeG.data();
  if (!nodes.length) return;
  const xs = nodes.map(n => n.x), ys = nodes.map(n => n.y);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const pad = 60;
  const bw = (maxX - minX) + pad * 2, bh = (maxY - minY) + pad * 2;
  const k = Math.max(CFG.zoom.min, Math.min(CFG.zoom.max, Math.min(W / bw, H / bh)));
  const cx = (minX + maxX) / 2, cy = (minY + maxY) / 2;
  const t = d3.zoomIdentity.translate(W / 2 - cx * k, H / 2 - cy * k).scale(k);
  svg.transition().duration(600).call(zoom.transform, t);
}

/* ── Cluster force: gentle pull toward per-community centroids (islands) ── */
function clusterForce(strength) {
  let nodes = [];
  function force(alpha) {
    const centroids = new Map();
    for (const d of nodes) {
      if (d.community == null) continue;
      const c = centroids.get(d.community) || { x: 0, y: 0, n: 0 };
      c.x += d.x; c.y += d.y; c.n++;
      centroids.set(d.community, c);
    }
    for (const d of nodes) {
      if (d.community == null) continue;
      const c = centroids.get(d.community);
      if (!c || !c.n) continue;
      d.vx += ((c.x / c.n) - d.x) * alpha * strength;
      d.vy += ((c.y / c.n) - d.y) * alpha * strength;
    }
  }
  force.initialize = ns => { nodes = ns; };
  return force;
}

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
const SHAPE_SVGS = {
  circle: '<svg width="12" height="12" viewBox="0 0 12 12"><circle cx="6" cy="6" r="4.5" fill="currentColor"/></svg>',
  square: '<svg width="12" height="12" viewBox="0 0 12 12"><rect x="1.5" y="1.5" width="9" height="9" rx="1.5" fill="currentColor"/></svg>',
  diamond: '<svg width="12" height="12" viewBox="0 0 12 12"><path d="M6 0.8 L11.2 6 L6 11.2 L0.8 6 Z" fill="currentColor"/></svg>',
  triangle: '<svg width="12" height="12" viewBox="0 0 12 12"><path d="M6 1 L11 10.5 L1 10.5 Z" fill="currentColor"/></svg>',
  link: '<svg width="14" height="12" viewBox="0 0 14 12"><line x1="1" y1="6" x2="13" y2="6" stroke="currentColor" stroke-width="1.6"/></svg>',
  taglink: '<svg width="14" height="12" viewBox="0 0 14 12"><line x1="1" y1="6" x2="13" y2="6" stroke="currentColor" stroke-width="1.6" stroke-dasharray="3 2.4"/></svg>',
};
function buildLegend() {
  const legend = document.getElementById("legend-content");
  let html = "";
  if (colorMode === "community") {
    const sizes = new Map();
    DATA.nodes.forEach(n => { if (n.community != null) sizes.set(n.community, (sizes.get(n.community) || 0) + 1); });
    const ranked = Array.from(sizes.entries()).sort((a, b) => b[1] - a[1]);
    html += '<div class="lg-title">Communities</div>';
    for (const [cid, count] of ranked.slice(0, CFG.cluster.legendMax)) {
      const color = commPalette.get(cid) || "#888";
      html += `<div class="row"><span class="swatch" style="background:${color};box-shadow:0 0 6px ${color};"></span>Community ${cid} (${count})</div>`;
    }
    if (ranked.length > CFG.cluster.legendMax) {
      html += `<div class="row" style="opacity:0.7;">+ ${ranked.length - CFG.cluster.legendMax} more communities</div>`;
    }
    const unclustered = DATA.nodes.filter(n => n.community == null).length;
    if (unclustered) {
      html += `<div class="row"><span class="swatch" style="background:#888888;"></span>unclustered (${unclustered})</div>`;
    }
  } else {
    html += '<div class="lg-title">Domains</div>';
    for (const [domain, color] of Object.entries(PALETTE)) {
      html += `<div class="row"><span class="swatch" style="background:${color};box-shadow:0 0 6px ${color};"></span>${domain}</div>`;
    }
  }
  html += '<div class="lg-title" style="margin-top:8px;">Shapes</div>';
  html += `<div class="row"><span class="shape-glyph">${SHAPE_SVGS.circle}</span> permanent</div>`;
  html += `<div class="row"><span class="shape-glyph">${SHAPE_SVGS.square}</span> literature</div>`;
  html += `<div class="row"><span class="shape-glyph">${SHAPE_SVGS.diamond}</span> moc</div>`;
  html += `<div class="row"><span class="shape-glyph">${SHAPE_SVGS.triangle}</span> index / log</div>`;
  html += '<div class="lg-title" style="margin-top:8px;">Edges</div>';
  html += `<div class="row"><span class="shape-glyph">${SHAPE_SVGS.link}</span> wikilink</div>`;
  html += `<div class="row"><span class="shape-glyph">${SHAPE_SVGS.taglink}</span> tag link</div>`;
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
  updateStats();
}

function updateStats() {
  const el = document.getElementById("stats-text");
  if (!el) return;
  const { nodes, edges } = getFilteredData();
  const dropped = DATA.edges.length - edges.length;
  const orphans = nodes.filter(n => (n.degree || 0) === 0).length;
  el.textContent =
    `${nodes.length} nodes / ${edges.length} edges` +
    (dropped > 0 ? ` (${dropped} hidden by filters)` : "") +
    ` | ${DATA.meta.domains.length} domains` +
    ` | ${orphans} orphans`;
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
  updateStats();
}

/* ── Focus mode + path dimming (one compositor; they must not fight) ── */
function applyDimming() {
  if (!nodeG) return;
  if (activePath && activePath.length > 1) {
    const onPath = new Set(activePath);
    const onPathEdge = new Set();
    for (let i = 0; i + 1 < activePath.length; i++) {
      onPathEdge.add(activePath[i] + "\u0000" + activePath[i + 1]);
      onPathEdge.add(activePath[i + 1] + "\u0000" + activePath[i]);
    }
    nodeG.style("opacity", d => onPath.has(d.id) ? 1 : 0.12);
    nodeG.classed("selected", false).classed("on-path", d => onPath.has(d.id));
    if (labelG) labelG.style("opacity", d => onPath.has(d.id) ? 1 : 0.08);
    if (linkG) linkG.style("opacity", e => {
      const s = typeof e.source === "object" ? e.source.id : e.source;
      const t = typeof e.target === "object" ? e.target.id : e.target;
      return onPathEdge.has(s + "\u0000" + t) ? 0.95 : 0.04;
    });
    return;
  }
  if (focusedId) {
    const neighbors = adjacency.get(focusedId) || new Set();
    nodeG.style("opacity", d => (d.id === focusedId || neighbors.has(d.id)) ? 1 : 0.12);
    nodeG.classed("on-path", false).classed("selected", d => d.id === focusedId);
    if (labelG) labelG.style("opacity", d => (d.id === focusedId || neighbors.has(d.id)) ? 1 : 0.08);
    if (linkG) linkG.style("opacity", e => {
      const s = typeof e.source === "object" ? e.source.id : e.source;
      const t = typeof e.target === "object" ? e.target.id : e.target;
      return (s === focusedId || t === focusedId) ? 0.85 : 0.04;
    });
    return;
  }
  if (orphanMode) {
    // Hygiene view: keep unlinked notes lit, fade everything connected.
    nodeG.style("opacity", d => (d.degree || 0) === 0 ? 1 : 0.12);
    nodeG.classed("selected", false).classed("on-path", false);
    if (labelG) labelG.style("opacity", d => (d.degree || 0) === 0 ? 1 : 0.08);
    if (linkG) linkG.style("opacity", 0.06);
    return;
  }
  nodeG.style("opacity", 1).classed("selected", false).classed("on-path", false);
  if (labelG) labelG.style("opacity", 1);
  if (linkG) linkG.style("opacity", 0.5);
}

function applyFocus(id) {
  focusedId = id;
  const node = nodeById.get(id);
  document.getElementById("focus-name").textContent = node ? (node.title || node.id) : id;
  document.getElementById("focus-banner").style.display = "block";
  applyDimming();
}

function clearFocus() {
  focusedId = null;
  document.getElementById("focus-banner").style.display = "none";
  applyDimming();
}

/* ─ Path tracing: click a node, shift-click a second one ── */
function pathBannerVisible() {
  return document.getElementById("path-banner").style.display === "block";
}

function pathBannerMessage(msg) {
  const el = document.getElementById("path-banner");
  el.textContent = msg;
  el.style.display = "block";
}

function handlePathClick(d) {
  // Shift-click: pick or complete the path query's endpoints.
  if (!pathStart) {
    pathStart = d.id;
    pathBannerMessage(`Path start: ${d.title || d.id} - shift-click another node`);
    return;
  }
  const fromId = pathStart;
  if (fromId === d.id) { clearPath(); return; }
  if (!location.protocol.startsWith("http")) {
    pathBannerMessage("Path tracing needs the local graph server (port 8075).");
    return;
  }
  fetch("/api/path?from=" + encodeURIComponent(fromId) + "&to=" + encodeURIComponent(d.id))
    .then(r => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
    .then(payload => {
      if (payload.found && payload.path && payload.path.length > 1) {
        showPath(payload.path, payload.hops);
      } else {
        pathBannerMessage(`No path between those nodes within ${payload.max_depth || 10} hops`);
      }
    })
    .catch(() => pathBannerMessage("Path search failed - is the graph server running?"));
}

function showPath(pathIds, hops) {
  activePath = pathIds;
  pathStart = pathIds[0];  // keep the origin so a further shift-click re-routes
  document.getElementById("focus-banner").style.display = "none";
  const fromNode = nodeById.get(pathIds[0]);
  const toNode = nodeById.get(pathIds[pathIds.length - 1]);
  const label = `${(fromNode && (fromNode.title || fromNode.id)) || pathIds[0]} → ${(toNode && (toNode.title || toNode.id)) || pathIds[pathIds.length - 1]}`;
  pathBannerMessage(`Path (${hops} hop${hops === 1 ? "" : "s"}): ${label} - Esc to clear`);
  applyDimming();
}

function clearPath() {
  activePath = null;
  pathStart = null;
  document.getElementById("path-banner").style.display = "none";
  applyDimming();
  if (focusedId && nodeG && nodeG.data().some(d => d.id === focusedId)) {
    const node = nodeById.get(focusedId);
    document.getElementById("focus-name").textContent = node ? (node.title || node.id) : focusedId;
    document.getElementById("focus-banner").style.display = "block";
  }
}

/* ── Search / zoom-to-node ── */
function jumpToNode(node) {
  if (!node) return;
  const scale = CFG.zoom.focusScale;
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

/* ─ Vault search: server-side FTS over ALL notes (not just the export) ── */
function runVaultSearch() {
  const q = document.getElementById("vault-search").value.trim();
  const box = document.getElementById("search-results");
  if (!q) { box.hidden = true; box.innerHTML = ""; return; }
  if (!location.protocol.startsWith("http")) {
    box.hidden = false;
    box.innerHTML = '<div class="search-empty">Full-text search needs the local graph server (port 8075).</div>';
    return;
  }
  fetch("/api/search?q=" + encodeURIComponent(q) + "&limit=20")
    .then(r => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
    .then(payload => renderSearchResults(payload.results || []))
    .catch(() => {
      box.hidden = false;
      box.innerHTML = '<div class="search-empty">Search failed - is the graph server running?</div>';
    });
}

function renderSearchResults(results) {
  const box = document.getElementById("search-results");
  box.hidden = false;
  if (!results.length) {
    box.innerHTML = '<div class="search-empty">No matches.</div>';
    return;
  }
  const rendered = new Set(nodeG ? nodeG.data().map(d => d.id) : []);
  box.innerHTML = "";
  results.forEach(r => {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "search-hit" + (rendered.has(r.note_id) ? "" : " off-graph");
    item.innerHTML = `<span class="sh-title">${escapeHtml(r.title || r.note_id)}</span>` +
      `<span class="sh-meta">${escapeHtml(r.domain || "uncategorized")}${rendered.has(r.note_id) ? "" : " · not in current view"}</span>`;
    item.addEventListener("click", () => selectSearchResult(r));
    box.appendChild(item);
  });
}

function selectSearchResult(r) {
  const node = nodeById.get(r.note_id);
  if (node && nodeG && nodeG.data().some(d => d.id === node.id)) {
    jumpToNode(node);
  } else {
    // Outside the 500-node export (or filtered out of the current view):
    // open through the same lazy-fetch modal path wikilinks use; the focus
    // guard inside openModal keeps the whole graph from dimming.
    const proxy = {
      id: r.note_id,
      title: r.title || r.note_id,
      domain: r.domain || "",
      type: r.type || "permanent",
      importance: r.importance != null ? r.importance : 0.3,
      tags: r.tags || [],
    };
    openModal(proxy, null);
  }
  const box = document.getElementById("search-results");
  if (box) box.hidden = true;
}

/* ── Render ── */
function render() {
  const { nodes, edges } = getFilteredData();
  document.getElementById("empty-state").style.display = nodes.length ? "none" : "block";
  updateStats();

  // Preserve positions of nodes that persist across re-renders
  const oldPos = new Map();
  if (nodeG) nodeG.each(function(d) { oldPos.set(d.id, { x: d.x, y: d.y, vx: d.vx, vy: d.vy }); });

  svg.selectAll(".layer").remove();
  rootG = svg.append("g").attr("class", "layer").style("will-change", "transform");
  linkG = rootG.append("g").attr("class", "links").style("mix-blend-mode", "screen").selectAll("path").data(edges).join("path")
    .attr("fill", "none").attr("stroke", d => edgeColor(d)).attr("stroke-width", d => edgeWidth(d))
    .attr("stroke-opacity", 0.65).attr("stroke-dasharray", d => edgeDash(d))
    .attr("stroke-linecap", "round").attr("stroke-linejoin", "round");
  linkG.style("filter", "drop-shadow(0 0 2px rgba(107,107,125,0.3))")
    .on("mouseenter", function(event, d) {
      d3.select(this).attr("stroke-opacity", 1).attr("stroke-width", edgeWidth(d) * 2.5);
      if (labelG) labelG.style("opacity", 1);
    })
    .on("mouseleave", function(event, d) {
      d3.select(this).attr("stroke-opacity", 0.65).attr("stroke-width", edgeWidth(d));
      if (labelG) labelG.style("opacity", computeLabelOpacity(currentTransform.k));
    });

  nodeG = rootG.append("g").attr("class", "nodes").selectAll("g").data(nodes, d => d.id).join("g")
    .attr("class", "node-group").attr("tabindex", 0)
    .attr("role", "button").attr("aria-label", d => `${d.title || d.id}, ${d.domain || "uncategorized"}`)
    .on("mouseover", (event, d) => {
      const incident = adjacency.get(d.id) || new Set();
      linkG.style("opacity", e => (incident.has(e.source.id) || incident.has(e.target.id)) ? 1 : 0.15)
          .attr("stroke", e => (incident.has(e.source.id) || incident.has(e.target.id)) ? "#8b7cf6" : (edgeColor(e)));
      d3.select(event.currentTarget).select(".node-shape").attr("stroke", "#5AE4AA").attr("stroke-width", 2.2);
      if (labelG) labelG.style("opacity", computeLabelOpacity(currentTransform.k));
    })
    .on("mouseout", (event, d) => {
      linkG.style("opacity", 0.65).attr("stroke", d => edgeColor(d));
      d3.select(event.currentTarget).select(".node-shape").attr("stroke", null).attr("stroke-width", null);
    })
    .call(d3.drag()
      .on("start", (event, d) => { if (!event.active) simulation.alphaTarget(CFG.physics.dragAlphaTarget).restart(); d.fx = d.x; d.fy = d.y; })
      .on("drag", (event, d) => { d.fx = event.x; d.fy = event.y; })
      .on("end", (event, d) => { if (!event.active) simulation.alphaTarget(0); d.fx = null; d.fy = null; }))
    .on("click", (event, d) => {
      event.stopPropagation();
      if (event.shiftKey) { handlePathClick(d); return; }
      pathStart = d.id;  // keep as the origin for a later shift-click path query
      openModal(d, event.currentTarget);
    })
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

  // Shape per node type: layered halo + core shape with glow filter
  nodeG.each(function(d) {
    const g = d3.select(this);
    const r = nodeRadius(d);
    const color = nodeColor(d);

    // Halo ring: per-color tinted radial gradient (velocity-responsive in updateNodeHalos)
    g.append("circle").attr("class", "node-halo")
      .attr("r", r * CFG.halo.baseScale).attr("fill", haloGradientRef(color))
      .attr("opacity", 0.0).attr("pointer-events", "none");

    // Core shape
    const path = shapePath(d.shape, r);
    if (path) {
      g.append("path").attr("class", "node-shape").attr("d", path)
        .attr("fill", color).attr("stroke", "#fff")
        .attr("stroke-width", 0.6).attr("stroke-opacity", 0.25)
        .attr("filter", "url(#node-glow)");
    } else {
      g.append("circle").attr("class", "node-shape").attr("r", r)
        .attr("fill", color).attr("stroke", "#fff")
        .attr("stroke-width", 0.6).attr("stroke-opacity", 0.25)
        .attr("filter", "url(#node-glow)");
    }
  });

  labelG = rootG.append("g").attr("class", "labels").selectAll("text").data(nodes, d => d.id).join("text")
    .text(d => (d.title ? d.title.substring(0, 28) : d.id))
    .attr("dy", d => nodeRadius(d) + 12).attr("text-anchor", "middle");

  simulation = d3.forceSimulation(nodes)
    .force("link", d3.forceLink(edges).id(d => d.id).distance(CFG.physics.linkDistance))
    .force("charge", d3.forceManyBody().strength(CFG.physics.charge))
    .force("center", d3.forceCenter(W / 2, H / 2))
    .force("collision", d3.forceCollide().radius(d => nodeRadius(d) + CFG.physics.collisionPad))
    .force("cluster", islandMode ? clusterForce(CFG.cluster.islandStrength) : null)
    .alphaDecay(CFG.physics.alphaDecay)
    .alphaMin(CFG.physics.alphaMin);

  simulation.on("tick", () => {
    linkG.attr("d", d => {
      const sx = d.source.x, sy = d.source.y, tx = d.target.x, ty = d.target.y;
      const dx = tx - sx, dy = ty - sy;
      const dr = Math.sqrt(dx * dx + dy * dy) * 1.2;
      return `M${sx.toFixed(1)},${sy.toFixed(1)}A${dr.toFixed(1)},${dr.toFixed(1)} 0 0,1 ${tx.toFixed(1)},${ty.toFixed(1)}`;
    });
    nodeG.attr("transform", d => `translate(${Math.round(d.x)},${Math.round(d.y)})`);
    labelG.attr("x", d => Math.round(d.x)).attr("y", d => Math.round(d.y));
    updateMinimap();
    updateNodeHalos();
  });

  // Auto-stop physics when energy drops to avoid perpetual jitter
  simulation.on("end", () => { if (focusedId === null) simulation.stop(); });

  rootG.attr("transform", currentTransform);
  // Re-apply focus only when the focused node is part of the current view;
  // a filtered-out id would dim every node (the applyFocus class bug).
  if (focusedId && nodes.some(d => d.id === focusedId)) applyFocus(focusedId);
  else clearFocus();
  // nodeG was recreated — force LOD badge re-evaluation (zoom may be > badge threshold)
  lastBadgeZoom = null;
  updateLOD();
}

/* ── Velocity-responsive halos ── */
function updateNodeHalos() {
  if (!nodeG) return;
  nodeG.each(function(d) {
    const speed = Math.sqrt((d.vx || 0) ** 2 + (d.vy || 0) ** 2);
    const halo = d3.select(this).select(".node-halo");
    if (halo.empty()) return;
    // Opacity scales with velocity: moving nodes show a wisp, resting nodes fade to near-zero
    const intensity = Math.min(speed / CFG.halo.speedDivisor, CFG.halo.maxIntensity);
    halo.attr("opacity", CFG.halo.minOpacity + intensity);
    // Scale halo slightly with speed; resting scale matches the render-time base
    const r = nodeRadius(d);
    halo.attr("r", r * (CFG.halo.baseScale + intensity * CFG.halo.velScale));
  });
}

/* ── Semantic LOD (level of detail) — hide labels at low zoom ── */
let lastBadgeZoom = null; // true/false/null: whether badges are currently shown
function computeLabelOpacity(k) { return k < CFG.lod.hideBelow ? 0 : k < CFG.lod.fadeBelow ? 0.3 : 1; }
function updateLOD() {
  if (!labelG) return;
  const k = currentTransform.k;
  const labelOpacity = k < CFG.lod.hideBelow ? 0 : k < CFG.lod.fadeBelow ? 0.3 : 1;
  labelG.style("opacity", labelOpacity);
  // Show tags as badges at high zoom; only touch the DOM when crossing the threshold
  if (!nodeG) return;
  const showBadges = k > CFG.lod.badgesAbove;
  if (showBadges === lastBadgeZoom) return;
  lastBadgeZoom = showBadges;
  nodeG.selectAll(".node-badge").remove();
  if (!showBadges) return;
  nodeG.each(function(d) {
    if (!d.tags || !d.tags.length) return;
    const g = d3.select(this);
    g.append("text").attr("class", "node-badge")
      .attr("y", nodeRadius(d) + 22).attr("text-anchor", "middle")
      .attr("font-size", "7px").attr("fill", nodeColor(d))
      .text(`#${d.tags.length}`);
  });
}

/* ── Tooltip ── */
function showTooltip(event, d) {
  const tip = document.getElementById("tooltip");
  tip.style.display = "block";
  tip.innerHTML = `<div class="tt-title" style="color:${nodeColor(d)}">${escapeHtml(d.title || d.id)}</div>
    <div class="tt-meta">${d.type} · ${d.domain || "uncategorized"} · importance ${(d.importance || 0).toFixed(2)}</div>
    <div class="tt-meta">tags: ${(d.tags || []).join(", ") || "—"}</div>
    <div class="tt-meta" style="margin-top:3px;color:#5AE4AA;">click to open · shift-click path · drag to move</div>`;
  moveTooltip(event);
}
function moveTooltip(event) {
  const tip = document.getElementById("tooltip");
  // Flip at viewport edges so the tooltip never clips offscreen.
  const flipX = event.pageX + 14 + tip.offsetWidth > window.innerWidth - 8;
  const flipY = event.pageY - 10 - tip.offsetHeight < 0;
  tip.style.left = (flipX ? Math.max(8, event.pageX - tip.offsetWidth - 14) : event.pageX + 14) + "px";
  tip.style.top = (flipY ? event.pageY + 22 : event.pageY - 10) + "px";
}
function hideTooltip() { document.getElementById("tooltip").style.display = "none"; }

/* ── Minimap ── */
function initMinimap() {
  mmSvg = d3.select("#minimap").append("svg").attr("width", 180).attr("height", 130);
  mmNodeG = mmSvg.append("g");
  mmViewport = mmSvg.append("rect").attr("class", "viewport-rect");
  // Click-to-pan: convert minimap click coords to world-space and center
  mmSvg.on("click", (event) => {
    if (!mmSvg || !mmSvg._mm) return;
    const [mx, my] = d3.pointer(event, mmSvg.node());
    const { scale, ox, oy } = mmSvg._mm;
    const wx = (mx - ox) / scale;
    const wy = (my - oy) / scale;
    const newTransform = d3.zoomIdentity
      .translate(W / 2 - wx * currentTransform.k, H / 2 - wy * currentTransform.k)
      .scale(currentTransform.k);
    svg.transition().duration(350).call(zoom.transform, newTransform);
  });
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
        span.className = "wikilink" + (dest ? "" : " pending");
        span.textContent = label;
        span.setAttribute("role", "link");
        span.tabIndex = 0;
        if (dest) {
          const open = () => openModal(dest, span);
          span.addEventListener("click", open);
          span.addEventListener("keydown", (e) => { if (e.key === "Enter") open(); });
        } else {
          // Target not in the current export — try resolving it lazily against
          // the full index via the local graph server before giving up.
          span.title = "Resolving link…";
          const openPending = () => {
            const canFetch = location.protocol.startsWith("http") && target;
            if (!canFetch) return failBroken();
            fetch("/api/note/by-title/" + encodeURIComponent(target))
              .then(r => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
              .then(payload => {
                // Cache the resolved note so reopening it is instant.
                const node = {
                  id: payload.note_id || payload.id,
                  title: payload.title || target,
                  type: payload.type || "permanent",
                  domain: payload.domain || "",
                  importance: payload.importance || 0.3,
                  tags: payload.tags || [],
                  color: payload.domain ? PALETTE[payload.domain] : PALETTE[payload.domain] || "#888",
                  shape: "circle",
                  body_preview: payload.body_preview || "",
                  full_body: payload.full_body || "",
                  path: payload.path || "",
                };
                if (!nodeById.has(node.id)) {
                  nodeById.set(node.id, node);
                  nodeByTitle.set((node.title || node.id).toLowerCase(), node);
                  if (!adjacency.has(node.id)) adjacency.set(node.id, new Set());
                }
                openModal(node, span);
              })
              .catch(failBroken);
          };
          const failBroken = () => {
            span.classList.remove("pending");
            span.classList.add("broken");
            span.title = "Linked note not found in the vault";
            span.removeEventListener("click", openPending);
            span.removeEventListener("keydown", onPendingKey);
          };
          const onPendingKey = (e) => { if (e.key === "Enter") openPending(); };
          span.addEventListener("click", openPending);
          span.addEventListener("keydown", onPendingKey);
        }
        frag.appendChild(span);
      } else if (part) {
        frag.appendChild(document.createTextNode(part));
      }
    });
    textNode.parentNode.replaceChild(frag, textNode);
  });
}

function renderModalContent(node, bodyEl) {
  let content = '<div class="frontmatter">';
  if (node.domain) content += `<div><span class="fm-key">domain:</span> <span class="fm-value">${escapeHtml(node.domain)}</span></div>`;
  if (node.type) content += `<div><span class="fm-key">type:</span> <span class="fm-value">${escapeHtml(node.type)}</span></div>`;
  if (node.importance != null) content += `<div><span class="fm-key">importance:</span> <span class="fm-value">${Number(node.importance).toFixed(2)}</span></div>`;
  if (node.tags && node.tags.length) {
    content += `<div><span class="fm-key">tags:</span> <span class="fm-value">` +
      node.tags.map(t => `<span class="fm-tag" data-tag="${escapeHtml(t)}">${escapeHtml(t)}</span>`).join("") +
      `</span></div>`;
  }
  if (node.path) content += `<div><span class="fm-key">path:</span> <span class="fm-value">${escapeHtml(node.path)}</span></div>`;
  content += '</div>';

  const noteBody = node.full_body || node.body_preview || "";
  if (noteBody) {
    content += marked.parse(noteBody);
  } else {
    content += '<p class="empty-note">No content available for this note.</p>';
  }

  bodyEl.innerHTML = content;
  linkifyWikilinks(bodyEl);

  // ── Linked Mentions pane (v2 Obsidian-style backlinks) ──
  const linked = (typeof DATA !== "undefined" && DATA.nodes && adjacency && adjacency.get(node.id)) ? adjacency.get(node.id) : new Set();
  if (linked && linked.size > 0) {
    const pane = document.createElement("section");
    pane.className = "modal-links";
    pane.innerHTML = '<h3 style="font-family:var(--display);font-size:1.05em;color:var(--accent);border-bottom:1px solid var(--border);padding-bottom:6px;margin:1.2em 0 0.6em;">Linked Mentions</h3>' +
      '<ul style="margin:0;padding-left:18px;color:#ccc;font-size:13px;line-height:1.6;">' +
      Array.from(linked).map(nid => {
        const n = DATA.nodes.find(x => x.id === nid) || { title: nid };
        return `<li><a href="#note=${encodeURIComponent(n.title || nid)}" onclick="closeModal();applyFocus('${String(nid).replace(/'/g,"\\'")}');return true;" style="color:var(--accent);text-decoration:none;border-bottom:1px dotted var(--accent);cursor:pointer;">${(n.title || nid).replace(/</g,"&lt;")}</a></li>`;
      }).join("") +
      "</ul>";
    bodyEl.appendChild(pane);
  }

  // Tag chips filter the graph and close the modal
  bodyEl.querySelectorAll(".fm-tag").forEach(chip => {
    chip.addEventListener("click", () => {
      document.getElementById("tag-search").value = chip.dataset.tag;
      closeModal();
      updateFilters();
    });
  });

  // Code block copy buttons
  bodyEl.querySelectorAll("pre").forEach(pre => {
    pre.style.position = "relative";
    const btn = document.createElement("button");
    btn.className = "btn code-copy-btn";
    btn.textContent = "Copy";
    btn.style.cssText = "position:absolute;top:6px;right:6px;padding:3px 8px;font-size:10px;opacity:0;transition:opacity 0.15s;";
    pre.addEventListener("mouseenter", () => btn.style.opacity = "1");
    pre.addEventListener("mouseleave", () => btn.style.opacity = "0");
    btn.addEventListener("click", () => {
      const code = pre.querySelector("code") ? pre.querySelector("code").textContent : pre.textContent;
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(code).then(() => {
          btn.textContent = "Copied!";
          setTimeout(() => btn.textContent = "Copy", 1200);
        }).catch(() => {});
      }
    });
    pre.appendChild(btn);
  });
}

function openModal(node, trigger) {
  lastTrigger = trigger || document.activeElement;
  const modal = document.getElementById("modal");
  const overlay = document.getElementById("modal-overlay");
  const bodyEl = document.getElementById("modal-body");
  document.getElementById("modal-title").textContent = node.title || node.id;

  // Show shell immediately; body may arrive via lazy fetch.
  renderModalContent(node, bodyEl);
  if (!(node.full_body || node.body_preview)) {
    bodyEl.innerHTML = '<p class="empty-note">Loading note content…</p>';
    // Lazy-load from the local graph server when the export omitted bodies
    // (security default). Same-origin only — file:// and foreign hosts skip.
    const canFetch = location.protocol.startsWith("http") && node.id;
    if (canFetch) {
      fetch("/api/note/" + encodeURIComponent(node.id))
        .then(r => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
        .then(payload => {
          // Merge into the in-memory node so re-open is instant
          node.full_body = payload.full_body || "";
          node.body_preview = payload.body_preview || node.body_preview || "";
          if (payload.tags && payload.tags.length) node.tags = payload.tags;
          if (payload.domain) node.domain = payload.domain;
          if (payload.type) node.type = payload.type;
          if (payload.path) node.path = payload.path;
          if (payload.importance != null) node.importance = payload.importance;
          document.getElementById("modal-title").textContent = payload.title || node.title || node.id;
          renderModalContent(node, bodyEl);
        })
        .catch(() => {
          bodyEl.innerHTML = '<p class="empty-note">No content available for this note. '
            + 'Open the graph via the local server (port 8075) and run an authenticated '
            + 'refresh with bodies enabled.</p>';
        });
    } else {
      bodyEl.innerHTML = '<p class="empty-note">No content available for this note.</p>';
    }
  }

  modal.style.display = "flex";
  overlay.style.display = "block";
  document.body.style.overflow = "hidden";
  document.getElementById("modal-close").focus();
  // Only focus-highlight notes that are actually in the rendered graph;
  // notes resolved lazily via /api/note/by-title may not be a node here.
  if (nodeG && nodeG.data().some(d => d.id === node.id)) applyFocus(node.id);
  else clearFocus();
}

/* Keep Tab cycling inside the modal while it is open. */
function trapModalFocus(e) {
  const modal = document.getElementById("modal");
  if (modal.style.display !== "flex" || e.key !== "Tab") return;
  const focusables = modal.querySelectorAll('button, [tabindex="0"], a[href], .wikilink:not(.broken)');
  if (!focusables.length) return;
  const first = focusables[0], last = focusables[focusables.length - 1];
  if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
}

function closeModal() {
  document.getElementById("modal").style.display = "none";
  document.getElementById("modal-overlay").style.display = "none";
  document.body.style.overflow = "";
  if (lastTrigger && typeof lastTrigger.focus === "function") lastTrigger.focus();
}

/* ── Copy link to note ── */
function copyNoteLink() {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    const title = document.getElementById("modal-title").textContent;
    const url = `${location.origin}${location.pathname}#note=${encodeURIComponent(title)}`;
    navigator.clipboard.writeText(url).then(() => {
      const btn = document.getElementById("btn-copy-link");
      const orig = btn.textContent;
      btn.textContent = "Copied!";
      setTimeout(() => { btn.textContent = orig; }, 1200);
    }).catch(() => {});
  }
}

/* ── Export PNG (HiDPI-aware, capped at 2x to bound file size) ── */
function exportPNG() {
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const svgEl = svg.node();
  const clone = svgEl.cloneNode(true);
  clone.setAttribute("width", W * dpr); clone.setAttribute("height", H * dpr);
  clone.setAttribute("viewBox", `0 0 ${W} ${H}`);
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  const bg = document.createElementNS("http://www.w3.org/2000/svg", "rect");
  bg.setAttribute("width", W); bg.setAttribute("height", H); bg.setAttribute("fill", "#0a0a0f");
  clone.insertBefore(bg, clone.firstChild);
  const xml = new XMLSerializer().serializeToString(clone);
  const img = new Image();
  const svg64 = "data:image/svg+xml;base64," + btoa(unescape(encodeURIComponent(xml)));
  img.onload = () => {
    const canvas = document.createElement("canvas");
    canvas.width = W * dpr; canvas.height = H * dpr;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(img, 0, 0, W * dpr, H * dpr);
    const a = document.createElement("a");
    a.download = "entropicmem-graph.png";
    a.href = canvas.toDataURL("image/png");
    a.click();
  };
  img.src = svg64;
}

/* ── Collapsible overlays (persisted to localStorage) ── */
const OVERLAYS = [
  { id: "panel", btn: "collapse-panel" },
  { id: "legend", btn: "collapse-legend" },
  { id: "minimap-wrap", btn: "collapse-minimap" },
  { id: "stats-wrap", btn: "collapse-stats" },
];
const lsKey = id => `entropicmem-graph-${id}-collapsed`;
function setOverlayCollapsed(entry, collapsed) {
  const el = document.getElementById(entry.id);
  const btn = document.getElementById(entry.btn);
  if (!el) return;
  el.classList.toggle("collapsed", collapsed);
  if (btn) btn.setAttribute("aria-expanded", String(!collapsed));
  try { localStorage.setItem(lsKey(entry.id), collapsed ? "1" : "0"); } catch (e) {}
}
function toggleOverlay(idOrEntry) {
  const entry = typeof idOrEntry === "string" ? OVERLAYS.find(o => o.id === idOrEntry) : idOrEntry;
  if (!entry) return;
  const el = document.getElementById(entry.id);
  if (el) setOverlayCollapsed(entry, !el.classList.contains("collapsed"));
}
function restoreOverlayStates() {
  OVERLAYS.forEach(entry => {
    let collapsed = false;
    try { collapsed = localStorage.getItem(lsKey(entry.id)) === "1"; } catch (e) {}
    if (collapsed) setOverlayCollapsed(entry, true);
    const btn = document.getElementById(entry.btn);
    if (btn) btn.addEventListener("click", ev => { ev.stopPropagation(); toggleOverlay(entry); });
  });
}

/* ─ Display prefs (color mode, cluster islands) persisted like overlays ── */
function restoreDisplayPrefs() {
  try {
    if (localStorage.getItem("entropicmem-graph-color-mode") === "community") colorMode = "community";
    if (localStorage.getItem("entropicmem-graph-island") === "1") islandMode = true;
  } catch (e) {}
  document.getElementById("color-mode").value = colorMode;
  document.getElementById("island-toggle").checked = islandMode;
}
function saveDisplayPrefs() {
  try {
    localStorage.setItem("entropicmem-graph-color-mode", colorMode);
    localStorage.setItem("entropicmem-graph-island", islandMode ? "1" : "0");
  } catch (e) {}
}

/* ── Wiring ── */
document.addEventListener("keydown", (e) => {
  const modalOpen = document.getElementById("modal").style.display === "flex";
  if (e.key === "Escape") {
    if (modalOpen) closeModal();
    else if (activePath || pathBannerVisible()) clearPath();
    else clearFocus();
    return;
  }
  trapModalFocus(e);
  // Everything below is ignored while typing in a form field.
  if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
  if (modalOpen) return;
  const key = e.key.toLowerCase();
  if (e.key === "+" || e.key === "=") { e.preventDefault(); zoomBy(CFG.zoom.keyboardFactor); }
  else if (e.key === "-" || e.key === "_") { e.preventDefault(); zoomBy(1 / CFG.zoom.keyboardFactor); }
  else if (e.key === "0") { e.preventDefault(); zoomFit(); }
  else if (key === "h") toggleOverlay("panel");
  else if (key === "l") toggleOverlay("legend");
  else if (key === "m") toggleOverlay("minimap-wrap");
  else if (key === "s") toggleOverlay("stats-wrap");
});

document.addEventListener("DOMContentLoaded", () => {
  svg = d3.select("#graph").append("svg").attr("width", "100%").attr("height", "100%");
  svg.append("defs"); // for per-color halo gradients (haloGradientRef)
  svg.call(zoom).on("click", () => {
    if (activePath || pathBannerVisible()) clearPath();
    else clearFocus();
  });
  // Double-click empty canvas zooms in at the cursor (nodes swallow their own clicks).
  svg.on("dblclick", (event) => {
    event.preventDefault();
    const [mx, my] = d3.pointer(event, svg.node());
    zoomBy(1.5, mx, my);
  });
  initMinimap();
  restoreDisplayPrefs();
  buildLegend();
  buildDomainChecks();
  buildTagSuggestions();
  restoreOverlayStates();

  document.getElementById("color-mode").addEventListener("change", (e) => {
    colorMode = e.target.value === "community" ? "community" : "domain";
    saveDisplayPrefs();
    buildLegend();
    render();
  });
  document.getElementById("island-toggle").addEventListener("change", (e) => {
    islandMode = e.target.checked;
    saveDisplayPrefs();
    render();
  });
  document.getElementById("orphan-toggle").addEventListener("change", (e) => {
    orphanMode = e.target.checked;
    if (orphanMode) {
      // Make the highlight immediately visible: path/focus win in the
      // dimming compositor, so drop them when entering the orphan view.
      if (activePath || pathBannerVisible()) clearPath();
      clearFocus();
    }
    applyDimming();
  });
  document.getElementById("imp-slider").addEventListener("input", updateFilters);
  document.getElementById("tag-search").addEventListener("input", updateFilters);
  document.getElementById("node-search").addEventListener("keydown", (e) => { if (e.key === "Enter") handleSearch(); });
  document.getElementById("vault-search").addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(runVaultSearch, 300);
  });
  document.getElementById("vault-search").addEventListener("keydown", (e) => {
    if (e.key === "Enter") { clearTimeout(searchTimer); runVaultSearch(); }
  });
  document.getElementById("btn-reset").addEventListener("click", resetFilters);
  document.getElementById("btn-export").addEventListener("click", exportPNG);
  document.getElementById("btn-zoom-in").addEventListener("click", () => zoomBy(CFG.zoom.keyboardFactor));
  document.getElementById("btn-zoom-out").addEventListener("click", () => zoomBy(1 / CFG.zoom.keyboardFactor));
  document.getElementById("btn-zoom-fit").addEventListener("click", zoomFit);
  document.getElementById("btn-zoom-100").addEventListener("click", () => zoomTo(1));
  document.getElementById("modal-close").addEventListener("click", closeModal);
  document.getElementById("modal-overlay").addEventListener("click", closeModal);
  document.getElementById("btn-copy-link").addEventListener("click", copyNoteLink);

  render();
  updateStats();
  window.addEventListener("resize", () => { W = window.innerWidth; H = window.innerHeight; });
  // Call updateLOD once after initial render
  setTimeout(updateLOD, 100);
  // Hide the loading overlay once the simulation has painted a few frames.
  let loadingHidden = false;
  const hideLoading = () => {
    if (loadingHidden) return;
    loadingHidden = true;
    document.getElementById("loading").classList.add("done");
  };
  if (simulation) simulation.on("tick.loading", () => hideLoading());
  setTimeout(hideLoading, 2500); // failsafe for tiny graphs that end instantly

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
