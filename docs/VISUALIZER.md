# Visualizer

```bash
python3 ~/.hermes/plugins/entropicmem/scripts/entropicmem.py graph export --format html --output-dir ./export
```

- Single self-contained `graph.html` (D3 v7, dark galaxy theme)
- Nodes = vault notes; edges = wikilinks + tag links + triples
- Filters: `--domain`, `--max-nodes`, `--min-importance`
- Serve: `python3 ~/.hermes/plugins/entropicmem/scripts/entropicmem.py graph serve --port 8069 --dir ./export`

## Shipped graph behavior

- Edges render as cool-gray `#6b6b7d` lines with 0.65 opacity; semantic `triple:*` links are dashed, while `wikilink` and `tag` links are solid.
- Edge width is kind-based: `wikilink` = 0.8px, `triple:*` = 1.8px, `tag` = 1.0px.
- Links are drawn as curved SVG arcs with `mix-blend-mode: screen`; hover brightens opacity and enlarges the hovered edge, while revealing all connected labels.
- Background uses a subtle SVG dot grid; label opacity follows LOD behavior.

## Typography & iconography

- Display font: Space Grotesk (panel titles, modal headings); body font: Inter, both loaded from Google Fonts with system fallbacks.
- All UI icons are inline SVG (Lucide-style, 24x24 stroke icons): zoom controls, collapse chevrons, close/copy buttons, legend shape glyphs. No raster or unicode-glyph icons.

## Zoom & navigation

- Wheel zoom is `deltaMode`-normalized: trackpads (pixel deltas) and mouse wheels (line deltas) zoom at the same calibrated rate (about 1.18x per notch).
- On-screen zoom controls in the panel: zoom in, zoom out, fit to view, and 1:1 (100%).
- Double-click empty canvas zooms in 1.5x anchored at the cursor.
- Minimap (bottom-right dock) shows a live viewport rect; click to pan.

## Color modes & communities

- **Color by: Domain | Community** (panel). In community mode each node takes its community's color from a deterministic colorblind-safe palette (Okabe-Ito core plus accessible extras), and the legend lists the largest communities as `Community <id> (<n>)` with a `unclustered (n)` row for isolated notes. Community ids are stable across rebuilds of identical vault state (deterministic label propagation at export time).
- **Cluster islands** (panel toggle, default off): a gentle centroid force pulls each community toward its own centroid, reading as separate 2D islands. Physics otherwise unchanged; off = the shipped layout.
- Both preferences persist to `localStorage` (`entropicmem-graph-color-mode`, `entropicmem-graph-island`).

## Vault search

- **Search the vault** (panel): full-text search over ALL notes via `GET /api/search?q=` on the graph server (vault FTS), independent of the 500-node export cap. Debounced (300 ms) and Enter-triggered.
- Results list shows title + domain; hits inside the current view zoom and focus the node, hits outside the export open the note modal through the lazy fetch ("not in current view" marker). Without the local server (`file://` or server down) the box explains what is missing.

## Path tracing

- Click a node, then shift-click a second node to highlight the shortest path between them (server BFS over `graph_edges`, depth-capped at 10 hops by default). The path lights up with an accent ring per node, the rest of the graph dims, and a banner reports the hop count; a further shift-click re-routes from the same origin. `Esc` or an empty-canvas click clears.
- A shift-click with no prior selection sets the path origin instead.

## Orphan highlight

- **Highlight orphans** (panel toggle): notes with zero graph edges stay lit while connected notes fade, making disconnected notes easy to find. The stats pill reports `<n> orphans` for the current view. This is a hygiene signal only; nothing is ever deleted.

## Collapsible overlays

Panel, legend, minimap, and stats each have a collapse toggle; collapsed state is persisted to `localStorage` (`entropicmem-graph-<id>-collapsed` keys).

| Key | Action |
|-----|--------|
| `+` / `-` | Zoom in / out |
| `0` | Fit graph to view |
| `Esc` | Clear the path, or release focus mode, or close the modal |
| `H` | Toggle control panel |
| `L` | Toggle legend |
| `M` | Toggle minimap |
| `S` | Toggle stats |

## Interaction details

