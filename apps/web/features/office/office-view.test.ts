import type { AgentOut } from "@moloko/shared-types";
import { describe, expect, it } from "vitest";

import { officeAgents } from "./office-view";

const agent = (id: string, agent_type: string, archived = false) =>
  ({
    id,
    agent_type,
    archived_at: archived ? "2026-01-01" : null,
  }) as unknown as AgentOut;

describe("the office", () => {
  it("shows the Orchestrator and the owner's agents — never old subagents or removed agents", () => {
    const all = [
      agent("o", "orchestrator"),
      agent("a", "autonomous"),
      agent("gone", "autonomous", true),
      agent("s", "subagent"),
    ];
    expect(officeAgents(all).map((a) => a.id)).toEqual(["o", "a"]);
  });
});
