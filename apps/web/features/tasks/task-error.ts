"use client";

import { useTranslations } from "next-intl";
import { useCallback } from "react";

/** Why a task failed, in the owner's language: known codes have their own text, the rest
 *  (provider errors, tool errors) keep the server's message. */
export function useTaskError(): (task: { error_code?: string | null; error_message?: string | null }) => string {
  const t = useTranslations("tasks.errors");
  return useCallback(
    (task) => {
      const code = task.error_code ?? "";
      return code && t.has(code as "empty_result") ? t(code as "empty_result") : (task.error_message ?? "");
    },
    [t],
  );
}
