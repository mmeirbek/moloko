"use client";

import type { TaskOut } from "@moloko/shared-types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Search } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import Link from "next/link";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { StatusBadge } from "@/features/agents/status-badge";
import { useErrorMessage } from "@/features/auth/use-error-message";
import { agentKeys, createTask, listAgents, listTasks, taskKeys } from "@/lib/api/agents";
import { useRealtimeStore } from "@/lib/realtime/store";
import { cn } from "@/lib/utils";
import { EmptyState } from "@/features/mascot/empty-state";

const FILTERS = ["all", "active", "completed", "failed", "cancelled"] as const;

function NewTaskForm({ onDone }: { onDone: () => void }) {
  const t = useTranslations("tasks");
  const toMessage = useErrorMessage();
  const queryClient = useQueryClient();
  const agents = useQuery({ queryKey: agentKeys.all, queryFn: ({ signal }) => listAgents(signal) });
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [agentId, setAgentId] = useState("");
  const create = useMutation({
    mutationFn: () =>
      createTask({ title: title.trim(), description, agent_id: agentId || null, start: Boolean(agentId) }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: taskKeys.all });
      onDone();
    },
  });
  const runnable = (agents.data ?? []).filter((a) => a.agent_type !== "subagent");

  function submit(e: FormEvent) {
    e.preventDefault();
    if (title.trim()) create.mutate();
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-3 rounded-lg border bg-card p-4">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="task-title">{t("title")}</Label>
        <Input id="task-title" value={title} onChange={(e) => setTitle(e.target.value)} autoFocus />
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="task-description">{t("description")}</Label>
        <textarea
          id="task-description"
          rows={4}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          className="rounded-md border border-input bg-background px-3 py-2 text-base md:text-sm"
        />
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="task-agent">{t("agent")}</Label>
        <select
          id="task-agent"
          value={agentId}
          onChange={(e) => setAgentId(e.target.value)}
          className="h-10 rounded-md border border-input bg-background px-2 text-sm"
        >
          <option value="">{t("noAgent")}</option>
          {runnable.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>
        {runnable.length === 0 && (
          <p className="text-xs text-muted-foreground">
            {t("noAgentsYet")}{" "}
            <Link href="/office/agents" className="underline">
              {t("createAgent")}
            </Link>
          </p>
        )}
      </div>
      {create.error && <p role="alert" className="text-sm text-destructive">{toMessage(create.error).message}</p>}
      <div className="flex gap-2">
        <Button type="submit" disabled={!title.trim() || create.isPending}>
          {agentId ? t("createAndStart") : t("create")}
        </Button>
        <Button type="button" variant="ghost" onClick={onDone}>
          {t("cancelForm")}
        </Button>
      </div>
    </form>
  );
}

function TaskRow({ task }: { task: TaskOut }) {
  const live = useRealtimeStore((s) => s.tasks[task.id]) ?? task;
  const agentName = useRealtimeStore((s) => (live.agent_id ? s.agents[live.agent_id]?.name : undefined));
  const format = useFormatter();
  return (
    <li>
      <Link
        href={`/tasks/${task.id}`}
        className="flex items-center justify-between gap-3 rounded-md px-3 py-3 hover:bg-accent/60"
      >
        <div className="min-w-0">
          <p className="truncate font-medium">{live.title}</p>
          <p className="truncate text-xs text-muted-foreground">
            {agentName ?? "—"} · {format.relativeTime(new Date(live.created_at))}
            {live.attempt > 1 && ` · #${live.attempt}`}
          </p>
        </div>
        <StatusBadge status={live.status} />
      </Link>
    </li>
  );
}

export function TasksView() {
  const t = useTranslations("tasks");
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>("all");
  const [q, setQ] = useState("");
  const [creating, setCreating] = useState(false);
  const tasks = useQuery({
    queryKey: taskKeys.list(filter, q),
    queryFn: ({ signal }) => listTasks(filter, q, signal),
  });

  return (
    <div className="flex max-w-3xl flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div role="tablist" aria-label={t("filter")} className="flex flex-wrap gap-1">
          {FILTERS.map((f) => (
            <button
              key={f}
              role="tab"
              aria-selected={filter === f}
              onClick={() => setFilter(f)}
              className={cn(
                "rounded-full px-3 py-1 text-sm",
                filter === f ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-accent",
              )}
            >
              {t(`filters.${f}`)}
            </button>
          ))}
        </div>
        {!creating && (
          <Button onClick={() => setCreating(true)}>
            <Plus /> {t("new")}
          </Button>
        )}
      </div>
      {creating && <NewTaskForm onDone={() => setCreating(false)} />}
      <div className="relative">
        <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          type="search"
          aria-label={t("search")}
          placeholder={t("search")}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          className="pl-9"
        />
      </div>
      <ul className="divide-y rounded-lg border bg-card">
        {tasks.data?.items.map((task) => <TaskRow key={task.id} task={task} />)}
        {tasks.data?.items.length === 0 && (
          <li>
            <EmptyState title={t("empty")} mood="sleep" />
          </li>
        )}
      </ul>
    </div>
  );
}
