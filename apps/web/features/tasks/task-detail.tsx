"use client";

import type { EventOut, TaskOut } from "@moloko/shared-types";
import { useQuery } from "@tanstack/react-query";
import { useFormatter, useTranslations } from "next-intl";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { ArrowLeft, Bot, ChevronDown, ChevronRight, Info, X } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/features/agents/status-badge";
import { MarkdownBody } from "@/features/chat/markdown";
import { MilkBottle } from "@/features/mascot/milk-bottle";
import { ErrorState, LoadingState } from "@/features/system/query-state";
import { AgentSteps } from "@/features/tasks/agent-steps";
import { ExportMenu } from "@/features/tasks/export-menu";
import { TaskComposer } from "@/features/tasks/task-composer";
import { ACTIVE_TASK } from "@/features/tasks/task-control";
import { useTaskError } from "@/features/tasks/task-error";
import { TaskOutcome } from "@/features/tasks/task-outcome";
import { TaskSidebar } from "@/features/tasks/task-sidebar";
import { TaskApprovals } from "@/features/tasks/tool-calls";
import { getTask, taskEvents, taskKeys } from "@/lib/api/agents";
import { useDocumentTitle } from "@/lib/hooks";
import { useRealtimeStore } from "@/lib/realtime/store";

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
    case "agent.created":
      // the Orchestrator created an agent for a part of this task (none of the owner's fitted)
      return t("ev.agentCreated", {
        name: String((p.agent as { name?: string } | undefined)?.name ?? ""),
      });
    case "task.owner_message":
      return t("ev.ownerMessage", { text: String(p.text ?? "") });
    case "task.owner_message_read":
      return t("ev.ownerMessageRead");
    case "schedule.fired":
      return p.trigger === "run_now" ? t("ev.scheduledNow") : t("ev.scheduled");
    default:
      return e.type;
  }
}

/** Keeps a scrolled container at the bottom while new content arrives — unless the owner
 *  scrolled up to read (then it stays where they are). */
function useStickToBottom<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    let stuck = true;
    const onScroll = () => {
      stuck = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    };
    const observer = new MutationObserver(() => {
      if (stuck) el.scrollTop = el.scrollHeight;
    });
    observer.observe(el, { childList: true, subtree: true, characterData: true });
    el.addEventListener("scroll", onScroll, { passive: true });
    el.scrollTop = el.scrollHeight;
    return () => {
      observer.disconnect();
      el.removeEventListener("scroll", onScroll);
    };
  }, []);
  return ref;
}

/** The owner's message, on the right like in the chat. */
function OwnerBubble({ text, at, testId }: { text: string; at?: string; testId?: string }) {
  return (
    <div className="flex flex-col items-end gap-1">
      <div className="max-w-[85%] bg-muted px-4 py-2.5 text-sm whitespace-pre-wrap break-words" data-testid={testId}>
        {text}
      </div>
      {at && <span className="text-xs text-muted-foreground">{at}</span>}
    </div>
  );
}

/** The owner's reply this attempt was started with (the task's chat), if any. */
function latestReply(task: TaskOut): string | null {
  const turns = task.extra?.follow_ups;
  if (!Array.isArray(turns) || turns.length === 0) return null;
  const last = turns[turns.length - 1] as { reply?: unknown };
  return typeof last.reply === "string" && last.reply.trim() ? last.reply : null;
}

/** The attempts this one continues, oldest first: each the owner's message and the agent's
 *  answer (its steps on request) — so a continued task reads as one chat. */
