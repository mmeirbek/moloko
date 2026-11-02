/** What a standing approval («больше не спрашивать») lets an agent do, in plain words. */
import { useTranslations } from "next-intl";

type Translate = (key: string, values?: Record<string, string>) => string;

const BY_TOOL = new Set([
  "terminal_run",
  "fs_write",
  "fs_move",
  "fs_delete",
  "github_checkout",
  "github_create_branch",
  "github_write_file",
  "github_commit_files",
  "github_create_pull_request",
  "memory_save",
  "browser_screenshot",
  "agent_ask",
  "agent_tell",
]);

/** `scopes` come from the approval (`approval.always`) or one rule each on the agent page
 *  ("" = the whole tool). The keys take different params, hence the loose `t`. */
export function useStandingWhat(): (tool: string, scopes: string[]) => string {
  const t = useTranslations("approvals.always.scope") as unknown as Translate;
  return (tool, scopes) => standingWhat(t, tool, scopes);
}

/** A terminal_run scope with package downloads (network "packages"), as the server stores it. */
const PACKAGES = "packages:";

export function standingWhat(t: Translate, tool: string, scopes: string[]): string {
  if (tool === "terminal_run" && scopes.some((s) => s.startsWith(PACKAGES))) {
    const offline = scopes.filter((s) => s && !s.startsWith(PACKAGES));
    const online = scopes.filter((s) => s.startsWith(PACKAGES)).map((s) => s.slice(PACKAGES.length));
    const parts = [t("terminal_run_packages", { scope: online.join(", ") })];
    if (offline.length) parts.unshift(t("terminal_run", { scope: offline.join(", ") }));
    return parts.join("; ");
  }
  const scope = scopes.filter(Boolean).join(", ");
  if (BY_TOOL.has(tool)) return t(tool, { scope });
  return scope ? t("otherIn", { tool, scope }) : t("other", { tool });
}
