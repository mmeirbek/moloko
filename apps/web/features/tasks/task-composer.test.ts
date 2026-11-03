import { describe, expect, it } from "vitest";

import { composerMode } from "./task-composer";

describe("the task's message box", () => {
  it("writes to a working agent, continues a stopped task, replies after a result", () => {
    const top = (status: string, status_reason: string | null = null) => ({ status, parent_task_id: null, status_reason });
    expect(composerMode(top("running"), "autonomous")).toBe("message");
    expect(composerMode(top("waiting_approval"), "autonomous")).toBe("message");
    expect(composerMode(top("running"), "orchestrator")).toBe("orchestrator");
    expect(composerMode(top("failed"), "autonomous")).toBe("continue");
    expect(composerMode(top("cancelled"), "orchestrator")).toBe("continue");
    expect(composerMode(top("completed"), "orchestrator")).toBe("reply");
    expect(composerMode(top("created"), "autonomous")).toBeNull();
    // waiting in line for its busy agent: notes wait for it (read first thing), or cancel it
    expect(composerMode(top("created", "waiting_for_agent"), "autonomous")).toBe("inLine");
  });

  it("a finished part is continued through the whole task", () => {
    expect(composerMode({ status: "completed", parent_task_id: "t", status_reason: null }, "autonomous")).toBeNull();
    expect(composerMode({ status: "running", parent_task_id: "t", status_reason: null }, "autonomous")).toBe("message");
  });
});
