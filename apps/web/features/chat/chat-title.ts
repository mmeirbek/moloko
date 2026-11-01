"use client";

import { useTranslations } from "next-intl";
import { useCallback } from "react";

import { plainTitle } from "@/lib/utils";

/** The server's title for a chat nobody has written in yet (apps/api services/chat.py DEFAULT_TITLE). */
export const UNTITLED_CHAT = "New chat";

/** Chat title for display: no Markdown, and "New chat" in the owner's language. */
export function useChatTitle(): (title: string) => string {
  const t = useTranslations("chat");
  return useCallback((title: string) => (title === UNTITLED_CHAT ? "" : plainTitle(title)) || t("newChat"), [t]);
}
