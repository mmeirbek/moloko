"use client";

import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useMemo } from "react";

import { ApprovalCard } from "@/features/approvals/approval-card";
import { FileBrowser } from "@/features/workspaces/file-browser";
import { taskWorkspace, toolingKeys } from "@/lib/api/tooling";
import { useRealtimeStore } from "@/lib/realtime/store";

/** Spec 16: what waits for the owner's approval, and the files of this task (the commands
 *  and their results are in the agent's steps, agent-steps.tsx). */
export function TaskToolActivity({ taskId, status }: { taskId: string; status: string }) {
  const t = useTranslations("tools.calls");
  const all = useRealtimeStore((s) => s.approvals); // stable reference; derive outside the selector
  const approvals = useMemo(
    () => Object.values(all).filter((a) => a.task_id === taskId && a.status === "pending"),
    [all, taskId],
  );
  const workspace = useQuery({
    queryKey: [...toolingKeys.taskWorkspace(taskId), status],
    queryFn: ({ signal }) => taskWorkspace(taskId, signal),
  });
  return (
    <>
      {approvals.map((a) => (
        <ApprovalCard key={a.id} approval={a} />
      ))}
      {workspace.data && (
        <section aria-label={t("workspace")} className="bg-card p-4 pixel-frame">
          <h2 className="mb-2 font-medium">{t("workspace")}</h2>
          <FileBrowser workspaceId={workspace.data.id} />
        </section>
      )}
    </>
  );
}
