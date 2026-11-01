import type { MemoryContextOut, MemoryCreate, MemoryOut, MemoryRevisionOut, MemoryUpdate } from "@moloko/shared-types";

import { api } from "./client";

export type MemoryScope = { agentId: string } | { shared: true };

export const memoryKeys = {
  all: ["memories"] as const,
  list: (scope: MemoryScope) => ["memories", "list", "agentId" in scope ? scope.agentId : "shared"] as const,
  revisions: (id: string) => ["memories", "revisions", id] as const,
  context: (agentId: string) => ["memories", "context", agentId] as const,
};

export function listMemories(scope: MemoryScope, signal?: AbortSignal) {
  const params = new URLSearchParams("agentId" in scope ? { agent_id: scope.agentId } : { shared: "true" });
  return api.request<MemoryOut[]>(`/memories?${params}`, { signal });
}
export const createMemory = (body: MemoryCreate) => api.request<MemoryOut>("/memories", { method: "POST", body });
export const updateMemory = (id: string, body: MemoryUpdate) =>
  api.request<MemoryOut>(`/memories/${id}`, { method: "PATCH", body });
export const deleteMemory = (id: string) => api.request<void>(`/memories/${id}`, { method: "DELETE" });
export const memoryRevisions = (id: string, signal?: AbortSignal) =>
  api.request<MemoryRevisionOut[]>(`/memories/${id}/revisions`, { signal });
export const agentMemoryContext = (agentId: string, signal?: AbortSignal) =>
  api.request<MemoryContextOut>(`/agents/${agentId}/memory-context`, { signal });
