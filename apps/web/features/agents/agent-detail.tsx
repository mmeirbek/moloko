"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Pause, Play, Send, Square, Trash2 } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useErrorMessage } from "@/features/auth/use-error-message";
import { MemoryPanel } from "@/features/memory/memory-panel";
import { agentAction, agentKeys, deleteAgent, getAgent, listAgentTasks, runAgent, taskKeys } from "@/lib/api/agents";
import { ApiError } from "@/lib/api/errors";
import { memoryKeys } from "@/lib/api/memories";
import { useRealtimeStore } from "@/lib/realtime/store";
import { cn } from "@/lib/utils";

import { AgentForm } from "./agent-form";
import { StatusBadge } from "./status-badge";

const ACTIVE = new Set(["planning", "working", "waiting", "reviewing"]);
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
  const toMessage = useErrorMessage();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<Tab>("profile");
  const [taskTitle, setTaskTitle] = useState("");
  const agent = useQuery({ queryKey: agentKeys.detail(agentId), queryFn: ({ signal }) => getAgent(agentId, signal) });
  const liveAgent = useRealtimeStore((s) => s.agents[agentId]);
  const live = liveAgent ? { ...agent.data, ...liveAgent } : agent.data;
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
  const action = useMutation({
    mutationFn: (a: "pause" | "resume" | "stop") => agentAction(agentId, a),
    onSuccess: invalidate,
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
  if (!agent.data || !live) return <p className="text-sm text-muted-foreground">{td("loading")}</p>;

  if (agent.data.archived_at) {
    return (
      <div className="flex flex-col gap-4">
        <Link href="/office/agents" className="flex items-center gap-1 text-sm text-muted-foreground hover:underline">
          <ArrowLeft className="size-4" /> {td("back")}
        </Link>
        <h1 className="truncate text-2xl font-semibold">{agent.data.name}</h1>
        <p role="status" className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
          {td("archived")}
        </p>
        <AgentTasks agentId={agentId} />
      </div>
    );
  }

  const isSub = live.agent_type === "subagent";
  const busy = ACTIVE.has(live.status ?? "") || live.status === "paused" || Boolean(live.current_task_id);
  const error = run.error ?? action.error ?? remove.error;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-3">
        <Link href="/office/agents" className="flex items-center gap-1 text-sm text-muted-foreground hover:underline">
          <ArrowLeft className="size-4" /> {td("back")}
        </Link>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="truncate text-2xl font-semibold">{live.name}</h1>
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
        {!isSub && (
          <div className="flex flex-wrap items-center gap-2">
            {!busy && (
              <form
                className="flex min-w-64 flex-1 gap-2"
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
            {ACTIVE.has(live.status ?? "") && (
              <Button variant="outline" onClick={() => action.mutate("pause")}>
                <Pause /> {t("pause")}
              </Button>
            )}
            {(live.status === "paused" || task?.status === "waiting") && (
              <Button variant="outline" onClick={() => action.mutate("resume")}>
                <Play /> {t("resume")}
              </Button>
            )}
            {(busy || live.status === "failed") && (
              <Button variant="ghost" onClick={() => action.mutate("stop")}>
                <Square /> {t("stop")}
              </Button>
            )}
            {live.agent_type === "autonomous" && (
              <Button
                variant="ghost"
                className="text-destructive"
                disabled={busy || remove.isPending}
                title={busy ? td("deleteBusy") : undefined}
                onClick={() => {
                  if (window.confirm(td("deleteConfirm", { name: live.name ?? "" }))) remove.mutate();
                }}
              >
                <Trash2 /> {td("delete")}
              </Button>
            )}
          </div>
        )}
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {toMessage(error).message}
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
    </div>
  );
}
