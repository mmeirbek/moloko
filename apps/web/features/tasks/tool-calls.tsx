"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import { ApprovalCard } from "@/features/approvals/approval-card";
import { FileBrowser } from "@/features/workspaces/file-browser";
import { taskWorkspace, toolingKeys } from "@/lib/api/tooling";
import { useRealtimeStore } from "@/lib/realtime/store";

/** What waits for the owner's approval in these tasks (the task and its parts), in the chat. */
export function TaskApprovals({ taskIds }: { taskIds: string[] }) {
  const all = useRealtimeStore((s) => s.approvals); // stable reference; derive outside the selector
  const key = taskIds.join(",");
  const approvals = useMemo(() => {
    const ids = new Set(key.split(","));
    return Object.values(all).filter((a) => ids.has(a.task_id) && a.status === "pending");
  }, [all, key]);
  return (
    <>
      {approvals.map((a) => (
        <ApprovalCard key={a.id} approval={a} />
      ))}
    </>
  );
}

/** Spec 16: the files of this task's workspace (the commands and their results are in the
 *  agent's steps, agent-steps.tsx). */
export function TaskWorkspace({ taskId, status }: { taskId: string; status: string }) {
  const workspace = useQuery({
    queryKey: [...toolingKeys.taskWorkspace(taskId), status],
    queryFn: ({ signal }) => taskWorkspace(taskId, signal),
  });
  if (!workspace.data) return null;
  return <FileBrowser workspaceId={workspace.data.id} />;
}
