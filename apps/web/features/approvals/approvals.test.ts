import type { ApprovalOut, EventEnvelope, SnapshotFrame, ToolOut } from "@moloko/shared-types";
import { beforeEach, describe, expect, it } from "vitest";

import { groupTools } from "@/features/integrations/tools-section";
import { parseRepos } from "@/features/integrations/github-section";
import { summarizeDetails } from "@/features/settings/audit-log";
import { parentOf } from "@/features/workspaces/file-browser";
import { pendingApprovals, useRealtimeStore } from "@/lib/realtime/store";

import { minutesLeft } from "./time-left";

const approval = (id: string, status: string, created: string) =>
  ({ id, status, created_at: created, task_id: "t", agent_id: "a" }) as unknown as ApprovalOut;

function event(seq: number, type: string, payload: Record<string, unknown>): EventEnvelope {
  return {
    id: `e${seq}`,
    seq,
    type: type as EventEnvelope["type"],
    version: 1,
    timestamp: "",
    agent_id: null,
    task_id: null,
    run_id: "r",
    payload,
  };
}

describe("approvals in the realtime store", () => {
  beforeEach(() => useRealtimeStore.getState().reset());

  it("comes from the snapshot and follows required/resolved events", () => {
    const s = useRealtimeStore.getState();
    s.applySnapshot({
      type: "snapshot",
      seq: 1,
      agents: [],
      tasks: [],
      runs: [],
      approvals: [approval("b", "pending", "2")],
    } as SnapshotFrame);
    s.applyEvent(event(2, "approval.required", { approval: approval("a", "pending", "1") }));
    expect(pendingApprovals(useRealtimeStore.getState().approvals).map((a) => a.id)).toEqual(["a", "b"]);
    s.applyEvent(event(3, "approval.resolved", { approval: approval("a", "approved", "1") }));
    expect(pendingApprovals(useRealtimeStore.getState().approvals).map((a) => a.id)).toEqual(["b"]);
    expect(useRealtimeStore.getState().approvals.a!.status).toBe("approved");
  });

  it("tool-call progress events do not replace the latest step text", () => {
    const s = useRealtimeStore.getState();
    s.applySnapshot({ type: "snapshot", seq: 1, agents: [], tasks: [], runs: [], approvals: [] } as SnapshotFrame);
    s.applyEvent(event(2, "agent.message", { step: 1, text: "thinking" }));
    s.applyEvent(event(3, "agent.message", { kind: "tool_call", tool: "fs_read", status: "succeeded" }));
    expect(useRealtimeStore.getState().lastMessage.r).toEqual({ step: 1, text: "thinking" });
  });
});

describe("helpers", () => {
  it("minutes left never goes negative", () => {
    const now = Date.parse("2026-11-01T10:00:00Z");
    expect(minutesLeft("2026-11-01T10:30:00Z", now)).toBe(30);
    expect(minutesLeft("2026-11-01T10:00:20Z", now)).toBe(1);
    expect(minutesLeft("2026-11-01T09:00:00Z", now)).toBe(0);
  });

  it("groups tools in a stable order", () => {
    const tool = (name: string, group: string) => ({ name, group }) as ToolOut;
    const groups = groupTools([tool("m", "mcp"), tool("g", "github"), tool("f", "files"), tool("x", "custom")]);
    expect(groups.map(([g]) => g)).toEqual(["files", "github", "mcp", "custom"]);
  });

  it("parses repositories from lines or commas", () => {
    expect(parseRepos(" me/app,\nme/site  me/app ")).toEqual(["me/app", "me/site"]);
  });

  it("summarizes audit details", () => {
    expect(summarizeDetails({ tool: "fs_read", reason: null, changed: ["a"] })).toBe('tool: fs_read · changed: ["a"]');
  });

  it("goes up one folder", () => {
    expect(parentOf("a/b/c")).toBe("a/b");
    expect(parentOf("a")).toBe(".");
  });
});

describe("localized approval texts", () => {
  it("builds parameters for built-in operations and falls back for others", async () => {
    const { opParams, reasonKey } = await import("./approval-text");
    expect(opParams({ tool_name: "fs_write", args: { path: "a.md", content: "hello" } } as never)).toEqual({
      path: "a.md",
      chars: "5",
      mode: "overwrite",
    });
    expect(opParams({ tool_name: "mcp_x_y", args: {} } as never)).toBeNull();
    expect(reasonKey({ reason: "The owner wants to approve every use of this tool.", category: "read" } as never)).toBe(
      "override",
    );
    expect(reasonKey({ reason: "Sensitive actions always need approval.", category: "sensitive" } as never)).toBe(
      "sensitive",
    );
    expect(reasonKey({ reason: "x", category: "read" } as never)).toBeNull();
  });
});