- **Focus mode** (click a node): dims non-neighbors, highlights the selected node with an accent ring; Esc or clicking empty space releases it.
- **Wikilinks resolve against the full vault.** `[[links]]` to notes outside the current export (the 500-node cap) are shown as dashed "pending" links and resolve lazily via `GET /api/note/by-title/{title}` (exact match, then shortest containing match) when served over HTTP; they only turn red when the target genuinely does not exist in the vault. Opening a lazily-resolved note no longer dims the graph.
- **Tooltip** flips at viewport edges so it never clips offscreen.
- **Modal**: full markdown rendering, wikilink navigation, tag chips that filter the graph, code-copy buttons, Tab focus trap, focus restored to the triggering node on close.
- **Loading state**: spinner overlay until the first simulation tick paints; **empty state** message when filters match zero notes.
- **PNG export** renders at `devicePixelRatio` (capped 2x) for crisp HiDPI output.
- Labels hide below 0.35x zoom and fade below 0.6x (semantic LOD); tag-count badges appear above 2.5x.

## Graph server security model

The read endpoints (`/`, `/graph.json`, `/api/note/*`, `/api/search`, `/api/path`) serve full vault content, so the server enforces its exposure policy at startup:

- **Loopback-only bind enforced.** A non-loopback bind is refused at startup. To serve beyond loopback you must set `ENTROPICMEM_GRAPH_EXPOSE=1` to explicitly accept the exposure.
- **One token, two sources.** The server token is `ENTROPICMEM_GRAPH_TOKEN` when set in the server environment; otherwise a random per-run token (256-bit, new on every start) that the server writes to `$HERMES_HOME/entropicmem/graph_server.token` (mode `0600`) at startup and removes at shutdown. It is sent per request in the `X-EntropicMem-Token` header and compared in constant time.
- **Token required when exposed.** When not loopback-bound, the body-bearing read endpoints require the token. On the loopback trust plane reads are tokenless.
- **`POST /refresh` is always token-gated**, loopback included: `curl -X POST -H "X-EntropicMem-Token: $(cat ~/.hermes/entropicmem/graph_server.token)" http://127.0.0.1:<port>/refresh`. A request with no token gets `403` while no static token is configured, `401` otherwise; a wrong token gets `401`.
- **Host allowlist (DNS-rebinding guard).** Every route except `/health` requires the `Host` header to name `127.0.0.1`, `localhost`, `[::1]` (or a loopback bind address) **on the port the server is actually listening on** (a `Host` without a port means `:80`); anything else gets `400 invalid Host header` before any token check. With `ENTROPICMEM_GRAPH_EXPOSE=1` the concrete bind host is also allowed, plus the comma-separated names in `ENTROPICMEM_GRAPH_ALLOWED_HOSTS` (required for a wildcard `0.0.0.0`/`::` bind, since no client sends that address; ignored without the exposure opt-in, so a same-host reverse proxy cannot silently widen the tokenless loopback plane).
- **Security headers on every response**, errors included: a `Content-Security-Policy` that allows only what `graph.html` loads (inline script/style, D3 from `d3js.org`, `marked` from `cdn.jsdelivr.net`, Google Fonts, `data:` images for PNG export) with `connect-src 'self'` (vault content cannot be fetched out to another origin), no remote images, `frame-ancestors 'none'`; plus `X-Content-Type-Options: nosniff` and `Referrer-Policy: no-referrer`.
- **`GET /health`** stays open (no token, no Host check; it carries no vault content) and reports the active bind policy, whether the token is required, and `token_source` (`env` or `per-run`).

### `entropicmem graph serve` (static CLI server)

`graph serve` is a small stdlib server for an exported directory; it needs no FastAPI and has no API endpoints (vault search and path tracing report the server as unavailable). It applies the same rules where they fit: a non-loopback `--bind` is refused unless `ENTROPICMEM_GRAPH_EXPOSE=1`, the same Host allowlist (`ENTROPICMEM_GRAPH_ALLOWED_HOSTS` when exposed) and the same security headers, and only `/`, `/graph.html` and `/graph.json` are served (no directory listing, no other files from `--dir`). It has **no token**: with `ENTROPICMEM_GRAPH_EXPOSE=1` anyone who can reach the address can read the export, so use the FastAPI server for authenticated remote access.

## Markdown sanitization (stored-XSS guard)

Note bodies are untrusted content. The modal renders markdown with `marked`, which passes raw HTML through and emits link hrefs verbatim, so every rendered result also passes a client-side `sanitizeRenderedHtml` pass before touching the DOM. This covers both bodies embedded at export time and raw lazy-fetched bodies from `/api/note/*`. Static export CLI defaults to metadata-only bodies (`--include-bodies` to embed); the local authenticated server pins bodies on (drop them only with `ENTROPICMEM_GRAPH_LEAN=1`).
