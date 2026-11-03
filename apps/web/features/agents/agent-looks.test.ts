import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { ANIMALS, assignLooks, lookOf, moodOf } from "./agent-looks";

const agent = (n: number, agent_type = "autonomous", animal: string | null = null) => ({
  id: `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`,
  created_at: new Date(Date.UTC(2026, 10, 1, 0, n)).toISOString(),
  agent_type,
  animal,
});
const key = (l: { animal: string; accessory: string; expression: string }) => `${l.animal}/${l.accessory}/${l.expression}`;

describe("agent faces", () => {
  it("lists the same species as the server", () => {
    const server = readFileSync(resolve(__dirname, "../../../api/app/agents/looks.py"), "utf8");
    const literal = server.slice(server.indexOf("Animal = Literal["), server.indexOf("]", server.indexOf("Animal = Literal[")));
    expect([...literal.matchAll(/"([a-z_]+)"/g)].map((m) => m[1])).toEqual([...ANIMALS]);
  });

  it("an agent is the animal it was given", () => {
    const looks = assignLooks([agent(1, "autonomous", "amur_tiger"), agent(2, "autonomous", "axolotl")]);
    expect(looks.get(agent(1).id)!.animal).toBe("amur_tiger");
    expect(looks.get(agent(2).id)!.animal).toBe("axolotl");
    expect(lookOf(agent(3).id, "okapi").animal).toBe("okapi");
  });

  it("no two agents look the same, and without a given animal the species spread first", () => {
    const office = Array.from({ length: 30 }, (_, i) => agent(i + 1));
    const looks = assignLooks(office);
    expect(new Set([...looks.values()].map(key)).size).toBe(30);
    const first = office.slice(0, ANIMALS.length).map((a) => looks.get(a.id)!.animal);
    expect(new Set(first).size).toBe(ANIMALS.length);
    // the same species several times: they still differ by accessory or expression
    const tigers = assignLooks(Array.from({ length: 8 }, (_, i) => agent(i + 1, "autonomous", "amur_tiger")));
    expect(new Set([...tigers.values()].map(key)).size).toBe(8);
  });

  it("the Orchestrator is the cow with a crown, and only it", () => {
    const office = [agent(1, "orchestrator"), ...Array.from({ length: 40 }, (_, i) => agent(i + 2))];
    const looks = assignLooks(office);
    expect(looks.get(office[0]!.id)).toMatchObject({ animal: "cow", accessory: "crown" });
    const crowned = [...looks.entries()].filter(([, l]) => l.animal === "cow" || l.accessory === "crown");
    expect(crowned.map(([id]) => id)).toEqual([office[0]!.id]);
  });

  it("an agent keeps its face when newer agents join", () => {
    const office = Array.from({ length: 6 }, (_, i) => agent(i + 1));
    const before = assignLooks(office);
    const after = assignLooks([...office, agent(7), agent(8)]);
    for (const a of office) expect(after.get(a.id)).toEqual(before.get(a.id));
  });

  it("an agent the office no longer lists still gets a stable face", () => {
    expect(lookOf("x")).toEqual(lookOf("x"));
    expect(lookOf("x").animal).not.toBe("cow");
  });

  it("the face shows how the agent feels", () => {
    expect(moodOf("working")).toBe("busy");
    expect(moodOf("planning")).toBe("thinking");
    expect(moodOf("waiting_approval")).toBe("waiting");
    expect(moodOf("completed")).toBe("happy");
    expect(moodOf("failed")).toBe("sad");
    expect(moodOf("paused")).toBe("sleepy");
    expect(moodOf("idle")).toBe("calm");
    expect(moodOf(undefined)).toBe("calm");
  });
});
