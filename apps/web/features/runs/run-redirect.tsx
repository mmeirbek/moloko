"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { ErrorState, LoadingState } from "@/features/system/query-state";
import { getRunTree, runKeys } from "@/lib/api/runs";

/** Opens the task of an Orchestrator run (its plan, parts and agents are on the task page). */
export function RunRedirect({ runId }: { runId: string }) {
  const router = useRouter();
  const run = useQuery({ queryKey: runKeys.tree(runId), queryFn: ({ signal }) => getRunTree(runId, signal) });
  const taskId = run.data?.task.id;
  useEffect(() => {
    if (taskId) router.replace(`/tasks/${taskId}`);
  }, [router, taskId]);
  return run.isError ? <ErrorState error={run.error} onRetry={() => run.refetch()} /> : <LoadingState />;
}
