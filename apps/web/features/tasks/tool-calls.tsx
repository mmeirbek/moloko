"use client";

import type { ToolCallOut } from "@moloko/shared-types";
import { useQuery } from "@tanstack/react-query";
import { useFormatter, useTranslations } from "next-intl";
import { useMemo } from "react";

import { ApprovalCard, CategoryBadge } from "@/features/approvals/approval-card";
import { FileBrowser } from "@/features/workspaces/file-browser";
import { taskToolCalls, taskWorkspace, toolingKeys } from "@/lib/api/tooling";
import { useRealtimeStore } from "@/lib/realtime/store";
import { cn } from "@/lib/utils";

const STATUS_TONE: Record<string, string> = {
  succeeded: "text-grass",
  failed: "text-destructive",
  denied: "text-destructive",
  rejected: "text-destructive",
  expired: "text-muted-foreground",
  unknown: "text-amber-700 dark:text-amber-300",
  awaiting_approval: "text-amber-700 dark:text-amber-300",
  running: "text-sky",
  pending: "text-muted-foreground",
};

function CallItem({ call }: { call: ToolCallOut }) {
  const t = useTranslations("tools.calls");
  const format = useFormatter();
  return (
    <li className="flex flex-col gap-1 py-3" data-tool-call={call.tool_name}>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-mono text-xs">{call.tool_name}</span>
        {call.category && <CategoryBadge category={call.category} />}
        <span className={cn("text-xs font-medium", STATUS_TONE[call.status])}>
          {t(`status.${call.status as "succeeded"}`)}
        </span>
        {call.duration_ms !== null && (
          <span className="text-xs text-muted-foreground">
            {format.number(call.duration_ms, { style: "unit", unit: "millisecond", unitDisplay: "short" })}
          </span>
        )}
      </div>
      {call.decision_reason && call.decision !== "allow" && (
        <p className="text-xs text-muted-foreground">{call.decision_reason}</p>
      )}
      <details className="text-xs">
        <summary className="cursor-pointer text-muted-foreground">{t("details")}</summary>
        <pre className="mt-1 max-h-48 overflow-auto rounded bg-muted p-2 whitespace-pre-wrap break-all">
          {JSON.stringify(call.args, null, 2)}
        </pre>
        {call.result && (
          <pre className="mt-1 max-h-64 overflow-auto rounded bg-muted p-2 whitespace-pre-wrap break-all">
            {call.result}
          </pre>
        )}
      </details>
    </li>
  );
}

/** Spec 16: commands run, files created/changed, errors and results of this task. */
export function TaskToolActivity({ taskId, status }: { taskId: string; status: string }) {
  const t = useTranslations("tools.calls");
  const all = useRealtimeStore((s) => s.approvals); // stable reference; derive outside the selector
  const approvals = useMemo(
    () => Object.values(all).filter((a) => a.task_id === taskId && a.status === "pending"),
    [all, taskId],
  );
  const calls = useQuery({
    queryKey: [...toolingKeys.taskCalls(taskId), status, approvals.length],
    queryFn: ({ signal }) => taskToolCalls(taskId, signal),
  });
  const workspace = useQuery({
    queryKey: [...toolingKeys.taskWorkspace(taskId), status],
    queryFn: ({ signal }) => taskWorkspace(taskId, signal),
  });
  return (
    <>
      {approvals.map((a) => (
        <ApprovalCard key={a.id} approval={a} />
      ))}
      {calls.data && calls.data.length > 0 && (
        <section aria-labelledby={`calls-${taskId}`}>
          <h2 id={`calls-${taskId}`} className="mb-1 font-medium">
            {t("title", { count: calls.data.length })}
          </h2>
          <ul className="divide-y rounded-lg border bg-card px-4">
            {calls.data.map((c) => (
              <CallItem key={c.id} call={c} />
            ))}
          </ul>
        </section>
      )}
      {workspace.data && (
        <section aria-label={t("workspace")} className="rounded-lg border bg-card p-4">
          <h2 className="mb-2 font-medium">{t("workspace")}</h2>
          <FileBrowser workspaceId={workspace.data.id} />
        </section>
      )}
    </>
  );
}
