import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { NewChat } from "@/features/chat/new-chat";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("pages.chat");
  return { title: t("title") };
}

/** The first screen is the message box (owner's choice); the chats and tasks are in the
 *  work list — the sidebar, on phones the «Работа» sheet. */
export default async function ChatIndexPage() {
  return <NewChat />;
}
