import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { NewChat } from "@/features/chat/new-chat";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("chat");
  return { title: t("newChat") };
}

/** The message box. The chats and tasks are in the work list (phones: «Работа» at the bottom). */
export default async function NewChatPage() {
  return <NewChat />;
}
