import { describe, expect, it } from "vitest";

import { outputPreview, stepLabel } from "./agent-steps";

describe("agent steps", () => {
  it("says in a few words what each tool call does", () => {
    expect(stepLabel("fs_write", { path: "moloko/apps/web/app/(app)/chat/layout.tsx", content: "…" })).toEqual({
      key: "fs_write",
      params: { file: "layout.tsx" },
    });
    expect(stepLabel("terminal_run", { command: 'python3 -c "\nprint(1)\n"' })).toEqual({
      key: "terminal_run",
      params: { command: 'python3 -c "' },
    });
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
