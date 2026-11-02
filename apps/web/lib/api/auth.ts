import type {
  HealthResponse,
  LoginRequest,
  MeResponse,
  SessionSettingsOut,
  SessionSettingsUpdate,
} from "@moloko/shared-types";

import { api } from "./client";

export const authKeys = { me: ["auth", "me"] as const, sessionSettings: ["auth", "session-settings"] as const };
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

/** How long a sign-in lasts (the owner's choice within the server's bounds). */
export function getSessionSettings(signal?: AbortSignal): Promise<SessionSettingsOut> {
  return api.request<SessionSettingsOut>("/auth/session-settings", { signal });
}

/** Needs the password; `ttl_hours: null` goes back to the server default. */
export function updateSessionSettings(body: SessionSettingsUpdate): Promise<SessionSettingsOut> {
  return api.request<SessionSettingsOut>("/auth/session-settings", { method: "PUT", body });
}

export function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  // 503 still carries a valid HealthResponse describing what is down.
  return api.request<HealthResponse>("/health", { signal, acceptStatuses: [503] });
}
