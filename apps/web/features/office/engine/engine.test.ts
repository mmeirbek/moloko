import { describe, expect, it } from "vitest";

import { SeatAssigner } from "./assign";
import { BEHAVIOR, behaviorFor } from "./behavior";
import { COLS, DESKS, isSeat, LAYOUT, ROWS, stepsTo, walkable, ZONES } from "./map";
import { findPath } from "./pathfinding";

describe("office map", () => {
  it("has the declared size", () => {
    expect(LAYOUT).toHaveLength(ROWS);
    for (const line of LAYOUT) expect(line).toHaveLength(COLS);
  });

  it("every desk seat and zone spot is floor or a seat, and reachable from the door", () => {
    const door = ZONES.door[0]!;
    const spots = [...DESKS.map((d) => d.seat), ...Object.values(ZONES).flat()];
    for (const spot of spots) {
      expect(walkable(spot.col, spot.row) || isSeat(spot.col, spot.row), `${spot.col},${spot.row}`).toBe(true);
      expect(findPath(door, spot, stepsTo(spot)), `${spot.col},${spot.row}`).not.toBeNull();
    }
  });

  it("nobody walks through a sofa or bench seat on the way somewhere else", () => {
    const sofa = ZONES.lounge[0]!;
    expect(isSeat(sofa.col, sofa.row)).toBe(true);
    expect(walkable(sofa.col, sofa.row)).toBe(false);
    const path = findPath(ZONES.door[0]!, ZONES.lounge.at(-1)!, stepsTo(ZONES.lounge.at(-1)!))!;
    expect(path.every((cell) => !isSeat(cell.col, cell.row))).toBe(true);
  });

  it("zones have room for a crowd (idle agents do not stack on one tile)", () => {
    expect(ZONES.lounge.length).toBeGreaterThanOrEqual(23);
    expect(ZONES.waiting.length).toBeGreaterThanOrEqual(13);
    const key = (s: { col: number; row: number }) => `${s.col},${s.row}`;
    for (const zone of Object.values(ZONES)) expect(new Set(zone.map(key)).size).toBe(zone.length);
  });

  it("has enough desks", () => {
    expect(DESKS.length).toBeGreaterThanOrEqual(10);
  });
});

describe("A*", () => {
  it("finds the shortest path around obstacles", () => {
    const grid = ["....", ".##.", "...."];
    const ok = (c: number, r: number) => r >= 0 && r < 3 && c >= 0 && c < 4 && grid[r]![c] === ".";
    const path = findPath({ col: 0, row: 1 }, { col: 3, row: 1 }, ok)!;
    expect(path[0]).toEqual({ col: 0, row: 1 });
    expect(path.at(-1)).toEqual({ col: 3, row: 1 });
    expect(path).toHaveLength(6); // around the wall: 5 moves
    for (const step of path) expect(ok(step.col, step.row)).toBe(true);
  });

  it("returns null when the goal is unreachable", () => {
    const ok = (c: number, r: number) => !(c === 2) && c >= 0 && c < 5 && r >= 0 && r < 3;
    expect(findPath({ col: 0, row: 0 }, { col: 4, row: 0 }, ok)).toBeNull();
  });
});

describe("status → behaviour (spec 18.4)", () => {
  it("covers every status with a distinct visual", () => {
    expect(Object.keys(BEHAVIOR).sort()).toEqual(
      ["completed", "failed", "idle", "paused", "planning", "reviewing", "waiting", "working"].sort(),
    );
    const visuals = Object.values(BEHAVIOR).map((b) => `${b.pose}/${b.indicator}`);
    expect(new Set(visuals).size).toBe(visuals.length);
    expect(BEHAVIOR.working.place).toBe("desk");
    // the owner's rule: no trips away from the desk while there is a task, and rest at the desk
    for (const status of ["idle", "planning", "working", "waiting", "reviewing", "completed", "failed"] as const)
      expect(BEHAVIOR[status].place).toBe("desk");
    expect(BEHAVIOR.paused.animated).toBe(false);
  });

  it("falls back to idle for unknown statuses", () => {
    expect(behaviorFor("weird")).toBe(BEHAVIOR.idle);
  });
});

describe("seat assignment", () => {
  it("is stable and gives new agents free seats", () => {
    const seats = new SeatAssigner({ desk: 3 });
    expect(seats.seat("desk", "a")).toBe(0);
    expect(seats.seat("desk", "b")).toBe(1);
    expect(seats.seat("desk", "a")).toBe(0);
    seats.release("desk", "a");
    expect(seats.seat("desk", "c")).toBe(0);
    expect(seats.seat("desk", "d")).toBe(2);
    const overflow = seats.seat("desk", "e");
    expect(overflow).toBeGreaterThanOrEqual(0);
    expect(overflow).toBeLessThan(3);
  });
});
