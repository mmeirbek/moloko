"use client";

import type { EventOut } from "@moloko/shared-types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, RotateCcw, Square } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { TaskToolActivity } from "@/features/tasks/tool-calls";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/features/agents/status-badge";
import { MilkBottle } from "@/features/mascot/milk-bottle";
import { ExportMenu } from "@/features/tasks/export-menu";
import { useErrorMessage } from "@/features/auth/use-error-message";
import { MarkdownBody } from "@/features/chat/markdown";
import { cancelTask, getTask, retryTask, taskEvents, taskKeys } from "@/lib/api/agents";
import { useRealtimeStore } from "@/lib/realtime/store";

const ACTIVE = new Set(["created", "queued", "running", "waiting", "waiting_approval"]);

function describe(e: EventOut, t: ReturnType<typeof useTranslations<"tasks">>, ts: (status: string) => string): string {
  const p = e.payload as Record<string, unknown>;
  switch (e.type) {
    case "agent.status_changed":
      return t("ev.agentStatus", { status: ts(String(p.new_status)) });
    case "task.created":
      return t("ev.created");
    case "task.updated":
      return t("ev.taskStatus", { status: ts(String(p.new_status ?? p.reason ?? "")) });
    case "task.completed":
      return t("ev.completed");
    case "task.failed":
      return t("ev.failed");
    case "task.cancelled":
      return t("ev.cancelled");
    case "agent.task_started":
      return t("ev.started");
    case "agent.message":
      if (p.kind === "tool_call") return t("ev.tool", { tool: String(p.tool), status: String(p.status) });
      if (p.kind === "plan") return t("ev.plan");
      if (p.kind === "agent_to_agent") return t("ev.agentMessage");
      return t("ev.step", { step: Number(p.step ?? 0) });
    case "agent.task_completed":
      return t("ev.agentDone");
    case "agent.task_failed":
      return t("ev.agentFailed");
    case "approval.required":
      return t("ev.approvalRequired", {
        tool: String((p.approval as { tool_name?: string } | undefined)?.tool_name ?? ""),
      });
    case "approval.resolved":
      return t("ev.approvalResolved", {
        status: String((p.approval as { status?: string } | undefined)?.status ?? ""),
      });
    default:
      return e.type;
  }
}

