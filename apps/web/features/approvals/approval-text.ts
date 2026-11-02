import type { ApprovalOut } from "@moloko/shared-types";

/** Long text for a one-line summary (the full arguments stay under «exact arguments»). */
const short = (text: string, max = 120) => (text.length > max ? `${text.slice(0, max - 1).trimEnd()}…` : text);

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
      return { command: s("command"), network: s("network") || "none" };
    case "github_checkout":
      return {
        repo: s("repo"),
        ref: s("ref") || "default",
        folder: s("folder").replace(/\/+$/, "") || (s("repo").split("/").pop() ?? ""),
        overwrite: a.overwrite === true ? "true" : "false",
      };
    case "github_create_branch":
      return { repo: s("repo"), branch: s("branch") };
    case "github_write_file":
      return { repo: s("repo"), branch: s("branch"), path: s("path"), message: s("message") };
    case "github_commit_files": {
      const count = (k: string) => (Array.isArray(a[k]) ? (a[k] as unknown[]).length : 0);
      return {
        repo: s("repo"),
        branch: s("branch"),
        count: String(count("paths") + count("delete")),
        message: short(s("message")),
      };
    }
    case "github_create_pull_request":
      return { repo: s("repo"), head: s("head"), base: s("base"), title: s("title") };
    case "memory_save":
      return { title: s("title") };
    case "browser_screenshot":
      return { url: s("url") };
    case "agent_ask":
      return { agent: s("agent"), request: short(s("request")) };
    case "agent_tell":
      return { agent: s("agent"), message: short(s("message")) };
    default:
      return null;
  }
}

/** Which `approvals.ops.<key>` describes the operation: some tools have variants. */
export function opKey(toolName: string, params: Record<string, string>): string {
  if (toolName === "fs_write" && params.mode === "append") return "fs_append";
  if (toolName === "terminal_run" && params.network === "packages") return "terminal_run_packages";
  if (toolName === "github_checkout" && params.overwrite === "true") return "github_checkout_overwrite";
  return toolName;
}

export type ReasonKey = "override" | "sensitive" | "write" | null;

export function reasonKey(approval: Pick<ApprovalOut, "reason" | "category">): ReasonKey {
  if (approval.reason.includes("approve every use")) return "override";
  if (approval.category === "sensitive") return "sensitive";
  if (approval.category === "write") return "write";
  return null;
}
