import { describe, expect, it } from "vitest";

import { asTab } from "@/features/agents/agent-tabs";

import { hitHref } from "./search-view";

const base = { source_id: "s", title: "t", snippet: "", score: 1, mode: "semantic", agent_id: null, workspace_id: null, conversation_id: null };

describe("search hits", () => {
  it("link to where the thing lives", () => {
    expect(hitHref({ ...base, source_type: "attachment", conversation_id: "c1" })).toBe("/chat/c1");
    expect(hitHref({ ...base, source_type: "memory", agent_id: "a1" })).toBe("/office/agents/a1");
    expect(hitHref({ ...base, source_type: "memory" })).toBe("/settings");
    expect(hitHref({ ...base, source_type: "file", workspace_id: "w" })).toBe("/integrations");
  });

  it("link work history to the task, the agent's messages and the chat", () => {
    expect(hitHref({ ...base, source_type: "task", source_id: "t1", agent_id: "a1" })).toBe("/tasks/t1");
    expect(hitHref({ ...base, source_type: "agent_message", agent_id: "a1", task_id: "t1" })).toBe(
      "/office/agents/a1?tab=messages",
    );
    expect(hitHref({ ...base, source_type: "agent_message", task_id: "t1" })).toBe("/tasks/t1");
    expect(hitHref({ ...base, source_type: "chat_message", conversation_id: "c2" })).toBe("/chat/c2");
  });

  it("open the agent tab named in the link", () => {
    expect(asTab("messages")).toBe("messages");
    expect(asTab("nope")).toBe("profile");
    expect(asTab(undefined)).toBe("profile");
  });
});
