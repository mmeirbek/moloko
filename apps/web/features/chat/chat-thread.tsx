"use client";

import {
  AssistantRuntimeProvider,
  ComposerPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
  useAuiState,
  useExternalStoreRuntime,
  type AppendMessage,
  type ThreadMessageLike,
} from "@assistant-ui/react";
import type { MessageOut } from "@moloko/shared-types";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUp, Network, RotateCcw, Square } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { createContext, useContext, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { useErrorMessage } from "@/features/auth/use-error-message";
import { chatKeys, getChat, listPickerModels, modelKeys, updateChat } from "@/lib/api/chat";
import { handOff } from "@/lib/api/runs";
import { cn } from "@/lib/utils";

import { MarkdownText } from "./markdown";
import { ModelPicker, modelLabel } from "./model-picker";
import { useChatThread } from "./use-chat-thread";

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
        <div
          role="alert"
          className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm"
        >
          <p>{errorText(message)}</p>
          <div className="mt-1 flex items-center justify-between gap-2">
            {message.error_id && (
              <span className="font-mono text-xs text-muted-foreground">
                {tc("errorId", { id: message.error_id })}
              </span>
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

function Composer({ disabled }: { disabled?: boolean }) {
  const t = useTranslations("chat");
  return (
    <ComposerPrimitive.Root className="flex items-end gap-2 rounded-2xl border bg-card p-2 shadow-sm">
      <ComposerPrimitive.Input
        rows={1}
        autoFocus
        disabled={disabled}
        placeholder={t("placeholder")}
        className="max-h-48 min-h-10 flex-1 resize-none bg-transparent px-2 py-2 text-base outline-none placeholder:text-muted-foreground md:text-sm"
      />
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
  const toMessage = useErrorMessage();
  const queryClient = useQueryClient();
  const thread = useChatThread(chatId);
  const chat = useQuery({ queryKey: chatKeys.detail(chatId), queryFn: ({ signal }) => getChat(chatId, signal) });
  const models = useQuery({ queryKey: modelKeys.picker, queryFn: ({ signal }) => listPickerModels(signal) });
  const [modelOverride, setModelOverride] = useState<string | null | undefined>(undefined);
  const [agentsMode, setAgentsMode] = useState(false);
  const [handoffError, setHandoffError] = useState<unknown>(null);
  const selectedModel = modelOverride !== undefined ? modelOverride : (chat.data?.model_config_id ?? null);

  const byId = useMemo(() => new Map(thread.messages.map((m) => [m.id, m])), [thread.messages]);
  const answeredRuns = useMemo(
    () =>
      new Set(
        thread.messages.filter((m) => m.role === "assistant" && m.agent_run_id).map((m) => m.agent_run_id!),
      ),
    [thread.messages],
  );
  const lastUser = [...thread.messages].reverse().find((m) => m.role === "user");
  // Spec 14.3: propose handing complex multi-step requests to the agents.
  const looksComplex =
    !!lastUser &&
    !lastUser.agent_run_id &&
    (lastUser.content.length > 400 || lastUser.content.split("\n").filter((l) => /^\s*(\d+[.)]|[-*•])\s/.test(l)).length >= 3);

  async function sendToAgents(text: string) {
    setHandoffError(null);
    try {
      await handOff(chatId, text);
      await queryClient.invalidateQueries({ queryKey: chatKeys.messages(chatId) });
      void queryClient.invalidateQueries({ queryKey: chatKeys.list });
    } catch (error) {
      setHandoffError(error);
    }
  }

  async function chooseModel(id: string | null) {
    setModelOverride(id);
    const updated = await updateChat(chatId, { model_config_id: id });
    queryClient.setQueryData(chatKeys.detail(chatId), updated);
  }

  function retry(failedAssistantId: string) {
    const index = thread.messages.findIndex((m) => m.id === failedAssistantId);
    const question = thread.messages
      .slice(0, index)
      .reverse()
      .find((m) => m.role === "user");
    if (question) void thread.send(question.content, selectedModel);
  }

  const runtime = useExternalStoreRuntime<MessageOut>({
    messages: thread.messages,
    isRunning: thread.isRunning,
    convertMessage: toThreadMessage,
    onNew: async (message: AppendMessage) => {
      const text = message.content
        .map((part) => (part.type === "text" ? part.text : ""))
        .join("")
        .trim();
      if (!text) return;
      if (agentsMode) await sendToAgents(text);
      else await thread.send(text, selectedModel);
    },
    onCancel: thread.cancel,
  });

  const noModels = models.data !== undefined && models.data.length === 0;
  const sendError = thread.sendError
    ? toMessage(thread.sendError)
    : handoffError
      ? toMessage(handoffError)
      : null;

  return (
    <MessagesById.Provider value={byId}>
      <AnsweredRuns.Provider value={answeredRuns}>
      <RetryContext.Provider value={retry}>
        <AssistantRuntimeProvider runtime={runtime}>
          <ThreadPrimitive.Root className="flex h-full min-h-0 flex-col">
            <div className="flex items-center justify-between gap-2 border-b px-1 pb-3">
              <h1 className="truncate text-lg font-semibold">{chat.data?.title ?? ""}</h1>
              {models.data && models.data.length > 0 && (
                <ModelPicker models={models.data} value={selectedModel} onChange={chooseModel} />
              )}
            </div>

            <ThreadPrimitive.Viewport className="flex min-h-0 flex-1 flex-col gap-6 overflow-y-auto px-1 py-6">
              <ThreadPrimitive.Empty>
                <div className="m-auto max-w-sm text-center text-sm text-muted-foreground">
                  {noModels ? (
                    <>
                      <p>{t("noModels")}</p>
                      <Link href="/settings" className="mt-2 inline-block underline">
                        {t("openSettings")}
                      </Link>
                    </>
                  ) : (
                    <p>{t("empty")}</p>
                  )}
                </div>
              </ThreadPrimitive.Empty>
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
                    }}
                  >
                    {t("dismiss")}
                  </button>
                </div>
              )}
              {looksComplex && !agentsMode && lastUser && (
                <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border bg-accent/50 px-3 py-2 text-sm">
                  <span>{t("suggestAgents")}</span>
                  <Button size="sm" variant="outline" onClick={() => void sendToAgents(lastUser.content)}>
                    <Network /> {t("handOff")}
                  </Button>
                </div>
              )}
              <Composer disabled={noModels} />
              <label className="flex items-center gap-2 px-2 text-xs text-muted-foreground">
                <input type="checkbox" checked={agentsMode} onChange={(e) => setAgentsMode(e.target.checked)} />
                <Network className="size-3.5" /> {t("agentsMode")}
              </label>
              {(() => {
                const current = models.data?.find((m) => m.id === selectedModel);
                return current ? (
                  <p className="px-2 text-xs text-muted-foreground">{modelLabel(current)}</p>
                ) : null;
              })()}
            </div>
          </ThreadPrimitive.Root>
        </AssistantRuntimeProvider>
      </RetryContext.Provider>
      </AnsweredRuns.Provider>
    </MessagesById.Provider>
  );
}
