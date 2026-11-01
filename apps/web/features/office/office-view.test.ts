import type { AgentOut } from "@moloko/shared-types";
import { describe, expect, it } from "vitest";

import { agentsForMode } from "./office-view";

const agent = (id: string, agent_type: string, archived = false) =>
  ({
    id,
    agent_type,
    archived_at: archived ? "2026-01-01" : null,
  }) as unknown as AgentOut;

describe("office modes", () => {
  it("agents mode shows persistent agents, subagents mode shows the run crews", () => {
    const all = [
      agent("o", "orchestrator"),
      agent("a", "autonomous"),
      agent("s", "subagent"),
      agent("x", "subagent", true),
    ];
    expect(agentsForMode(all, "agents").map((a) => a.id)).toEqual(["o", "a"]);
    expect(agentsForMode(all, "subagents").map((a) => a.id)).toEqual(["o", "s"]);
  });
});
