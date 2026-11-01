import { describe, expect, it } from "vitest";

import { hitHref } from "./search-view";

const base = { source_id: "s", title: "t", snippet: "", score: 1, mode: "semantic", agent_id: null, workspace_id: null, conversation_id: null };

describe("search hits", () => {
  it("link to where the thing lives", () => {
    expect(hitHref({ ...base, source_type: "attachment", conversation_id: "c1" })).toBe("/chat/c1");
    expect(hitHref({ ...base, source_type: "memory", agent_id: "a1" })).toBe("/office/agents/a1");
    expect(hitHref({ ...base, source_type: "memory" })).toBe("/settings");
    expect(hitHref({ ...base, source_type: "file", workspace_id: "w" })).toBe("/integrations");
  });
});
