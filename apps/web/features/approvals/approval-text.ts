import type { ApprovalOut } from "@moloko/shared-types";

/** Parameters for the localized description of a built-in operation. */
export function opParams(approval: Pick<ApprovalOut, "tool_name" | "args">): Record<string, string> | null {
  const a = approval.args as Record<string, unknown>;
  const s = (k: string) => (a[k] === undefined || a[k] === null ? "" : String(a[k]));
  switch (approval.tool_name) {
    case "fs_write":
      return { path: s("path"), chars: String(s("content").length), mode: s("mode") || "overwrite" };
    case "fs_move":
      return { source: s("source"), destination: s("destination") };
    case "fs_delete":
      return { path: s("path") };
    case "terminal_run":
      return { command: s("command") };
    case "github_create_branch":
      return { repo: s("repo"), branch: s("branch") };
    case "github_write_file":
      return { repo: s("repo"), branch: s("branch"), path: s("path"), message: s("message") };
    case "github_create_pull_request":
      return { repo: s("repo"), head: s("head"), base: s("base"), title: s("title") };
    case "memory_save":
      return { title: s("title") };
    default:
      return null;
  }
}

export type ReasonKey = "override" | "sensitive" | "write" | null;

export function reasonKey(approval: Pick<ApprovalOut, "reason" | "category">): ReasonKey {
  if (approval.reason.includes("approve every use")) return "override";
  if (approval.category === "sensitive") return "sensitive";
  if (approval.category === "write") return "write";
  return null;
}
