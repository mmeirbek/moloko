import type {
  AttachmentOut,
  CancelResult,
  ConversationCreate,
  ConversationOut,
  ConversationPage,
  ConversationUpdate,
  MessageOut,
  MessagePage,
  ModelOut,
} from "@moloko/shared-types";

import { api } from "./client";
import { readSse } from "./sse";

export const chatKeys = {
  list: ["chats"] as const,
  detail: (id: string) => ["chats", id] as const,
  messages: (id: string) => ["chats", id, "messages"] as const,
};
export const modelKeys = { picker: ["models", "enabled"] as const };

export function listChats(signal?: AbortSignal): Promise<ConversationPage> {
  return api.request<ConversationPage>("/chats?limit=100", { signal });
}

export function createChat(body: ConversationCreate = {}): Promise<ConversationOut> {
  return api.request<ConversationOut>("/chats", { method: "POST", body });
}

export function getChat(id: string, signal?: AbortSignal): Promise<ConversationOut> {
  return api.request<ConversationOut>(`/chats/${id}`, { signal });
}

export function updateChat(id: string, body: ConversationUpdate): Promise<ConversationOut> {
  return api.request<ConversationOut>(`/chats/${id}`, { method: "PATCH", body });
}

export function deleteChat(id: string): Promise<void> {
  return api.request<void>(`/chats/${id}`, { method: "DELETE" });
}

export function listMessages(id: string, signal?: AbortSignal): Promise<MessagePage> {
  return api.request<MessagePage>(`/chats/${id}/messages?limit=200`, { signal });
}

export function cancelMessage(chatId: string, messageId: string): Promise<CancelResult> {
  return api.request<CancelResult>(`/chats/${chatId}/messages/${messageId}/cancel`, {
    method: "POST",
  });
}

export function listPickerModels(signal?: AbortSignal): Promise<ModelOut[]> {
  return api.request<ModelOut[]>("/models", { signal });
}

export type StreamHandlers = {
  onCreated?: (user: MessageOut, assistant: MessageOut) => void;
  onSnapshot?: (text: string) => void;
  onDelta?: (text: string) => void;
  onFinished?: (message: MessageOut) => void;
};

async function consume(response: Response, handlers: StreamHandlers): Promise<void> {
  if (!response.body) return;
  for await (const { event, data } of readSse(response.body)) {
    const d = data as Record<string, unknown>;
    if (event === "message.created") {
      handlers.onCreated?.(d.user_message as MessageOut, d.assistant_message as MessageOut);
    } else if (event === "message.snapshot") {
      handlers.onSnapshot?.(String(d.text ?? ""));
    } else if (event === "message.delta") {
      handlers.onDelta?.(String(d.text ?? ""));
    } else if (event === "message.completed" || event === "message.failed") {
      handlers.onFinished?.(d.message as MessageOut);
    }
  }
}

/** Send a message and stream the answer. The answer is saved server-side even if this aborts. */
export async function sendMessage(
  chatId: string,
  body: { content: string; model_config_id?: string | null; attachment_ids?: string[] },
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const response = await api.stream(`/chats/${chatId}/messages`, { method: "POST", body, signal });
  await consume(response, handlers);
}

/** Re-attach to an answer that is still being generated (e.g. opened on another device). */
export async function attachStream(
  chatId: string,
  messageId: string,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const response = await api.stream(`/chats/${chatId}/messages/${messageId}/stream`, { signal });
  await consume(response, handlers);
}

/** Upload a text file; send its id with the next message. */
export function uploadAttachment(chatId: string, file: File): Promise<AttachmentOut> {
  const form = new FormData();
  form.append("file", file, file.name);
  return api.request<AttachmentOut>(`/chats/${chatId}/attachments`, { method: "POST", body: form });
}
