"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";

import { Network } from "@/components/icons";
import { cn } from "@/lib/utils";

type TaskLike = { status: string; status_reason?: string | null; task_type?: string; extra?: Record<string, unknown> | null };

/** The colleague a task is waiting for (`agent_ask`), from `task.extra.waiting_for`; null otherwise. */
export function waitingFor(task: TaskLike): { agentId: string; agentName: string; taskId: string } | null {
  const w = task.extra?.waiting_for as { agent_id?: unknown; agent_name?: unknown; task_id?: unknown } | undefined;
  if (task.status !== "waiting" || !w || typeof w.agent_id !== "string") return null;
  return {
    agentId: w.agent_id,
    agentName: typeof w.agent_name === "string" ? w.agent_name : "",
    taskId: typeof w.task_id === "string" ? w.task_id : "",
  };
}

/** Who asked for a consult task (`agent_ask`), from `task.extra.ask`; null for other tasks. */
export function askedBy(task: TaskLike): { agentId: string; agentName: string; taskId: string } | null {
  if (task.task_type !== "consult") return null;
  const a = task.extra?.ask as { asker_agent_id?: unknown; asker_name?: unknown; asker_task_id?: unknown } | undefined;
  if (!a || typeof a.asker_agent_id !== "string") return null;
  return {
    agentId: a.asker_agent_id,
    agentName: typeof a.asker_name === "string" ? a.asker_name : "",
    taskId: typeof a.asker_task_id === "string" ? a.asker_task_id : "",
  };
}

/** One line on a task: «Ждёт ответа от X» or «Спросил агент X», with links (task page, inspector). */
export function TeamLine({ task, className }: { task: TaskLike; className?: string }) {
  const t = useTranslations("agents.team");
  const waiting = waitingFor(task);
  const asker = askedBy(task);
  if (!waiting && !asker) return null;
  return (
    <p className={cn("inline-flex flex-wrap items-center gap-x-2 gap-y-1 text-sm", className)} data-testid="team-line">
      <Network className="size-3 shrink-0 text-sky" aria-hidden />
      {waiting && (
        <>
          <span>{t("waitingFor")}</span>
          <Link href={`/office/agents/${waiting.agentId}`} className="underline-offset-2 hover:underline">
            {waiting.agentName}
          </Link>
          {waiting.taskId && (
            <Link href={`/tasks/${waiting.taskId}`} className="text-sky underline-offset-2 hover:underline">
              {t("openRequest")}
            </Link>
          )}
        </>
      )}
      {asker && (
        <>
          <span>{t("askedBy")}</span>
          <Link href={`/office/agents/${asker.agentId}`} className="underline-offset-2 hover:underline">
            {asker.agentName}
          </Link>
          {asker.taskId && (
            <Link href={`/tasks/${asker.taskId}`} className="text-sky underline-offset-2 hover:underline">
              {t("openAskerTask")}
            </Link>
          )}
        </>
      )}
    </p>
  );
}
