import { describe, expect, it } from "vitest";

import { autoLevel, clampDpr, fitZoom, nearestLevel, stepLevel, zoomLevels, zoomPercent } from "./zoom";

describe("office zoom levels", () => {
  it("are whole device pixels per art pixel", () => {
    for (const dpr of [1, 1.25, 1.5, 2, 3]) {
      const levels = zoomLevels(dpr, fitZoom(1134 * dpr, 628 * dpr, 640, 360));
      expect(levels.every((level) => Number.isInteger(level) && level >= 1)).toBe(true);
      expect([...levels].sort((a, b) => a - b)).toEqual(levels);
      expect(new Set(levels).size).toBe(levels.length);
    }
  });

  it("fit shows the whole office; a retina laptop gets 150 %, a plain screen 100 %", () => {
    // 1440×900 laptop: the map is about 1134×628 CSS px
    expect(fitZoom(1134 * 2, 628 * 2, 640, 360)).toBe(3);
    expect(zoomPercent(3, 2)).toBe(150);
    expect(fitZoom(1134, 628, 640, 360)).toBe(1);
    expect(fitZoom(1614, 756, 640, 360)).toBe(2);
  });

  it("does not start microscopic on a phone, but fit can still show everything", () => {
    // iPhone: 358×268 CSS px at ratio 3 → the whole office fits only at 1 device px
    const fit = fitZoom(358 * 3, 268 * 3, 640, 360);
    expect(fit).toBe(1);
    const levels = zoomLevels(3, fit);
    expect(levels[0]).toBe(1);
    expect(zoomPercent(autoLevel(levels, fit, 3), 3)).toBe(67);
    // a big screen starts at fit
    expect(autoLevel(zoomLevels(2, 3), 3, 2)).toBe(3);
  });

  it("steps through the ladder and stops at the ends", () => {
    const levels = zoomLevels(2, 3); // 1 2 3 4 6 8 12
    expect(levels).toEqual([1, 2, 3, 4, 6, 8, 12]);
    expect(stepLevel(levels, 3, 1)).toBe(4);
    expect(stepLevel(levels, 3, -1)).toBe(2);
    expect(stepLevel(levels, 12, 1)).toBe(12);
    expect(stepLevel(levels, 1, -1)).toBe(1);
    expect(stepLevel(levels, 5, 1)).toBe(6);
  });

  it("remembers a size across screens by its CSS scale", () => {
    expect(nearestLevel(zoomLevels(2, 3), 1.5, 2)).toBe(3);
    expect(nearestLevel(zoomLevels(1, 1), 1.5, 1)).toBe(2);
    expect(nearestLevel(zoomLevels(3, 1), 2, 3)).toBe(6);
  });

  it("guards odd device pixel ratios", () => {
    expect(clampDpr(Number.NaN)).toBe(1);
    expect(clampDpr(0.5)).toBe(1);
    expect(clampDpr(4)).toBe(3);
    expect(clampDpr(1.25)).toBe(1.25);
  });
});
