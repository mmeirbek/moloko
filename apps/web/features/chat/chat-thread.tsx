"use client";

import {
  AssistantRuntimeProvider,
  ComposerPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
  useAui,
  useAuiState,
  useExternalStoreRuntime,
  type AppendMessage,
  type ThreadMessageLike,
} from "@assistant-ui/react";
import type { AttachmentOut, MessageOut } from "@moloko/shared-types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUp, Network, Paperclip, RotateCcw, Square, X } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { useErrorMessage } from "@/features/auth/use-error-message";
import { chatKeys, getChat, listPickerModels, modelKeys, updateChat, uploadAttachment } from "@/lib/api/chat";

import { MicButton } from "@/features/voice/mic-button";

import { AttachmentChip } from "./attachment-chip";
import { handOff } from "@/lib/api/runs";
import { cn } from "@/lib/utils";

import { useChatTitle } from "./chat-title";
import { MarkdownText } from "./markdown";
import { ModelPicker, modelLabel } from "./model-picker";
import { useChatThread } from "./use-chat-thread";
import { EmptyState } from "@/features/mascot/empty-state";
import { useDocumentTitle } from "@/lib/hooks";

const MAX_ATTACHMENTS = 5; // files per message

/** Our own message records, so message components can show server-side details. */
const MessagesById = createContext<Map<string, MessageOut>>(new Map());
const RetryContext = createContext<(messageId: string) => void>(() => {});

function toThreadMessage(m: MessageOut): ThreadMessageLike {
  const base = {
    id: m.id,
    role: m.role === "user" ? ("user" as const) : ("assistant" as const),
    content: [{ type: "text" as const, text: m.content }],
    createdAt: new Date(m.created_at),
  };
  if (m.role === "user") return base;
  const status: ThreadMessageLike["status"] =
    m.status === "streaming"
      ? { type: "running" }
      : m.status === "completed"
        ? { type: "complete", reason: "stop" }
        : m.status === "cancelled"
          ? { type: "incomplete", reason: "cancelled" }
          : { type: "incomplete", reason: "error", error: m.error_message ?? "error" };
  return { ...base, status };
}

function useCurrentMessage(): MessageOut | undefined {
  const id = useAuiState((s) => s.message.id);
  return useContext(MessagesById).get(id);
}

const AnsweredRuns = createContext<Set<string>>(new Set());

function UserMessage() {
  const t = useTranslations("chat");
  const message = useCurrentMessage();
  const answered = useContext(AnsweredRuns);
  const runId = message?.agent_run_id;
  return (
    <MessagePrimitive.Root className="flex flex-col items-end gap-1">
      <div className="max-w-[85%] rounded-2xl rounded-br-sm bg-primary px-4 py-2 whitespace-pre-wrap text-primary-foreground">
        <MessagePrimitive.Parts />
      </div>
      {message?.attachments && message.attachments.length > 0 && (
        <ul className="flex max-w-[85%] flex-wrap justify-end gap-1" aria-label={t("attachments")}>
          {message.attachments.map((a) => (
            <AttachmentChip key={a.id} chatId={message.conversation_id} attachment={a} />
          ))}
        </ul>
      )}
      {runId && (
        <Link
          href={`/office/subagents?run=${runId}`}
          className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:underline"
        >
          <Network className="size-3.5" />
          {answered.has(runId) ? t("handedOff") : t("agentsWorking")}
        </Link>
      )}
    </MessagePrimitive.Root>
  );
}

