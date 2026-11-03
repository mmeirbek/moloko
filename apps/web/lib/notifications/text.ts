/**
 * Notification wording: who, and what in plain words — never a raw command, file contents
 * or a long path. The same rules as the server's pushes (apps/api/app/push/texts.py).
 */

const TITLE_MAX = 90;

/** One readable line: no code blocks or [[markers]], whitespace collapsed, cut at a word. */
export function shortText(text: string, limit = TITLE_MAX): string {
  const clean = (text || "")
    .replace(/```[\s\S]*?(```|$)/g, " ")
    .replace(/\[\[[^\]]*\]\]/g, " ")
    .replace(/[`#]/g, " ")
    .split(/\s+/)
    .filter(Boolean)
    .join(" ");
  if (clean.length <= limit) return clean;
  let cut = clean.slice(0, limit - 1);
  const space = cut.lastIndexOf(" ");
  if (space > limit / 2) cut = cut.slice(0, space);
  return `${cut.replace(/[ ,.;:—-]+$/, "")}…`;
}

const SUMMARY_MAX = 200; // a task's short result in the notification text
export const TASK_IN_TITLE_MAX = 60;
const FENCES = /```[\s\S]*?(```|$)/g;

/** The start of an agent's answer as one readable line (the short result of a task). */
export function resultSummary(text: string, limit = SUMMARY_MAX): string {
  const plain = (text || "")
    .replace(FENCES, " ")
    .replace(/\*\*|__/g, "")
    .replace(/^\s*(?:[-*>]|\d+[.)])\s+|\|/gm, " ");
  const withoutHeadings = plain.replace(/^\s*#.*$/gm, " ");
  return shortText(withoutHeadings.trim() ? withoutHeadings : plain, limit);
}

/** The question an answer ends with («Уточните, какой сайт?») — the agent waits for the
 *  owner's reply — or "" when the answer does not end with a question. */
export function ownerQuestion(text: string): string {
  const paragraphs = (text || "")
    .replace(FENCES, " ")
    .split(/\n\s*\n/)
    .filter((p) => p.trim());
  const last = paragraphs.at(-1);
  if (!last) return "";
  return last.replace(/[*_»")\s]+$/, "").endsWith("?") ? resultSummary(last) : "";
}

const fileName = (path: unknown) => shortText(String(path ?? "").trim().split("/").pop() ?? "", 50) || "?";

function program(command: unknown): string {
  const first = String(command ?? "").trim().split(/\s+/)[0] ?? "";
  const word = first.split("/").pop() ?? "";
  return /^[A-Za-z0-9_.+-]{1,24}$/.test(word) ? word : "";
}

/** `notifications.ops.<key>` and its params for what an agent asks to do. */
export function approvalOp(tool: string, args: Record<string, unknown> | undefined): { key: string; params: Record<string, string> } {
  const a = args ?? {};
  const s = (k: string, max = 60) => shortText(String(a[k] ?? ""), max);
  switch (tool) {
    case "fs_write":
      return { key: a.mode === "append" ? "fs_append" : "fs_write", params: { file: fileName(a.path) } };
    case "fs_append":
    case "fs_delete":
      return { key: tool, params: { file: fileName(a.path) } };
    case "fs_move":
      return { key: tool, params: { file: fileName(a.source) } };
    case "terminal_run": {
      const p = program(a.command);
      const key = a.network === "packages" ? "terminal_run_packages" : "terminal_run";
      return p ? { key, params: { program: p } } : { key: `${key}_plain`, params: {} };
    }
    case "github_checkout":
      return { key: tool, params: { repo: s("repo") } };
    case "github_create_branch":
      return { key: tool, params: { branch: s("branch", 40), repo: s("repo") } };
    case "github_write_file":
      return { key: tool, params: { file: fileName(a.path), repo: s("repo") } };
    case "github_commit_files":
      return { key: tool, params: { repo: s("repo"), branch: s("branch", 40) } };
    case "github_create_pull_request":
      return { key: tool, params: { repo: s("repo") } };
    case "memory_save":
      return { key: tool, params: { title: s("title") } };
    case "browser_screenshot": {
      let host = "";
      try {
        host = new URL(String(a.url ?? "")).hostname;
      } catch {
        host = s("url", 40);
      }
      return { key: tool, params: { host } };
    }
    case "agent_ask":
    case "agent_tell":
      return { key: tool, params: { agent: s("agent", 40) } };
    default:
      return { key: "other", params: { tool: shortText(tool.replaceAll("_", " "), 40) } };
  }
}
