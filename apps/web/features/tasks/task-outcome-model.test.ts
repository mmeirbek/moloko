import type { ToolCallOut } from "@moloko/shared-types";
import { describe, expect, it } from "vitest";

import { isEmpty, outcomeOf } from "./task-outcome-model";

const call = (tool_name: string, args: Record<string, unknown>, result = "", status = "succeeded") =>
  ({ tool_name, args, result, status, is_error: false }) as ToolCallOut;

describe("what a task left behind", () => {
  it("collects pull requests, commits, branches and files", () => {
    const o = outcomeOf([
      call("github_create_branch", { repo: "me/app", branch: "fix-login" }, "Created branch fix-login from main."),
      call(
        "github_commit_files",
        { repo: "me/app", branch: "fix-login", files: [] },
        "Committed 3 file(s) to me/app@fix-login as one commit 1a2b3c4d5e. https://github.com/me/app/commit/1a2b3c4d5e6f",
      ),
      call("github_write_file", { repo: "me/app", branch: "fix-login", path: "a.ts" }, "Committed a.ts to fix-login (abcdef1234)."),
      call("github_create_pull_request", { repo: "me/app" }, "Opened pull request #12: https://github.com/me/app/pull/12"),
      call("fs_write", { path: "report.md", content: "…" }),
      call("fs_write", { path: "tmp.txt", content: "…" }),
      call("fs_delete", { path: "tmp.txt" }),
      call("fs_move", { source: "report.md", destination: "out/report.md" }),
      call("fs_write", { path: "never.txt" }, "", "failed"),
    ]);
    expect(o.pullRequests).toEqual([{ number: "12", url: "https://github.com/me/app/pull/12", repo: "me/app" }]);
    expect(o.commits).toEqual([
      { url: "https://github.com/me/app/commit/1a2b3c4d5e6f", sha: "1a2b3c4", repo: "me/app", branch: "fix-login" },
      { url: "https://github.com/me/app/commit/abcdef1234", sha: "abcdef1", repo: "me/app", branch: "fix-login" },
    ]);
    expect(o.branches).toEqual([{ url: "https://github.com/me/app/tree/fix-login", repo: "me/app", branch: "fix-login" }]);
    expect(o.files).toEqual(["out/report.md"]);
  });

  it("is empty when the agents only read", () => {
    expect(isEmpty(outcomeOf([call("fs_read", { path: "a" }, "x"), call("web_fetch", { url: "https://x.org" }, "y")]))).toBe(true);
  });
});
