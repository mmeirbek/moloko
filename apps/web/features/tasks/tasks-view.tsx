"use client";

import type { TaskOut } from "@moloko/shared-types";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Search } from "lucide-react";
import { useFormatter, useNow, useTranslations } from "next-intl";
import Link from "next/link";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { StatusBadge } from "@/features/agents/status-badge";
import { useErrorMessage } from "@/features/auth/use-error-message";
import { agentKeys, createTask, listAgents, listTasks, taskKeys } from "@/lib/api/agents";
import { useDebounced } from "@/lib/hooks";
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

function TaskRow({ task, now }: { task: TaskOut; now: Date }) {
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
            {agentName ?? "—"} · {format.relativeTime(new Date(live.created_at), now)}
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
  const tc = useTranslations("common");
  const toMessage = useErrorMessage();
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>("all");
  const [q, setQ] = useState("");
  const query = useDebounced(q.trim());
  const [creating, setCreating] = useState(false);
  const now = useNow({ updateInterval: 60_000 }); // "5 minutes ago" stays true
  const tasks = useQuery({
    queryKey: taskKeys.list(filter, query),
    queryFn: ({ signal }) => listTasks(filter, query, signal),
    placeholderData: keepPreviousData, // no blank list while the next filter or search loads
  });

  return (
    <div className="flex max-w-3xl flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        {/* One scrollable row on phones instead of wrapping onto a second line. */}
        <div
          role="group"
          aria-label={t("filter")}
          className="-mx-4 flex max-w-[calc(100%+2rem)] gap-1 overflow-x-auto px-4 md:mx-0 md:max-w-none md:px-0"
        >
          {FILTERS.map((f) => (
            <button
              key={f}
              type="button"
              aria-pressed={filter === f}
              onClick={() => setFilter(f)}
              className={cn(
                "min-h-9 shrink-0 rounded-full px-3.5 text-sm whitespace-nowrap",
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
      {tasks.isError && !tasks.data ? (
        <div role="alert" className="flex flex-col items-start gap-2 rounded-lg border p-4 text-sm">
          <p>{toMessage(tasks.error).message}</p>
          <Button variant="outline" size="sm" onClick={() => tasks.refetch()}>
            {tc("retry")}
          </Button>
        </div>
      ) : (
        <ul
          className={cn("divide-y rounded-lg border bg-card transition-opacity", tasks.isPlaceholderData && "opacity-60")}
          aria-busy={tasks.isFetching}
        >
          {tasks.isPending && <li className="px-3 py-4 text-sm text-muted-foreground">{tc("loading")}</li>}
          {tasks.data?.items.map((task) => <TaskRow key={task.id} task={task} now={now} />)}
          {tasks.data?.items.length === 0 && (
            <li>
              <EmptyState
                title={query || filter !== "all" ? t("emptyFiltered") : t("empty")}
                hint={query || filter !== "all" ? undefined : t("emptyHint")}
                mood="sleep"
              />
            </li>
          )}
        </ul>
      )}
    </div>
  );
}
