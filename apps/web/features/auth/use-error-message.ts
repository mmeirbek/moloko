"use client";

import { useTranslations } from "next-intl";

import { ApiError } from "@/lib/api/errors";

const KNOWN = new Set([
  "invalid_credentials",
  "too_many_attempts",
  "network_error",
  "csrf_failed",
  "validation_error",
  "not_authenticated",
  "database_unavailable",
  "redis_unavailable",
  "no_model_configured",
  "model_unavailable",
  "generation_in_progress",
  "encryption_unavailable",
  "provider_kind_unavailable",
  "conflict",
  "not_found",
  "agent_busy",
  "engine_stopped",
  "invalid_transition",
  "agent_archived",
  "idempotency_key_reused",
  "server_error",
] as const);
type KnownCode = typeof KNOWN extends Set<infer T> ? T : never;

/** Turn any thrown value into a localized, user-facing message (+ server error id). */
export function useErrorMessage() {
  const t = useTranslations("errors");
  return (error: unknown): { message: string; errorId: string | null } => {
    if (error instanceof ApiError) {
      const code = error.code as KnownCode;
      const message = KNOWN.has(code)
        ? t(code)
        : error.status >= 500
          ? t("server_error")
          : t("generic");
      return { message, errorId: error.errorId };
    }
    return { message: t("generic"), errorId: null };
  };
}