function AssistantMessage() {
  const t = useTranslations("chat");
  const tc = useTranslations("common");
  const message = useCurrentMessage();
  const retry = useContext(RetryContext);
  const failed = message?.status === "failed";
  const cancelled = message?.status === "cancelled";
  const streaming = message?.status === "streaming";
  const errorText = (m: MessageOut) => {
    const key = `errors.${m.error_code}` as Parameters<typeof t>[0];
    return t.has(key) ? t(key) : m.error_message;
  };

  return (
    <MessagePrimitive.Root className="flex flex-col gap-1">
      <div className="max-w-full text-[15px] leading-relaxed">
        {streaming && !message?.content ? (
          <span className="inline-flex gap-1 py-2" aria-label={t("thinking")}>
            <span className="size-1.5 animate-pulse rounded-full bg-muted-foreground" />
            <span className="size-1.5 animate-pulse rounded-full bg-muted-foreground [animation-delay:150ms]" />
            <span className="size-1.5 animate-pulse rounded-full bg-muted-foreground [animation-delay:300ms]" />
          </span>
        ) : (
          <MessagePrimitive.Parts components={{ Text: MarkdownText }} />
        )}
      </div>
      {failed && message && (
        <div role="alert" className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm">
          <p>{errorText(message)}</p>
          <div className="mt-1 flex items-center justify-between gap-2">
            {message.error_id && (
              <span className="font-mono text-xs text-muted-foreground">{tc("errorId", { id: message.error_id })}</span>
            )}
            <Button size="sm" variant="outline" onClick={() => retry(message.id)}>
              <RotateCcw /> {tc("retry")}
            </Button>
          </div>
        </div>
      )}
      {cancelled && <p className="text-xs text-muted-foreground">{t("stopped")}</p>}
      {message?.status === "completed" && message.model && (
        <p className="text-xs text-muted-foreground">
          {message.model}
          {message.output_tokens != null && ` · ${t("tokens", { count: message.output_tokens })}`}
        </p>
      )}
    </MessagePrimitive.Root>
  );
}

/** Voice input appends the spoken text to what is already typed. */
function ComposerMic({ disabled }: { disabled?: boolean }) {
  const aui = useAui();
  return (
    <MicButton
      disabled={disabled}
      onText={(text) => {
        const composer = aui.composer();
        const current = composer.getState().text;
        composer.setText(current ? `${current.trimEnd()} ${text}` : text);
      }}
    />
  );
}

/** Puts a draft back into the composer (a message the server did not accept is not lost). */
function DraftRestorer({ draft, onRestored }: { draft: string | null; onRestored: () => void }) {
  const aui = useAui();
  useEffect(() => {
    if (draft === null) return;
    const composer = aui.composer();
    if (!composer.getState().text) composer.setText(draft);
    onRestored();
  }, [aui, draft, onRestored]);
  return null;
}

/** Example questions for an empty chat: a tap puts one into the composer to edit or send. */
function Suggestions() {
  const t = useTranslations("chat");
  const aui = useAui();
  const items = [t("suggestions.explain"), t("suggestions.plan"), t("suggestions.letter")];
  return (
    <ul className="flex flex-col gap-2" aria-label={t("suggestions.label")}>
      {items.map((text) => (
        <li key={text}>
          <button
            type="button"
            onClick={() => aui.composer().setText(text)}
            className="w-full rounded-xl border bg-card px-3 py-2 text-left text-sm text-foreground transition-colors hover:bg-accent"
          >
            {text}
          </button>
        </li>
      ))}
    </ul>
  );
}

function Composer({ disabled, attach, agents }: { disabled?: boolean; attach?: ReactNode; agents?: boolean }) {
  const t = useTranslations("chat");
  return (
    <ComposerPrimitive.Root
      className={cn(
        "flex items-end gap-2 rounded-2xl border bg-card p-2 shadow-sm focus-within:ring-2 focus-within:ring-ring",
        agents && "border-sky/60 bg-accent/40",
      )}
    >
      {attach}
      <ComposerPrimitive.Input
        rows={1}
        autoFocus
        disabled={disabled}
        placeholder={agents ? t("placeholderAgents") : t("placeholder")}
        className="max-h-48 min-h-10 flex-1 resize-none bg-transparent px-2 py-2 text-base outline-none placeholder:text-muted-foreground md:text-sm"
      />
      <ComposerMic disabled={disabled} />
      <ThreadPrimitive.If running={false}>
        <ComposerPrimitive.Send asChild>
          <Button size="icon" aria-label={t("send")} className="rounded-full">
            <ArrowUp />
          </Button>
        </ComposerPrimitive.Send>
      </ThreadPrimitive.If>
      <ThreadPrimitive.If running>
        <ComposerPrimitive.Cancel asChild>
          <Button size="icon" variant="outline" aria-label={t("stop")} className="rounded-full">
            <Square />
          </Button>
        </ComposerPrimitive.Cancel>
      </ThreadPrimitive.If>
    </ComposerPrimitive.Root>
  );
}

