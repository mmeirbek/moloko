import { describe, expect, it } from "vitest";

import { ANIMALS, assignLooks, lookOf } from "./agent-looks";

const agent = (n: number, agent_type = "autonomous") => ({
  id: `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`,
  created_at: new Date(Date.UTC(2026, 10, 1, 0, n)).toISOString(),
  agent_type,
});
const key = (l: { animal: string; accessory: string; expression: string }) => `${l.animal}/${l.accessory}/${l.expression}`;

describe("agent faces", () => {
  it("no two agents look the same, and the animals spread first", () => {
    const office = Array.from({ length: 30 }, (_, i) => agent(i + 1));
    const looks = assignLooks(office);
    expect(new Set([...looks.values()].map(key)).size).toBe(30);
    const first = office.slice(0, ANIMALS.length).map((a) => looks.get(a.id)!.animal);
    expect(new Set(first).size).toBe(ANIMALS.length); // the first twelve are twelve animals
  });

  it("the Orchestrator is the cow with a crown, and only it", () => {
    const office = [agent(1, "orchestrator"), ...Array.from({ length: 40 }, (_, i) => agent(i + 2))];
    const looks = assignLooks(office);
    expect(looks.get(office[0]!.id)).toMatchObject({ animal: "cow", accessory: "crown" });
    const crowned = [...looks.entries()].filter(([, l]) => l.animal === "cow" && l.accessory === "crown");
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
    expect(lookOf("x").animal === "cow" && lookOf("x").accessory === "crown").toBe(false);
  });
});
