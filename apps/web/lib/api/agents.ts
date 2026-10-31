import type {
  AgentCreate,
  AgentOut,
  AgentRunRequest,
  AgentUpdate,
  EventOut,
  StartedRun,
  StopAllResult,
  SystemState,
  TaskCreate,
  TaskDetail,
  TaskOut,
  TaskPage,
  TaskUpdate,
} from "@moloko/shared-types";

import { api } from "./client";

export const agentKeys = { all: ["agents"] as const, detail: (id: string) => ["agents", id] as const };
export const taskKeys = {
  all: ["tasks"] as const,
  list: (filter: string, q: string) => ["tasks", "list", filter, q] as const,
  detail: (id: string) => ["tasks", "detail", id] as const,
  events: (id: string) => ["tasks", "events", id] as const,
};
export const systemStateKey = ["system", "state"] as const;

export const listAgents = (signal?: AbortSignal) => api.request<AgentOut[]>("/agents", { signal });
export const createAgent = (body: AgentCreate) => api.request<AgentOut>("/agents", { method: "POST", body });
export const updateAgent = (id: string, body: AgentUpdate) =>
  api.request<AgentOut>(`/agents/${id}`, { method: "PATCH", body });
export const deleteAgent = (id: string) => api.request<void>(`/agents/${id}`, { method: "DELETE" });
export const runAgent = (id: string, body: AgentRunRequest) =>
  api.request<StartedRun>(`/agents/${id}/run`, { method: "POST", body });
export const agentAction = (id: string, action: "pause" | "resume" | "stop") =>
  api.request<AgentOut>(`/agents/${id}/${action}`, { method: "POST" });

export function listTasks(filter: string, q: string, signal?: AbortSignal) {
  const params = new URLSearchParams({ status: filter, limit: "100" });
  if (q) params.set("q", q);
  return api.request<TaskPage>(`/tasks?${params}`, { signal });
}
export const getTask = (id: string, signal?: AbortSignal) => api.request<TaskDetail>(`/tasks/${id}`, { signal });
export const taskEvents = (id: string, signal?: AbortSignal) =>
  api.request<EventOut[]>(`/tasks/${id}/events`, { signal });
export const createTask = (body: TaskCreate) => api.request<TaskOut>("/tasks", { method: "POST", body });
export const updateTask = (id: string, body: TaskUpdate) =>
  api.request<TaskOut>(`/tasks/${id}`, { method: "PATCH", body });
export const cancelTask = (id: string) => api.request<TaskOut>(`/tasks/${id}/cancel`, { method: "POST" });
export const retryTask = (id: string) => api.request<TaskOut>(`/tasks/${id}/retry`, { method: "POST" });

export const systemState = (signal?: AbortSignal) => api.request<SystemState>("/system/state", { signal });
export const stopAll = () => api.request<StopAllResult>("/system/stop-all", { method: "POST" });
export const startEngine = () => api.request<SystemState>("/system/start", { method: "POST" });