export function ChatThread({ chatId }: { chatId: string }) {
  const t = useTranslations("chat");
  const tc = useTranslations("common");
  const toMessage = useErrorMessage();
  const queryClient = useQueryClient();
  const thread = useChatThread(chatId);
  const chatTitle = useChatTitle();
  const chat = useQuery({ queryKey: chatKeys.detail(chatId), queryFn: ({ signal }) => getChat(chatId, signal) });
  useDocumentTitle(chat.data ? chatTitle(chat.data.title) : null);
  const models = useQuery({ queryKey: modelKeys.picker, queryFn: ({ signal }) => listPickerModels(signal) });
  const [modelOverride, setModelOverride] = useState<string | null | undefined>(undefined);
  const [agentsMode, setAgentsMode] = useState(false);
  const [handoffError, setHandoffError] = useState<unknown>(null);
  const [handingOff, setHandingOff] = useState(false);
  const [modelError, setModelError] = useState<unknown>(null);
  const [draft, setDraft] = useState<string | null>(null);
  const clearDraft = useCallback(() => setDraft(null), []);
  const [pending, setPending] = useState<AttachmentOut[]>([]);
  const [uploadError, setUploadError] = useState<unknown>(null);
  const [uploadSkipped, setUploadSkipped] = useState(0);
  const fileInput = useRef<HTMLInputElement>(null);
  const upload = useMutation({
    // Each file on its own: one failure keeps the others that did upload.
    mutationFn: async (files: File[]) => Promise.allSettled(files.map((f) => uploadAttachment(chatId, f))),
    onSuccess: (results) => {
      const added = results.flatMap((r) => (r.status === "fulfilled" ? [r.value] : []));
      const failed = results.find((r) => r.status === "rejected");
      setPending((list) => [...list, ...added].slice(0, MAX_ATTACHMENTS));
      if (failed) setUploadError(failed.reason);
    },
    onError: setUploadError,
  });
  const selectedModel = modelOverride !== undefined ? modelOverride : (chat.data?.model_config_id ?? null);

  const byId = useMemo(() => new Map(thread.messages.map((m) => [m.id, m])), [thread.messages]);
  const answeredRuns = useMemo(
    () => new Set(thread.messages.filter((m) => m.role === "assistant" && m.agent_run_id).map((m) => m.agent_run_id!)),
    [thread.messages],
  );
  const lastUser = [...thread.messages].reverse().find((m) => m.role === "user");
  // Spec 14.3: propose handing complex multi-step requests to the agents.
  const looksComplex =
    !!lastUser &&
    !lastUser.agent_run_id &&
    (lastUser.content.length > 400 ||
      lastUser.content.split("\n").filter((l) => /^\s*(\d+[.)]|[-*•])\s/.test(l)).length >= 3);

  async function sendToAgents(text: string): Promise<boolean> {
    if (handingOff) return false;
    setHandoffError(null);
    setHandingOff(true);
    try {
      await handOff(chatId, text);
      await queryClient.invalidateQueries({ queryKey: chatKeys.messages(chatId) });
      void queryClient.invalidateQueries({ queryKey: chatKeys.list });
      return true;
    } catch (error) {
      setHandoffError(error);
      return false;
    } finally {
      setHandingOff(false);
    }
  }

  async function chooseModel(id: string | null) {
    const previous = modelOverride;
    setModelError(null);
    setModelOverride(id);
    try {
      const updated = await updateChat(chatId, { model_config_id: id });
      queryClient.setQueryData(chatKeys.detail(chatId), updated);
    } catch (error) {
      setModelOverride(previous); // show the model the server really has
      setModelError(error);
    }
  }

  function retry(failedAssistantId: string) {
    const index = thread.messages.findIndex((m) => m.id === failedAssistantId);
    const question = thread.messages
      .slice(0, index)
      .reverse()
      .find((m) => m.role === "user");
    if (question) {
      const ids = (question.attachments ?? []).map((a) => a.id);
      void thread.send(question.content, selectedModel, ids);
    }
  }

  function submit(message: AppendMessage) {
    const text = message.content
      .map((part) => (part.type === "text" ? part.text : ""))
      .join("")
      .trim();
    if (!text) return;
    if (agentsMode) {
      void sendToAgents(text).then((ok) => !ok && setDraft(text));
      return;
    }
    const kept = pending;
    setPending([]);
    void thread.send(
      text,
      selectedModel,
      kept.map((a) => a.id),
    ).then((accepted) => {
      // Not accepted (network, budget, …): the typed text and the files come back.
      if (!accepted) {
        setDraft(text);
        setPending((list) => (list.length ? list : kept));
      }
    });
  }

  const runtime = useExternalStoreRuntime<MessageOut>({
    messages: thread.messages,
    isRunning: thread.isRunning,
    convertMessage: toThreadMessage,
    // Return at once (send() reports its own errors; isRunning comes from our store).
    onNew: async (message: AppendMessage) => submit(message),
    // assistant-ui treats a send whose parent is not its latest message as an edit (this can
    // happen right after a refetch). We have no branches: an "edit" is a new message —
    // without this handler such a message was silently dropped.
    onEdit: async (message: AppendMessage) => submit(message),
    onCancel: thread.cancel,
  });

  const noModels = models.data !== undefined && models.data.length === 0;
  const sendError = thread.sendError
    ? toMessage(thread.sendError)
    : handoffError
      ? toMessage(handoffError)
      : uploadError
        ? toMessage(uploadError)
        : modelError
          ? toMessage(modelError)
          : null;
  const loadFailed = Boolean(thread.loadError) && thread.messages.length === 0;
  const attachButton = agentsMode ? undefined : (
    <>
      <input
        ref={fileInput}
        type="file"
        multiple
        hidden
        accept=".txt,.md,.markdown,.csv,.tsv,.json,.yaml,.yml,.xml,.html,.log,.py,.js,.ts,.tsx,.jsx,.sql,.sh,.toml,.ini,.cfg,text/*,image/png,image/jpeg,image/webp,image/gif,application/pdf,.pdf"
        onChange={(e) => {
          const chosen = [...(e.target.files ?? [])];
          e.target.value = "";
          const files = chosen.slice(0, MAX_ATTACHMENTS - pending.length);
          setUploadSkipped(chosen.length - files.length);
          if (files.length) {
            setUploadError(null);
            upload.mutate(files);
          }
        }}
      />
      <Button
        type="button"
        size="icon"
        variant="ghost"
        className="rounded-full"
        aria-label={t("attach")}
        disabled={noModels || loadFailed || upload.isPending || pending.length >= MAX_ATTACHMENTS}
        onClick={() => fileInput.current?.click()}
      >
        <Paperclip />
      </Button>
    </>
  );

  return (
    <MessagesById.Provider value={byId}>
      <AnsweredRuns.Provider value={answeredRuns}>
        <RetryContext.Provider value={retry}>
          <AssistantRuntimeProvider runtime={runtime}>
            <ThreadPrimitive.Root className="flex h-full min-h-0 flex-col">
              <div className="flex items-center justify-between gap-2 border-b px-1 pb-3">
                <h1 className="truncate font-sans text-lg font-semibold">{chat.data ? chatTitle(chat.data.title) : ""}</h1>
                {models.data && models.data.length > 0 && (
                  <ModelPicker models={models.data} value={selectedModel} onChange={chooseModel} />
                )}
              </div>

              {/* A log: screen readers read new messages; aria-busy holds them while an answer streams. */}
              <ThreadPrimitive.Viewport
                role="log"
                aria-live="polite"
                aria-relevant="additions"
                aria-busy={thread.isRunning}
                aria-label={t("messages")}
                className="flex min-h-0 flex-1 flex-col gap-6 overflow-y-auto px-1 py-6"
              >
                {thread.isLoading && (
                  <p className="m-auto text-sm text-muted-foreground">{tc("loading")}</p>
                )}
                {loadFailed && (
                  <div role="alert" className="m-auto flex max-w-sm flex-col items-center gap-2 text-center text-sm">
                    <p>{toMessage(thread.loadError).message}</p>
                    <Button variant="outline" size="sm" onClick={thread.reload}>
                      <RotateCcw /> {tc("retry")}
                    </Button>
                  </div>
                )}
                {!thread.isLoading && !loadFailed && (
                  <ThreadPrimitive.Empty>
                    <div className="m-auto flex w-full max-w-md flex-col gap-4 text-center text-sm text-muted-foreground">
                      {noModels ? (
                        <>
                          <EmptyState title={t("noModels")} hint={t("noModelsHint")} mood="sad" className="py-2" />
                          <Button asChild className="self-center">
                            <Link href="/settings#ai">{t("openSettings")}</Link>
                          </Button>
                        </>
                      ) : (
                        <>
                          <EmptyState title={t("empty")} hint={t("emptyHint")} mood="happy" className="py-2" />
                          <Suggestions />
                        </>
                      )}
                    </div>
                  </ThreadPrimitive.Empty>
                )}
                <ThreadPrimitive.Messages components={{ UserMessage, AssistantMessage }} />
              </ThreadPrimitive.Viewport>

              <div className="flex flex-col gap-2 pt-2">
                {sendError && (
                  <div
                    role="alert"
                    className={cn(
                      "flex items-center justify-between gap-2 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm",
                    )}
                  >
                    <span>{sendError.message}</span>
                    <button
                      type="button"
                      className="text-xs underline"
                      onClick={() => {
                        thread.clearSendError();
                        setHandoffError(null);
                        setUploadError(null);
                      }}
                    >
                      {t("dismiss")}
                    </button>
                  </div>
                )}
                {uploadSkipped > 0 && (
                  <p role="status" className="px-1 text-xs text-muted-foreground">
                    {t("tooManyFiles", { max: MAX_ATTACHMENTS, count: uploadSkipped })}
                  </p>
                )}
                {looksComplex && !agentsMode && lastUser && (
                  <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border bg-accent/50 px-3 py-2 text-sm">
                    <span>{t("suggestAgents")}</span>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={handingOff}
                      onClick={() => void sendToAgents(lastUser.content)}
                    >
                      <Network /> {t("handOff")}
                    </Button>
                  </div>
                )}
                {pending.length > 0 && !agentsMode && (
                  <ul className="flex flex-wrap gap-1 px-1" aria-label={t("attachments")}>
                    {pending.map((a) => (
                      <AttachmentChip key={a.id} chatId={chatId} attachment={a}>
                        <button
                          type="button"
                          aria-label={t("removeAttachment", { name: a.filename })}
                          className="-m-1.5 flex size-7 items-center justify-center rounded-full text-muted-foreground hover:text-foreground"
                          onClick={() => setPending((list) => list.filter((x) => x.id !== a.id))}
                        >
                          <X className="size-3" />
                        </button>
                      </AttachmentChip>
                    ))}
                  </ul>
                )}
                <Composer disabled={noModels || loadFailed} attach={attachButton} agents={agentsMode} />
                <DraftRestorer draft={draft} onRestored={clearDraft} />
                <label className="flex min-h-9 items-start gap-2 px-2 text-xs text-muted-foreground">
                  <input
                    type="checkbox"
                    className="mt-0.5 size-4 shrink-0"
                    checked={agentsMode}
                    onChange={(e) => setAgentsMode(e.target.checked)}
                  />
                  <Network className="mt-0.5 size-3.5 shrink-0" aria-hidden />
                  <span>
                    <span className="font-medium text-foreground">{t("agentsMode")}</span> — {t("agentsModeHint")}
                  </span>
                </label>
                {(() => {
                  const current = models.data?.find((m) => m.id === selectedModel);
                  return current ? <p className="px-2 text-xs text-muted-foreground">{modelLabel(current)}</p> : null;
                })()}
              </div>
            </ThreadPrimitive.Root>
          </AssistantRuntimeProvider>
        </RetryContext.Provider>
      </AnsweredRuns.Provider>
    </MessagesById.Provider>
  );
}
