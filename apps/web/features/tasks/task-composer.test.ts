import { describe, expect, it } from "vitest";

import { composerMode } from "./task-composer";

describe("the task's message box", () => {
  it("writes to a working agent, continues a stopped task, replies after a result", () => {
    const top = (status: string) => ({ status, parent_task_id: null });
    expect(composerMode(top("running"), "autonomous")).toBe("message");
    expect(composerMode(top("waiting_approval"), "autonomous")).toBe("message");
    expect(composerMode(top("running"), "orchestrator")).toBe("orchestrator");
    expect(composerMode(top("failed"), "autonomous")).toBe("continue");
    expect(composerMode(top("cancelled"), "orchestrator")).toBe("continue");
    expect(composerMode(top("completed"), "orchestrator")).toBe("reply");
    expect(composerMode(top("created"), "autonomous")).toBeNull();
  });

  it("a finished part is continued through the whole task", () => {
    expect(composerMode({ status: "completed", parent_task_id: "t" }, "autonomous")).toBeNull();
    expect(composerMode({ status: "running", parent_task_id: "t" }, "autonomous")).toBe("message");
  });
});
