# Visualizer

`entropicmem graph export --format html --output-dir ./export`

- Single self-contained `graph.html` (D3 v7, dark galaxy theme)
- Nodes = vault notes; edges = wikilinks + tag links + triples
- Filters: `--domain`, `--max-nodes`, `--min-importance`
- Serve: `entropicmem graph serve --port 8069 --dir ./export`

## Shipped graph behavior
- Edges render as cool-gray `#6b6b7d` lines with 0.65 opacity; semantic `triple:*` links are dashed, while `wikilink` and `tag` links are solid.
- Edge width is kind-based: `wikilink` = 0.8px, `triple:*` = 1.8px, `tag` = 1.0px.
- Links are drawn as curved SVG arcs with `mix-blend-mode: screen`; hover brightens opacity and enlarges the hovered edge, while revealing all connected labels.
- Background uses a subtle SVG dot grid; label opacity follows LOD behavior.

## Typography & iconography

- Display font: **Space Grotesk** (panel titles, modal headings); body font: **Inter** — both loaded from Google Fonts with system fallbacks.
- All UI icons are inline SVG (Lucide-style, 24x24 stroke icons): zoom controls, collapse chevrons, close/copy buttons, legend shape glyphs. No raster or unicode-glyph icons.

## Zoom & navigation

- Wheel zoom is `deltaMode`-normalized: trackpads (pixel deltas) and mouse wheels (line deltas) zoom at the same calibrated rate (~1.18x per notch).
- On-screen zoom controls in the panel: zoom in, zoom out, **fit to view**, and 1:1 (100%).
- Double-click empty canvas zooms in 1.5x anchored at the cursor.
- Minimap (bottom-right dock) shows a live viewport rect; click to pan.

## Collapsible overlays

Panel, legend, minimap, and stats each have a collapse toggle; collapsed state is persisted to `localStorage` (`entropicmem-graph-<id>-collapsed` keys).

| Key | Action |
|-----|--------|
| `+` / `-` | Zoom in / out |
| `0` | Fit graph to view |
| `Esc` | Close modal, or release focus mode |
| `H` | Toggle control panel |
| `L` | Toggle legend |
| `M` | Toggle minimap |
| `S` | Toggle stats |

## Interaction details

- **Focus mode** (click a node): dims non-neighbors, highlights the selected node with an accent ring; Esc or clicking empty space releases it.
- **Wikilinks resolve against the full vault** — `[[links]]` to notes outside the current export (the 500-node cap) are shown as dashed "pending" links and resolve lazily via `GET /api/note/by-title/{title}` (exact match, then shortest containing match) when served over HTTP; they only turn red when the target genuinely doesn't exist in the vault. Opening a lazily-resolved note no longer dims the graph.
- **Tooltip** flips at viewport edges so it never clips offscreen.
- **Modal**: full markdown rendering, wikilink navigation, tag chips that filter the graph, code-copy buttons, Tab focus trap, focus restored to the triggering node on close.
- **Loading state**: spinner overlay until the first simulation tick paints; **empty state** message when filters match zero notes.
- **PNG export** renders at `devicePixelRatio` (capped 2x) for crisp HiDPI output.
- Labels hide below 0.35x zoom and fade below 0.6x (semantic LOD); tag-count badges appear above 2.5x.
