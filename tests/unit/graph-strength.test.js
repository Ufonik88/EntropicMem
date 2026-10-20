import { describe, expect, it } from "vitest";

import {
  EDGE_OPACITY_MAX,
  EDGE_OPACITY_MIN,
  EDGE_WIDTH_MAX_PX,
  EDGE_WIDTH_MIN_PX,
  mapEdgeStrength,
} from "../../plugins/entropicmem/scripts/em/graph/assets/graph-strength.js";

describe("mapEdgeStrength bounds", () => {
  it("never leaves the opacity band [0.2, 0.9]", () => {
    for (const s of [-Infinity, -1, 0, 0.5, 1, 1e6, Infinity, NaN, null, undefined]) {
      const { opacity } = mapEdgeStrength(s, 1, 10);
      expect(Number.isFinite(opacity)).toBe(true);
      expect(opacity).toBeGreaterThanOrEqual(EDGE_OPACITY_MIN);
      expect(opacity).toBeLessThanOrEqual(EDGE_OPACITY_MAX);
    }
  });

  it("never leaves the width band [1, 2] px", () => {
    for (const s of [-Infinity, -1, 0, 0.5, 1, 1e6, Infinity, NaN, null, undefined]) {
      const { width } = mapEdgeStrength(s, 1, 10);
      expect(Number.isFinite(width)).toBe(true);
      expect(width).toBeGreaterThanOrEqual(EDGE_WIDTH_MIN_PX);
      expect(width).toBeLessThanOrEqual(EDGE_WIDTH_MAX_PX);
    }
  });
});

describe("mapEdgeStrength strength extremes", () => {
  it("maps the weakest strength to the lowest visible opacity", () => {
    expect(mapEdgeStrength(1, 1, 10)).toEqual({ opacity: 0.2, width: 1.0 });
  });

  it("maps the strongest strength to the highest allowed opacity", () => {
    const style = mapEdgeStrength(10, 1, 10);
    expect(style.opacity).toBeCloseTo(0.9, 6);
    expect(style.width).toBe(2.0);
  });

  it("interpolates a mid-strength edge linearly", () => {
    expect(mapEdgeStrength(5.5, 1, 10)).toEqual({ opacity: 0.55, width: 1.5 });
    expect(mapEdgeStrength(1, 1, 10).opacity).toBeLessThan(mapEdgeStrength(5, 1, 10).opacity);
    expect(mapEdgeStrength(5, 1, 10).opacity).toBeLessThan(mapEdgeStrength(10, 1, 10).opacity);
  });

  it("clamps strengths outside the extent instead of leaving the band", () => {
    expect(mapEdgeStrength(0, 1, 10)).toEqual({ opacity: 0.2, width: 1.0 });
    expect(mapEdgeStrength(100, 1, 10).opacity).toBeCloseTo(0.9, 6);
    expect(mapEdgeStrength(100, 1, 10).width).toBe(2.0);
  });
});

describe("mapEdgeStrength edge cases", () => {
  it("missing strength uses the lowest visible opacity, never 0", () => {
    for (const strength of [undefined, null, NaN, -1, 0]) {
      const style = mapEdgeStrength(strength, 1, 10);
      expect(style.opacity).toBe(0.2);
      expect(style.opacity).not.toBe(0);
      expect(style.width).toBe(1.0);
    }
  });

  it("a single edge falls back to mid-range opacity", () => {
    const style = mapEdgeStrength(7, 7, 7);
    expect(style.opacity).toBe((0.2 + 0.9) / 2);
    expect(style.width).toBe((1.0 + 2.0) / 2);
  });

  it("all-equal strengths fall back to mid-range opacity", () => {
    const style = mapEdgeStrength(4, 4, 4);
    expect(style.opacity).toBe(0.55);
    expect(style.width).toBe(1.5);
    expect(mapEdgeStrength(4, 4, 4).opacity).toBeGreaterThan(mapEdgeStrength(1, 1, 10).opacity);
    expect(mapEdgeStrength(4, 4, 4).opacity).toBeLessThan(mapEdgeStrength(10, 1, 10).opacity);
  });

  it("non-finite extent is treated as flat", () => {
    expect(mapEdgeStrength(5, NaN, 10).opacity).toBe(0.55);
    expect(mapEdgeStrength(5, 1, Infinity).width).toBe(1.5);
  });
});
