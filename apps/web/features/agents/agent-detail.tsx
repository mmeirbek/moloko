"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Send, Trash2 } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useConfirm } from "@/components/ui/confirm";
import { useErrorMessage } from "@/features/auth/use-error-message";
import { MemoryPanel } from "@/features/memory/memory-panel";
import { agentKeys, deleteAgent, getAgent, listAgentTasks, runAgent, taskKeys } from "@/lib/api/agents";
import { ApiError } from "@/lib/api/errors";
import { memoryKeys } from "@/lib/api/memories";
import { useRealtimeStore } from "@/lib/realtime/store";
import { cn } from "@/lib/utils";
import { ErrorState, LoadingState } from "@/features/system/query-state";
import { useDocumentTitle } from "@/lib/hooks";

import { AgentControls, isAgentBusy } from "./agent-controls";
import { AgentForm } from "./agent-form";
import { StatusBadge } from "./status-badge";

const TABS = ["profile", "memory", "tasks"] as const;
type Tab = (typeof TABS)[number];

function AgentTasks({ agentId }: { agentId: string }) {
  const t = useTranslations("agents.detail");
  const format = useFormatter();
  const tasks = useQuery({
    queryKey: agentKeys.tasks(agentId),
    queryFn: ({ signal }) => listAgentTasks(agentId, signal),
  });
  const live = useRealtimeStore((s) => s.tasks);
  if (tasks.data?.items.length === 0)
    return (
      <p className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">{t("noTasks")}</p>
    );
  return (
    <ul className="flex flex-col divide-y rounded-lg border bg-card" aria-label={t("tasks")}>
      {tasks.data?.items.map((task) => {
        const current = live[task.id] ?? task;
        return (
          <li key={task.id}>
            <Link
              href={`/tasks/${task.id}`}
              className="flex items-center justify-between gap-3 px-4 py-3 text-sm hover:bg-accent"
            >
              <span className="min-w-0">
                <span className="block truncate font-medium">{current.title}</span>
                <span className="text-xs text-muted-foreground">
                  {format.dateTime(new Date(task.created_at), { dateStyle: "short", timeStyle: "short" })}
                  {current.error_message ? ` · ${current.error_message}` : ""}
                </span>
              </span>
              <StatusBadge status={current.status} />
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

export function AgentDetail({ agentId }: { agentId: string }) {
  const t = useTranslations("agents");
  const td = useTranslations("agents.detail");
  const confirm = useConfirm();
  const toMessage = useErrorMessage();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<Tab>("profile");
  const [taskTitle, setTaskTitle] = useState("");
  const agent = useQuery({ queryKey: agentKeys.detail(agentId), queryFn: ({ signal }) => getAgent(agentId, signal) });
  const liveAgent = useRealtimeStore((s) => s.agents[agentId]);
  const live = liveAgent ? { ...agent.data, ...liveAgent } : agent.data;
  useDocumentTitle(live?.name);
  const task = useRealtimeStore((s) => (live?.current_task_id ? s.tasks[live.current_task_id] : undefined));

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: agentKeys.all });
    void queryClient.invalidateQueries({ queryKey: taskKeys.all });
  };
  const run = useMutation({
    mutationFn: () => runAgent(agentId, { title: taskTitle.trim(), description: "" }),
    onSuccess: () => {
      setTaskTitle("");
      invalidate();
    },
  });
  const remove = useMutation({
    mutationFn: () => deleteAgent(agentId),
    onSuccess: () => {
      invalidate();
      void queryClient.invalidateQueries({ queryKey: memoryKeys.all });
      router.push("/office/agents");
    },
  });

  if (agent.error instanceof ApiError && agent.error.status === 404) {
    return (
      <div className="flex flex-col items-start gap-3">
        <p className="text-sm text-muted-foreground">{td("notFound")}</p>
        <Button variant="outline" asChild>
          <Link href="/office/agents">
            <ArrowLeft /> {td("back")}
          </Link>
        </Button>
      </div>
    );
  }
  if (!agent.data || !live)
    return agent.isError ? <ErrorState error={agent.error} onRetry={() => agent.refetch()} /> : <LoadingState />;

  if (agent.data.archived_at) {
    return (
      <div className="flex flex-col gap-4">
        <Link href="/office/agents" className="flex items-center gap-1 text-sm text-muted-foreground hover:underline">
          <ArrowLeft className="size-4" /> {td("back")}
        </Link>
        <h1 className="truncate font-sans text-2xl font-semibold">{agent.data.name}</h1>
        <p role="status" className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
          {td("archived")}
        </p>
        <AgentTasks agentId={agentId} />
      </div>
    );
  }

  const isSub = live.agent_type === "subagent";
  const busy = isAgentBusy({ status: live.status ?? "idle", current_task_id: live.current_task_id ?? null });

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-3">
        <Link href="/office/agents" className="flex items-center gap-1 text-sm text-muted-foreground hover:underline">
          <ArrowLeft className="size-4" /> {td("back")}
        </Link>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="truncate font-sans text-2xl font-semibold">{live.name}</h1>
            <p className="text-sm text-muted-foreground">
              {t(`types.${live.agent_type as "autonomous"}`)}
              {live.specialization ? ` · ${live.specialization}` : ""}
            </p>
          </div>
          <StatusBadge status={live.status ?? "idle"} />
        </div>
        {task && (
          <Link href={`/tasks/${task.id}`} className="truncate text-sm underline-offset-2 hover:underline">
            {t("currentTask")}: {task.title}
          </Link>
        )}
        {!isSub && !busy && (
          <form
            className="flex max-w-xl gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (taskTitle.trim()) run.mutate();
            }}
          >
            <Input
              aria-label={t("giveTask")}
              placeholder={t("giveTask")}
              value={taskTitle}
              onChange={(e) => setTaskTitle(e.target.value)}
            />
            <Button type="submit" disabled={!taskTitle.trim() || run.isPending}>
              <Send /> {t("start")}
            </Button>
          </form>
        )}
        {!isSub && (
          <AgentControls
            agent={{ id: agentId, name: live.name ?? "", status: live.status ?? "idle", current_task_id: live.current_task_id ?? null }}
            size="default"
          />
        )}
        {run.error && (
          <p role="alert" className="text-sm text-destructive">
            {toMessage(run.error).message}
          </p>
        )}
      </div>

      <div role="tablist" aria-label={td("sections")} className="flex gap-1 border-b">
        {TABS.map((name) => (
          <button
            key={name}
            role="tab"
            type="button"
            id={`agent-tab-${name}`}
            aria-selected={tab === name}
            aria-controls={`agent-panel-${name}`}
            onClick={() => setTab(name)}
            className={cn(
              "-mb-px border-b-2 px-3 py-2 text-sm",
              tab === name
                ? "border-primary font-medium"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {td(`tabs.${name}`)}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`agent-panel-${tab}`} aria-labelledby={`agent-tab-${tab}`}>
        {tab === "profile" &&
          (isSub ? (
            <p className="text-sm text-muted-foreground">{td("subagentReadOnly")}</p>
          ) : (
            <AgentForm agent={agent.data} onSaved={() => undefined} />
          ))}
        {tab === "memory" &&
          (isSub ? (
            <p className="text-sm text-muted-foreground">{td("subagentNoMemory")}</p>
          ) : (
            <MemoryPanel scope={{ agentId }} />
          ))}
        {tab === "tasks" && <AgentTasks agentId={agentId} />}
      </div>

      {live.agent_type === "autonomous" && (
        <section
          aria-labelledby="danger-title"
          className="flex flex-col items-start gap-2 rounded-lg border border-destructive/40 p-4 sm:flex-row sm:items-center sm:justify-between"
        >
          <div className="flex flex-col gap-0.5">
            <p id="danger-title" className="text-sm font-medium">
              {td("dangerTitle")}
            </p>
            <p className="text-sm text-muted-foreground">{busy ? td("deleteBusy") : td("dangerHint")}</p>
          </div>
          <Button
            variant="outline"
            className="border-destructive/50 text-destructive hover:bg-destructive/10 hover:text-destructive"
            disabled={busy || remove.isPending}
            onClick={async () => {
              const question = td("deleteConfirm", { name: live.name ?? "" });
              if (await confirm({ title: question, confirmLabel: td("delete"), destructive: true })) remove.mutate();
            }}
          >
            <Trash2 /> {td("delete")}
          </Button>
          {remove.error && (
            <p role="alert" className="text-sm text-destructive">
              {toMessage(remove.error).message}
            </p>
          )}
        </section>
      )}
    </div>
  );
}
