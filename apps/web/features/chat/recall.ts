import type { RecalledSourceOut } from "@moloko/shared-types";

/**
 * Where an earlier chat, task or memory that recall gave the model lives in the app
 * (null = nowhere to open). Source types come from the search index; unknown new ones
 * still open their chat when they belong to one. Pure: tested.
 */
export function recallHref(source: RecalledSourceOut): string | null {
  if (source.type === "conversation") return `/chat/${source.id}`;
  if (source.conversation_id) return `/chat/${source.conversation_id}`;
  if (source.type === "task") return `/tasks/${source.id}`;
  if (source.type === "memory") return source.agent_id ? `/office/agents/${source.agent_id}` : "/settings#memory";
  if (source.agent_id) return `/office/agents/${source.agent_id}`;
  return null;
}

/** The kind of source, for the label next to its title. */
export function recallKind(source: RecalledSourceOut): "chat" | "task" | "memory" | "other" {
  if (source.type === "conversation" || source.conversation_id) return "chat";
  if (source.type === "task") return "task";
  if (source.type === "memory") return "memory";
  return "other";
}
