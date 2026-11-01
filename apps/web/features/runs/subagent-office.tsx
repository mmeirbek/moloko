"use client";

import type { AgentOut, RunOut, TaskOut } from "@moloko/shared-types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Send } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { useOrchestratorBusy } from "@/features/agents/agent-controls";
import { StatusBadge } from "@/features/agents/status-badge";
import { useErrorMessage } from "@/features/auth/use-error-message";
import { MarkdownBody } from "@/features/chat/markdown";
import { getRunTree, listRuns, runKeys, startRun } from "@/lib/api/runs";
import { useRealtimeStore } from "@/lib/realtime/store";
import { cn } from "@/lib/utils";
import { EmptyState } from "@/features/mascot/empty-state";
import { MilkBottle } from "@/features/mascot/milk-bottle";
import { ExportMenu } from "@/features/tasks/export-menu";
import { MicButton } from "@/features/voice/mic-button";
import { ErrorState, LoadingState } from "@/features/system/query-state";

function NewRun({ onStarted }: { onStarted: (runId: string) => void }) {
  const t = useTranslations("runs");
  const toMessage = useErrorMessage();
  const queryClient = useQueryClient();
  const [text, setText] = useState("");
  const busy = useOrchestratorBusy();
  const start = useMutation({
    mutationFn: () => {
      const title = text.split("\n")[0]!.slice(0, 120).trim() || t("untitled");
      return startRun({ title, description: text });
    },
    onSuccess: (started) => {
      setText("");
      void queryClient.invalidateQueries({ queryKey: runKeys.list });
      onStarted(started.run.id);
    },
  });
  return (
    <form
      className="flex flex-col gap-2 rounded-lg border bg-card p-4"
      onSubmit={(e) => {
        e.preventDefault();
        if (text.trim() && !busy) start.mutate();
      }}
    >
      <label htmlFor="run-text" className="text-sm font-medium">
        {t("newRun")}
      </label>
      <textarea
        id="run-text"
        rows={3}
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={t("newRunHint")}
        className="rounded-md border border-input bg-background px-3 py-2 text-base md:text-sm"
      />
      {start.error && (
        <p role="alert" className="text-sm text-destructive">
          {toMessage(start.error).message}
        </p>
      )}
      {busy && (
        <p role="status" className="text-xs text-muted-foreground">
          {t("orchestratorBusy")}
        </p>
      )}
      <div className="flex items-center gap-1">
        <Button type="submit" disabled={!text.trim() || start.isPending || busy}>
          <Send /> {t("start")}
        </Button>
        <MicButton onText={(spoken) => setText((cur) => (cur ? `${cur.trimEnd()} ${spoken}` : spoken))} />
      </div>
    </form>
  );
}

function SubagentCard({ agent, task }: { agent: AgentOut; task?: TaskOut }) {
  const t = useTranslations("runs");
  const live = useRealtimeStore((s) => s.agents[agent.id]) ?? agent;
  const liveTask = useRealtimeStore((s) => (task ? s.tasks[task.id] : undefined)) ?? task;
  return (
    <li className="flex flex-col gap-1.5 rounded-lg border bg-card p-3" style={{ marginLeft: (live.depth - 1) * 16 }}>
      <div className="flex items-center justify-between gap-2">
        <p className="truncate text-sm font-medium">{live.name}</p>
        <StatusBadge status={live.status} />
      </div>
      {liveTask && (
        <Link
          href={`/tasks/${liveTask.id}`}
          className="flex items-center justify-between gap-2 text-xs text-muted-foreground hover:underline"
        >
          <span className="truncate">{liveTask.title}</span>
          <StatusBadge status={liveTask.status} />
        </Link>
      )}
      {liveTask && liveTask.depends_on.length > 0 && (
        <p className="text-xs text-muted-foreground">{t("waitsFor", { count: liveTask.depends_on.length })}</p>
      )}
    </li>
  );
}

