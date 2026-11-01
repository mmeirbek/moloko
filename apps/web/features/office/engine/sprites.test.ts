import { describe, expect, it } from "vitest";

import { BEHAVIOR } from "./behavior";
import { FRAME, FRAMES, ICONS, paletteFor, POSE_FRAMES } from "./sprites";

describe("pixel art", () => {
  it("every frame is 16×16 and only uses palette keys", () => {
    const allowed = new Set([".", "o", "s", "h", "c", "p", "f", "e", "w", "d"]);
    for (const [name, grid] of Object.entries(FRAMES)) {
      expect(grid, name).toHaveLength(FRAME);
      for (const line of grid) {
        expect(line.length, `${name}: "${line}"`).toBe(FRAME);
        for (const ch of line) expect(allowed.has(ch), `${name}: ${ch}`).toBe(true);
      }
    }
  });

  it("every pose used by a behaviour has frames, every icon is 8×8", () => {
    for (const b of Object.values(BEHAVIOR)) {
      for (const frame of POSE_FRAMES[b.pose]) expect(FRAMES[frame], frame).toBeDefined();
    }
    for (const [name, rows] of Object.entries(ICONS)) {
      expect(rows, name).toHaveLength(8);
      for (const row of rows) expect(row, name).toHaveLength(8);
    }
  });

  it("palettes are deterministic per agent and mark the orchestrator", () => {
    expect(paletteFor("abc", "autonomous")).toEqual(paletteFor("abc", "autonomous"));
    expect(paletteFor("abc", "orchestrator").c).toBe("#f0b43c");
  });
});
