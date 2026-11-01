import { describe, expect, it } from "vitest";

import { BEHAVIOR, cowBehaviorFor, type AgentStatus } from "./behavior";
import { bubbleRows, COW_H, COW_W, cowFrame, hornOf, petFor, PETS } from "./cow";
import { isNight, phaseFor, skyFor } from "./daynight";
import { LAYOUT, walkable, ZONES } from "./map";

describe("the cow (Orchestrator)", () => {
  it("has a look for every status", () => {
    for (const status of Object.keys(BEHAVIOR) as AgentStatus[]) {
      expect(cowBehaviorFor(status).pose).toBeTruthy();
    }
    expect(cowBehaviorFor("idle").pose).toBe("graze");
    expect(cowBehaviorFor("working").place).toBe("patrol");
    expect(cowBehaviorFor("failed").pose).toBe("sad");
    expect(cowBehaviorFor("completed").pose).toBe("cheer");
    expect(cowBehaviorFor("unknown").pose).toBe("graze");
  });

  it("sleeps at night only when idle", () => {
    expect(cowBehaviorFor("idle", { night: true })).toMatchObject({ pose: "sleep", bubble: "zzz" });
    expect(cowBehaviorFor("working", { night: true }).pose).toBe("carry");
  });

  it("moos when an approval waits, unless paused", () => {
    expect(cowBehaviorFor("working", { attention: true })).toMatchObject({ pose: "moo", bubble: "moo" });
    expect(cowBehaviorFor("paused", { attention: true }).pose).toBe("frozen");
  });

  it("wears the seasonal hat on its head in every frame", () => {
    for (const frame of ["stand", "graze1", "moo1", "sleep1"]) {
      const plain = cowFrame(frame, null);
      const hat = cowFrame(frame, "newyear");
      expect(plain).toHaveLength(COW_H);
      expect(plain[0]).toHaveLength(COW_W);
      expect(hat.join("")).toContain("R");
      expect(plain.join("")).not.toContain("R");
      const horn = hornOf(plain);
      const hatTop = hat.findIndex((row) => row.includes("R"));
      expect(hatTop).toBeLessThanOrEqual(horn.y);
    }
  });

  it("lives on a walkable pasture by the gate", () => {
    for (const spot of ZONES.pasture) {
      expect(walkable(spot.col, spot.row)).toBe(true);
      expect(LAYOUT[spot.row]![spot.col]).toBe("G");
    }
  });
});

describe("bubbles and pets", () => {
  it("draws a closed bubble around the text", () => {
    const rows = bubbleRows("МУ!");
    const width = rows[0]!.length;
    expect(rows.every((r) => r.length === width)).toBe(true);
    expect(rows[3]!.startsWith("ow") && rows[3]!.endsWith("wo")).toBe(true);
  });

  it("gives each persistent agent a stable pet", () => {
    expect(petFor("agent-1")).toBe(petFor("agent-1"));
    expect(Object.keys(PETS)).toContain(petFor("agent-2"));
    for (const rows of Object.values(PETS)) expect(rows.every((r) => r.length === rows[0]!.length)).toBe(true);
  });
});

describe("day and night", () => {
  it.each([
    [3, "night"],
    [5, "dawn"],
    [12, "day"],
    [20, "dusk"],
    [23, "night"],
    [-1, "night"],
  ])("hour %i is %s", (hour, phase) => {
    expect(phaseFor(hour)).toBe(phase);
  });

  it("darkens the office at night only", () => {
    expect(skyFor(12).tintAlpha).toBe(0);
    expect(skyFor(23).tintAlpha).toBeGreaterThan(0.2);
    expect(skyFor(23).stars).toBe(true);
    expect(isNight(23)).toBe(true);
    expect(isNight(9)).toBe(false);
  });
});