function RunView({ runId }: { runId: string }) {
  const t = useTranslations("runs");
  const format = useFormatter();
  const tree = useQuery({ queryKey: runKeys.tree(runId), queryFn: ({ signal }) => getRunTree(runId, signal) });
  const liveTask = useRealtimeStore((s) => (tree.data ? s.tasks[tree.data.task.id] : undefined));
  if (!tree.data) return tree.isError ? <ErrorState error={tree.error} onRetry={() => tree.refetch()} /> : <LoadingState />;
  const { run, subagents, subtasks, messages } = tree.data;
  const task = liveTask ?? tree.data.task;
  const agents = subagents as AgentOut[];
  const team = (tree.data.team ?? []) as AgentOut[]; // the owner's own agents that took parts
  const taskByAgent = new Map(subtasks.map((s) => [s.agent_id, s]));
  const names = new Map([...agents, ...team].map((a) => [a.id, a.name]));
  const plan = run.plan as { mode?: string; summary?: string; warnings?: string[] } | null;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="min-w-0 text-lg font-semibold break-words">{task.title}</h2>
        <StatusBadge status={task.status} />
        {(task.progress > 0 || task.status === "completed") && (
          <MilkBottle percent={task.progress} done={task.status === "completed"} size={18} />
        )}
        <Link
          href={`/tasks/${task.id}`}
          className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:underline"
        >
          {t("openTask")} <ArrowRight className="size-3.5" />
        </Link>
      </div>
      {plan && (
        <p className="text-sm text-muted-foreground">
          {plan.mode === "direct" ? t("directAnswer") : t("plan", { summary: plan.summary ?? "" })}
          {task.progress > 0 && task.status !== "completed" && ` · ${task.progress}%`}
        </p>
      )}
      {plan?.warnings?.map((w) => (
        <p key={w} className="text-xs text-amber-700 dark:text-amber-300">
          {w}
        </p>
      ))}
      {agents.length > 0 && (
        <section>
          <h3 className="mb-2 text-sm font-medium">{t("subagents", { count: agents.length })}</h3>
          <ul className="grid gap-2 sm:grid-cols-2">
            {agents.map((a) => (
              <SubagentCard key={a.id} agent={a} task={taskByAgent.get(a.id)} />
            ))}
          </ul>
        </section>
      )}
      {team.length > 0 && (
        <section>
          <h3 className="mb-2 text-sm font-medium">{t("team", { count: team.length })}</h3>
          <ul className="grid gap-2 sm:grid-cols-2">
            {team.map((a) => (
              <SubagentCard key={a.id} agent={a} task={taskByAgent.get(a.id)} />
            ))}
          </ul>
        </section>
      )}
      {task.result && (
        <section className="print-area rounded-lg border bg-card p-4">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-sm font-medium text-muted-foreground">{t("result")}</h3>
            <ExportMenu taskId={task.id} title={task.title} />
          </div>
          <MarkdownBody text={task.result} />
        </section>
      )}
      {task.status === "failed" && (
        <p role="alert" className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm">
          {task.error_message}
        </p>
      )}
      {messages.length > 0 && (
        <section>
          <h3 className="mb-2 text-sm font-medium">{t("messages")}</h3>
          <ol className="flex flex-col gap-1 text-sm">
            {messages.map((m) => (
              <li key={m.id} className="flex flex-wrap gap-x-2">
                <span className="text-muted-foreground tabular-nums">
                  {format.dateTime(new Date(m.created_at), { timeStyle: "medium" })}
                </span>
                <span>
                  {names.get(m.sender_agent_id) ?? t("orchestrator")} →{" "}
                  {names.get(m.receiver_agent_id) ?? t("orchestrator")}:
                </span>
                <span className={cn("text-muted-foreground", m.message_type === "error" && "text-destructive")}>
                  {String((m.content as { summary?: string }).summary ?? m.message_type)}
                </span>
              </li>
            ))}
          </ol>
        </section>
      )}
    </div>
  );
}

export function SubagentOffice() {
  const t = useTranslations("runs");
  const runs = useQuery({ queryKey: runKeys.list, queryFn: ({ signal }) => listRuns(signal) });
  const fromUrl = useSearchParams().get("run");
  // A click picks a run until the URL names another one (the cow dialog pushes ?run=<new>).
  const [picked, setPicked] = useState<{ url: string | null; id: string | null }>({ url: fromUrl, id: null });
  const selected = picked.url === fromUrl ? (picked.id ?? fromUrl) : fromUrl;
  const current = selected ?? runs.data?.[0]?.id ?? null;
  const viewRef = useRef<HTMLDivElement>(null);

  function select(id: string) {
    setPicked({ url: fromUrl, id });
    // Phones show the run under the list: bring it into view so the tap visibly did something.
    if (window.matchMedia("(max-width: 1023px)").matches) {
      requestAnimationFrame(() => viewRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
    }
  }

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[18rem_minmax(0,1fr)]">
      <div className="flex flex-col gap-3">
        <NewRun onStarted={select} />
        {runs.isPending && <LoadingState />}
        {runs.isError && !runs.data && <ErrorState error={runs.error} onRetry={() => runs.refetch()} />}
        <ul className="flex flex-col gap-1" aria-label={t("runs")}>
          {runs.data?.map((run: RunOut) => (
            <RunListItem key={run.id} run={run} active={run.id === current} onSelect={() => select(run.id)} />
          ))}
        </ul>
        {runs.data?.length === 0 && (
          <EmptyState title={t("empty")} hint={t("emptyHint")} size={56} className="py-4" />
        )}
      </div>
      <div ref={viewRef} className="min-w-0 scroll-mt-20">
        {current && <RunView key={current} runId={current} />}
      </div>
    </div>
  );
}

function RunListItem({ run, active, onSelect }: { run: RunOut; active: boolean; onSelect: () => void }) {
  const task = useRealtimeStore((s) => s.tasks[run.task_id]);
  const format = useFormatter();
  return (
    <li>
      <button
        type="button"
        onClick={onSelect}
        aria-current={active ? "true" : undefined}
        className={cn(
          "flex w-full items-center justify-between gap-2 rounded-md px-3 py-2 text-left text-sm",
          active ? "bg-accent" : "hover:bg-accent/60",
        )}
      >
        <span className="min-w-0">
          <span className="block truncate">
            {task?.title ?? format.dateTime(new Date(run.created_at), { dateStyle: "short", timeStyle: "short" })}
          </span>
        </span>
        <StatusBadge status={task?.status ?? run.status} />
      </button>
    </li>
  );
}
