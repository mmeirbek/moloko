"use client";

import type { TaskOut } from "@moloko/shared-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";

import { ArrowUp, Loader2, Paperclip, Play, RotateCcw, Square, X } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { useErrorMessage } from "@/features/auth/use-error-message";
import { MicButton, type VoiceMessage } from "@/features/voice/mic-button";
import { agentKeys, cancelTask, continueTask, messageTaskAgent, retryTask, taskKeys, uploadTaskFile } from "@/lib/api/agents";
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

/** Modes where the text is a note to the task (it is not finished): files can go with it. */
const NOTE_MODES = new Set<ComposerMode>(["message", "orchestrator", "inLine"]);

type Pending = { key: string; name: string; path?: string; failed?: boolean };

/**
 * The task's message box — the same as the chat's: text on top, then one toolbar (files on the
 * left, voice and send on the right). Until the task ends the text goes to it at any time —
 * read before the agent's next step, first thing when a task in line starts, and by every part
 * at work plus the Orchestrator for a plan; files land in the task's folder and the message
 * names them. A stopped task continues from where it stopped with it; after a result it is
 * the owner's reply and the agent goes on from its answer (a new attempt, opened right away).
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
  const [files, setFiles] = useState<Pending[]>([]);
  const [uploadError, setUploadError] = useState<unknown>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const picker = useRef<HTMLInputElement>(null);

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
      setFiles([]);
      setSent(true);
      void queryClient.invalidateQueries({ queryKey: taskKeys.events(task.id) });
    },
  });

  /** Files go up at once (to the task's folder); the message sent next names them. */
  function attach(list: FileList | null) {
    setUploadError(null);
    for (const file of Array.from(list ?? [])) {
      const key = `${file.name}-${file.size}-${Math.random()}`;
      setFiles((cur) => [...cur, { key, name: file.name }]);
      uploadTaskFile(task.id, file)
        .then((saved) => setFiles((cur) => cur.map((f) => (f.key === key ? { ...f, path: saved.path } : f))))
        .catch((e: unknown) => {
          setUploadError(e);
          setFiles((cur) => cur.filter((f) => f.key !== key));
        });
    }
    if (picker.current) picker.current.value = "";
  }

  /** A recording: its file goes to the task's folder, its words are the message. */
  async function sendVoice(voice: VoiceMessage) {
    if (!mode || !NOTE_MODES.has(mode)) {
      goOn.mutate(voice.text);
      return;
    }
    setUploadError(null);
    try {
      const saved = await uploadTaskFile(task.id, new File([voice.audio], voice.filename, { type: voice.audio.type }));
      const spoken = `${t("voiceNote", { path: saved.path })}\n${voice.text}`;
      message.mutate(withFiles(text.trim() ? `${text.trim()}\n\n${spoken}` : spoken)); // with what was typed
    } catch (e) {
      setUploadError(e);
      setText((cur) => (cur ? `${cur.trimEnd()} ${voice.text}` : voice.text)); // the words are not lost
    }
  }

  const withFiles = (body: string) => {
    const paths = files.flatMap((f) => (f.path ? [f.path] : []));
    if (paths.length === 0) return body;
    const note = t("filesNote", { paths: paths.join(", ") });
    return body ? `${body}\n\n${note}` : note;
  };
  const goOn = useMutation({ mutationFn: (body: string) => continueTask(task.id, body), onSuccess: open });
  const over = useMutation({ mutationFn: () => retryTask(task.id), onSuccess: open });
  const stop = useMutation({ mutationFn: () => cancelTask(task.id), onSuccess: refresh });
  const busy = message.isPending || goOn.isPending || over.isPending;
  const error = message.error ?? goOn.error ?? over.error ?? stop.error ?? uploadError;

  if (!mode) return null;
  const note = NOTE_MODES.has(mode);
  const body = text.trim();
  const uploading = files.some((f) => !f.path);
  const canSend = !busy && !uploading && (body.length > 0 || files.length > 0 || mode === "continue");
  const send = () => {
    if (!canSend) return;
    if (note) message.mutate(withFiles(body));
    else goOn.mutate(body);
  };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      send();
    }
  };
  const sendLabel = note ? t("send") : mode === "continue" ? t("continue") : t("reply");
  const sentLabel = mode === "inLine" ? t("sentInLine") : mode === "orchestrator" ? t("sentOrchestrator") : t("sent");

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
        {files.length > 0 && (
          <ul className="flex flex-wrap gap-1 px-3 pt-3" aria-label={t("attach")}>
            {files.map((f) => (
              <li key={f.key} className="inline-flex items-center gap-1 bg-muted px-2 py-1 text-xs pixel-frame" data-attachment={f.name}>
                {f.path ? <Paperclip className="size-3" aria-hidden /> : <Loader2 className="size-3 animate-spin" aria-label={t("uploading")} />}
                <span className="max-w-48 truncate">{f.name}</span>
                <button
                  type="button"
                  aria-label={`${t("removeFile")}: ${f.name}`}
                  className="-mr-1 flex size-5 items-center justify-center text-muted-foreground hover:text-foreground"
                  onClick={() => setFiles((cur) => cur.filter((x) => x.key !== f.key))}
                >
                  <X className="size-3" />
                </button>
              </li>
            ))}
          </ul>
        )}
        <textarea
          id={`composer-${task.id}`}
          ref={input}
          rows={1}
          maxLength={4000}
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            setSent(false);
          }}
          onKeyDown={onKey}
          placeholder={t(`placeholder.${mode}`)}
          className="max-h-60 min-h-14 w-full resize-none bg-transparent px-4 pt-4 pb-1 text-base outline-none placeholder:text-muted-foreground"
        />
        <div className="flex flex-wrap items-center gap-1 px-2 pb-2">
          {note && (
            <>
              <input ref={picker} type="file" multiple hidden onChange={(e) => attach(e.target.files)} data-testid="task-file-input" />
              <Button type="button" size="icon" variant="ghost" aria-label={t("attach")} title={t("attach")} onClick={() => picker.current?.click()}>
                <Paperclip />
              </Button>
            </>
          )}
          {mode === "continue" && (
            <Button type="button" size="sm" variant="ghost" onClick={() => over.mutate()} disabled={busy}>
              <RotateCcw /> {t("startOver")}
            </Button>
          )}
          {sent && note && (
            <span role="status" className="min-w-0 px-2 text-xs text-muted-foreground">
              {sentLabel}
            </span>
          )}
          <div className="min-w-0 flex-1" />
          <MicButton
            disabled={busy}
            onVoice={sendVoice}
            onText={(spoken) => setText((cur) => (cur ? `${cur.trimEnd()} ${spoken}` : spoken))}
          />
          {note && (
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
          <Button type="submit" size="icon" aria-label={sendLabel} title={sendLabel} className="shrink-0" disabled={!canSend}>
            {mode === "continue" && !body ? <Play /> : <ArrowUp />}
          </Button>
        </div>
      </form>
      {/* the placeholder says it already; the longer hint only where there is room */}
      <p className="hidden px-4 text-xs text-muted-foreground sm:block">{t(`hint.${mode}`)}</p>
      {Boolean(error) && (
        <p role="alert" className="px-4 text-xs text-destructive">
          {toMessage(error).message}
        </p>
      )}
    </div>
  );
}
