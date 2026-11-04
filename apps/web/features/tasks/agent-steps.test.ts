import { describe, expect, it } from "vitest";

import { outputPreview, stepLabel } from "./agent-steps";

describe("agent steps", () => {
  it("says in a few words what each tool call does", () => {
    expect(stepLabel("fs_write", { path: "moloko/apps/web/app/(app)/chat/layout.tsx", content: "…" })).toEqual({
      key: "fs_write",
      params: { file: "layout.tsx" },
    });
    // A command by what it is for (the command itself is one click away).
    expect(stepLabel("terminal_run", { command: 'python3 -c "\nprint(1)\n"' })).toEqual({
      key: "cmd_script",
      params: { program: "python3" },
    });
    expect(stepLabel("terminal_run", { command: "cd app && npm test" }).key).toBe("cmd_tests");
    expect(stepLabel("github_read_file", { repo: "me/app", path: "src/index.ts" }).params).toEqual({ file: "index.ts", repo: "me/app" });
    expect(stepLabel("web_fetch", { url: "https://example.org/a?b=1" }).params).toEqual({ host: "example.org" });
    expect(stepLabel("some_mcp_tool", {})).toEqual({ key: "other", params: { tool: "some mcp tool" } });
  });

  it("previews what a command printed, not just its exit code", () => {
    expect(outputPreview("terminal_run", "exit code 0\n--- stdout ---\nhi from sandbox\n")).toBe("hi from sandbox");
    expect(outputPreview("terminal_run", "exit code 1\n--- stderr ---\nTraceback: boom")).toBe("Traceback: boom");
    expect(outputPreview("terminal_run", "exit code 0")).toBe("exit code 0");
    expect(outputPreview("fs_read", "line one\nline two")).toBe("line one");
  });
});

describe("reads in a row", () => {
  const call = (id: string, tool: string, status = "succeeded") =>
    ({ id, tool_name: tool, status, is_error: false, args: { path: `${id}.ts` }, result: "x", step: 1 }) as never;
  it("are one line; the step running now stays its own", async () => {
    const { groupReads } = await import("./agent-steps");
    const items = [
      { kind: "tool", call: call("a", "fs_read") },
      { kind: "tool", call: call("b", "fs_read") },
      { kind: "tool", call: call("c", "fs_read") },
      { kind: "tool", call: call("d", "fs_write") },
      { kind: "tool", call: call("e", "fs_read") },
      { kind: "tool", call: call("f", "fs_read", "running") },
    ];
    const out = groupReads(items, (i) => (i as { call: never }).call);
    const label = (i: unknown) => {
      const item = i as { kind: string; calls?: unknown[]; call?: { id: string } };
      return item.kind === "group" ? `group:${item.calls!.length}` : item.call!.id;
    };
    expect(out.map(label)).toEqual([
      "group:3",
      "d",
      "e",
      "f",
    ]);
  });
});
