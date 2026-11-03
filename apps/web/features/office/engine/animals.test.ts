import { describe, expect, it } from "vitest";

import { ANIMALS } from "@/features/agents/agent-looks";

import { ANIMAL_ART, animalFrame } from "./animals";
import { FRAME, FRAMES, paletteFor } from "./sprites";

describe("office animals", () => {
  it("every species has a head of 7 rows × 16 pixels in its own colours", () => {
    expect(Object.keys(ANIMAL_ART).sort()).toEqual([...ANIMALS].sort());
    for (const [species, art] of Object.entries(ANIMAL_ART)) {
      expect(art.head, species).toHaveLength(7);
      for (const row of art.head) {
        expect(row, species).toHaveLength(FRAME);
        expect(row, species).toMatch(/^[.abknxew]+$/);
      }
      if (art.head.join("").includes("x")) expect(art.colors.x, species).toBeDefined();
      if (art.head.join("").includes("w")) expect(art.colors.w, species).toBeDefined();
      expect(art.head.join("").match(/e/g), `${species}: two eyes`).toHaveLength(2);
    }
  });

  it("puts the head on every body frame: a face in front, fur from behind", () => {
    for (const species of ANIMALS) {
      for (const [name, base] of Object.entries(FRAMES)) {
        const frame = animalFrame(name, base, species);
        expect(frame, `${species} ${name}`).toHaveLength(FRAME);
        for (const row of frame) expect(row).toHaveLength(FRAME);
        const head = frame.join("");
        expect(head).not.toMatch(/h/); // no human hair left
        if (name.startsWith("type") || name === "read2") expect(head, `${species} ${name}`).not.toMatch(/e/);
        else expect(head.match(/e/g), `${species} ${name}`).toHaveLength(2);
        expect(frame.slice(7).join(""), "the body stays").toContain("c");
      }
    }
  });

  it("glances aside while thinking", () => {
    const eyes = (frame: string[]) => frame.flatMap((row, y) => [...row].flatMap((ch, x) => (ch === "e" ? [`${x},${y}`] : [])));
    const still = eyes(animalFrame("think1", FRAMES.think1!, "quokka"));
    const glance = eyes(animalFrame("think2", FRAMES.think2!, "quokka"));
    expect(glance).toEqual(still.map((p) => `${Number(p.split(",")[0]) + 1},${p.split(",")[1]}`));
  });

  it("the arms are fur, the eyes and the shirt the agent's own", () => {
    const p = paletteFor("agent-1", "autonomous", "amur_tiger");
    expect(p.s).toBe(ANIMAL_ART.amur_tiger.colors.a);
    expect(p.a).toBe(p.s);
    expect(p.c).toBe(paletteFor("agent-1", "autonomous").c);
    expect(paletteFor("agent-1", "autonomous", "okapi").e).toBe(ANIMAL_ART.okapi.eyes);
  });
});