function EarlierTurns({ taskId, depth }: { taskId: string; depth: number }) {
  const t = useTranslations("tasks.chat");
  const taskError = useTaskError();
  const format = useFormatter();
  const [steps, setSteps] = useState(false);
  const detail = useQuery({ queryKey: taskKeys.detail(taskId), queryFn: ({ signal }) => getTask(taskId, signal) });
  const prev = detail.data?.task;
  if (!prev) return null;
  const before = typeof prev.extra?.continued_from === "string" ? prev.extra.continued_from : null;
  const reply = before ? latestReply(prev) : null;
  return (
    <>
      {before && depth < 10 && <EarlierTurns taskId={before} depth={depth + 1} />}
      {(!before || reply) && (
        <OwnerBubble
          text={reply ?? (prev.description?.trim() || prev.title)}
          at={format.dateTime(new Date(prev.created_at), { dateStyle: "short", timeStyle: "short" })}
        />
      )}
      <AgentTurn agentId={prev.agent_id} label={t("earlier")} status={prev.status} testId="earlier-turn">
        <button
          type="button"
          className="inline-flex items-center gap-1 self-start text-xs text-muted-foreground hover:text-foreground"
          aria-expanded={steps}
          onClick={() => setSteps((v) => !v)}
        >
          {steps ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
          {steps ? t("hideSteps") : t("showSteps")}
          <Link href={`/tasks/${prev.id}`} className="ml-2 underline-offset-2 hover:underline" onClick={(e) => e.stopPropagation()}>
            {t("openAttempt")}
          </Link>
        </button>
        {steps && <AgentSteps taskId={prev.id} status={prev.status} result={prev.result} bare />}
        {prev.result ? (
          <div className="bg-card p-3 text-sm pixel-frame">
            <MarkdownBody text={prev.result} />
          </div>
        ) : prev.status === "failed" ? (
          <p className="text-sm text-destructive">{taskError(prev)}</p>
        ) : null}
      </AgentTurn>
    </>
  );
}

/** One agent's turn in the task chat: who, what it is doing, its steps. */
function AgentTurn({
  agentId,
  label,
  status,
  children,
  testId,
}: {
  agentId: string | null;
  label?: string;
  status: string;
  children: React.ReactNode;
  testId?: string;
}) {
  const name = useRealtimeStore((s) => (agentId ? s.agents[agentId]?.name : undefined));
  return (
    <div className="flex gap-3" data-testid={testId}>
      <span className="mt-0.5 flex size-7 shrink-0 items-center justify-center bg-muted pixel-frame" aria-hidden>
        <Bot className="size-4" />
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <p className="flex flex-wrap items-center gap-2 text-sm">
          {agentId ? (
            <Link href={`/office/agents/${agentId}`} className="font-medium hover:underline">
              {name ?? "—"}
            </Link>
          ) : (
            <span className="font-medium">—</span>
          )}
          {label && <span className="text-muted-foreground">{label}</span>}
          <StatusBadge status={status} />
        </p>
        {children}
      </div>
    </div>
  );
}

/** A part of the Orchestrator's plan, done by one of the agents: its steps and its result. */
function PartTurn({ part }: { part: TaskOut }) {
  const t = useTranslations("tasks.chat");
  const live = useRealtimeStore((s) => s.tasks[part.id]) ?? part;
  const name = useRealtimeStore((s) => (live.agent_id ? s.agents[live.agent_id]?.name : undefined));
  const active = ACTIVE_TASK.has(live.status);
  const [open, setOpen] = useState<boolean | null>(null);
  const shown = open ?? active;
  return (
    <AgentTurn
      agentId={live.agent_id}
      label={live.task_type === "consult" ? t("consult", { title: live.title }) : t("part", { title: live.title })}
      status={live.status}
    >
      <span className="sr-only" data-testid="part-agent">
        {name ?? ""}
      </span>
      <button
        type="button"
        className="inline-flex items-center gap-1 self-start text-xs text-muted-foreground hover:text-foreground"
        aria-expanded={shown}
        onClick={() => setOpen(!shown)}
      >
        {shown ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
        {shown ? t("hideSteps") : t("showSteps")}
        <Link href={`/tasks/${live.id}`} className="ml-2 underline-offset-2 hover:underline" onClick={(e) => e.stopPropagation()}>
          {t("openPart")}
        </Link>
      </button>
      {shown && <AgentSteps taskId={live.id} status={live.status} result={live.result} bare />}
      {live.result && (
        <div className="bg-card p-3 text-sm pixel-frame">
          <MarkdownBody text={live.result} />
        </div>
      )}
    </AgentTurn>
  );
}

export function TaskDetailView({ taskId }: { taskId: string }) {
  const t = useTranslations("tasks");
  const tChat = useTranslations("tasks.chat");
  const taskError = useTaskError();
  const tc = useTranslations("common");
  const tStatus = useTranslations("status");
  const ts = (status: string) => {
    const key = status as Parameters<typeof tStatus>[0];
    return tStatus.has(key) ? tStatus(key).toLowerCase() : status;
  };
  const format = useFormatter();
  const detail = useQuery({ queryKey: taskKeys.detail(taskId), queryFn: ({ signal }) => getTask(taskId, signal) });
  const events = useQuery({ queryKey: taskKeys.events(taskId), queryFn: ({ signal }) => taskEvents(taskId, signal) });
  const live = useRealtimeStore((s) => s.tasks[taskId]);
  const task = live ?? detail.data?.task;
  useDocumentTitle(task?.title);
  const mainIsOrchestrator = useRealtimeStore((s) =>
    task?.agent_id ? s.agents[task.agent_id]?.agent_type === "orchestrator" : false,
  );
  const [details, setDetails] = useState(false);
  const scroller = useStickToBottom<HTMLDivElement>();


  if (!task) return detail.isError ? <ErrorState error={detail.error} onRetry={() => detail.refetch()} /> : <LoadingState />;
  const run = detail.data?.run;
  const subtasks = detail.data?.subtasks ?? [];
  const continuedFrom = typeof task.extra?.continued_from === "string" ? task.extra.continued_from : null;
  // What the owner wrote for this attempt: the task itself, or — continuing the chat — the reply.
  const reply = continuedFrom ? latestReply(task) : null;
  const sidebar = (className?: string) => (
    <TaskSidebar
      task={task}
      run={run}
      subtasks={subtasks}
      events={events.data}
      describe={(e) => describe(e, t, ts)}
      className={className}
    />
  );

  return (
    // The task as a chat (like Claude Code): the conversation in the middle, the details on the right.
    <div className="-mt-2 flex h-[calc(100dvh-10.5rem)] min-w-0 gap-4 md:h-[calc(100dvh-5.5rem)]">
      <section className="flex min-w-0 flex-1 flex-col" aria-label={tChat("label")}>
        <header className="flex flex-wrap items-center gap-2 border-b-2 pb-2">
          <Link href="/tasks" className="inline-flex items-center text-muted-foreground" aria-label={t("allTasks")}>
            <ArrowLeft className="size-4" />
          </Link>
          <h1 className="min-w-0 flex-1 truncate font-sans text-lg font-semibold tracking-tight">{task.title}</h1>
          <StatusBadge status={task.status} />
          {(task.progress > 0 || task.status === "completed") && (
            <MilkBottle percent={task.progress} done={task.status === "completed"} size={20} />
          )}
          <Button
            size="sm"
            variant="ghost"
            className="lg:hidden"
            aria-expanded={details}
            onClick={() => setDetails((v) => !v)}
          >
            {details ? <X /> : <Info />} {tChat("details")}
          </Button>
        </header>
        {details && sidebar("mt-2 max-h-[55%] shrink-0 overflow-y-auto lg:hidden")}

        <div ref={scroller} className="min-h-0 flex-1 overflow-y-auto py-4" data-testid="task-chat">
          <div className="mx-auto flex max-w-3xl flex-col gap-5 px-1">
            {/* Earlier in this chat (the attempts this one continues), then the owner's message */}
            {continuedFrom && <EarlierTurns taskId={continuedFrom} depth={0} />}
            {continuedFrom && !reply ? (
              <Link href={`/tasks/${continuedFrom}`} className="self-center text-xs underline underline-offset-2">
                {t("control.continuedFrom")}
              </Link>
            ) : (
              <OwnerBubble
                text={reply ?? (task.description?.trim() || task.title)}
                at={format.dateTime(new Date(task.created_at), { dateStyle: "short", timeStyle: "short" })}
                testId="task-request"
              />
            )}

            <AgentTurn
              agentId={task.agent_id}
              label={mainIsOrchestrator ? tChat("orchestratorLabel") : undefined}
              status={task.status}
              testId="task-main-turn"
            >
              <AgentSteps taskId={task.id} status={task.status} events={events.data} result={task.result} bare />
            </AgentTurn>

            {subtasks.map((s) => (
              <PartTurn key={s.id} part={s} />
            ))}

            <TaskApprovals taskIds={[task.id, ...subtasks.map((s) => s.id)]} />

            {task.result && (
              <AgentTurn agentId={task.agent_id} label={tChat("answer")} status={task.status} testId="task-result">
                <div className="print-area bg-card p-4 pixel-frame">
                  <MarkdownBody text={task.result} />
                  <div className="mt-3 flex justify-end">
                    <ExportMenu taskId={task.id} title={task.title} />
                  </div>
                </div>
              </AgentTurn>
            )}
            {!ACTIVE_TASK.has(task.status) && <TaskOutcome task={task} parts={subtasks} />}
            {task.status === "failed" && (
              <section role="alert" className="border-2 border-destructive/40 bg-destructive/10 p-4 text-sm">
                {task.error_code === "agent_budget_exceeded" && task.agent_id ? (
                  // A readable reason in the owner's language, and where to raise the budget.
                  <p className="mb-1">
                    {t("agentBudgetExceeded")}{" "}
                    <Link href={`/office/agents/${task.agent_id}`} className="underline underline-offset-2">
                      {t("openAgent")}
                    </Link>
                  </p>
                ) : null}
                <p>{taskError(task)}</p>
                <p className="mt-1 font-mono text-xs text-muted-foreground">
                  {task.error_code} · {tc("errorId", { id: task.error_id ?? "—" })}
                </p>
              </section>
            )}
            {task.status === "waiting" && task.status_reason === "unknown_outcome" && (
              <section role="alert" className="border-2 border-amber-400/50 bg-amber-400/10 p-4 text-sm">
                {t("unknownOutcome")}
              </section>
            )}
          </div>
        </div>

        {/* The chat input, as in the chat: to the working agent, or continuing the task. */}
        <footer className="mx-auto w-full max-w-3xl pt-2" data-testid="task-composer">
          <TaskComposer task={task} />
        </footer>
      </section>

      <aside className="hidden w-80 shrink-0 overflow-y-auto lg:block" aria-label={tChat("details")}>
        {sidebar()}
      </aside>
    </div>
  );
}
