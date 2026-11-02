"use client";

import { useTranslations } from "next-intl";

import { PasskeyCeremonyError } from "@/lib/webauthn";

import { useErrorMessage } from "./use-error-message";

/** Like useErrorMessage, plus the reasons a device's passkey prompt can fail. */
export function usePasskeyErrorMessage() {
  const t = useTranslations("passkeys.errors");
  const toMessage = useErrorMessage();
  return (error: unknown): { message: string; errorId: string | null } => {
    if (error instanceof PasskeyCeremonyError) {
      return { message: t(error.kind), errorId: null };
    }
    return toMessage(error);
  };
}
