import { describe, expect, it } from "vitest";

import { typesFor } from "./memory-panel";

describe("memory types per scope", () => {
  it("shared memory is about the owner or a project", () => {
    expect(typesFor({ shared: true })).toEqual(["user", "project"]);
  });
  it("an agent's memory is its own (never the shared 'user' type)", () => {
    expect(typesFor({ agentId: "a" })).not.toContain("user");
    expect(typesFor({ agentId: "a" })[0]).toBe("agent");
  });
});
