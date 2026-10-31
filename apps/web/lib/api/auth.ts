import type { HealthResponse, LoginRequest, MeResponse } from "@moloko/shared-types";

import { api } from "./client";

export const authKeys = { me: ["auth", "me"] as const };
export const systemKeys = { health: ["system", "health"] as const };

export function getMe(signal?: AbortSignal): Promise<MeResponse> {
  return api.request<MeResponse>("/auth/me", { signal });
}

export function login(body: LoginRequest): Promise<MeResponse> {
  return api.request<MeResponse>("/auth/login", { method: "POST", body });
}

export function logout(): Promise<void> {
  return api.request<void>("/auth/logout", { method: "POST" });
}

export function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  // 503 still carries a valid HealthResponse describing what is down.
  return api.request<HealthResponse>("/health", { signal, acceptStatuses: [503] });
}
