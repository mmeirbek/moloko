"use client";

import type { TaskOut } from "@moloko/shared-types";
import { useQueries, useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";

import { ExternalLink, File, Network } from "@/components/icons";
import { Dialog } from "@/components/ui/dialog";
import { FileView } from "@/features/workspaces/file-browser";
import { taskToolCalls, taskWorkspace, toolingKeys } from "@/lib/api/tooling";

import { isEmpty, outcomeOf } from "./task-outcome-model";

const FILES_SHOWN = 12;

/**
 * «Что получилось» under the answer: the pull requests, commits and branches the agents made
 * and the files they wrote — each one tap away (owner: the answer, the files and the GitHub
 * links were hard to find).
 */
export function TaskOutcome({ task, parts }: { task: TaskOut; parts: TaskOut[] }) {
  const t = useTranslations("tasks.outcome");
  const ids = [task.id, ...parts.map((p) => p.id)];
  const results = useQueries({
    queries: ids.map((id) => ({
      queryKey: [...toolingKeys.taskCalls(id), task.status],
      queryFn: ({ signal }: { signal: AbortSignal }) => taskToolCalls(id, signal),
    })),
  });
  const workspace = useQuery({
    queryKey: [...toolingKeys.taskWorkspace(task.id), task.status],
    queryFn: ({ signal }) => taskWorkspace(task.id, signal),
  });
  const [open, setOpen] = useState<string | null>(null);
  const loaded = results.map((r) => r.dataUpdatedAt).join();
  const outcome = useMemo(
    () =>
      outcomeOf(results.flatMap((r) => r.data ?? []).sort((a, b) => a.created_at.localeCompare(b.created_at))),
    // `results` is a new array every render; `loaded` changes when any of them got new data.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [loaded],
  );
  if (isEmpty(outcome)) return null;
  const files = outcome.files.slice(-FILES_SHOWN);
  const link = "inline-flex max-w-full items-center gap-1.5 break-all underline underline-offset-2 hover:text-foreground";

  return (
    <section className="flex flex-col gap-2 bg-card p-4 text-sm pixel-frame" data-testid="task-outcome" aria-label={t("title")}>
      <h3 className="text-xs font-medium tracking-wide text-muted-foreground uppercase">{t("title")}</h3>
      <ul className="flex flex-col gap-1">
        {outcome.pullRequests.map((pr) => (
          <li key={pr.url}>
            <a href={pr.url} target="_blank" rel="noreferrer" className={link}>
              <ExternalLink className="size-3.5 shrink-0" aria-hidden /> {t("pullRequest", { number: pr.number, repo: pr.repo })}
            </a>
          </li>
        ))}
        {outcome.commits.map((c) => (
          <li key={c.url}>
            <a href={c.url} target="_blank" rel="noreferrer" className={link}>
              <ExternalLink className="size-3.5 shrink-0" aria-hidden /> {t("commit", { sha: c.sha, repo: c.repo, branch: c.branch || "—" })}
            </a>
          </li>
        ))}
        {outcome.branches.map((b) => (
          <li key={b.url}>
            <a href={b.url} target="_blank" rel="noreferrer" className={link}>
              <Network className="size-3.5 shrink-0" aria-hidden /> {t("branch", { branch: b.branch, repo: b.repo })}
            </a>
          </li>
        ))}
      </ul>
      {files.length > 0 && workspace.data && (
        <div className="flex flex-col gap-1">
          <p className="text-xs text-muted-foreground">{t("files", { count: outcome.files.length })}</p>
          <ul className="flex flex-wrap gap-1.5">
            {files.map((path) => (
              <li key={path}>
                <button
                  type="button"
                  onClick={() => setOpen(path)}
                  className="inline-flex max-w-full items-center gap-1.5 border-2 px-2 py-1 text-xs break-all hover:bg-accent"
                  title={path}
                >
                  <File className="size-3.5 shrink-0" aria-hidden /> {path.split("/").pop()}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      {open && workspace.data && (
        <Dialog open onClose={() => setOpen(null)} labelledBy="outcome-file" data-testid="outcome-file">
          <div className="flex max-h-[80dvh] flex-col gap-2 overflow-y-auto p-4">
            <p id="outcome-file" className="sr-only">
              {open}
            </p>
            <FileView workspaceId={workspace.data.id} path={open} onClose={() => setOpen(null)} />
          </div>
        </Dialog>
      )}
    </section>
  );
}
