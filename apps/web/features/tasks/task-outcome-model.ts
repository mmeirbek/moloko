import type { ToolCallOut } from "@moloko/shared-types";

/** What a task left behind, from what its agents actually did (owner: «трудно найти ответ,
 *  файлы, ссылки на GitHub»): pull requests, commits, branches, and files of the workspace. */
export interface Outcome {
  pullRequests: { url: string; number: string; repo: string }[];
  commits: { url: string; sha: string; repo: string; branch: string }[];
  branches: { url: string; repo: string; branch: string }[];
  /** Workspace files written (newest last), minus the ones deleted afterwards. */
  files: string[];
}

const ok = (c: ToolCallOut) => c.status === "succeeded" && !c.is_error;
const str = (v: unknown) => (typeof v === "string" ? v : "");
const REPO = /^[\w.-]+\/[\w.-]+$/;

/** Pure: tested. Calls in the order they ran. */
export function outcomeOf(calls: ToolCallOut[]): Outcome {
  const out: Outcome = { pullRequests: [], commits: [], branches: [], files: [] };
  const files = new Map<string, number>();
  let order = 0;
  for (const c of calls) {
    if (!ok(c)) continue;
    const a = c.args as Record<string, unknown>;
    const repo = REPO.test(str(a.repo)) ? str(a.repo) : "";
    const result = c.result ?? "";
    if (c.tool_name === "github_create_pull_request") {
      const m = /#(\d+):\s*(https:\/\/github\.com\/\S+)/.exec(result);
      if (m) out.pullRequests.push({ number: m[1]!, url: m[2]!, repo });
    } else if (c.tool_name === "github_commit_files" || c.tool_name === "github_write_file") {
      const link = /(https:\/\/github\.com\/\S+\/commit\/([0-9a-f]{7,40}))/.exec(result);
      const sha = link?.[2] ?? /\(([0-9a-f]{7,40})\)|commit ([0-9a-f]{7,40})/.exec(result)?.slice(1).find(Boolean);
      if (sha && repo) {
        out.commits.push({ url: link?.[1] ?? `https://github.com/${repo}/commit/${sha}`, sha: sha.slice(0, 7), repo, branch: str(a.branch) });
      }
    } else if (c.tool_name === "github_create_branch" && repo && str(a.branch)) {
      out.branches.push({ url: `https://github.com/${repo}/tree/${str(a.branch)}`, repo, branch: str(a.branch) });
    } else if (c.tool_name === "fs_write" || c.tool_name === "fs_append") {
      if (str(a.path)) files.set(str(a.path), order++);
    } else if (c.tool_name === "fs_move") {
      files.delete(str(a.source));
      if (str(a.destination)) files.set(str(a.destination), order++);
    } else if (c.tool_name === "fs_delete") {
      files.delete(str(a.path));
    }
  }
  out.files = [...files.entries()].sort((x, y) => x[1] - y[1]).map(([path]) => path.replace(/^\.\//, ""));
  return out;
}

export const isEmpty = (o: Outcome) => !o.pullRequests.length && !o.commits.length && !o.branches.length && !o.files.length;
