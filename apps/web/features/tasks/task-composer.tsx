"use client";

import type { TaskOut } from "@moloko/shared-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";

import { ArrowUp, Play, RotateCcw, Square } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { useErrorMessage } from "@/features/auth/use-error-message";
import { MicButton } from "@/features/voice/mic-button";
import { agentKeys, cancelTask, continueTask, messageTaskAgent, retryTask, taskKeys } from "@/lib/api/agents";
import { useRealtimeStore } from "@/lib/realtime/store";
import { cn } from "@/lib/utils";

import { ACTIVE_TASK } from "./task-control";

/** What the message box does for a task in this state. */
export type ComposerMode = "message" | "continue" | "reply" | "orchestrator" | "inLine" | null;

export function composerMode(
  task: Pick<TaskOut, "status" | "parent_task_id" | "status_reason">,
  agentType: string | undefined,
): ComposerMode {
  // Waiting for its busy agent: it starts by itself (or the owner cancels it).
  if (task.status === "created") return task.status_reason === "waiting_for_agent" ? "inLine" : null;
  if (ACTIVE_TASK.has(task.status)) return agentType === "orchestrator" ? "orchestrator" : "message";
  if (task.parent_task_id) return null; // a part is continued through the whole task
  if (task.status === "failed" || task.status === "cancelled") return "continue";
  if (task.status === "completed") return "reply";
  return null;
}

/**
 * The task's message box — the same as the chat's: text on top, then one toolbar (voice and
 * send on the right). While the agent works the text goes to it (read before its next step);
 * a stopped task continues from where it stopped with it; after a result it is the owner's
 * reply and the agent goes on from its answer (a new attempt, opened right away).
 */
export function TaskComposer({ task, className }: { task: TaskOut; className?: string }) {
  const t = useTranslations("tasks.composer");
  const toMessage = useErrorMessage();
  const queryClient = useQueryClient();
  const router = useRouter();
  const agentType = useRealtimeStore((s) => (task.agent_id ? s.agents[task.agent_id]?.agent_type : undefined));
  const mode = composerMode(task, agentType);
  const [text, setText] = useState("");
  const [sent, setSent] = useState(false);
  const input = useRef<HTMLTextAreaElement>(null);

  // Grow with the text like the chat's box (up to its max height).
  useEffect(() => {
    const el = input.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [text]);

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: taskKeys.all });
    void queryClient.invalidateQueries({ queryKey: agentKeys.all });
  };
  const open = (next: TaskOut) => {
    refresh();
    router.push(`/tasks/${next.id}`);
  };
  const message = useMutation({
    mutationFn: (body: string) => messageTaskAgent(task.id, body),
    onSuccess: () => {
      setText("");
      setSent(true);
      void queryClient.invalidateQueries({ queryKey: taskKeys.events(task.id) });
    },
  });
  const goOn = useMutation({ mutationFn: (body: string) => continueTask(task.id, body), onSuccess: open });
  const over = useMutation({ mutationFn: () => retryTask(task.id), onSuccess: open });
  const stop = useMutation({ mutationFn: () => cancelTask(task.id), onSuccess: refresh });
  const busy = message.isPending || goOn.isPending || over.isPending;
  const error = message.error ?? goOn.error ?? over.error ?? stop.error;

  if (!mode) return null;
  const writable = mode !== "orchestrator" && mode !== "inLine";
  const body = text.trim();
  const canSend = writable && !busy && (body.length > 0 || mode === "continue");
  const send = () => {
    if (!canSend) return;
    if (mode === "message") message.mutate(body);
    else goOn.mutate(body);
  };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      send();
    }
  };
  const sendLabel = mode === "message" ? t("send") : mode === "continue" ? t("continue") : t("reply");

  return (
    <div
      className={cn("flex flex-col gap-1.5", className)}
      data-testid={mode === "message" ? "message-agent" : mode === "continue" ? "continue-task" : `composer-${mode}`}
    >
      <form
        className="flex flex-col bg-card transition-colors focus-within:ring-2 focus-within:ring-ring/40 pixel-frame"
        onSubmit={(e) => {
          e.preventDefault();
          send();
        }}
      >
        <label htmlFor={`composer-${task.id}`} className="sr-only">
          {t(`label.${mode}`)}
        </label>
        <textarea
          id={`composer-${task.id}`}
          ref={input}
          rows={1}
          maxLength={4000}
          value={text}
          disabled={!writable}
          onChange={(e) => {
            setText(e.target.value);
            setSent(false);
          }}
          onKeyDown={onKey}
          placeholder={t(`placeholder.${mode}`)}
          className="max-h-60 min-h-14 w-full resize-none bg-transparent px-4 pt-4 pb-1 text-base outline-none placeholder:text-muted-foreground disabled:cursor-not-allowed"
        />
        <div className="flex flex-wrap items-center gap-1 px-2 pb-2">
          {mode === "continue" && (
            <Button type="button" size="sm" variant="ghost" onClick={() => over.mutate()} disabled={busy}>
              <RotateCcw /> {t("startOver")}
            </Button>
          )}
          {sent && mode === "message" && (
            <span role="status" className="px-2 text-xs text-muted-foreground">
              {t("sent")}
            </span>
          )}
          <div className="min-w-0 flex-1" />
          {writable && (
            <MicButton
              disabled={busy}
              onText={(spoken) => setText((cur) => (cur ? `${cur.trimEnd()} ${spoken}` : spoken))}
            />
          )}
          {(mode === "message" || mode === "orchestrator" || mode === "inLine") && (
            <Button
              type="button"
              size="icon"
              variant="outline"
              aria-label={t("stop")}
              title={t("stop")}
              className="shrink-0"
              disabled={stop.isPending}
              onClick={() => stop.mutate()}
            >
              <Square />
            </Button>
          )}
          {writable && (
            <Button type="submit" size="icon" aria-label={sendLabel} title={sendLabel} className="shrink-0" disabled={!canSend}>
              {mode === "continue" && !body ? <Play /> : <ArrowUp />}
            </Button>
          )}
        </div>
      </form>
      <p className="px-4 text-xs text-muted-foreground">{t(`hint.${mode}`)}</p>
      {error && (
        <p role="alert" className="px-4 text-xs text-destructive">
          {toMessage(error).message}
        </p>
      )}
    </div>
  );
}
