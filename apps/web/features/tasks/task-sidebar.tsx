"use client";

import type { EventOut, RunOut, TaskOut, ToolCallOut } from "@moloko/shared-types";
import { useQueries } from "@tanstack/react-query";
import { useFormatter, useTranslations } from "next-intl";
import Link from "next/link";
import { useState, type ReactNode } from "react";

import { CalendarDays, Check, Folder, Link2, Loader2, Network, X } from "@/components/icons";
import { StatusBadge, taskBadge } from "@/features/agents/status-badge";
import { TeamLine } from "@/features/agents/team-links";
import { MilkBottle } from "@/features/mascot/milk-bottle";
import { TaskWorkspace } from "@/features/tasks/tool-calls";
import { taskToolCalls, toolingKeys } from "@/lib/api/tooling";
import { useRealtimeStore } from "@/lib/realtime/store";
import { cn } from "@/lib/utils";

const ACTIVE = new Set(["queued", "running", "waiting", "waiting_approval"]);

function Section({ title, children, testId }: { title: string; children: ReactNode; testId?: string }) {
  return (
    <section className="flex flex-col gap-1.5 border-b-2 px-3 py-3 last:border-b-0" data-testid={testId}>
      <h2 className="text-xs font-medium tracking-wide text-muted-foreground uppercase">{title}</h2>
      {children}
    </section>
  );
}

function PartStatus({ status }: { status: string }) {
  if (ACTIVE.has(status)) return <Loader2 className="size-3.5 shrink-0 animate-spin text-sky" aria-hidden />;
  if (status === "completed") return <Check className="size-3.5 shrink-0 text-grass" aria-hidden />;
  if (status === "failed" || status === "cancelled") return <X className="size-3.5 shrink-0 text-destructive" aria-hidden />;
  return <span className="size-3.5 shrink-0 border-2" aria-hidden />;
}

/** Where the agents work, from what they actually did: repositories (and branches), sites,
 *  sandbox commands. The workspace's files are listed below it. */
function useWhere(taskIds: string[], status: string) {
  const results = useQueries({
    queries: taskIds.map((id) => ({
      queryKey: [...toolingKeys.taskCalls(id), status],
      queryFn: ({ signal }: { signal: AbortSignal }) => taskToolCalls(id, signal),
    })),
  });
  const calls: ToolCallOut[] = results.flatMap((r) => r.data ?? []);
  const repos = new Map<string, Set<string>>();
  const sites = new Set<string>();
  let commands = 0;
  for (const c of calls) {
    const a = c.args as Record<string, unknown>;
    if (c.tool_name.startsWith("github_") && typeof a.repo === "string" && a.repo) {
      const branches = repos.get(a.repo) ?? new Set<string>();
      for (const k of ["branch", "ref", "head"]) if (typeof a[k] === "string" && a[k]) branches.add(String(a[k]));
      repos.set(a.repo, branches);
    }
    if ((c.tool_name === "web_fetch" || c.tool_name === "browser_screenshot") && typeof a.url === "string") {
      try {
        sites.add(new URL(a.url).hostname);
      } catch {
        /* not a URL: nothing to show */
      }
    }
    if (c.tool_name === "terminal_run") commands += 1;
  }
  return { repos, sites, commands };
}

