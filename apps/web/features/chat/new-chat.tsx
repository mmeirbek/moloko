"use client";

import {
  AssistantRuntimeProvider,
  ThreadPrimitive,
  useAui,
  useExternalStoreRuntime,
  type AppendMessage,
  type ThreadMessageLike,
} from "@assistant-ui/react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { useErrorMessage } from "@/features/auth/use-error-message";
import { GettingStarted } from "@/features/onboarding/getting-started";
import { chatKeys, createChat, listPickerModels, modelKeys, sendMessage } from "@/lib/api/chat";
import { handOff } from "@/lib/api/runs";

import { useComposerAttachments } from "./attachments";
import { Composer, Suggestions } from "./composer";
import { ModelPicker } from "./model-picker";
import { useAgentTask } from "./use-agent-task";
import { ChatWelcome } from "./welcome";

const NO_MESSAGES: ThreadMessageLike[] = [];

/** Puts the text back when the first message did not get through. */
function DraftRestorer({ draft }: { draft: string | null }) {
  const aui = useAui();
  useEffect(() => {
    if (draft !== null && !aui.composer().getState().text) aui.composer().setText(draft);
  }, [aui, draft]);
  return null;
}

/**
 * A new conversation, like Claude's start page: a greeting and the composer in the middle.
 * The chat is created on the server by the first message (or the first attached file), so
 * "New chat" never leaves empty chats behind. Once the server has the message, the open chat
 * takes over and follows the answer as it is written.
 */
export function NewChat() {
  const t = useTranslations("chat");
  const toMessage = useErrorMessage();
  const router = useRouter();
  const queryClient = useQueryClient();
  const models = useQuery({ queryKey: modelKeys.picker, queryFn: ({ signal }) => listPickerModels(signal) });
  const [model, setModel] = useState<string | null>(null);
  const [agentsMode, setAgentsMode] = useState(false);
  const agentTask = useAgentTask();
  const creating = useRef<Promise<string> | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [draft, setDraft] = useState<string | null>(null);

  function ensureChat(): Promise<string> {
    creating.current ??= createChat({ model_config_id: model }).then(
      (chat) => {
        void queryClient.invalidateQueries({ queryKey: chatKeys.list });
        return chat.id;
      },
      (e: unknown) => {
        creating.current = null; // let the next try create it
        throw e;
      },
    );
    return creating.current;
  }

  const files = useComposerAttachments({ ensureChat });

  async function submit(message: AppendMessage) {
    const text = message.content
      .map((part) => (part.type === "text" ? part.text : ""))
      .join("")
      .trim();
    if (!text || busy) return;
    setBusy(true);
    setError(null);
    const mention = agentTask.match(text);
    if (mention) {
      // «@Кодер почини…»: that agent's task, no chat.
      try {
        await agentTask.start(mention);
      } catch (e) {
        setError(e);
        setDraft(text);
        setBusy(false);
      }
      return;
    }
    const kept = agentsMode ? [] : await files.take(); // waits for files still uploading
    try {
      const id = await ensureChat();
      if (agentsMode) {
        await handOff(id, text);
      } else {
        // Wait only until the server has saved the message, then hand over to the open chat
        // (the answer keeps being written on the server and the chat attaches to it).
        const stream = new AbortController();
        let accepted = false;
        await sendMessage(
          id,
          { content: text, model_config_id: model, attachment_ids: kept.map((a) => a.id) },
          {
            onCreated: () => {
              accepted = true;
              stream.abort();
            },
          },
          stream.signal,
        ).catch((e: unknown) => {
          if (!accepted) throw e;
        });
        if (!accepted) throw new Error(t("notSent"));
      }
      void queryClient.invalidateQueries({ queryKey: chatKeys.list });
      router.push(`/chat/${id}`);
    } catch (e) {
      setError(e);
      setDraft(text);
      files.restore(kept);
      setBusy(false);
    }
  }

  const runtime = useExternalStoreRuntime<ThreadMessageLike>({
    messages: NO_MESSAGES,
    isRunning: false,
    convertMessage: (m) => m,
    onNew: async (message: AppendMessage) => void submit(message),
  });

  const noModels = models.data !== undefined && models.data.length === 0;
  const shownError = error;

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <ThreadPrimitive.Root className="relative flex h-full min-h-0 flex-col overflow-y-auto" {...(agentsMode ? {} : files.dropProps)}>
        {files.dropOverlay}
        <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col justify-center gap-6 px-1 py-8">
          <ChatWelcome noModels={noModels} />
          {shownError ? (
            <div
              role="alert"
              className="flex items-center justify-between gap-2 border-2 border-destructive/40 bg-destructive/10 px-3 py-2 text-sm"
            >
              <span>{toMessage(shownError).message}</span>
              <button
                type="button"
                className="text-xs underline"
                onClick={() => {
                  setError(null);
                }}
              >
                {t("dismiss")}
              </button>
            </div>
          ) : null}
          {files.notice}
          <Composer
            disabled={noModels || busy}
            agents={agentsMode}
            onAgentsChange={setAgentsMode}
            attach={agentsMode ? undefined : files.button({ disabled: noModels || busy })}
            chips={agentsMode ? undefined : files.chips}
            onPaste={agentsMode ? undefined : files.onPaste}
            model={
              models.data && models.data.length > 0 && !agentsMode ? (
                <ModelPicker models={models.data} value={model} onChange={setModel} />
              ) : undefined
            }
          />
          <DraftRestorer draft={draft} />
          {!noModels && <Suggestions />}
          <GettingStarted className="mt-2" />
        </div>
      </ThreadPrimitive.Root>
    </AssistantRuntimeProvider>
  );
}
