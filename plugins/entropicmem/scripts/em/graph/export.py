"""
em/graph/export.py — the graph renderers: json, dot, canvas and the HTML file.

EM-605 split this out of the 2,100-line ``graph_export.py`` monolith. The model
(what the graph *is*) lives in :mod:`em.graph.model`; this module is the four
renderers over it. The HTML viewer itself is three packaged assets —
``assets/graph.html`` (the shell), ``assets/graph.css`` and ``assets/graph.js`` —
read through :mod:`importlib.resources` and **inlined** at export, so a written
``graph.html`` stays one self-contained file that works over ``file://``.

Stdlib-only. The HTML output loads D3 v7 and marked from public CDNs
(d3js.org, cdn.jsdelivr.net), plus Google Fonts, when it is opened in a
browser. There is no vendored or offline fallback: opening the file offline
shows no graph.
"""

import json
from html import escape as html_escape
from importlib.resources import files
from pathlib import Path
from typing import Optional

from em.graph.model import (
    EntityGraph,
    build_graph_payload,
    get_color,
    resolve_note_path,
)
from em_internal.index import VaultIndex

__all__ = [
    "export_canvas",
    "export_dot",
    "export_html",
    "export_json",
]

# ── JSON export ─────────────────────────────────────────────────────────────

def export_json(
    index: VaultIndex,
    output_path: Path,
    domain: Optional[str] = None,
    min_importance: float = 0.0,
    max_nodes: int = 500,
    include_bodies: bool = False,
    *,
    entity_graph: Optional[EntityGraph] = None,
) -> dict:
    """
    Export nodes + edges as JSON. Primary format consumed by graph.html.

    Note bodies (body_preview/full_body) are only embedded when
    include_bodies=True. Default is off so a shared/exported graph.json
    never leaks vault content. Pass include_bodies=True only for offline
    modal reading on a trusted machine.

    ``entity_graph`` optionally adds the memory.db subgraph (EM-605 2.1).

    Returns the dict that was written (for testing).
    """
    payload = build_graph_payload(
        index,
        domain=domain,
        min_importance=min_importance,
        max_nodes=max_nodes,
        include_bodies=include_bodies,
        context=f"export_json({output_path})",
        entity_graph=entity_graph,
    )
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
    *,
    entity_graph: Optional[EntityGraph] = None,
) -> str:
    """
    Export as a single self-contained HTML file with embedded graph data.
    Works via file:// or HTTP server. D3 v7 + marked are loaded from public
    CDNs (d3js.org, cdn.jsdelivr.net) when the page is opened; there is no
    vendored fallback, so the viewer needs network access to render.

    By default note bodies are NOT embedded (security: avoids leaking vault
    content via local HTTP/graph share). Pass include_bodies=True for offline
    modal reading on a trusted machine only.

    vault_root: path to the vault when include_bodies=True. When omitted and
    bodies are requested, resolved from ENTROPICMEM_VAULT_PATH only (not Obsidian).

    Stored-XSS guard: body text embedded into the template is HTML-escaped at
    embed time (the modal renders bodies via marked.parse() into innerHTML and
    marked passes raw HTML through). Lazy /api/note bodies arrive raw and are
    covered by the client-side sanitizeRenderedHtml pass in the template.
    """
    data = export_json(
        index, output_path.parent / "graph.json",
        domain=domain, min_importance=min_importance, max_nodes=max_nodes,
        include_bodies=include_bodies,
        entity_graph=entity_graph,
    )

    # Attach full bodies only when explicitly requested.
    if include_bodies:
        vault = None
        if vault_root is None:
            try:
                import os

                from em_internal.vault import resolve_vault_path
                env = os.environ.get("ENTROPICMEM_VAULT_PATH")
                vault_root = Path(env).expanduser() if env else resolve_vault_path()
            except Exception:
                vault_root = None
        if vault_root is not None:
            try:
                from em_internal.vault import Vault
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
                    # resolve_note_path rejects absolute/dot-dot DB paths: a
                    # poisoned notes_meta.path must not become an arbitrary
                    # file read (its ValueError lands in the except below).
                    note = vault.read_note(resolve_note_path(Path(vault_root), meta["path"]))
                    node["full_body"] = note.body
                except Exception:
                    pass

    # Stored-XSS guard: escape every embedded body so a stored
    # <img onerror=…> payload reaches the modal DOM as literal text, never as
    # markup (marked would otherwise pass it straight into innerHTML). Only
    # the template payload is escaped — graph.json, already written above,
    # keeps raw body text (it is data, not markup).
    for node in data.get("nodes", []):
        for key in ("full_body", "body_preview"):
            if node.get(key):
                node[key] = html_escape(node[key], quote=True)


    # Serialize and make it safe to embed inside a <script> tag: the only
    # sequence that can prematurely close the tag is "</", so escape it.
    graph_json = json.dumps(data).replace("</", "<\\/")
    html = _render_html(graph_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    return html


# ── Viewer assets (EM-605): the HTML/CSS/JS ship as package data ────────────

def _read_asset(name: str) -> str:
    """Read one packaged viewer asset (``em/graph/assets/<name>``)."""
    return (files("em.graph") / "assets" / name).read_text(encoding="utf-8")


def _render_html(graph_json: str) -> str:
    """Inline the three viewer assets into one self-contained HTML document.

    The shell carries ``__ENTROPICMEM_CSS__`` / ``__ENTROPICMEM_D3_JS__`` /
    ``__ENTROPICMEM_MARKED_JS__`` / ``__ENTROPICMEM_JS__`` placeholders (and
    ``__ENTROPICMEM_FAVICON__``); the JS carries
    ``__ENTROPICMEM_GRAPH_DATA__``. Composing the shell first means the data
    and favicon placeholders are found wherever they ended up.
    """
    html = (
        _read_asset("graph.html")
        .replace("__ENTROPICMEM_CSS__", _read_asset("graph.css"))
        .replace("__ENTROPICMEM_D3_JS__", _read_asset("d3.min.js"))
        .replace("__ENTROPICMEM_MARKED_JS__", _read_asset("marked.min.js"))
        .replace("__ENTROPICMEM_JS__", _read_asset("graph.js"))
    )
    return html.replace("__ENTROPICMEM_GRAPH_DATA__", graph_json).replace(
        "__ENTROPICMEM_FAVICON__", _FAVICON_DATA_URI
    )


# ── Branding ─────────────────────────────────────────────────────────────────
# The favicon: the EntropicMem mark (the network glyph cropped from the logo),
# 64×64 PNG inlined as a data URI so the export stays one self-contained file
# and the CSP (`img-src 'self' data:`) admits it. Regenerate from the
# 2048×2048 source: crop the square mark (sips -c 1200 1200 --cropOffset 0 424),
# then sips -s format png --resampleHeightWidth 64 64.
_FAVICON_DATA_URI = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAIAAAAlC+aJAAAAAXNSR0IArs4c6QAAAHhlWElmTU0AKgAAAAgABAEaAAUAAAAB"
    "AAAAPgEbAAUAAAABAAAARgEoAAMAAAABAAIAAIdpAAQAAAABAAAATgAAAAAAAAEsAAAAAQAAASwAAAABAAOgAQADAAAAAQAB"
    "AACgAgAEAAAAAQAAAECgAwAEAAAAAQAAAEAAAAAAEz0GrAAAAAlwSFlzAAAuIwAALiMBeKU/dgAAAp5pVFh0WE1MOmNvbS5h"
    "ZG9iZS54bXAAAAAAADx4OnhtcG1ldGEgeG1sbnM6eD0iYWRvYmU6bnM6bWV0YS8iIHg6eG1wdGs9IlhNUCBDb3JlIDYuMC4w"
    "Ij4KICAgPHJkZjpSREYgeG1sbnM6cmRmPSJodHRwOi8vd3d3LnczLm9yZy8xOTk5LzAyLzIyLXJkZi1zeW50YXgtbnMjIj4K"
    "ICAgICAgPHJkZjpEZXNjcmlwdGlvbiByZGY6YWJvdXQ9IiIKICAgICAgICAgICAgeG1sbnM6dGlmZj0iaHR0cDovL25zLmFk"
    "b2JlLmNvbS90aWZmLzEuMC8iCiAgICAgICAgICAgIHhtbG5zOmV4aWY9Imh0dHA6Ly9ucy5hZG9iZS5jb20vZXhpZi8xLjAv"
    "Ij4KICAgICAgICAgPHRpZmY6WFJlc29sdXRpb24+MzAwPC90aWZmOlhSZXNvbHV0aW9uPgogICAgICAgICA8dGlmZjpZUmVz"
    "b2x1dGlvbj4zMDA8L3RpZmY6WVJlc29sdXRpb24+CiAgICAgICAgIDx0aWZmOlJlc29sdXRpb25Vbml0PjI8L3RpZmY6UmVz"
    "b2x1dGlvblVuaXQ+CiAgICAgICAgIDxleGlmOlBpeGVsWURpbWVuc2lvbj4xMjAwPC9leGlmOlBpeGVsWURpbWVuc2lvbj4K"
    "ICAgICAgICAgPGV4aWY6UGl4ZWxYRGltZW5zaW9uPjEyMDA8L2V4aWY6UGl4ZWxYRGltZW5zaW9uPgogICAgICAgICA8ZXhp"
    "ZjpDb2xvclNwYWNlPjE8L2V4aWY6Q29sb3JTcGFjZT4KICAgICAgPC9yZGY6RGVzY3JpcHRpb24+CiAgIDwvcmRmOlJERj4K"
    "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"
    "RK5CYII="
)
