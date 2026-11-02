import type { RecalledSourceOut } from "@moloko/shared-types";
import { describe, expect, it } from "vitest";

import { recallHref, recallKind } from "./recall";

const base: RecalledSourceOut = { type: "memory", id: "m1", title: "Note" };

describe("recalled sources", () => {
  it("open the chat a source belongs to", () => {
    const file = { ...base, type: "attachment", id: "a1", conversation_id: "c1" };
    expect(recallHref(file)).toBe("/chat/c1");
    expect(recallKind(file)).toBe("chat");
    expect(recallHref({ ...base, type: "conversation", id: "c2" })).toBe("/chat/c2");
    // A new message type from the index still opens its chat.
    expect(recallHref({ ...base, type: "message", id: "x", conversation_id: "c3" })).toBe("/chat/c3");
  });

  it("open tasks, agents' memory and shared memory", () => {
    expect(recallHref({ ...base, type: "task", id: "t1" })).toBe("/tasks/t1");
    expect(recallKind({ ...base, type: "task", id: "t1" })).toBe("task");
    expect(recallHref({ ...base, agent_id: "ag" })).toBe("/office/agents/ag");
    expect(recallHref(base)).toBe("/settings#memory");
    expect(recallKind(base)).toBe("memory");
  });

  it("have no link when there is nowhere to go", () => {
    expect(recallHref({ ...base, type: "agent_message", id: "x" })).toBeNull();
    expect(recallHref({ ...base, type: "agent_message", id: "x", agent_id: "ag" })).toBe("/office/agents/ag");
    expect(recallKind({ ...base, type: "file", id: "f" })).toBe("other");
  });
});