export function TaskDetailView({ taskId }: { taskId: string }) {
  const t = useTranslations("tasks");
  const tc = useTranslations("common");
  const tStatus = useTranslations("status");
  const ts = (status: string) => {
    const key = status as Parameters<typeof tStatus>[0];
    return tStatus.has(key) ? tStatus(key).toLowerCase() : status;
  };
  const format = useFormatter();
  const router = useRouter();
  const toMessage = useErrorMessage();
  const queryClient = useQueryClient();
  const detail = useQuery({ queryKey: taskKeys.detail(taskId), queryFn: ({ signal }) => getTask(taskId, signal) });
  const events = useQuery({ queryKey: taskKeys.events(taskId), queryFn: ({ signal }) => taskEvents(taskId, signal) });
  const live = useRealtimeStore((s) => s.tasks[taskId]);
  const task = live ?? detail.data?.task;
  const agentName = useRealtimeStore((s) => (task?.agent_id ? s.agents[task.agent_id]?.name : undefined));
  const lastMessage = useRealtimeStore((s) => (task?.run_id ? s.lastMessage[task.run_id] : undefined));

  const invalidate = () => void queryClient.invalidateQueries({ queryKey: taskKeys.all });
  const cancel = useMutation({ mutationFn: () => cancelTask(taskId), onSuccess: invalidate });
  const retry = useMutation({
    mutationFn: () => retryTask(taskId),
    onSuccess: (created) => {
      invalidate();
      router.push(`/tasks/${created.id}`);
    },
  });
  const error = cancel.error ?? retry.error;

  if (!task) return <p className="text-sm text-muted-foreground">{tc("loading")}</p>;
  const run = detail.data?.run;

  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <Link href="/tasks" className="inline-flex items-center gap-1 text-sm text-muted-foreground">
        <ArrowLeft className="size-4" /> {t("allTasks")}
      </Link>
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-semibold tracking-tight">{task.title}</h1>
          <StatusBadge status={task.status} />
          {(task.progress > 0 || task.status === "completed") && (
            <MilkBottle percent={task.progress} done={task.status === "completed"} size={20} />
          )}
        </div>
        <p className="text-sm text-muted-foreground">
          {agentName ?? t("noAgent")}
          {task.attempt > 1 && ` · ${t("attempt", { n: task.attempt })}`}
          {run && ` · ${t("steps", { n: run.steps })}`}
          {run?.usage?.output_tokens != null && ` · ${t("tokens", { n: Number(run.usage.output_tokens) })}`}
        </p>
        {task.description && <p className="text-sm whitespace-pre-wrap">{task.description}</p>}
        <div className="flex gap-2">
          {ACTIVE.has(task.status) && (
            <Button variant="outline" size="sm" onClick={() => cancel.mutate()} disabled={cancel.isPending}>
              <Square /> {t("cancel")}
            </Button>
          )}
          {(task.status === "failed" || task.status === "cancelled") && !task.parent_task_id && (
            <Button size="sm" onClick={() => retry.mutate()} disabled={retry.isPending}>
              <RotateCcw /> {t("retry")}
            </Button>
          )}
        </div>
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {toMessage(error).message}
          </p>
        )}
      </div>

      {task.status === "running" && lastMessage?.text && (
        <section className="rounded-lg border bg-card p-4">
          <h2 className="mb-2 text-sm font-medium text-muted-foreground">
            {t("latestStep", { step: lastMessage.step })}
          </h2>
          <MarkdownBody text={lastMessage.text} />
        </section>
      )}
      {task.result && (
        <section className="print-area rounded-lg border bg-card p-4">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-medium text-muted-foreground">{t("result")}</h2>
            <ExportMenu taskId={task.id} title={task.title} />
          </div>
          <MarkdownBody text={task.result} />
        </section>
      )}
      {task.status === "failed" && (
        <section role="alert" className="rounded-lg border border-destructive/40 bg-destructive/10 p-4 text-sm">
          <p>{task.error_message}</p>
          <p className="mt-1 font-mono text-xs text-muted-foreground">
            {task.error_code} · {tc("errorId", { id: task.error_id ?? "—" })}
          </p>
        </section>
      )}
      {task.status === "waiting" && task.status_reason === "unknown_outcome" && (
        <section role="alert" className="rounded-lg border border-amber-400/50 bg-amber-400/10 p-4 text-sm">
          {t("unknownOutcome")}
        </section>
      )}

      <TaskToolActivity taskId={task.id} status={task.status} />

      {detail.data && detail.data.subtasks.length > 0 && (
        <section>
          <h2 className="mb-2 font-medium">{t("subtasks")}</h2>
          <ul className="divide-y rounded-lg border bg-card">
            {detail.data.subtasks.map((s) => (
              <li key={s.id}>
                <Link
                  href={`/tasks/${s.id}`}
                  className="flex items-center justify-between gap-2 px-3 py-2 hover:bg-accent/60"
                >
                  <span className="truncate text-sm">{s.title}</span>
                  <StatusBadge status={s.status} />
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section>
        <h2 className="mb-2 font-medium">{t("history")}</h2>
        <ol className="flex flex-col gap-1 border-l pl-4 text-sm">
          {events.data?.map((e) => (
            <li key={e.id} className="relative">
              <span className="absolute top-2 -left-[21px] size-2 rounded-full bg-border" aria-hidden="true" />
              <span className="text-muted-foreground tabular-nums">
                {format.dateTime(new Date(e.timestamp), { timeStyle: "medium" })}
              </span>{" "}
              {describe(e, t, ts)}
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