export function TaskSidebar({
  task,
  run,
  subtasks,
  events,
  describe,
  className,
}: {
  task: TaskOut;
  run: RunOut | null | undefined;
  subtasks: TaskOut[];
  events: EventOut[] | undefined;
  describe: (e: EventOut) => string;
  className?: string;
}) {
  const t = useTranslations("tasks.chat");
  const tSchedules = useTranslations("schedules");
  const format = useFormatter();
  const agents = useRealtimeStore((s) => s.agents);
  const liveTasks = useRealtimeStore((s) => s.tasks);
  const [fullGoal, setFullGoal] = useState(false);
  const parts = subtasks.map((s) => liveTasks[s.id] ?? s);
  const where = useWhere([task.id, ...parts.map((p) => p.id)], task.status);

  const main = task.agent_id ? agents[task.agent_id] : undefined;
  const isOrchestrator = main?.agent_type === "orchestrator";
  // Who works on this task, and on what: the main agent, then each agent with all its parts.
  const team: { id: string; role: string }[] = [];
  if (task.agent_id) team.push({ id: task.agent_id, role: isOrchestrator ? t("roleOrchestrator") : t("roleMain") });
  const byAgent = new Map<string, { parts: string[]; consult: boolean }>();
  for (const p of parts) {
    if (!p.agent_id || p.agent_id === task.agent_id) continue;
    const entry = byAgent.get(p.agent_id) ?? { parts: [], consult: false };
    if (p.task_type === "consult") entry.consult = true;
    else entry.parts.push(p.title);
    byAgent.set(p.agent_id, entry);
  }
  for (const [id, { parts: titles, consult }] of byAgent) {
    const role = titles.length
      ? t("rolePart", { count: titles.length, titles: titles.join(", ") })
      : consult
        ? t("roleConsult")
        : "";
    team.push({ id, role });
  }
  const plan = (run?.plan ?? null) as { mode?: string; summary?: string } | null;
  const time = (iso: string | null | undefined) =>
    iso ? format.dateTime(new Date(iso), { dateStyle: "short", timeStyle: "short" }) : "—";
  const scheduleId = typeof task.extra?.schedule_id === "string" ? task.extra.schedule_id : null;

  return (
    <div className={cn("flex flex-col bg-card text-sm pixel-frame", className)} data-testid="task-sidebar">
      <Section title={t("goal")} testId="task-goal">
        <p className="font-medium break-words">{task.title}</p>
        {task.description && task.description.trim() !== task.title.trim() && (
          <>
            <p className={cn("text-xs whitespace-pre-wrap break-words text-muted-foreground", !fullGoal && "line-clamp-6")}>
              {task.description}
            </p>
            {task.description.length > 300 && (
              <button type="button" className="self-start text-xs underline" onClick={() => setFullGoal((v) => !v)}>
                {fullGoal ? t("showLess") : t("showAll")}
              </button>
            )}
          </>
        )}
      </Section>

      <Section title={t("state")}>
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge status={taskBadge(task)} />
          {(task.progress > 0 || task.status === "completed") && (
            <span className="inline-flex items-center gap-1 text-xs">
              <MilkBottle percent={task.progress} done={task.status === "completed"} size={16} /> {task.progress}%
            </span>
          )}
        </div>
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
          <dt className="text-muted-foreground">{t("created")}</dt>
          <dd>{time(task.created_at)}</dd>
          {task.started_at && (
            <>
              <dt className="text-muted-foreground">{t("started")}</dt>
              <dd>{time(task.started_at)}</dd>
            </>
          )}
          {task.completed_at && (
            <>
              <dt className="text-muted-foreground">{t("finished")}</dt>
              <dd>{time(task.completed_at)}</dd>
            </>
          )}
          {run && (
            <>
              <dt className="text-muted-foreground">{t("stepsLabel")}</dt>
              <dd>{run.steps}</dd>
            </>
          )}
          {run?.usage?.output_tokens != null && (
            <>
              <dt className="text-muted-foreground">{t("tokensLabel")}</dt>
              <dd>{format.number(Number(run.usage.input_tokens ?? 0) + Number(run.usage.output_tokens))}</dd>
            </>
          )}
          {task.attempt > 1 && (
            <>
              <dt className="text-muted-foreground">{t("attemptLabel")}</dt>
              <dd>{task.attempt}</dd>
            </>
          )}
        </dl>
        {scheduleId && (
          <Link href={`/schedules#schedule-${scheduleId}`} className="inline-flex items-center gap-1.5 text-xs underline">
            <CalendarDays className="size-3" aria-hidden /> {tSchedules("fromSchedule")}
          </Link>
        )}
        <TeamLine task={task} className="text-xs" />
      </Section>

      <Section title={t("plan")} testId="task-plan">
        {plan?.mode === "delegate" ? (
          <>
            {plan.summary && <p className="text-xs">{plan.summary}</p>}
            <ol className="flex flex-col gap-1">
              {parts
                .filter((p) => p.task_type !== "consult")
                .map((p) => (
                  <li key={p.id} className="flex items-start gap-2" data-testid="plan-part">
                    <PartStatus status={p.status} />
                    <span className="min-w-0">
                      <Link href={`/tasks/${p.id}`} className="block break-words hover:underline">
                        {p.title}
                      </Link>
                      {p.agent_id && agents[p.agent_id] && (
                        <span className="block text-xs text-muted-foreground">{agents[p.agent_id]!.name}</span>
                      )}
                    </span>
                  </li>
                ))}
            </ol>
          </>
        ) : plan?.mode === "direct" ? (
          <p className="text-xs text-muted-foreground">{t("planDirect")}</p>
        ) : (
          <p className="text-xs text-muted-foreground">{isOrchestrator ? t("planPending") : t("planNone")}</p>
        )}
      </Section>

      <Section title={t("agents")} testId="task-agents">
        <ul className="flex flex-col gap-1.5">
          {team.map(({ id, role }) => {
            const agent = agents[id];
            return (
              <li key={id} className="flex items-start justify-between gap-2">
                <span className="min-w-0">
                  <Link href={`/office/agents/${id}`} className="block truncate font-medium hover:underline">
                    {agent?.name ?? "—"}
                  </Link>
                  <span className="block text-xs text-muted-foreground break-words">{role}</span>
                </span>
                {agent && <StatusBadge status={agent.status} />}
              </li>
            );
          })}
        </ul>
      </Section>

      <Section title={t("where")} testId="task-where">
        {where.repos.size > 0 && (
          <ul className="flex flex-col gap-0.5 text-xs">
            {[...where.repos.entries()].map(([repo, branches]) => (
              <li key={repo} className="flex items-start gap-1.5">
                <Network className="mt-0.5 size-3 shrink-0" aria-hidden />
                <span className="min-w-0 break-words">
                  <a href={`https://github.com/${repo}`} target="_blank" rel="noreferrer" className="underline">
                    {repo}
                  </a>
                  {branches.size > 0 && <span className="text-muted-foreground"> · {[...branches].join(", ")}</span>}
                </span>
              </li>
            ))}
          </ul>
        )}
        {where.sites.size > 0 && (
          <p className="flex items-start gap-1.5 text-xs">
            <Link2 className="mt-0.5 size-3 shrink-0" aria-hidden />
            <span className="break-words">{[...where.sites].join(", ")}</span>
          </p>
        )}
        {where.commands > 0 && <p className="text-xs text-muted-foreground">{t("sandbox", { count: where.commands })}</p>}
        <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Folder className="size-3" aria-hidden /> {t("workspace")}
        </p>
        <TaskWorkspace taskId={task.id} status={task.status} />
      </Section>

      <Section title={t("log")}>
        <details>
          <summary className="cursor-pointer text-xs text-muted-foreground">{t("logShow", { count: events?.length ?? 0 })}</summary>
          <ol className="mt-2 flex flex-col gap-1 border-l-2 pl-3 text-xs">
            {events?.map((e) => (
              <li key={e.id}>
                <span className="text-muted-foreground tabular-nums">
                  {format.dateTime(new Date(e.timestamp), { timeStyle: "medium" })}
                </span>{" "}
                {describe(e)}
              </li>
            ))}
          </ol>
        </details>
      </Section>
    </div>
  );
}
