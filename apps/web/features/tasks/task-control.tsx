"use client";

import type { TaskOut } from "@moloko/shared-types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useId, useState } from "react";

import { Play, RotateCcw, Send } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { useErrorMessage } from "@/features/auth/use-error-message";
import { useTaskError } from "@/features/tasks/task-error";
import { MicButton } from "@/features/voice/mic-button";
import { agentKeys, continueTask, listAgentTasks, messageTaskAgent, retryTask, taskKeys } from "@/lib/api/agents";
import { useRealtimeStore } from "@/lib/realtime/store";
import { cn } from "@/lib/utils";

/** Task statuses that mean "not finished yet". */
export const ACTIVE_TASK = new Set(["created", "queued", "running", "waiting", "waiting_approval"]);

type TaskLike = Pick<TaskOut, "id" | "title" | "status" | "parent_task_id" | "agent_id">;

/** A failed or cancelled top-level task can be continued (or started over). */
export function canContinue(task: Pick<TaskOut, "status" | "parent_task_id">): boolean {
  return (task.status === "failed" || task.status === "cancelled") && !task.parent_task_id;
}

const fieldClass = "w-full bg-background px-2 py-1.5 text-base md:text-sm pixel-frame pixel-sunken";

/**
 * Write to the agent while it works. The message waits on the server and the agent reads it
 * before its next step — also after a pause or an approval. Not for the Orchestrator: it
 * works through its plan, so the owner writes to the agent doing the step.
 */
export function MessageAgent({ task, compact = false }: { task: TaskLike; compact?: boolean }) {
  const t = useTranslations("tasks.control");
  const toMessage = useErrorMessage();
  const queryClient = useQueryClient();
  const id = useId();
  const [text, setText] = useState("");
  const [sent, setSent] = useState(false);
  const agentType = useRealtimeStore((s) => (task.agent_id ? s.agents[task.agent_id]?.agent_type : undefined));
  const send = useMutation({
    mutationFn: () => messageTaskAgent(task.id, text.trim()),
    onSuccess: () => {
      setText("");
      setSent(true);
      void queryClient.invalidateQueries({ queryKey: taskKeys.events(task.id) });
    },
  });
  if (!ACTIVE_TASK.has(task.status) || task.status === "created" || agentType === "orchestrator") return null;
  return (
    <form
      className="flex flex-col gap-1.5"
      data-testid="message-agent"
      onSubmit={(e) => {
        e.preventDefault();
        if (text.trim()) send.mutate();
      }}
    >
      <label htmlFor={id} className={cn("text-muted-foreground", compact ? "text-xs" : "text-sm")}>
        {t("messageLabel")}
      </label>
      <textarea
        id={id}
        rows={compact ? 2 : 3}
        maxLength={4000}
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          setSent(false);
        }}
        placeholder={t("messagePlaceholder")}
        className={fieldClass}
      />
      <div className="flex flex-wrap items-center gap-1">
        <Button type="submit" size="sm" variant="outline" disabled={!text.trim() || send.isPending}>
          <Send /> {t("send")}
        </Button>
        <MicButton onText={(spoken) => setText((cur) => (cur ? `${cur.trimEnd()} ${spoken}` : spoken))} />
        {sent && (
          <span role="status" className="text-xs text-muted-foreground">
            {t("messageSent")}
          </span>
        )}
      </div>
      {send.error && (
        <p role="alert" className="text-xs text-destructive">
          {toMessage(send.error).message}
        </p>
      )}
    </form>
  );
}

/**
 * A stopped task: continue from where it stopped (the agent keeps everything it did and is
 * told why it stopped; the owner may add an instruction) — or start over from scratch.
 * `navigate`: open the new attempt's page afterwards (the task page does; the office stays).
 */
export function ContinueTask({ task, navigate = true }: { task: TaskLike; navigate?: boolean }) {
  const t = useTranslations("tasks.control");
  const toMessage = useErrorMessage();
  const queryClient = useQueryClient();
  const router = useRouter();
  const id = useId();
  const [withInstruction, setWithInstruction] = useState(false);
  const [instruction, setInstruction] = useState("");
  const done = (created: TaskOut) => {
    void queryClient.invalidateQueries({ queryKey: taskKeys.all });
    void queryClient.invalidateQueries({ queryKey: agentKeys.all });
    if (navigate) router.push(`/tasks/${created.id}`);
  };
  const go = useMutation({ mutationFn: () => continueTask(task.id, instruction.trim()), onSuccess: done });
  const over = useMutation({ mutationFn: () => retryTask(task.id), onSuccess: done });
  if (!canContinue(task)) return null;
  const busy = go.isPending || over.isPending;
  const error = go.error ?? over.error;
  return (
    <div className="flex flex-col gap-1.5" data-testid="continue-task">
      {withInstruction && (
        <>
          <label htmlFor={id} className="text-xs text-muted-foreground">
            {t("instructionLabel")}
          </label>
          <textarea
            id={id}
            rows={2}
            maxLength={4000}
            value={instruction}
            onChange={(e) => setInstruction(e.target.value)}
            placeholder={t("instructionPlaceholder")}
            className={fieldClass}
          />
        </>
      )}
      <div className="flex flex-wrap items-center gap-1">
        <Button size="sm" onClick={() => go.mutate()} disabled={busy}>
          <Play /> {t("continue")}
        </Button>
        {!withInstruction && (
          <Button size="sm" variant="ghost" onClick={() => setWithInstruction(true)} disabled={busy}>
            {t("addInstruction")}
          </Button>
        )}
        <Button size="sm" variant="outline" onClick={() => over.mutate()} disabled={busy}>
          <RotateCcw /> {t("startOver")}
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">{t("continueHint")}</p>
      {error && (
        <p role="alert" className="text-xs text-destructive">
          {toMessage(error).message}
        </p>
      )}
    </div>
  );
}

/**
 * Control for an agent (office inspector, agent page): write to it while it works, or —
 * when its last task stopped — continue that task from where it stopped.
 */
export function AgentTaskControl({ agentId, currentTaskId }: { agentId: string; currentTaskId: string | null }) {
  const t = useTranslations("tasks.control");
  const taskError = useTaskError();
  const current = useRealtimeStore((s) => (currentTaskId ? s.tasks[currentTaskId] : undefined));
  const tasks = useQuery({
    queryKey: agentKeys.tasks(agentId),
    queryFn: ({ signal }) => listAgentTasks(agentId, signal),
    enabled: !currentTaskId,
  });
  const latest = tasks.data?.items[0];
  const liveLatest = useRealtimeStore((s) => (latest ? s.tasks[latest.id] : undefined)) ?? latest;
  if (current) return <MessageAgent task={current} compact />;
  if (!liveLatest || !canContinue(liveLatest)) return null;
  return (
    <section className="flex flex-col gap-1.5 border-2 border-dashed p-2 text-xs" data-testid="stopped-task">
      <p>
        {t("lastStopped")}{" "}
        <Link href={`/tasks/${liveLatest.id}`} className="font-medium underline-offset-2 hover:underline">
          {liveLatest.title}
        </Link>
        {liveLatest.status === "failed" && <span className="text-muted-foreground"> · {taskError(liveLatest)}</span>}
      </p>
      <ContinueTask task={liveLatest} navigate={false} />
    </section>
  );
}
