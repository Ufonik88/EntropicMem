/**
 * Relationship-strength → edge stroke style for the EntropicMem visual graph.
 *
 * Pure, deterministic, side-effect free: given an edge's strength and the
 * current edge strength extent, returns the stroke opacity and stroke width
 * that encode that strength visually. The viewer consumes it per edge at
 * render time; nothing here touches the graph model, the strength data or
 * the layout algorithm.
 *
 * The model exposes relationship strength as each edge's `weight`; this
 * module only reads it.
 *
 * Visual encoding (house style: dark theme, neon accents, no default-library
 * look):
 *   - opacity maps linearly from the strength extent into [0.2, 0.9], so the
 *     weakest edge stays visible and the strongest never competes with the
 *     node's painted border (0.6 px at rest, 2.2 px selected / on-path in
 *     graph.css);
 *   - width maps linearly into [1.0, 2.0] px, always below the node's 2.2 px
 *     selected border weight;
 *   - missing, zero or non-finite strength ⇒ lowest visible opacity (0.2,
 *     never 0) and the minimum width;
 *   - a single edge, or all-equal strengths (no extent to normalise against),
 *     ⇒ mid-range opacity (0.55) and mid width (1.5 px).
 */

// ── tokens (existing house values only; no new visual tokens) ──────────────

export const EDGE_OPACITY_MIN = 0.2;
export const EDGE_OPACITY_MAX = 0.9;
export const EDGE_OPACITY_MID = (EDGE_OPACITY_MIN + EDGE_OPACITY_MAX) / 2; // 0.55

export const EDGE_WIDTH_MIN_PX = 1.0;
export const EDGE_WIDTH_MAX_PX = 2.0; // ≤ node's 2.2 px selected border weight
export const EDGE_WIDTH_MID_PX = (EDGE_WIDTH_MIN_PX + EDGE_WIDTH_MAX_PX) / 2; // 1.5

// ── pure mapping ───────────────────────────────────────────────────────────

/**
 * Map one edge's strength to a stroke style.
 *
 * @param {number} strength - edge strength from the graph model (`edge
 *   weight`); non-finite or <= 0 is treated as missing
 * @param {number} lo - minimum strength across the currently rendered edges
 * @param {number} hi - maximum strength across the currently rendered edges
 * @returns {{opacity: number, width: number}} opacity in [0.2, 0.9], width
 *   in [1, 2] px; both finite. Missing/zero strength ⇒ lowest visible
 *   opacity, never 0. Flat extent (single edge / all-equal strengths) ⇒
 *   mid-range values.
 */
export function mapEdgeStrength(strength, lo, hi) {
  const s = Number(strength);
  if (!Number.isFinite(s) || s <= 0) {
    // Missing / zero / never-painted strength: lowest visible opacity,
    // never fully transparent, minimum width.
    return { opacity: EDGE_OPACITY_MIN, width: EDGE_WIDTH_MIN_PX };
  }
  if (!Number.isFinite(lo) || !Number.isFinite(hi) || hi <= lo) {
    // One edge, or every edge equally strong: nothing to normalise against,
    // so fall back to the middle of the visible band.
    return { opacity: EDGE_OPACITY_MID, width: EDGE_WIDTH_MID_PX };
  }
  // Clamp into [0, 1] so strengths just outside the extent stay in band.
  const t = Math.max(0, Math.min(1, (s - lo) / (hi - lo)));
  return {
    opacity: EDGE_OPACITY_MIN + t * (EDGE_OPACITY_MAX - EDGE_OPACITY_MIN),
    width: EDGE_WIDTH_MIN_PX + t * (EDGE_WIDTH_MAX_PX - EDGE_WIDTH_MIN_PX),
  };
}

// Expose to the classic-script viewer (graph.js) loaded alongside this
// module in graph.html; a no-op in non-browser environments.
if (typeof window !== "undefined") {
  window.__emGraphStrength = {
    mapEdgeStrength,
    EDGE_OPACITY_MIN,
    EDGE_OPACITY_MAX,
    EDGE_OPACITY_MID,
    EDGE_WIDTH_MIN_PX,
    EDGE_WIDTH_MAX_PX,
    EDGE_WIDTH_MID_PX,
  };
}
