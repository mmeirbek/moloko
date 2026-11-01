import { describe, expect, it } from "vitest";

import { COW, composeFace, runs, seasonFor } from "./art";
import { bottleRows } from "./milk-bottle";

describe("cow art", () => {
  it("has rectangular frames using only palette colours", () => {
    for (const sheet of [COW.face, COW.side]) {
      for (const [name, rows] of Object.entries(sheet.frames)) {
        expect(rows, name).toHaveLength(sheet.height);
        for (const row of rows) {
          expect(row, name).toHaveLength(sheet.width);
          for (const key of row) if (key !== ".") expect(COW.palette[key], `${name}:${key}`).toBeDefined();
        }
      }
    }
    for (const rows of Object.values(COW.overlays)) {
      expect(rows).toHaveLength(COW.face.height);
      for (const row of rows) for (const key of row) if (key !== ".") expect(COW.palette[key]).toBeDefined();
    }
  });

  it("draws an outfit over the cow and keeps the cow elsewhere", () => {
    const plain = composeFace("idle");
    const dressed = composeFace("idle", "newyear");
    expect(dressed[0]).not.toEqual(plain[0]);
    expect(dressed[19]).toEqual(plain[19]);
  });

  it("merges runs of one colour", () => {
    expect(runs(["aab.", ".bbb"])).toEqual([
      { x: 0, y: 0, w: 2, key: "a" },
      { x: 2, y: 0, w: 1, key: "b" },
      { x: 1, y: 1, w: 3, key: "b" },
    ]);
  });

  it.each([
    ["2026-12-31", "newyear"],
    ["2027-01-14", "newyear"],
    ["2027-01-15", null],
    ["2026-10-31", "halloween"],
    ["2026-11-01", "halloween"],
    ["2026-11-02", null],
    ["2027-04-10", "spring"],
    ["2027-07-01", null],
  ])("season on %s is %s", (day, season) => {
    expect(seasonFor(new Date(`${day}T12:00:00`))).toBe(season);
  });
});

describe("milk bottle", () => {
  const milk = (rows: string[]) => rows.join("").split("m").length - 1;
  it("fills from the bottom with progress", () => {
    expect(milk(bottleRows(0))).toBe(0);
    expect(milk(bottleRows(50))).toBeGreaterThan(0);
    expect(milk(bottleRows(100))).toBeGreaterThan(milk(bottleRows(50)));
    const half = bottleRows(50);
    expect(half[16]).toContain("m");
    expect(half[3]).not.toContain("m");
  });
  it("clamps out-of-range values", () => {
    expect(bottleRows(150)).toEqual(bottleRows(100));
    expect(bottleRows(-5)).toEqual(bottleRows(0));
  });
});
