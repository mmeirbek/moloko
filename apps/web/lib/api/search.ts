import type { AiServicesIn, AiServicesOut, SearchOut, SearchStatus } from "@moloko/shared-types";

import { api } from "./client";

export const searchKeys = {
  query: (q: string, types: string) => ["search", q, types] as const,
  status: ["search", "status"] as const,
  ai: ["ai", "settings"] as const,
};

export const searchAll = (q: string, types: string, signal?: AbortSignal) =>
  api.request<SearchOut>(`/search?q=${encodeURIComponent(q)}&types=${encodeURIComponent(types)}`, { signal });
export const searchStatus = (signal?: AbortSignal) => api.request<SearchStatus>("/search/status", { signal });
export const getAiServices = (signal?: AbortSignal) => api.request<AiServicesOut>("/ai/settings", { signal });
export const updateAiServices = (body: AiServicesIn) =>
  api.request<AiServicesOut>("/ai/settings", { method: "PUT", body });
