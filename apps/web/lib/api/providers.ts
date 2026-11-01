import type {
  ModelCreate,
  ModelOut,
  ModelUpdate,
  ProviderCreate,
  ProviderOut,
  ProviderTestResult,
  ProviderUpdate,
  SyncModelsResult,
} from "@moloko/shared-types";

import { api } from "./client";

export const providerKeys = {
  kinds: ["providers", "kinds"] as const,
  list: ["providers"] as const,
  models: ["models", "all"] as const,
};

export const getProviderKinds = (signal?: AbortSignal) =>
  api.request<string[]>("/providers/kinds", { signal });
export const listProviders = (signal?: AbortSignal) =>
  api.request<ProviderOut[]>("/providers", { signal });
export const createProvider = (body: ProviderCreate) =>
  api.request<ProviderOut>("/providers", { method: "POST", body });
export const updateProvider = (id: string, body: ProviderUpdate) =>
  api.request<ProviderOut>(`/providers/${id}`, { method: "PATCH", body });
export const testProvider = (id: string) =>
  api.request<ProviderTestResult>(`/providers/${id}/test`, { method: "POST" });
export const syncModels = (id: string) =>
  api.request<SyncModelsResult>(`/providers/${id}/sync-models`, { method: "POST" });
export const listAllModels = (signal?: AbortSignal) =>
  api.request<ModelOut[]>("/models?include_disabled=true", { signal });
export const createModel = (body: ModelCreate) =>
  api.request<ModelOut>("/models", { method: "POST", body });
export const updateModel = (id: string, body: ModelUpdate) =>
  api.request<ModelOut>(`/models/${id}`, { method: "PATCH", body });
