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
    expect(kindsOf({ approval: true, taskDone: false, taskFailed: true, budget: false, system: false, push: true })).toEqual([
      "approval",
      "taskFailed",
    ]);
  });
});

describe("finished tasks", () => {
  it("say the short result, or the question the agent waits on", () => {
    const task = (result: string) => ({ id: "t", title: "Сайт", parent_task_id: null, result });
    expect(noticeFor(ev("task.completed", { task: task("## Итог\n\n**Готово**: отчёт в report.md.") }), now)).toMatchObject({
      kind: "taskDone",
      title: "taskDone",
      subject: "Сайт",
      summary: "Готово: отчёт в report.md.",
    });
    expect(noticeFor(ev("task.completed", { task: task("Нашёл два.\n\n**Уточните, какой нужен?**") }), now)).toMatchObject({
      kind: "taskDone", // the same switch as «готово»
      title: "taskQuestion",
      summary: "Уточните, какой нужен?",
    });
    expect(noticeFor(ev("task.failed", { task: task("") }), now)).toMatchObject({ title: "taskFailed", summary: "" });
  });
});

describe("budget notices", () => {
  it("stays quiet before the budget is used up", async () => {
    const { noticeFor } = await import("./rules");
    const event = {
      id: "e",
      seq: 1,
      type: "budget.warning" as const,
      version: 1,
      timestamp: new Date().toISOString(),
      agent_id: null,
      task_id: null,
      run_id: null,
      payload: { month: "2026-11", percent: 80, spent_usd: "8.00", limit_usd: "10" },
    };
    expect(noticeFor(event)).toBeNull();
  });

  it("announces a used-up budget once per month", async () => {
    const { noticeFor } = await import("./rules");
    const event = {
      id: "e",
      seq: 1,
      type: "budget.warning" as const,
      version: 1,
      timestamp: new Date().toISOString(),
      agent_id: null,
      task_id: null,
      run_id: null,
      payload: { month: "2026-11", percent: 100, spent_usd: "10.00", limit_usd: "10" },
    };
    expect(noticeFor(event)).toMatchObject({ kind: "budget", key: "budget:2026-11:100", url: "/settings/costs" });
  });

  it("announces an agent's own budget separately and links to the agent", async () => {
    const { noticeFor } = await import("./rules");
    const event = {
      id: "e2",
      seq: 2,
      type: "budget.warning" as const,
      version: 1,
      timestamp: new Date().toISOString(),
      agent_id: "a1",
      task_id: null,
      run_id: null,
      payload: {
        scope: "agent",
        agent_id: "a1",
        agent_name: "Researcher",
        month: "2026-11",
        percent: 100,
        spent_usd: "5.02",
        limit_usd: "5.00",
      },
    };
    expect(noticeFor(event)).toEqual({
      kind: "budget",
      key: "budget:2026-11:a1:100",
      title: "budget",
      subject: "«Researcher»: 100% · $5.02 / $5.00",
      url: "/office/agents/a1",
    });
  });
});


describe("plain words, not code", () => {
  it("says what the agent wants to do without the command or the whole path", async () => {
    const { approvalOp, shortText } = await import("./text");
    expect(approvalOp("terminal_run", { command: 'python3 -c "\ndef L(h):\n  return 1\n"' })).toEqual({
      key: "terminal_run",
      params: { program: "python3" },
    });
    expect(approvalOp("fs_write", { path: "moloko-mobile-polish/apps/web/app/(app)/chat/layout.tsx", content: "…" })).toEqual({
      key: "fs_write",
      params: { file: "layout.tsx" },
    });
    expect(approvalOp("github_write_file", { repo: "mmeirbek/moloko", path: "a/b/page-header.tsx" }).params).toEqual({
      file: "page-header.tsx",
      repo: "mmeirbek/moloko",
    });
    expect(approvalOp("weird_tool", {})).toEqual({ key: "other", params: { tool: "weird tool" } });
    expect(approvalOp("terminal_run", { command: "npm ci", network: "packages" })).toEqual({
      key: "terminal_run_packages",
      params: { program: "npm" },
    });
    expect(approvalOp("terminal_run", { command: "$(x)", network: "packages" }).key).toBe("terminal_run_packages_plain");
    expect(approvalOp("github_checkout", { repo: "mmeirbek/moloko", ref: "main" })).toEqual({
      key: "github_checkout",
      params: { repo: "mmeirbek/moloko" },
    });
    expect(approvalOp("github_commit_files", { repo: "mmeirbek/moloko", branch: "ui", paths: ["a", "b"] })).toEqual({
      key: "github_commit_files",
      params: { repo: "mmeirbek/moloko", branch: "ui" },
    });
    expect(shortText("[[mock:sleep:1]] Отчёт ```py\nprint(1)\n```")).toBe("Отчёт");
    expect(shortText("слово ".repeat(40)).endsWith("…")).toBe(true);
  });

  it("groups one task's approvals and keeps the agent", () => {
    const n = noticeFor(
      ev("approval.required", {
        approval: { id: "a", summary: "Run: python3 -c ...", tool_name: "terminal_run", args: { command: "python3 -V" }, agent_name: "Кодер", task_id: "t1" },
      }),
      now,
    );
    expect(n).toMatchObject({ agentName: "Кодер", tag: "approval:task:t1", op: { key: "terminal_run" } });
  });
});
