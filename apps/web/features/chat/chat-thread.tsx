"use client";

import {
  ActionBarPrimitive,
  AssistantRuntimeProvider,
  MessagePrimitive,
  ThreadPrimitive,
  useAui,
  useAuiState,
  useExternalStoreRuntime,
  type AppendMessage,
  type ThreadMessageLike,
} from "@assistant-ui/react";
import type { MessageOut } from "@moloko/shared-types";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, Check, Copy, Network, RotateCcw } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { LogoMark } from "@/components/brand/logo";
import { Button } from "@/components/ui/button";
import { useErrorMessage } from "@/features/auth/use-error-message";
import { chatKeys, getChat, listPickerModels, modelKeys, updateChat } from "@/lib/api/chat";
import { handOff } from "@/lib/api/runs";
import { useDocumentTitle } from "@/lib/hooks";

import { AttachmentChip } from "./attachment-chip";
import { useComposerAttachments } from "./attachments";
import { useChatTitle } from "./chat-title";
import { Composer, Suggestions } from "./composer";
import { MarkdownText } from "./markdown";
import { ModelPicker } from "./model-picker";
import { useChatThread } from "./use-chat-thread";
import { ChatWelcome } from "./welcome";

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
    <MessagePrimitive.Root className="flex flex-col items-end gap-1.5">
      <div className="max-w-[85%] rounded-3xl bg-muted px-4 py-2.5 whitespace-pre-wrap text-foreground">
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
    <MessagePrimitive.Root className="flex gap-3">
      {/* moloko's own face on its answers: the logo tile. */}
      <LogoMark size="sm" className="mt-0.5 rounded-md" />
      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
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
          <div role="alert" className="rounded-xl border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm">
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
        {message?.status === "completed" && (
          <ActionBarPrimitive.Root className="-ml-2 flex items-center gap-1 text-xs text-muted-foreground">
            <ActionBarPrimitive.Copy asChild>
              <Button variant="ghost" size="icon" className="size-8 text-muted-foreground" aria-label={t("copy")} title={t("copy")}>
                <Copy className="[[data-copied]_&]:hidden" />
                <Check className="hidden [[data-copied]_&]:block" />
              </Button>
            </ActionBarPrimitive.Copy>
            {message.model && (
              <span>
                {message.model}
                {message.output_tokens != null && ` · ${t("tokens", { count: message.output_tokens })}`}
              </span>
            )}
          </ActionBarPrimitive.Root>
        )}
      </div>
    </MessagePrimitive.Root>
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
  const files = useComposerAttachments({ chatId, ensureChat: async () => chatId });
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
    const kept = files.take();
    void thread.send(
      text,
      selectedModel,
      kept.map((a) => a.id),
    ).then((accepted) => {
      // Not accepted (network, budget, …): the typed text and the files come back.
      if (!accepted) {
        setDraft(text);
        files.restore(kept);
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
  const error = thread.sendError ?? handoffError ?? files.error ?? modelError;
  const sendError = error ? toMessage(error) : null;
  const loadFailed = Boolean(thread.loadError) && thread.messages.length === 0;
  const disabled = noModels || loadFailed;

  return (
    <MessagesById.Provider value={byId}>
      <AnsweredRuns.Provider value={answeredRuns}>
        <RetryContext.Provider value={retry}>
          <AssistantRuntimeProvider runtime={runtime}>
            <ThreadPrimitive.Root className="flex h-full min-h-0 flex-col">
              <h1 className="mx-auto w-full max-w-3xl truncate px-1 pb-2 font-sans text-base font-medium text-muted-foreground">
                {chat.data ? chatTitle(chat.data.title) : ""}
              </h1>

              {/* A log: screen readers read new messages; aria-busy holds them while an answer streams. */}
              <ThreadPrimitive.Viewport
                role="log"
                aria-live="polite"
                aria-relevant="additions"
                aria-busy={thread.isRunning}
                aria-label={t("messages")}
                className="flex min-h-0 flex-1 flex-col overflow-y-auto"
              >
                <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-8 px-1 py-6">
                  {thread.isLoading && <p className="m-auto text-sm text-muted-foreground">{tc("loading")}</p>}
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
                      <div className="m-auto flex w-full flex-col gap-6">
                        <ChatWelcome noModels={noModels} />
                        {!noModels && <Suggestions />}
                      </div>
                    </ThreadPrimitive.Empty>
                  )}
                  <ThreadPrimitive.Messages components={{ UserMessage, AssistantMessage }} />
                </div>
              </ThreadPrimitive.Viewport>

              <div className="relative mx-auto flex w-full max-w-3xl flex-col gap-2 pt-2">
                <ThreadPrimitive.ScrollToBottom asChild>
                  <Button
                    variant="outline"
                    size="icon"
                    aria-label={t("scrollDown")}
                    className="absolute -top-11 left-1/2 -translate-x-1/2 rounded-full shadow-md disabled:invisible"
                  >
                    <ArrowDown />
                  </Button>
                </ThreadPrimitive.ScrollToBottom>
                {sendError && (
                  <div
                    role="alert"
                    className="flex items-center justify-between gap-2 rounded-xl border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm"
                  >
                    <span>{sendError.message}</span>
                    <button
                      type="button"
                      className="text-xs underline"
                      onClick={() => {
                        thread.clearSendError();
                        setHandoffError(null);
                        files.clearError();
                        setModelError(null);
                      }}
                    >
                      {t("dismiss")}
                    </button>
                  </div>
                )}
                {looksComplex && !agentsMode && lastUser && (
                  <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border bg-accent/50 px-3 py-2 text-sm">
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
                {files.notice}
                <Composer
                  disabled={disabled}
                  agents={agentsMode}
                  onAgentsChange={setAgentsMode}
                  attach={agentsMode ? undefined : files.button({ disabled })}
                  chips={agentsMode ? undefined : files.chips}
                  model={
                    models.data && models.data.length > 0 && !agentsMode ? (
                      <ModelPicker models={models.data} value={selectedModel} onChange={chooseModel} />
                    ) : undefined
                  }
                />
                <DraftRestorer draft={draft} onRestored={clearDraft} />
              </div>
            </ThreadPrimitive.Root>
          </AssistantRuntimeProvider>
        </RetryContext.Provider>
      </AnsweredRuns.Provider>
    </MessagesById.Provider>
  );
}
