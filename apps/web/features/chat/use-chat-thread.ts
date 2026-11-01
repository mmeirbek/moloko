"use client";

import type { MessageOut, MessagePage } from "@moloko/shared-types";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

import { attachStream, cancelMessage, chatKeys, listMessages, sendMessage } from "@/lib/api/chat";

type Patch = (messages: MessageOut[]) => MessageOut[];

/**
 * Messages of one conversation plus live streaming. The server owns the state:
 * this hook only mirrors it (initial page, SSE deltas, final saved message), and
 * re-attaches to an answer that is still running (reload, another device).
 */
export function useChatThread(chatId: string) {
  const queryClient = useQueryClient();
  const key = chatKeys.messages(chatId);
  const query = useQuery({ queryKey: key, queryFn: ({ signal }) => listMessages(chatId, signal) });
  const [sendError, setSendError] = useState<unknown>(null);
  const attached = useRef<string | null>(null);
  const controllers = useRef(new Set<AbortController>());

  const patch = useCallback(
    (fn: Patch) => {
      queryClient.setQueryData<MessagePage>(key, (page) =>
        page ? { ...page, items: fn(page.items) } : page,
      );
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [queryClient, chatId],
  );

  const handlers = useCallback(
    (assistantId: () => string | null) => ({
      onSnapshot: (text: string) =>
        patch((ms) => ms.map((m) => (m.id === assistantId() ? { ...m, content: text } : m))),
      onDelta: (text: string) =>
        patch((ms) =>
          ms.map((m) => (m.id === assistantId() ? { ...m, content: m.content + text } : m)),
        ),
      onFinished: (message: MessageOut) => {
        patch((ms) => ms.map((m) => (m.id === message.id ? message : m)));
        void queryClient.invalidateQueries({ queryKey: chatKeys.list });
      },
    }),
    [patch, queryClient],
  );

  // Abort open streams when leaving the page (the server keeps generating).
  useEffect(() => {
    const open = controllers.current;
    return () => {
      for (const c of open) c.abort();
      open.clear();
    };
  }, [chatId]);

  // Re-attach to an answer that is still being generated.
  const items = query.data?.items;
  const running = items?.find((m) => m.role === "assistant" && m.status === "streaming");
  useEffect(() => {
    if (!running || attached.current === running.id) return;
    attached.current = running.id;
    const controller = new AbortController();
    controllers.current.add(controller);
    const id = running.id;
    attachStream(chatId, id, handlers(() => id), controller.signal)
      .catch(() => void queryClient.invalidateQueries({ queryKey: key }))
      .finally(() => controllers.current.delete(controller));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [running?.id, chatId]);

  /** Resolves to false when the server never accepted the message (the caller restores the draft). */
  const send = useCallback(
    async (content: string, modelConfigId: string | null, attachmentIds: string[] = []): Promise<boolean> => {
      setSendError(null);
      let assistantId: string | null = null;
      const controller = new AbortController();
      controllers.current.add(controller);
      try {
        await sendMessage(
          chatId,
          { content, model_config_id: modelConfigId, attachment_ids: attachmentIds },
          {
            onCreated: (user, assistant) => {
              assistantId = assistant.id;
              attached.current = assistant.id; // we are already streaming it
              patch((ms) => [...ms, user, assistant]);
            },
            ...handlers(() => assistantId),
          },
          controller.signal,
        );
      } catch (error) {
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          setSendError(error);
          void queryClient.invalidateQueries({ queryKey: key });
        }
      } finally {
        controllers.current.delete(controller);
      }
      return assistantId !== null;
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [chatId, handlers, patch, queryClient],
  );

  const cancel = useCallback(async () => {
    if (!running) return;
    try {
      await cancelMessage(chatId, running.id);
    } catch (error) {
      setSendError(error);
    }
  }, [chatId, running]);

  return {
    messages: items ?? [],
    isLoading: query.isPending,
    loadError: query.error,
    reload: () => void query.refetch(),
    isRunning: Boolean(running),
    sendError,
    clearSendError: () => setSendError(null),
    send,
    cancel,
  };
}
