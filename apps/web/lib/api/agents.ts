import type {
  AgentBudgetOut,
  AgentCreate,
  AgentFromTemplate,
  AgentFullAccessUpdate,
  AgentOut,
  AgentRestore,
  AgentTemplateOut,
  AgentRunRequest,
  AgentUpdate,
  EventOut,
  SaveAsTemplate,
  StartedRun,
  StopAllResult,
  StorageStatus,
  SystemLimits,
  SystemState,
  TaskCreate,
  TaskDetail,
  TaskOut,
  TaskPage,
} from "@moloko/shared-types";

import { api } from "./client";

export const agentKeys = {
  all: ["agents"] as const,
  detail: (id: string) => ["agents", id] as const,
  tasks: (id: string) => ["tasks", "agent", id] as const,
  templates: (locale: string) => ["agents", "templates", locale] as const,
  archived: ["agents", "archived"] as const,
  budget: (id: string) => ["agents", id, "budget"] as const,
  // Under "tasks" so agent.message / task events refresh it (lib/realtime/provider.tsx).
  messages: (id: string, direction: MessageDirection) => ["tasks", "agent-messages", id, direction] as const,
};
export const taskKeys = {
  all: ["tasks"] as const,
  list: (filter: string, q: string) => ["tasks", "list", filter, q] as const,
  detail: (id: string) => ["tasks", "detail", id] as const,
  events: (id: string) => ["tasks", "events", id] as const,
};
export const systemStateKey = ["system", "state"] as const;
export const systemLimitsKey = ["system", "limits"] as const;
export const storageKey = ["system", "storage"] as const;

/** One message between two agents, seen from `agent_id` (GET /agents/{id}/messages). */
export type AgentMessageItem = {
  id: string;
  created_at: string;
  direction: "in" | "out";
  sender_agent_id: string;
  sender_name: string;
  receiver_agent_id: string;
  receiver_name: string;
  /** request = a question (agent_ask), task_result = the answer, error = no answer, note = agent_tell, context = Orchestrator input */
  message_type: "request" | "task_result" | "error" | "note" | "context";
  status: "delivered" | "refused";
  error: string | null;
  summary: string;
  text: string | null;
  files: string[];
  task_id: string | null;
  consult_task_id: string | null;
  asker_task_id: string | null;
  read_at: string | null;
};
export type MessageDirection = "all" | "in" | "out";

export function listAgentMessages(agentId: string, direction: MessageDirection, cursor?: string | null, signal?: AbortSignal) {
  const q = new URLSearchParams({ direction, limit: "50" });
  if (cursor) q.set("cursor", cursor);
  return api.request<{ items: AgentMessageItem[]; next_cursor: string | null }>(`/agents/${agentId}/messages?${q}`, {
    signal,
  });
}

export const listAgents = (signal?: AbortSignal) => api.request<AgentOut[]>("/agents", { signal });
export const getAgent = (id: string, signal?: AbortSignal) => api.request<AgentOut>(`/agents/${id}`, { signal });
export const createAgent = (body: AgentCreate) => api.request<AgentOut>("/agents", { method: "POST", body });
export const listAgentTemplates = (locale: string, signal?: AbortSignal) =>
  api.request<AgentTemplateOut[]>(`/agents/templates?locale=${encodeURIComponent(locale)}`, { signal });
export const createAgentFromTemplate = (body: AgentFromTemplate) =>
  api.request<AgentOut>("/agents/from-template", { method: "POST", body });
/** Save the agent's configuration as an own template (no memory, no history). */
export const saveAgentAsTemplate = (id: string, body: SaveAsTemplate = {}) =>
  api.request<AgentTemplateOut>(`/agents/${id}/save-template`, { method: "POST", body });
export const deleteAgentTemplate = (id: string) => api.request<void>(`/agents/templates/${id}`, { method: "DELETE" });
/** This month's spending against the budget that applies to the agent (a subagent: the one above it). */
export const getAgentBudget = (id: string, signal?: AbortSignal) =>
  api.request<AgentBudgetOut>(`/agents/${id}/budget`, { signal });
export const updateAgent = (id: string, body: AgentUpdate) =>
  api.request<AgentOut>(`/agents/${id}`, { method: "PATCH", body });
/** «Полный доступ»: turning it on needs the owner's password; turning it off does not. */
export const setAgentFullAccess = (id: string, body: AgentFullAccessUpdate) =>
  api.request<AgentOut>(`/agents/${id}/full-access`, { method: "PUT", body });
export const deleteAgent = (id: string) => api.request<void>(`/agents/${id}`, { method: "DELETE" });
/** Agents removed from the office (newest first) — they can be brought back. */
export const listArchivedAgents = (signal?: AbortSignal) => api.request<AgentOut[]>("/agents/archived", { signal });
export const restoreAgent = (id: string, body: AgentRestore = {}) =>
  api.request<AgentOut>(`/agents/${id}/restore`, { method: "POST", body });
export const runAgent = (id: string, body: AgentRunRequest) =>
  api.request<StartedRun>(`/agents/${id}/run`, { method: "POST", body });
export const agentAction = (id: string, action: "pause" | "resume" | "stop") =>
  api.request<AgentOut>(`/agents/${id}/${action}`, { method: "POST" });

export function listTasks(filter: string, q: string, signal?: AbortSignal) {
  const params = new URLSearchParams({ status: filter, limit: "100" });
  if (q) params.set("q", q);
  return api.request<TaskPage>(`/tasks?${params}`, { signal });
}
/** Task history of one agent (newest first). */
export function listAgentTasks(agentId: string, signal?: AbortSignal) {
  const params = new URLSearchParams({ status: "all", agent_id: agentId, limit: "100" });
  return api.request<TaskPage>(`/tasks?${params}`, { signal });
}
export const getTask = (id: string, signal?: AbortSignal) => api.request<TaskDetail>(`/tasks/${id}`, { signal });
export const taskEvents = (id: string, signal?: AbortSignal) =>
  api.request<EventOut[]>(`/tasks/${id}/events`, { signal });
export const createTask = (body: TaskCreate) => api.request<TaskOut>("/tasks", { method: "POST", body });
export const cancelTask = (id: string) => api.request<TaskOut>(`/tasks/${id}/cancel`, { method: "POST" });
export const retryTask = (id: string) => api.request<TaskOut>(`/tasks/${id}/retry`, { method: "POST" });
/** A new attempt that starts from where the stopped task stopped (optional instruction from the owner). */
export const continueTask = (id: string, instruction?: string) =>
  api.request<TaskOut>(`/tasks/${id}/continue`, { method: "POST", body: { instruction: instruction || null } });
/** Write to the agent while it works: it reads the message before its next step. */
export const messageTaskAgent = (id: string, text: string) =>
  api.request<TaskOut>(`/tasks/${id}/message`, { method: "POST", body: { text } });

export const systemLimits = (signal?: AbortSignal) => api.request<SystemLimits>("/system/limits", { signal });
export const systemStorage = (signal?: AbortSignal) => api.request<StorageStatus>("/system/storage", { signal });
export const systemState = (signal?: AbortSignal) => api.request<SystemState>("/system/state", { signal });
export const stopAll = () => api.request<StopAllResult>("/system/stop-all", { method: "POST" });
export const startEngine = () => api.request<SystemState>("/system/start", { method: "POST" });
