import type { EventEnvelope } from "@moloko/shared-types";
import { describe, expect, it } from "vitest";

import { noticeFor } from "./rules";

const now = Date.parse("2026-11-01T10:00:00Z");
const ev = (type: string, payload: Record<string, unknown>, timestamp = "2026-11-01T09:59:00Z") =>
  ({
    id: "e",
    seq: 1,
    type,
    version: 1,
    timestamp,
    agent_id: null,
    task_id: null,
    run_id: null,
    payload,
  }) as EventEnvelope;

describe("notifications", () => {
  it("announces approvals and finished top-level tasks", () => {
    expect(noticeFor(ev("approval.required", { approval: { id: "a", summary: "Delete x" } }), now)).toMatchObject({
      kind: "approval",
      url: "/approvals",
      subject: "Delete x",
    });
    const task = { id: "t", title: "Report", parent_task_id: null };
    expect(noticeFor(ev("task.completed", { task }), now)?.kind).toBe("taskDone");
    expect(noticeFor(ev("task.failed", { task }), now)?.url).toBe("/tasks/t");
  });

  it("stays quiet for subtasks, other events and old replays", () => {
    expect(noticeFor(ev("task.completed", { task: { id: "s", title: "x", parent_task_id: "t" } }), now)).toBeNull();
    expect(noticeFor(ev("agent.status_changed", {}), now)).toBeNull();
    const old = ev("approval.required", { approval: { id: "a", summary: "x" } }, "2026-11-01T09:00:00Z");
    expect(noticeFor(old, now)).toBeNull();
  });
});

describe("web push helpers", () => {
  it("decodes the VAPID key and picks the chosen kinds", async () => {
    const { kindsOf, urlBase64ToUint8Array } = await import("./push");
    expect([...urlBase64ToUint8Array("AQID_-8")]).toEqual([1, 2, 3, 255, 239]);
    expect(kindsOf({ approval: true, taskDone: false, taskFailed: true, system: false, push: true })).toEqual([
      "approval",
      "taskFailed",
    ]);
  });
});
