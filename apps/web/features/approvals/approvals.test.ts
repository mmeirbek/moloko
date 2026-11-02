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

  it("describes repository downloads, multi-file commits and package downloads in both languages", async () => {
    const { createTranslator } = await import("next-intl");
    const { opKey, opParams } = await import("./approval-text");
    const en = (await import("@/messages/en.json")).default;
    const ru = (await import("@/messages/ru.json")).default;
    const cases: [string, Record<string, unknown>, string, string][] = [
      ["github_checkout", { repo: "me/app" }, "github_checkout", "Download me/app (default branch) into the folder app/"],
      [
        "github_checkout",
        { repo: "me/app", ref: "dev", folder: "code/", overwrite: true },
        "github_checkout_overwrite",
        "Download me/app (dev) into code/, replacing files",
      ],
      [
        "github_commit_files",
        { repo: "me/app", branch: "ui", message: "Header", paths: ["a.ts", "b.ts"], delete: ["c.ts"] },
        "github_commit_files",
        "Commit to me/app@ui (files: 3): Header",
      ],
      ["terminal_run", { command: "npm ci", network: "packages" }, "terminal_run_packages", "Run with package downloads: npm ci"],
      ["terminal_run", { command: "npm test" }, "terminal_run", "Run: npm test"],
    ];
    for (const [tool, args, key, english] of cases) {
      const params = opParams({ tool_name: tool, args } as never)!;
      expect(opKey(tool, params)).toBe(key);
      const tEn = createTranslator({ locale: "en", messages: en, namespace: "approvals" });
      const tRu = createTranslator({ locale: "ru", messages: ru, namespace: "approvals" });
      expect(tEn(`ops.${key}.summary` as "ops.fs_write.summary", params)).toBe(english);
      expect(tRu(`ops.${key}.summary` as "ops.fs_write.summary", params)).not.toContain("{");
      expect(tRu(`ops.${key}.consequences` as "ops.fs_write.consequences")).toBeTruthy();
    }
    const tRu = createTranslator({ locale: "ru", messages: ru, namespace: "approvals" });
    expect(tRu("ops.github_checkout.summary", opParams({ tool_name: "github_checkout", args: { repo: "me/app" } } as never)!)).toBe(
      "Скачать me/app (ветка по умолчанию) в папку app/",
    );
  });

  it("says what a standing approval of package downloads allows", async () => {
    const { standingWhat } = await import("./standing-text");
    const t = (key: string, values?: Record<string, string>) => `${key}(${values?.scope ?? ""})`;
    expect(standingWhat(t, "terminal_run", ["packages:npm"])).toBe("terminal_run_packages(npm)");
    expect(standingWhat(t, "terminal_run", ["npm", "node"])).toBe("terminal_run(npm, node)");
    expect(standingWhat(t, "github_commit_files", ["me/app"])).toBe("github_commit_files(me/app)");
  });
});
