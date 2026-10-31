import type { RunCreate, RunOut, RunTree, StartedRun } from "@moloko/shared-types";

import { api } from "./client";

// Under the "tasks" prefix so task/agent events refresh them too.
export const runKeys = {
  list: ["tasks", "runs"] as const,
  tree: (id: string) => ["tasks", "runs", id] as const,
};

export const listRuns = (signal?: AbortSignal) => api.request<RunOut[]>("/runs?limit=20", { signal });
export const getRunTree = (id: string, signal?: AbortSignal) => api.request<RunTree>(`/runs/${id}`, { signal });
export const startRun = (body: RunCreate) => api.request<StartedRun>("/runs", { method: "POST", body });
export const handOff = (chatId: string, content: string) =>
  api.request<StartedRun>(`/chats/${chatId}/handoff`, { method: "POST", body: { content } });
